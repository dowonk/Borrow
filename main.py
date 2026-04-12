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
RE_LOCATION = re.compile(r"us\)|usa|u\.s\.\)|united", re.IGNORECASE)
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
    if not loan_ids:
        report = "No loans found."

    loans = get_loan_details(loan_ids)
    valid = [
        loans[lid] for lid in loan_ids
        if lid in loans and loans[lid]["borrower"].lower() == username.lower()
    ]

    total_borrowed = sum(l["principal_minor"] for l in valid)
    report = f"**Total:** *${total_borrowed/100:.0f}*"

    in_progress = [
        (lid, loans[lid]) for lid in sorted(loan_ids, reverse=True)
        if lid in loans
        and loans[lid]["borrower"].lower() == username.lower()
        and not loans[lid]["repaid_at"]
        and not loans[lid]["unpaid_at"]
        and not loans[lid]["deleted_at"]
    ]

    if not in_progress:
        report += " | *No loans.*"
    else:
        report += f" | **In-progress ({len(in_progress)}):**"
        for loan_id, loan in in_progress:
            report += f" | *Loan #{loan_id} | {format_ts(loan['created_at'])} | "f"Principal: ${loan['principal_minor']/100:.0f} | "f"Repaid: ${loan['principal_repayment_minor']/100:.0f} | "f"Lender: u/{loan['lender']}*"

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

        activity = []
        async for item in redditor.new(limit=1000):
            sub_name = item.subreddit.display_name.lower()
            if sub_name in FORBIDDEN_SUBS:
                return sub_name
            activity.append(item)
        
        output = [f"**Karma:** *{karma}* | **Age:** *{format_time_ago(redditor.created_utc)}*"]
        output.append(check_loans(username) + "\n")

        if not activity:
            output.append("\n*No posts/comments found.*")
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
    if not channel:
        return

    try:
        subreddit = await reddit.subreddit("Borrow")
        history = ""
        async for m in channel.history(limit=10):
            if m.author == bot.user:
                history += m.content.lower()

        cutoff = time.time() - (12 * 60 * 60)

        async for post in subreddit.new(limit=5):
            if post.created_utc < cutoff:
                continue

            title = RE_COMMA.sub('', post.title.lower())
            if "req" not in title or "arranged" in title: continue
            if not RE_LOCATION.search(title): continue

            amount_match = RE_AMOUNT.search(title)
            if not amount_match or int(amount_match.group()) > 300: continue

            user_info = await get_reddit_user_info(post.author)
            if post.id.lower() in history: continue
            if not user_info or user_info in FORBIDDEN_SUBS: continue

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
        await redditor.load()

        karma = (redditor.link_karma or 0) + (redditor.comment_karma or 0)
        age = format_time_ago(redditor.created_utc)
        loan_report = check_loans(username)

        unique_subs = set()
        async for item in redditor.new(limit=1000):
            unique_subs.add(item.subreddit.display_name)

        if not unique_subs and karma == 0:
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
            f"Report for **/u/{username}**\n"
            f"**Karma:** *{karma}* | **Age:** *{age}*\n"
            f"{loan_report}\n\n"
            f"**Subreddits:**\n{safe_text}\n\n"
            f"**Forbidden Subreddits:**\n{forbidden_text}"
        )

        if len(response) <= 2000:
            await ctx.send(response)
        else:
            for i in range(0, len(response), 2000):
                await ctx.send(response[i:i+2000])

    except Exception as e:
        print(f"Error: {e}")

@bot.event
async def on_ready():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
        
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
