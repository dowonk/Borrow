import os
import webserver
import requests
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

subreddit = "AskReddit"
url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=3"
CHANNEL_ID = 1488789667313614930

ids = []

@tasks.loop(seconds=30)
async def check_reddit():
	channel = bot.get_channel(CHANNEL_ID)
	if not channel:
		return

	try:
		response = requests.get(url)
		data = response.json()
		posts = data['data']['children']
	    
		for post in reversed(posts):
			post_data = post['data']
			post_id = post_data['name']
	        
			if post_id not in ids:
				link = f"https://www.reddit.com{post_data['permalink']}"
				
				print(f"New Post Found: {post_data['title']}")
				await channel.send(f"{title}\n{link}")
				ids.append(post_id)
	    
		if len(ids) > 3:
			ids = list(ids)[-3:]
	
	except Exception as e:
		print(f"Error: {e}")

@bot.event
async def on_ready():
	check_reddit.start()

@bot.command()
async def hello(ctx):
	await ctx.send('Hello!')

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
