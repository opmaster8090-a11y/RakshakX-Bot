import discord
from discord.ext import commands
import sqlite3
import time
import os

# -------- INTENTS --------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# -------- BOT OBJECT --------
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# -------- DATABASE SETUP --------
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
db.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS voice_activity (
    user_id INTEGER PRIMARY KEY,
    total_time INTEGER DEFAULT 0,
    join_time INTEGER
)
""")
db.commit()


# -------- READY EVENT --------
@bot.event
async def on_ready():
    print(f"[+] Bot logged in as: {bot.user}")
    print("[+] Database connected & ready")

# -------- MESSAGE LISTENER --------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    channel_id = message.channel.id
    last_seen = int(time.time())

    # DB me data save / update
    cursor.execute(
        """
        INSERT INTO activity (user_id, channel_id, last_seen)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, channel_id)
        DO UPDATE SET last_seen = excluded.last_seen
        """,
        (user_id, channel_id, last_seen)
    )
    db.commit()

    print(f"[DB] user={user_id} channel={channel_id} time={last_seen}")

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    now = int(time.time())

    # User JOIN voice
    if before.channel is None and after.channel is not None:
        cursor.execute("""
            INSERT INTO voice_activity (user_id, join_time)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET join_time = ?
        """, (member.id, now, now))
        db.commit()

    # User LEAVE voice
    if before.channel is not None and after.channel is None:
        cursor.execute(
            "SELECT join_time, total_time FROM voice_activity WHERE user_id = ?",
            (member.id,)
        )
        row = cursor.fetchone()

        if row and row[0]:
            join_time, total_time = row
            session_time = now - join_time
            total_time += session_time

            cursor.execute("""
                UPDATE voice_activity
                SET total_time = ?, join_time = NULL
                WHERE user_id = ?
            """, (total_time, member.id))
            db.commit()


@bot.command()
async def activity(ctx):
    now = int(time.time())
    seven_days = 7 * 24 * 60 * 60  # seconds

    # total unique users
    cursor.execute("SELECT DISTINCT user_id, MAX(last_seen) FROM activity GROUP BY user_id")
    rows = cursor.fetchall()

    active = 0
    inactive = 0

    for user_id, last_seen in rows:
        if now - last_seen <= seven_days:
            active += 1
        else:
            inactive += 1

    await ctx.send(
        f"📊 **User Activity (Last 7 Days)**\n"
        f"🟢 Active Users: {active}\n"
        f"🔴 Inactive Users: {inactive}"
    )

@bot.command()
async def who_active(ctx):
    now = int(time.time())
    seven_days = 7 * 24 * 60 * 60

    cursor.execute("""
        SELECT user_id, MAX(last_seen)
        FROM activity
        GROUP BY user_id
    """)
    rows = cursor.fetchall()

    active_users = []
    inactive_users = []

    for user_id, last_seen in rows:
        member = ctx.guild.get_member(user_id)
        if not member:
            continue  # user left server

        if now - last_seen <= seven_days:
            active_users.append(member.display_name)
        else:
            inactive_users.append(member.display_name)

    msg = "🟢 **Active Users (Last 7 Days):**\n"
    msg += "\n".join(active_users) if active_users else "None"

    msg += "\n\n🔴 **Inactive Users:**\n"
    msg += "\n".join(inactive_users) if inactive_users else "None"

    await ctx.send(msg)

@bot.command()
async def dead_channels(ctx):
    now = int(time.time())
    fourteen_days = 14 * 24 * 60 * 60  # seconds

    # har channel ka latest last_seen
    cursor.execute("""
        SELECT channel_id, MAX(last_seen)
        FROM activity
        GROUP BY channel_id
    """)
    rows = cursor.fetchall()

    dead = []

    for channel_id, last_seen in rows:
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            continue  # channel delete ho chuka hoga

        if now - last_seen > fourteen_days:
            dead.append(channel.mention)

    if dead:
        msg = "💀 **Dead Channels (14+ days inactive):**\n"
        msg += "\n".join(dead)
    else:
        msg = "🎉 **No dead channels found!**"

    await ctx.send(msg)

from collections import Counter
import datetime

@bot.command()
async def peak_time(ctx):
    # sab last_seen timestamps nikaalo
    cursor.execute("SELECT last_seen FROM activity")
    rows = cursor.fetchall()

    if not rows:
        await ctx.send("No data yet 📉")
        return

    hours = []
    for (ts,) in rows:
        hour = datetime.datetime.fromtimestamp(ts).hour
        hours.append(hour)

    counter = Counter(hours)
    peak_hour, count = counter.most_common(1)[0]

    await ctx.send(
        f"⏰ **Peak Activity Time**\n"
        f"🔥 Most active hour: **{peak_hour}:00 – {peak_hour}:59**\n"
        f"📨 Messages count (approx): **{count}**"
    )

@bot.command()
async def server_health(ctx):
    now = int(time.time())
    seven_days = 7 * 24 * 60 * 60
    fourteen_days = 14 * 24 * 60 * 60

    # ---------- USERS ----------
    cursor.execute("""
        SELECT user_id, MAX(last_seen)
        FROM activity
        GROUP BY user_id
    """)
    user_rows = cursor.fetchall()

    active_users = []
    inactive_users = []

    for user_id, last_seen in user_rows:
        member = ctx.guild.get_member(user_id)
        if not member:
            continue
        if now - last_seen <= seven_days:
            active_users.append(member.display_name)
        else:
            inactive_users.append(member.display_name)

    # ---------- DEAD CHANNELS ----------
    cursor.execute("""
        SELECT channel_id, MAX(last_seen)
        FROM activity
        GROUP BY channel_id
    """)
    channel_rows = cursor.fetchall()

    dead_channels = []
    for channel_id, last_seen in channel_rows:
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            continue
        if now - last_seen > fourteen_days:
            dead_channels.append(channel.mention)

    # ---------- PEAK TIME ----------
    cursor.execute("SELECT last_seen FROM activity")
    ts_rows = cursor.fetchall()

    if ts_rows:
        hours = [datetime.datetime.fromtimestamp(ts).hour for (ts,) in ts_rows]
        peak_hour, count = Counter(hours).most_common(1)[0]
        peak_text = f"{peak_hour}:00–{peak_hour}:59 ({count} msgs)"
    else:
        peak_text = "No data"

    # ---------- MESSAGE BUILD ----------
    msg = (
        "📊 **Server Health Report**\n\n"
        f"🟢 **Active Users ({len(active_users)}):**\n"
        f"{', '.join(active_users) if active_users else 'None'}\n\n"
        f"🔴 **Inactive Users ({len(inactive_users)}):**\n"
        f"{', '.join(inactive_users) if inactive_users else 'None'}\n\n"
        f"💀 **Dead Channels (14+ days):**\n"
        f"{', '.join(dead_channels) if dead_channels else 'None'}\n\n"
        f"⏰ **Peak Activity Time:** {peak_text}"
    )

    await ctx.send(msg)
@bot.command()
async def most_active(ctx):
    # -------- TEXT ACTIVITY --------
    cursor.execute("""
        SELECT user_id, COUNT(*) as msg_count
        FROM activity
        GROUP BY user_id
        ORDER BY msg_count DESC
        LIMIT 1
    """)
    text_top = cursor.fetchone()

    text_user = "None"
    text_count = 0

    if text_top:
        member = ctx.guild.get_member(text_top[0])
        if member:
            text_user = member.display_name
            text_count = text_top[1]

    # -------- VOICE ACTIVITY --------
    cursor.execute("""
        SELECT user_id, total_time
        FROM voice_activity
        ORDER BY total_time DESC
        LIMIT 1
    """)
    voice_top = cursor.fetchone()

    voice_user = "None"
    voice_time = 0

    if voice_top:
        member = ctx.guild.get_member(voice_top[0])
        if member:
            voice_user = member.display_name
            voice_time = voice_top[1] // 60  # minutes

    await ctx.send(
        "🏆 **Most Active Users**\n\n"
        f"📝 **Text Chat:** {text_user} ({text_count} messages)\n"
        f"🎙️ **Voice Chat:** {voice_user} ({voice_time} minutes)"
    )

@bot.command()
async def most_popular(ctx):
    scores = {}

    # -------- TEXT MESSAGES --------
    cursor.execute("""
        SELECT user_id, COUNT(*) 
        FROM activity
        GROUP BY user_id
    """)
    for user_id, msg_count in cursor.fetchall():
        scores[user_id] = scores.get(user_id, 0) + (msg_count * 0.5)

    # -------- MENTIONS --------
    cursor.execute("SELECT user_id, mention_count FROM popularity")
    for user_id, mentions in cursor.fetchall():
        scores[user_id] = scores.get(user_id, 0) + (mentions * 2)

    # -------- VOICE TIME --------
    cursor.execute("SELECT user_id, total_time FROM voice_activity")
    for user_id, total_time in cursor.fetchall():
        minutes = total_time // 60
        scores[user_id] = scores.get(user_id, 0) + minutes

    if not scores:
        await ctx.send("No data yet 📉")
        return

    # -------- TOP USER --------
    top_user_id = max(scores, key=scores.get)
    member = ctx.guild.get_member(top_user_id)

    if not member:
        await ctx.send("User not found")
        return

    await ctx.send(
        f"🌟 **Most Popular User** 🌟\n"
        f"👤 {member.display_name}\n"
        f"🏆 Popularity Score: **{int(scores[top_user_id])}**"
    )



@bot.command()
async def help(ctx):
    msg = (
        "🛡️ **RakshakX Security – Help Menu** 🛡️\n\n"

        "📊 **Analytics Commands**\n"
        "`!stats` → Total users & channels\n"
        "`!activity` → Active vs Inactive users\n"
        "`!who_active` → Active/Inactive user names\n"
        "`!dead_channels` → Inactive channels (14+ days)\n"
        "`!peak_time` → Most active hour\n"
        "`!server_health` → Full server report\n\n"

        "ℹ️ **Utility**\n"
        "`!help` → Show this menu\n\n"

        "🔐 *Only server data is analyzed. No messages are stored.*"
    )

    await ctx.send(msg)
@bot.command()
@commands.has_permissions(administrator=True)
@server_health.error
async def server_health_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need **Admin permission** to use this command.")






@bot.command()
async def stats(ctx):
    # total unique users
    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM activity")
    users = cursor.fetchone()[0]

    # total unique channels
    cursor.execute("SELECT COUNT(DISTINCT channel_id) FROM activity")
    channels = cursor.fetchone()[0]

    await ctx.send(
        f"📊 **Server Stats**\n"
        f"👤 Users tracked: {users}\n"
        f"💬 Channels tracked: {channels}"
    )


# -------- RUN BOT (LAST LINE) --------
bot.run(os.getenv("TOKEN"))
