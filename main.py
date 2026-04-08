import os
import re
import time
import asyncio
import asyncpraw
import webserver
import discord
from discord.ext import commands, tasks

CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994
INTERVALS = (('Y', 31536000), ('MO', 2592000), ('D', 86400), ('H', 3600), ('M', 60), ('S', 1))
FORBIDDEN_SUBS = {"borrownew", "loanhelp_", "loansharks", "loanspaydayonline", "simpleloans"}

RE_COMMA = re.compile(r'(?<=\d),')
RE_LOCATION = re.compile(r"us\)|usa|u\.s\.\)|united", re.IGNORECASE)
RE_AMOUNT = re.compile(r"\d+")

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
        karma = (redditor.link_karma or 0) + (redditor.comment_karma or 0)
        
        activity = []
        async for item in redditor.new(limit=1000):
            sub_name = item.subreddit.display_name.lower()
            if sub_name in FORBIDDEN_SUBS:
                return sub_name
            activity.append(item)

        output = [
            f"**Karma:** *{karma}*",
            f"**Age:** *{format_time_ago(redditor.created_utc)}*\n"
        ]

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
        return None

@tasks.loop(seconds=1)
async def check_rborrow():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        subreddit = await reddit.subreddit("Borrow")
        history = "".join([m.content.lower() async for m in channel.history(limit=5) if m.author == bot.user])
        
        cutoff = time.time() - (12 * 60 * 60)

        async for post in subreddit.new(limit=3):
            if post.created_utc < cutoff:
                continue

            title = RE_COMMA.sub('', post.title.lower())
            
            if "req" not in title or "arranged" in title:
                continue
            
            if not RE_LOCATION.search(title) or post.id in history:
                continue

            amount_match = RE_AMOUNT.search(title)
            if not amount_match or int(amount_match.group()) > 300:
                continue

            user_info = await get_reddit_user_info(post.author)
            if not user_info or user_info in FORBIDDEN_SUBS:
                continue
            
            selftext = f"*{post.selftext}*" if post.selftext else ""
            message = (
                f"<@{USER_ID}> {post.id}\n"
                f"**{post.title}**\n"
                f"{selftext}\n"
                f"<{post.url}>\n\n"
                f"{user_info}"
            )
            await channel.send(message)
                    
    except Exception as e:
        print(f"Error: {e}")

@bot.command()
async def check(ctx, username: str):
    try:
        await ctx.send(f"Checking **/u/{username}**...")
        
        redditor = await reddit.redditor(username)
        unique_subs = set()

        async for item in redditor.new(limit=1000):
            unique_subs.add(item.subreddit.display_name)

        if not unique_subs:
            return await ctx.send(f"No activity found for **/u/{username}**.")

        safe_subs = []
        found_forbidden = []

        for sub in sorted(list(unique_subs), key=lambda s: s.lower()):
            if sub.lower() in FORBIDDEN_SUBS:
                found_forbidden.append(f"{sub}")
            else:
                safe_subs.append(f"{sub}")

        safe_text = ", ".join(safe_subs) if safe_subs else "None"
        forbidden_text = ", ".join(found_forbidden) if found_forbidden else "None"

        response = (
            f"Activity Report for **/u/{username}**\n\n"
            f"**Subreddits:**\n{safe_text}\n\n"
            f"**Forbidden Subreddits:**\n{forbidden_text}"
        )

        if len(response) > 2000:
            await ctx.send("Output is too long for one message. Sending a truncated version.")
            await ctx.send(response[:1990] + "...")
        else:
            await ctx.send(response)

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
    if not channel:
        return

    await channel.send("Booted up!")
    
    if not check_rborrow.is_running():
        check_rborrow.start()

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
