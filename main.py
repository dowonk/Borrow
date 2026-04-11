import os
import re
import time
import asyncio
import asyncpraw
import webserver
import subprocess
import discord
from discord.ext import commands, tasks
from playwright.sync_api import sync_playwright

CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994
INTERVALS = (('Y', 31536000), ('MO', 2592000), ('D', 86400), ('H', 3600), ('M', 60), ('S', 1))
FORBIDDEN_SUBS = {"borrownew", "loanhelp_", "loansharks", "loanspaydayonline", "simpleloans"}

RE_COMMA = re.compile(r'(?<=\d),')
RE_LOCATION = re.compile(r"us\)|usa|u\.s\.\)|united", re.IGNORECASE)
RE_AMOUNT = re.compile(r"\d+")

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

def get_chromium_path():
    try:
        result = subprocess.run(["which", "chromium"], capture_output=True, text=True)
        path = result.stdout.strip()
        if path:
            return path
    except Exception:
        pass
    return None

def get_usl_user(username):
    url = f"https://www.universalscammerlist.com/?username={username}"
    chromium_path = get_chromium_path()

    with sync_playwright() as p:
        launch_kwargs = {"headless": True}
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path

        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            user_agent=(
                "Discord-Borrow-Bot-v1"
            )
        )
        page = context.new_page()
        page.goto(url, wait_until="load", timeout=15000)

        try:
            page.wait_for_function(
                "document.getElementById('userStatus').innerText.trim() !== ''",
                timeout=12000
            )
        except Exception:
            pass

        status = page.inner_text("#userStatus").strip()
        history_items = page.query_selector_all("#userHistory li")
        confirmations = page.query_selector_all("#userConfirmations li")

        try:
            loading_msg = page.inner_text("#loadingMessage").strip()
        except Exception:
            loading_msg = ""

        results = []
        if status:
            results.append(f"Status: {status}")
        for item in history_items:
            results.append(item.inner_text().strip())
        for item in confirmations:
            results.append(item.inner_text().strip())

        browser.close()

        if not results:
            if loading_msg:
                results.append(f"Loading error: {loading_msg}")
            else:
                results.append(
                    "No data returned — Reddit's API may be blocking requests from this server's IP."
                )

        return results

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

        usl_table = []
        usl_data = get_usl_user(redditor)
        for entry in usl_data:
            usl_table.append(entry)
        usl_report = "\n".join(usl_table)

        output = [
            f"**Karma:** *{karma}*",
            f"**Age:** *{format_time_ago(redditor.created_utc)}*\n",
            f"{usl_report}\n"
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
            f"**Posts:** <https://www.reddit.com/r/borrow/search?q=author%3A{redditor.name}&include_over_18=on&sort=new&t=all>",
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
            prearranged_text = ["pre arranged", "prearranged", "pre-arranged"]

            if any(text in selftext.lower() for text in prearranged_text):
                continue
                
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

        if len(response) <= 2000:
            await ctx.send(response)
        else:
            while len(response) > 0:
                chunk = response[:2000]
                await ctx.send(chunk)
                response = response[2000:]

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
