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

CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994

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

def get_reddit_user_info(username, limit=5):
    session = requests.Session()
    session.headers.update({'User-Agent': 'Discord-Borrow-Bot-v1.0'})
    
    try:
        profile_res = session.get(f"https://www.reddit.com/user/{username}/about.json")
        profile_res.raise_for_status()
        p_data = profile_res.json()['data']
        
        user_id = p_data.get('id') 
        age_str = format_time_ago(p_data['created_utc'])
        karma = p_data.get('total_karma', 0)

        output = [f"[{karma}][{age_str}]"]

        activity_res = session.get(f"https://www.reddit.com/user/{username}/overview.json", params={'limit': limit})
        activity_res.raise_for_status()
        
        for item in activity_res.json()['data']['children']:
            data = item['data']
            time_ago = format_time_ago(data['created_utc'])
            sub = f"r/{data['subreddit']}"
            
            raw_content = data.get('title') or data.get('body', '')
            content = raw_content.replace('\n', ' ')[:80]
            
            output.append(f"[{time_ago}][{sub}] {content}")

        if user_id:
            output.append(f"<https://www.reddit.com/chat/user/t2_{user_id}>")
        
        return "\n".join(output)

    except Exception as e:
        return f"Error: {str(e)}"

@tasks.loop(seconds=10)
async def check_rborrow():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        feed = feedparser.parse(f"https://www.reddit.com/r/Borrow/new.rss?limit=3", agent="Discord-Borrow-Bot-v1.0")

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
                    user_info = get_reddit_user_info(username)
                    loan_link = f"https://redditloans.com/loans.html?username={username}"
                    usl_link = f"https://www.universalscammerlist.com/?username={username}"
                    
                    await channel.send(
                        f"<@{USER_ID}> {post_id}\n"
                        f"**{title}**\n"
                        f"<{post_link}>\n\n"
                        f"{user_info}\n\n"
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
    check_rborrow.start()

@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello!")

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
