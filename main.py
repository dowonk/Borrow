import os
import re
import time
import praw
import discord
import webserver
from discord.ext import commands, tasks

CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994

reddit = praw.Reddit(
    client_id=os.environ['CLIENT_ID'],
    client_secret=os.environ['CLIENT_SECRET'],
    user_agent="Discord-Borrow-Bot-v1.1 by /u/YourUsername"
)

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

def get_reddit_user_info(redditor):
    try:
        total_karma = redditor.link_karma + redditor.comment_karma
        tracked_subs = {"borrownew", "simpleloans", "borrow"}
        
        activity_count = 0
        for item in redditor.new:
            if item.subreddit.display_name.lower() in tracked_subs:
                activity_count += 1

        output = [
            f"**Karma:** {total_karma} | **Age:** {format_time_ago(redditor.created_utc)}",
            f"**Activity in {', '.join(tracked_subs)} (Last 100):** {activity_count}",
            "\n**Recent Activity:**"
        ]

        for item in redditor.new(limit=5):
            content = (getattr(item, 'title', '') or getattr(item, 'body', ''))
            content = content.replace('\n', ' ')[:100]
            output.append(f"[{format_time_ago(item.created_utc)}] **r/{item.subreddit.display_name}** *{content}*")

        # 3. Append Links
        output.extend([
            f"\n**Profile:** <https://www.reddit.com/user/{redditor.name}>",
            f"**DM:** <https://www.reddit.com/chat/user/t2_{redditor.id}>",
            f"**Loans:** <https://redditloans.com/loans.html?username={redditor.name}>",
            f"**USL:** <https://www.universalscammerlist.com/?username={redditor.name}>"
        ])

        return "\n".join(output)

    except Exception:
        return "⚠️ *User info unavailable (Account may be deleted or shadow-banned).* "

@tasks.loop(seconds=30)
async def check_rborrow():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        subreddit = reddit.subreddit("Borrow")
        history = [m.content.lower() async for m in channel.history(limit=5) if m.author == bot.user]

        for submission in subreddit.new(limit=3):
            title = submission.title.lower()
            post_id = submission.id

            is_req = "req" in title
            is_not_arranged = "arranged" not in title
            is_us = re.search(r"(us\)|usa\)|u\.s\.\)|united)", title)
            is_new = not any(post_id in msg for msg in history)

            if is_req and is_not_arranged and is_us and is_new:
                amount_match = re.search(r"\d+", title)
                if amount_match:
                    amount = int(amount_match.group())

                    if amount <= 200:
                        user_data = get_reddit_user_info(submission.author)

                        message = (
                            f"<@{USER_ID}> `{post_id}`\n"
                            f"**{submission.title}**\n"
                            f"<{submission.url}>\n\n"
                            f"{user_data}"
                        )
                        await channel.send(message)

    except Exception as e:
        print(f"Error in background task: {e}")

@bot.event
async def on_ready():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    await channel.send("Booted up")
    check_rborrow.start()

@bot.command()
async def hello(ctx):
    await ctx.send("Hello!")

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
