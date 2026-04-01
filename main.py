import discord
from discord.ext import commands

# 1. Setup Intents (Permissions)
intents = discord.Intents.default()
intents.message_content = True  # Allows the bot to read messages

# 2. Define the Bot and its command prefix
bot = commands.Bot(command_prefix="!", intents=intents)

# Event: Runs when the bot is online
@bot.event
async def on_ready():
		print(f'Logged in as {bot.user} (ID: {bot.user.id})')
		print('------')

# Command: Responds to !hello
@bot.command()
async def hello(ctx):
		await ctx.send('Hello there! I am your Python bot.')

# 3. Run the bot
# Replace 'YOUR_TOKEN_HERE' with the token from the Developer Portal
bot.run(os.environ['TOKEN'])
