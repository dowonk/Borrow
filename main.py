import os
import re
import webserver
import feedparser
import discord
from discord.ext import commands, tasks

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

SUBREDDIT = "Borrow"
RSS_URL = f"https://www.reddit.com/r/{SUBREDDIT}/new.rss?limit=3"
CHANNEL_ID = 1488789667313614930
TARGET_USER_ID = 314300380051668994

ids = []

@tasks.loop(seconds=30)
async def check_reddit():
    global ids
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        feed = feedparser.parse(RSS_URL, agent="Discord-Borrow-Bot-v1.0")

        for entry in feed.entries:
            post_id = entry.id

            if post_id not in ids:
                title = entry.title
                title_lower = title.lower()
                link = entry.link

                if (
                    "[req]" in title_lower
                    and "arranged" not in title_lower
                    and "ca)" not in title_lower
                    and "can)" not in title_lower
                ):
                    amount_match = re.search(r"\$(\d+)", title)

                    if amount_match:
                        amount = int(amount_match.group(1))

                        if amount <= 200:
                            print(f"Match Found: {title}")
                            mention = f"<@{TARGET_USER_ID}>"
                            await channel.send(f"{mention} {title}\n{link}")

                    ids.append(post_id)

        if len(ids) > 3:
            ids = ids[-3:]

    except Exception as e:
        print(f"Error: {e}")

@bot.event
async def on_ready():
    print("Running")
    check_reddit.start()

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
