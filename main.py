import os
import re
import webserver
import feedparser
import requests
import discord
from discord.ext import commands, tasks
from datetime import datetime

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

RSS_URL = f"https://www.reddit.com/r/Borrow/new.rss?limit=3"
CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994

def get_reddit_user_stats(username):
    json_url = f"https://www.reddit.com/user/{username}/about.json"
    
    try:
        response = requests.get(json_url, headers={'User-Agent': 'Profile-Checker/1.0'})
        data = response.json()['data']

        total_karma = data.get('total_karma')
        created_utc = data.get('created_utc')
        creation_date = datetime.fromtimestamp(created_utc)
        now = datetime.now()
        
        years = now.year - creation_date.year
        months = now.month - creation_date.month
        days = now.day - creation_date.day

        if days < 0:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        
        age_string = f"{years}y, {months}m"
        if years == 0:
            age_string = f"{months} months"
        
        return (f"Karma: {total_karma} Age: {age_string}")

    except Exception as e:
        print(f"Error: {e}")

@tasks.loop(seconds=10)
async def check_reddit():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        feed = feedparser.parse(RSS_URL, agent="Discord-Borrow-Bot-v1.0")

        for entry in feed.entries:
            messages = []
            
            async for msg in channel.history(limit=5):
                if msg.author == bot.user:
                    messages.append(msg.content.lower())
            
                if len(messages) == 5:
                    break
            
            post_id = entry.id.split('/')[-1]
            
            if any(post_id in msg for msg in messages):
                continue
            
            title = entry.title
            title_lower = title.lower()
            
            if (
                "req" in title_lower
                and "arranged" not in title_lower
                and ("us)" in title_lower or "usa)" in title_lower or "u.s.)" in title_lower or "u.s.a)" in title_lower or "u.s.a.)" in title_lower or "united" in title_lower)
            ):
                amount = int(re.search(r"\d+", title).group())
                
                if amount <= 200:
                    post_link = entry.link
                    username = entry.author.replace("/u/", "")
                    user_stats = get_reddit_user_stats(username)
                    loan_link = f"https://redditloans.com/loans.html?username={username}"
                    usl_link = f"https://www.universalscammerlist.com/?username={username}"
                    
                    await channel.send(f"<@{USER_ID}>\n{post_id}\n{user_stats}\n{title}\n<{post_link}>\n{loan_link}\n<{usl_link}>")
                            
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
