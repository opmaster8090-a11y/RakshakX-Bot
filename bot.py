import discord
from discord.ext import commands
import sqlite3, time, os, datetime
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS mention_activity (
    user_id INTEGER PRIMARY KEY,
    mention_count INTEGER DEFAULT 0
)
""")

db.commit()

# ---------- READY ----------
@bot.event
async def on_ready():
    print(f"[+] Bot logged in as {bot.user}")

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
        DO UPDATE SET last_seen=excluded.last_seen
    """, (message.author.id, message.channel.id, now))

    cursor.execute("""
        INSERT INTO message_activity (user_id, msg_count)
        VALUES (?, 1)
        ON CONFLICT(user_id)
        DO UPDATE SET msg_count = msg_count + 1
    """, (message.author.id,))

    for u in message.mentions:
        if not u.bot:
            cursor.execute("""
                INSERT INTO mention_activity (user_id, mention_count)
                VALUES (?, 1)
                ON CONFLICT(user_id)
                DO UPDATE SET mention_count = mention_count + 1
            """, (u.id,))

    db.commit()
    await bot.process_commands(message)

# ---------- VOICE TRACK ----------
@bot.event
async def on_voice_state_update(member, before, after):
    now = int(time.time())

    if before.channel is None and after.channel:
        cursor.execute("""
            INSERT INTO voice_activity (user_id, join_time)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET join_time=?
        """, (member.id, now, now))
        db.commit()

    if before.channel and after.channel is None:
        cursor.execute(
            "SELECT join_time, total_time FROM voice_activity WHERE user_id=?",
            (member.id,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            cursor.execute("""
                UPDATE voice_activity
                SET total_time=?, join_time=NULL
                WHERE user_id=?
            """, (row[1] + (now - row[0]), member.id))
            db.commit()

# ---------- COMMANDS ----------

@bot.command()
async def stats(ctx):
    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM activity")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT channel_id) FROM activity")
    channels = cursor.fetchone()[0]
    await ctx.send(f"📊 **Stats**\n👤 Users: {users}\n💬 Channels: {channels}")

@bot.command()
async def activity(ctx):
    now = int(time.time())
    week = 7*24*60*60
    cursor.execute("SELECT user_id, MAX(last_seen) FROM activity GROUP BY user_id")
    rows = cursor.fetchall()
    active = sum(1 for _, t in rows if now-t <= week)
    inactive = len(rows) - active
    await ctx.send(f"🟢 Active: {active}\n🔴 Inactive: {inactive}")

@bot.command()
async def who_active(ctx):
    now = int(time.time())
    week = 7*24*60*60
    cursor.execute("SELECT user_id, MAX(last_seen) FROM activity GROUP BY user_id")
    rows = cursor.fetchall()
    active, inactive = [], []
    for uid, t in rows:
        m = ctx.guild.get_member(uid)
        if not m: continue
        (active if now-t<=week else inactive).append(m.display_name)

    await ctx.send(
        "🟢 **Active Users**\n" + ("\n".join(active) or "None") +
        "\n\n🔴 **Inactive Users**\n" + ("\n".join(inactive) or "None")
    )

@bot.command()
async def dead_channels(ctx):
    now = int(time.time())
    limit = 14*24*60*60
    cursor.execute("SELECT channel_id, MAX(last_seen) FROM activity GROUP BY channel_id")
    dead=[]
    for cid,t in cursor.fetchall():
        ch=ctx.guild.get_channel(cid)
        if ch and now-t>limit:
            dead.append(ch.mention)
    await ctx.send("💀 Dead Channels:\n"+("\n".join(dead) if dead else "None"))

@bot.command()
async def peak_time(ctx):
    cursor.execute("SELECT last_seen FROM activity")
    rows = cursor.fetchall()
    if not rows:
        return await ctx.send("No data")
    hours=[datetime.datetime.fromtimestamp(r[0]).hour for r in rows]
    h,c=Counter(hours).most_common(1)[0]
    await ctx.send(f"⏰ Peak Time: {h}:00–{h}:59 ({c} msgs)")

@bot.command()
async def most_active(ctx):
    cursor.execute("SELECT user_id,msg_count FROM message_activity ORDER BY msg_count DESC LIMIT 1")
    text=cursor.fetchone()
    cursor.execute("SELECT user_id,total_time FROM voice_activity ORDER BY total_time DESC LIMIT 1")
    voice=cursor.fetchone()

    msg="🏆 **Most Active Users**\n\n"
    if text and ctx.guild.get_member(text[0]):
        msg+=f"📝 Text: {ctx.guild.get_member(text[0]).display_name} ({text[1]})\n"
    else: msg+="📝 Text: None\n"
    if voice and ctx.guild.get_member(voice[0]):
        msg+=f"🎙 Voice: {ctx.guild.get_member(voice[0]).display_name} ({voice[1]//60} min)"
    else: msg+="🎙 Voice: None"
    await ctx.send(msg)

@bot.command()
async def most_popular(ctx):
    score={}
    for u,c in cursor.execute("SELECT user_id,msg_count FROM message_activity"):
        score[u]=score.get(u,0)+c
    for u,t in cursor.execute("SELECT user_id,total_time FROM voice_activity"):
        score[u]=score.get(u,0)+(t//60)
    for u,m in cursor.execute("SELECT user_id,mention_count FROM mention_activity"):
        score[u]=score.get(u,0)+(m*3)

    if not score:
        return await ctx.send("No data yet")

    top=max(score,key=score.get)
    m=ctx.guild.get_member(top)
    await ctx.send(
        f"🌟 **Most Popular User** 🌟\n"
        f"👤 {m.display_name if m else 'Unknown'}\n"
        f"🔥 Score: {score[top]}"
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def server_health(ctx):
    await ctx.send("🩺 Server is **HEALTHY & ACTIVE**")
@bot.command()
async def info(ctx):
    embed = discord.Embed(
        title="🛡️ RakshakX Security Bot",
        description="Advanced Discord Analytics & Activity Monitoring Bot",
        color=0x0aff9d
    )

    embed.add_field(
        name="🤖 What this bot does",
        value=(
            "• Tracks **text & voice activity**\n"
            "• Finds **most active & popular users**\n"
            "• Shows **peak activity time**\n"
            "• Generates **server health reports**\n"
            "• Helps admins understand engagement"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 Main Commands",
        value=(
            "`!most_active` → Top text & voice user\n"
            "`!most_popular` → Overall popularity score\n"
            "`!peak_time` → Most active hour\n"
            "`!stats` → Server statistics\n"
            "`!server_health` → Admin-only report"
        ),
        inline=False
    )

    embed.add_field(
        name="👨‍💻 Creator / Researcher",
        value=(
            "**Yougenst(14 years old) Hacker** 🧠\n"
            "• Found **4 bugs in Epic Games Store** 🐞\n"
            "• **AIR-1 Rank** – TryHackMe (Weekly)\n"
            "• Cybersecurity • Bug Bounty • Pentesting"
        ),
        inline=False
    )

    embed.add_field(
        name="🔐 Privacy Notice",
        value=(
            "• No message content is stored\n"
            "• Only activity metadata is analyzed\n"
            "• Data is used for analytics only"
        ),
        inline=False
    )

    embed.set_footer(
        text="RakshakX Security • Built for hackers, by a hacker ⚔️"
    )

    await ctx.send(embed=embed)


# ---------- HELP ----------
@bot.command()
async def help(ctx):
    await ctx.send(
        "📊 **Analytics Commands**\n"
        "`!stats` → Total users & channels\n"
        "`!activity` → Active vs Inactive users\n"
        "`!who_active` → Active/Inactive user names\n"
        "`!dead_channels` → Inactive channels (14+ days)\n"
        "`!peak_time` → Most active hour\n"
        "`!server_health` → Full server report (admin)\n\n"
        "🏆 **Ranking**\n"
        "`!most_active` → Top text & voice user\n"
        "`!most_popular` → Most popular user\n\n"
        "🔐 Only server data is analyzed. No messages are stored."
    )

# ---------- RUN ----------
bot.run(os.getenv("TOKEN"))

