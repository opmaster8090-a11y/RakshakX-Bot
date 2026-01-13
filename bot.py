import discord
from discord.ext import commands
import sqlite3
import time
import os
import datetime
from collections import Counter

# ---------- INTENTS ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ---------- DATABASE ----------
db = sqlite3.connect("analytics.db")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS activity (
    user_id INTEGER,
    channel_id INTEGER,
    last_seen INTEGER,
    PRIMARY KEY (user_id, channel_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS message_activity (
    user_id INTEGER PRIMARY KEY,
    msg_count INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS voice_activity (
    user_id INTEGER PRIMARY KEY,
    total_time INTEGER DEFAULT 0,
    join_time INTEGER
)
""")
db.commit()

# ---------- READY ----------
@bot.event
async def on_ready():
    print(f"[+] Logged in as {bot.user}")

# ---------- MESSAGE TRACK ----------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    now = int(time.time())

    cursor.execute("""
        INSERT INTO activity (user_id, channel_id, last_seen)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, channel_id)
        DO UPDATE SET last_seen = excluded.last_seen
    """, (message.author.id, message.channel.id, now))

    cursor.execute("""
        INSERT INTO message_activity (user_id, msg_count)
        VALUES (?, 1)
        ON CONFLICT(user_id)
        DO UPDATE SET msg_count = msg_count + 1
    """, (message.author.id,))

    db.commit()
    await bot.process_commands(message)

# ---------- VOICE TRACK ----------
@bot.event
async def on_voice_state_update(member, before, after):
    now = int(time.time())

    if before.channel is None and after.channel is not None:
        cursor.execute("""
            INSERT INTO voice_activity (user_id, join_time)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET join_time = ?
        """, (member.id, now, now))
        db.commit()

    if before.channel is not None and after.channel is None:
        cursor.execute(
            "SELECT join_time, total_time FROM voice_activity WHERE user_id=?",
            (member.id,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            join_time, total_time = row
            cursor.execute("""
                UPDATE voice_activity
                SET total_time=?, join_time=NULL
                WHERE user_id=?
            """, (total_time + (now - join_time), member.id))
            db.commit()

# ---------- COMMANDS ----------
@bot.command()
async def most_active(ctx):
    cursor.execute("""
        SELECT user_id, msg_count
        FROM message_activity
        ORDER BY msg_count DESC
        LIMIT 1
    """)
    text = cursor.fetchone()

    cursor.execute("""
        SELECT user_id, total_time
        FROM voice_activity
        ORDER BY total_time DESC
        LIMIT 1
    """)
    voice = cursor.fetchone()

    msg = "🏆 **Most Active Users**\n\n"

    if text and ctx.guild.get_member(text[0]):
        msg += f"📝 Text: **{ctx.guild.get_member(text[0]).display_name}** ({text[1]} msgs)\n"
    else:
        msg += "📝 Text: None\n"

    if voice and ctx.guild.get_member(voice[0]):
        msg += f"🎙 Voice: **{ctx.guild.get_member(voice[0]).display_name}** ({voice[1]//60} min)"
    else:
        msg += "🎙 Voice: None"

    await ctx.send(msg)

@bot.command()
async def peak_time(ctx):
    cursor.execute("SELECT last_seen FROM activity")
    rows = cursor.fetchall()

    if not rows:
        await ctx.send("No data yet 📉")
        return

    hours = [datetime.datetime.fromtimestamp(r[0]).hour for r in rows]
    hour, count = Counter(hours).most_common(1)[0]

    await ctx.send(
        f"⏰ **Peak Activity Time**\n🔥 {hour}:00–{hour}:59 ({count} msgs)"
    )

@bot.command()
async def stats(ctx):
    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM activity")
    users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT channel_id) FROM activity")
    channels = cursor.fetchone()[0]

    await ctx.send(
        f"📊 **Server Stats**\n👤 Users: {users}\n💬 Channels: {channels}"
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def server_health(ctx):
    await ctx.send("✅ Server is healthy")

@server_health.error
async def server_health_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Admin permission required")

@bot.command()
async def help(ctx):
    await ctx.send(
        "🛡 **RakshakX Security Bot**\n\n"
        "`!most_active` → Top text & voice user\n"
        "`!peak_time` → Most active hour\n"
        "`!stats` → Server stats\n"
        "`!server_health` → Admin only\n"
    )

# ---------- RUN ----------
bot.run(os.getenv("TOKEN"))
