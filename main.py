import os
import re
import time
from datetime import datetime, timedelta
import asyncio
import asyncpraw
import webserver
import discord
from discord.ext import commands, tasks


CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994
INTERVALS = (('Y', 31536000), ('MO', 2592000), ('D', 86400), ('H', 3600), ('M', 60), ('S', 1))

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

def format_time_ago(timestamp):
    diff = int(time.time() - timestamp)
    for label, seconds in INTERVALS:
        if diff >= seconds:
            return f"{diff // seconds}{label}"
    return "0s"

async def get_reddit_user_info(redditor):
    try:
        await redditor.load()
        TRACKED_SUBS = {"borrownew", "loanhelp_", "loansharks", "simpleloans"}
        karma = (redditor.link_karma or 0) + (redditor.comment_karma or 0)

        activity = []
        async for item in redditor.new(limit=1000):
            activity.append(item)
            if item.subreddit.display_name.lower() in TRACKED_SUBS:
                continue

        output = [f"**Karma:** *{karma}*\n**Age:** *{format_time_ago(redditor.created_utc)}*\n"]

        if not activity:
            output.append("*No posts/comments found.*")
        else:
            for item in activity[:5]:
                text = getattr(item, 'title', getattr(item, 'body', ''))
                text = text.replace('\n', ' ')[:100]
                output.append(f"[{format_time_ago(item.created_utc)}] **r/{item.subreddit.display_name}** *{text}...*")

        links = [
            f"\n**Profile:** <https://www.reddit.com/user/{redditor.name}>",
            f"**DM:** <https://www.reddit.com/chat/user/t2_{redditor.id}>",
            f"**Loans:** <https://redditloans.com/loans.html?username={redditor.name}>",
            f"**USL:** <https://www.universalscammerlist.com/?username={redditor.name}>"
        ]
        return "\n".join(output + links)
        
    except Exception as e:
        print(f"Error: {e}")

@tasks.loop(seconds=10)
async def check_rborrow():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return

    try:
        subreddit = await reddit.subreddit("Borrow")
        history = [m.content.lower() async for m in channel.history(limit=5) if m.author == bot.user]

        now = time.time()
        twelve_hours_ago = now - (12 * 60 * 60)

        async for post in subreddit.new(limit=3):
            if post.created_utc < twelve_hours_ago:
                continue
                
            title = post.title.lower()
            if "req" in title and "arranged" not in title and re.compile(r"(us\)|usa|u\.s\.\)|united)").search(title) and post.id not in "".join(history):
                amount_match = re.compile(r"\d+").search(title)
                amount = int(amount_match.group())
                if amount_match and amount <= 300:
                    selftext = f"\n{post.selftext}" if post.selftext else ""
                    user_info = await get_reddit_user_info(post.author)
                    if user_info == None:
                        continue
                    
                    await channel.send(f"<@{USER_ID}> {post.id}\n**{post.title}**{selftext}\n<{post.url}>\n\n{user_info}")
                    
    except Exception as e:
        print(f"Error: {e}")

@bot.event
async def on_ready():
    global reddit
    reddit = asyncpraw.Reddit(
        client_id=os.environ['CLIENT_ID'],
        client_secret=os.environ['CLIENT_SECRET'],
        user_agent="Discord-Borrow-Bot-v1"
    )
    
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return
        
    check_rborrow.start()
    await channel.send("Booted up!")

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
