import os
import re
import webserver
import feedparser
import discord
from discord.ext import commands, tasks

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

RSS_URL = f"https://www.reddit.com/r/Borrow/new.rss?limit=3"
CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994

@tasks.loop(seconds=10)
async def check_reddit():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        feed = feedparser.parse(RSS_URL, agent="Discord-Borrow-Bot-v1.0")

        for entry in feed.entries:
            messages = []
            
            async for msg in channel.history(limit=10):
                if msg.author == bot.user:
                    messages.append(msg.content.lower())
            
                if len(messages) == 10:
                    break
            
            post_id = entry.id.split('/')[-1]
            
            if any(post_id in msg for msg in messages):
                continue
            
            title = entry.title
            title_lower = title.lower()
            
            if (
                "req" in title_lower
                and "arranged" not in title_lower
                and ("us)" in title_lower or "usa)" in title_lower or "u.s.)" in title_lower or "u.s.a)" in title_lower or "united" in title_lower)
            ):
                amount = int(re.search(r"\d+", title).group())
                
                if amount <= 200:
                    post_link = entry.link
                    username = entry.author.replace("/u/", "")
                    loan_link = f"https://redditloans.com/loans.html?username={username}"
                    usl_link = f"https://www.universalscammerlist.com/?username={username}"
                    
                    await channel.send(f"<@{USER_ID}>\n{post_id}\n{title}\n<{post_link}>\n{loan_link}\n{usl_link}")
                            
    except Exception as e:
        print(f"Error: {e}")

@bot.event
async def on_ready():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
        
    print("Booted up!")
    await channel.send("Booted up!")
    check_reddit.start()

@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello!")

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
