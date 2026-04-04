import os
import re
import time
import webserver
import requests
import feedparser
import discord
from discord.ext import commands, tasks

CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Discord-Borrow-Bot-v1.0'})

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

INTERVALS = (
    ('Y', 31536000), ('MO', 2592000), ('D', 86400),
    ('H', 3600), ('M', 60), ('S', 1)
)

def format_time_ago(timestamp):
    diff = int(time.time() - timestamp)
    for label, seconds in INTERVALS:
        if diff >= seconds:
            return f"{diff // seconds}{label}"
    return "0s"

def reddit_user_info(username, limit=5):
    try:
        p_res = SESSION.get(f"https://www.reddit.com/user/{username}/about.json").json()['data']
        output = [f"**Karma:** {p_res.get('total_karma', 0)} **Age:** {format_time_ago(p_res['created_utc'])}\n"]

        a_res = SESSION.get(f"https://www.reddit.com/user/{username}/overview.json?limit=5", params={'limit': limit}).json()
        for item in a_res['data']['children']:
            d = item['data']
            content = (d.get('title') or d.get('body', '')).replace('\n', ' ')[:100]
            output.append(f"[{format_time_ago(d['created_utc'])}] **r/{d['subreddit']}** *{content}*")

        output.append(f"\n**Profile:** <https://www.reddit.com/user/{username}>")
        output.append(f"\n**DM:** <https://www.reddit.com/chat/user/t2_{p_res['id']}>")
        output.append(f"**Loans:** https://redditloans.com/loans.html?username={username}")
        output.append(f"**USL:** <https://www.universalscammerlist.com/?username={username}>")
        
        return "\n".join(output)
    except:
        return "Error fetching user info"

@tasks.loop(seconds=10)
async def check_rborrow():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return

    try:
        feed = feedparser.parse("https://www.reddit.com/r/Borrow/new.rss?limit=3", agent="Discord-Borrow-Bot-v1.0")
        history = [m.content.lower() async for m in channel.history(limit=5) if m.author == bot.user]

        for entry in feed.entries:
            title = entry.title.lower()
            post_id = entry.id.split('/')[-1]

            if ("req" in title and "arranged" not in title and 
                re.search(r"(us\)|usa\)|u\.s\.\)|united)", title) and 
                not any(post_id in msg for msg in history)):
                
                amount_match = re.search(r"\d+", title)
                if amount_match and int(amount_match.group()) <= 200:
                    username = entry.author.replace("/u/", "")
                    
                    await channel.send(
                        f"<@{USER_ID}> {post_id}\n"
                        f"**{entry.title}**\n"
                        f"<{entry.link}>\n\n"
                        f"{reddit_user_info(username)}\n"
                    )
                    
    except Exception as e:
        print(f"Error: {e}")

@bot.event
async def on_ready():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return
        
    await channel.send('Booted up!')
    check_rborrow.start()

@bot.command()
async def hello(ctx):
    await ctx.send("Hello!")

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
