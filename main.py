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

def get_reddituser_age_karma(username):
    json_url = f"https://www.reddit.com/user/{username}/about.json"
    
    try:
        response = requests.get(json_url, headers={'User-Agent': 'Discord-Borrow-Bot-v1.0'})
        data = response.json()['data']

        total_karma = data.get('total_karma')
        created_utc = data.get('created_utc')
        
        years = datetime.now().year - datetime.fromtimestamp(created_utc).year
        months = datetime.now().month - datetime.fromtimestamp(created_utc).month
        days = datetime.now().day - datetime.fromtimestamp(created_utc).day

        if days < 0:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        
        age_string = f"{years}Y{months}M"
        if years == 0:
            age_string = f"{months}M"
        
        return (f"[{age_string}] [{total_karma}]")

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
            title = entry.title.lower()
            
            if (
                "req" in title
                and "arranged" not in title
                and ("us)" in title or "usa)" in title or "u.s.)" in title or "u.s.a)" in title or "u.s.a.)" in title or "united" in title)
            ):
                amount = int(re.search(r"\d+", title).group())
                
                if amount <= 200:
                    messages = []
                    
                    async for msg in channel.history(limit=5):
                        if msg.author == bot.user:
                            messages.append(msg.content.lower())
                    
                        if len(messages) == 5:
                            break
                    
                    post_id = entry.id.split('/')[-1]
                    
                    if any(post_id in msg for msg in messages):
                        continue
                
                    post_link = entry.link
                    username = entry.author.replace("/u/", "")
                    age_karma = get_reddituser_age_karma(username)
                    loan_link = f"https://redditloans.com/loans.html?username={username}"
                    usl_link = f"https://www.universalscammerlist.com/?username={username}"
                    
                    await channel.send(
                        f"<@{USER_ID}>\n"
                        f"**{age_karma}** {post_id}\n"
                        f"{title}\n"
                        f"<{post_link}>\n"
                        f"{loan_link}\n"
                        f"<{usl_link}>"
                    )
                    
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
