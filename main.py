import os
import re
import time
import requests
import asyncpraw
import webserver
import discord
from discord.ext import commands, tasks
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

FORBIDDEN_SUBS = ["borrownew", "loanhelp_", "loansharks", "loanspaydayonline", "simpleloans"]
HISTORY_IDS = []
INTERVALS = (('Y', 31536000), ('MO', 2592000), ('D', 86400), ('H', 3600), ('M', 60), ('S', 1))
LOCATIONS = ["usa", "u.s.a", "u.s.a.", "u.s.", "u.s", "us)", "state"]
PREARRANGED_WORDS = ["pre ", "pre-", "arrange"]
PREARRANGED_SELFTEXT = ["pre arranged", "prearranged", "pre-arranged"]
RE_AMOUNT = re.compile(r"\d+")
RE_HISTORY = re.compile(r'\[(.*?)\]')

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

def get_loans(username, max_workers=20):
    headers = {"User-Agent": "Discord-Borrow-Bot-v1"}
    results = {}

    with requests.Session() as session:
        loan_ids = session.get(
            "https://redditloans.com/api/loans",
            params={"borrower_name": username, "limit": 10, "order": "id_desc"},
            headers=headers
        ).json()

        url_template = "https://redditloans.com/api/loans/{}"
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

    valid = [
        loan for loan in results.values() 
        if loan["borrower"].lower() == username.lower()
    ]

    total_borrowed = sum(l["principal_minor"] for l in valid)
    loans_report = f"**Total:** *${total_borrowed/100:.0f}*"

    in_progress = [
        loan for loan in valid
        if not loan["repaid_at"]
        and not loan["unpaid_at"]
        and not loan["deleted_at"]
    ]

    loans_report += " | **Open:**"

    if not in_progress:
        loans_report += f" *$0*"
    if in_progress:
        for loan in in_progress:
            loans_report += f" *${loan['principal_minor']/100:.0f}*"

    return loans_report

def format_time_ago(timestamp):
    diff = int(time.time() - timestamp)
    for label, seconds in INTERVALS:
        if diff >= seconds:
            return f"{diff // seconds}{label}"
    return "0s"

async def get_user_info(redditor):
    try:
        await redditor.load()
        username = redditor.name 
        karma = redditor.link_karma + redditor.comment_karma
        age = format_time_ago(redditor.created_utc)

        activity = []
        async for item in redditor.new(limit=100):
            sub_name = item.subreddit.display_name.lower()
            if sub_name in FORBIDDEN_SUBS:
                return None
            elif sub_name != "borrow":
                activity.append(item)

        try:
            moderated_subs = await redditor.moderated()
            if not moderated_subs:
                user_report = [f"{get_loans(username)} | **Karma:** *{karma}* | **Age:** *{age}* | **Moderating:** *None*\n"]
            else:
                user_report = [f"{get_loans(username)} | **Karma:** *{karma}* | **Age:** *{age}* | **Moderating:** *" + ", ".join([f"{s.display_name}" for s in moderated_subs]) + "*\n"]
        except Exception as e:
            print(f"Error getting moderated subs: {e}")

        if not activity:
            user_report.append("*Hidden profile*")
        else:
            for item in activity[:5]:
                text = getattr(item, 'title', getattr(item, 'body', ''))
                text = text.replace('\n', ' ')[:100]
                user_report.append(f"[{format_time_ago(item.created_utc)}] **r/{item.subreddit.display_name}** *{text}*")

        links = [
            f"\n**DM:** <https://www.reddit.com/chat/user/t2_{redditor.id}>",
            f"**Profile:** <https://www.reddit.com/user/{username}>",
            f"**Posts:** <https://www.reddit.com/r/borrow/search?q=author%3A{username}&include_over_18=on&sort=new&t=all>",
            f"**Loans:** <https://redditloans.com/loans.html?username={username}>",
            f"**USL:** <https://www.universalscammerlist.com/?username={username}>"
        ]
        return "\n".join(user_report + links)

    except Exception as e:
        print(f"Error in get_user_info: {e}")
        return None

@tasks.loop(seconds=1)
async def check_posts():
    try:
        subreddit = await REDDIT.subreddit("Borrow")

        async for post in subreddit.new(limit=3):
            if post.created_utc < time.time() - (60 * 60) or post.id in HISTORY_IDS:
                continue

            title = post.title.lower()
            if ("req" not in title or 
                any(word in title for word in PREARRANGED_WORDS) or 
                not any(word in title for word in LOCATIONS)):
                continue

            amount_match = RE_AMOUNT.search(title)
            if not amount_match or int(amount_match.group()) > 500: continue

            user_info = await get_user_info(post.author)
            if (user_info is None or 
                any(text in post.selftext.lower() for text in PREARRANGED_SELFTEXT)):
                continue

            HISTORY_IDS.append(post.id)
            if len(HISTORY_IDS) > 3: HISTORY_IDS.pop(0)

            selftext = f"{post.selftext}" if post.selftext else "None"

            message = (
                f"<@314300380051668994> [{post.id}]\n"
                f"**{post.title}**\n"
                f"*{selftext[:500]}*\n"
                f"<{post.url}>\n\n"
                f"{user_info}"
            )
            await MAIN_CHANNEL.send(message)
            await check.callback(None, str(post.author))

    except Exception as e:
        print(f"Error in check_posts: {e}")

@bot.command()
async def check(ctx, username: str):
    try:
        redditor = await REDDIT.redditor(username)
        try:
            await redditor.load()
        except Exception:
            return await CHECK_CHANNEL.send(f"**/u/{username}** not found.")

        karma = redditor.link_karma + redditor.comment_karma
        age = format_time_ago(redditor.created_utc)
        user_loans = get_loans(username)

        try:
            moderated_subs = await redditor.moderated()
            if not moderated_subs:
                moderated_list = "None"
            else:
                moderated_list = ", ".join([f"{s.display_name}" for s in moderated_subs])
        except Exception as e:
            print(f"Error: {e}")

        unique_subs = set()
        async for item in redditor.new(limit=1000):
            unique_subs.add(item.subreddit.display_name)

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
            f"{get_loans(username)} | **Karma:** *{karma}* | **Age:** *{age}* | **Moderating:** *{moderated_list}*\n\n"
            f"**Subreddits:**\n{subreddit_report}\n\n"
            f"**Forbidden Subreddits:**\n{forbidden_report}"
        )

        if len(report) <= 2000:
            await CHECK_CHANNEL.send(report)
        else:
            for i in range(0, len(report), 2000):
                await CHECK_CHANNEL.send(report[i:i+2000])

    except Exception as e:
        print(f"Error in check command: {e}")

@bot.event
async def on_ready():
    await bot.wait_until_ready()
    
    global REDDIT
    global MAIN_CHANNEL
    global CHECK_CHANNEL

    MAIN_CHANNEL = bot.get_channel(1488789667313614930)
    CHECK_CHANNEL = bot.get_channel(1490949539367227432)
    REDDIT = asyncpraw.Reddit(
        client_id=os.environ['CLIENT_ID'],
        client_secret=os.environ['CLIENT_SECRET'],
        user_agent="Discord-Borrow-Bot-v1"
    )
    
    async for m in MAIN_CHANNEL.history(limit=3):
        match = RE_HISTORY.search(m.content.lower())
        if match and m.author == bot.user:
            HISTORY_IDS.append(match.group(1))

    await CHECK_CHANNEL.send("Booted Up!")
    check_posts.start()
    
webserver.keep_alive()
bot.run(os.environ['TOKEN'])
