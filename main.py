import os
import re
import time
import asyncpraw
import requests
import webserver
import discord
from discord.ext import commands, tasks
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

CHANNEL_ID = 1488789667313614930
USER_ID = 314300380051668994
INTERVALS = (('Y', 31536000), ('MO', 2592000), ('D', 86400), ('H', 3600), ('M', 60), ('S', 1))
FORBIDDEN_SUBS = {"borrownew", "loanhelp_", "loansharks", "loanspaydayonline", "simpleloans"}

RE_COMMA = re.compile(r'(?<=\d),')
RE_LOCATION = re.compile(r"\bu\.?s\.?\b|usa|state", re.IGNORECASE)
RE_AMOUNT = re.compile(r"\d+")

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

def get_loan_details(loan_ids, max_workers=20):
    results = {}
    url_template = "https://redditloans.com/api/loans/{}"
    headers = {"User-Agent": "Discord-Borrow-Bot-v1"}

    with requests.Session() as session:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_loan = {
                executor.submit(session.get, url_template.format(lid), headers=headers): lid 
                for lid in loan_ids
            }

            for future in as_completed(future_to_loan):
                loan_id = future_to_loan[future]
                try:
                    resp = future.result()
                    if resp.status_code == 200:
                        results[loan_id] = resp.json()
                except:
                    pass

    return results

def format_ts(ts):
    if ts is None:
        return "N/A"
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")

def check_loans(username):
    loan_ids = requests.get(
        f"https://redditloans.com/api/loans",
        params={"borrower_name": username, "limit": 100, "order": "id_desc"},
        headers={"User-Agent": "Discord-Borrow-Bot-v1"}
    ).json()

    all_loans = get_loan_details(loan_ids).values()

    valid = [
        loan for loan in all_loans 
        if loan["borrower"].lower() == username.lower()
    ]

    total_borrowed = sum(l["principal_minor"] for l in valid)
    report = f"**Total:** *${total_borrowed/100:.0f}*"

    in_progress = [
        loan for loan in valid
        if not loan["repaid_at"]
        and not loan["unpaid_at"]
        and not loan["deleted_at"]
    ]

    if not in_progress:
        report += " | *None*"
    else:
        report += f" | **In-progress ({len(in_progress)}):**"
        for loan in in_progress:
            report += (
                f" *${loan['principal_minor']/100:.0f} | "
                f"Lender: {loan['lender']} |*"
            )

    return report

def format_time_ago(timestamp):
    diff = int(time.time() - timestamp)
    for label, seconds in INTERVALS:
        if diff >= seconds:
            return f"{diff // seconds}{label}"
    return "0s"

async def get_reddit_user_info(redditor):
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
        
    try:
        await redditor.load()
        username = redditor.name 
        karma = (redditor.link_karma or 0) + (redditor.comment_karma or 0)
        age = format_time_ago(redditor.created_utc)

        activity = []
        async for item in redditor.new(limit=1000):
            sub_name = item.subreddit.display_name.lower()
            if sub_name in FORBIDDEN_SUBS:
                return sub_name
            elif sub_name != "borrow":
                activity.append(item)
        
        output = [f"**Karma:** *{karma}* | **Age:** *{age}*"]
        output.append(check_loans(username) + "\n")

        if not activity:
            output.append("*Hidden profile*")
        else:
            for item in activity[:5]:
                text = getattr(item, 'title', getattr(item, 'body', ''))
                text = text.replace('\n', ' ')[:100]
                output.append(f"[{format_time_ago(item.created_utc)}] **r/{item.subreddit.display_name}** *{text}...*")

        links = [
            f"\n**Profile:** <https://www.reddit.com/user/{username}>",
            f"**DM:** <https://www.reddit.com/chat/user/t2_{redditor.id}>",
            f"**Posts:** <https://www.reddit.com/r/borrow/search?q=author%3A{username}&include_over_18=on&sort=new&t=all>",
            f"**Loans:** <https://redditloans.com/loans.html?username={username}>",
            f"**USL:** <https://www.universalscammerlist.com/?username={username}>"
        ]
        return "\n".join(output + links)
        
    except Exception as e:
        print(f"Error: {e}")
        return None

@tasks.loop(seconds=1)
async def check_rborrow():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return

    try:
        subreddit = await reddit.subreddit("Borrow")
        
        history = ""
        async for m in channel.history(limit=10):
            if m.author == bot.user:
                history += m.content.lower()

        cutoff = time.time() - (12 * 60 * 60)

        async for post in subreddit.new(limit=5):
            if post.created_utc < cutoff:continue
            if post.id.lower() in history: continue

            title = RE_COMMA.sub('', post.title.lower())
            if "req" not in title or "arranged" in title: continue
            if not RE_LOCATION.search(title): continue

            amount_match = RE_AMOUNT.search(title)
            if not amount_match or int(amount_match.group()) > 300: continue

            user_info = await get_reddit_user_info(post.author)
            if user_info is None or user_info in FORBIDDEN_SUBS: continue

            selftext = f"*{post.selftext}*" if post.selftext else ""
            prearranged_text = ["pre arranged", "prearranged", "pre-arranged"]
            if any(text in selftext.lower() for text in prearranged_text): continue

            message = (
                f"<@{USER_ID}> {post.id}\n"
                f"**{post.title}**\n"
                f"{selftext[:500]}\n"
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
        try:
            await redditor.load()
        except Exception:
            return await ctx.send(f"**/u/{username}** not found.")

        karma = (redditor.link_karma or 0) + (redditor.comment_karma or 0)
        age = format_time_ago(redditor.created_utc)
        loan_report = check_loans(username)

        unique_subs = set()
        async for item in redditor.new(limit=1000):
            unique_subs.add(item.subreddit.display_name)

        if not unique_subs:
            report = (
                f"Report for **/u/{username}**\n"
                f"**Karma:** *{karma}* | **Age:** *{age}*\n"
                f"{loan_report}\n\n"
                f"No activity found for **/u/{username}**."
            )
            return await ctx.send(report)

        subreddit_list = []
        forbidden_list = []

        for sub in sorted(list(unique_subs), key=lambda s: s.lower()):
            if sub.lower() in FORBIDDEN_SUBS:
                forbidden_list.append(f"{sub}")
            else:
                subreddit_list.append(f"{sub}")

        subreddit_report = ", ".join(subreddit_list) if subreddit_list else "None"
        forbidden_report = ", ".join(forbidden_list) if forbidden_list else "None"

        report = (
            f"Report for **/u/{username}**\n"
            f"**Karma:** *{karma}* | **Age:** *{age}*\n"
            f"{loan_report}\n\n"
            f"**Subreddits:**\n{subreddit_report}\n\n"
            f"**Forbidden Subreddits:**\n{forbidden_report}"
        )

        if len(report) <= 2000:
            await ctx.send(report)
        else:
            for i in range(0, len(report), 2000):
                await ctx.send(report[i:i+2000])

    except Exception as e:
        print(f"Error: {e}")

@bot.event
async def on_ready():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return
        
    global reddit
    reddit = asyncpraw.Reddit(
        client_id=os.environ['CLIENT_ID'],
        client_secret=os.environ['CLIENT_SECRET'],
        user_agent="Discord-Borrow-Bot-v1"
    )
    
    if not check_rborrow.is_running():
        check_rborrow.start()

    await channel.send("Booted up!")
    
webserver.keep_alive()
bot.run(os.environ['TOKEN'])
