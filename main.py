import os
import re
import time
import asyncio
import aiohttp
import asyncpraw
import webserver
import discord
from discord.ext import commands, tasks

FORBIDDEN_SUBS = frozenset({"borrownew", "loanhelp_", "loansharks", "loanspaydayonline", "simpleloans"})
LOCATIONS = frozenset({"usa", "u.s.a", "u.s.a.", "u.s.", "u.s", " us)", ",us)", "state"})
PREARRANGED_WORDS = frozenset({"pre ", "pre-", "arrange"})
PREARRANGED_SELFTEXT = frozenset({"pre arranged", "prearranged", "pre-arranged"})

HISTORY_IDS = []

INTERVALS = (
    ('Y', 31536000),
    ('MO', 2592000),
    ('D', 86400),
    ('H', 3600),
    ('M', 60),
    ('S', 1)
)

RE_AMOUNT = re.compile(r"\d+")
RE_HISTORY = re.compile(r'\[(.*?)\]')

HTTP_SESSION = None
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

async def get_loans(username: str) -> str:
    headers = {"User-Agent": "Discord-Borrow-Bot-v1"}
    base_url = "https://redditloans.com/api/loans"
    username_l = username.lower()

    try:
        async with HTTP_SESSION.get(
            base_url,
            params={"borrower_name": username, "limit": 10, "order": "id_desc"},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=4)
        ) as r:
            if r.status != 200:
                return "*Error fetching loans**"
            loan_ids = await r.json()
    except Exception:
        return "*Error fetching loans**"

    if not loan_ids:
        return "**Total:** *$0* | **Open:** *$0*"

    sem = asyncio.Semaphore(50)

    async def fetch_loan(lid):
        async with sem:
            try:
                async with HTTP_SESSION.get(
                    f"{base_url}/{lid}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=2.5)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
            except Exception:
                return None
        return None

    loans_data = await asyncio.gather(*(fetch_loan(lid) for lid in loan_ids))

    total = 0
    open_loans = []

    for loan in loans_data:
        if not loan:
            continue

        if loan.get("borrower", "").lower() != username_l:
            continue

        principal = loan.get("principal_minor") or 0
        total += principal

        if not (
            loan.get("repaid_at")
            or loan.get("unpaid_at")
            or loan.get("deleted_at")
        ):
            open_loans.append(f"*${principal / 100:.0f}*")

    open_str = " ".join(open_loans) if open_loans else "*$0*"
    return f"**Total:** *${total / 100:.0f}* | **Open:** {open_str}"

def format_time_ago(timestamp):
    diff = int(time.time() - timestamp)
    for label, seconds in INTERVALS:
        if diff >= seconds:
            return f"{diff // seconds}{label}"
    return "0s"

async def get_user_info(redditor):
    try:
        lower = str.lower

        await redditor.load()
        loans_task = get_loans(redditor.name)

        activity = []
        async for item in redditor.new(limit=50):
            sub_name = lower(item.subreddit.display_name)

            if sub_name in FORBIDDEN_SUBS:
                return None

            if sub_name != "borrow":
                activity.append(item)

            if len(activity) == 5:
                break

        loans = await loans_task
        karma = redditor.link_karma + redditor.comment_karma
        age = format_time_ago(redditor.created_utc)

        links = (
            f"**[Message](<https://www.reddit.com/chat/user/t2_{redditor.id}>) -** "
            f"**[Profile](<https://www.reddit.com/user/{redditor.name}>) -** "
            f"**[Loans](<https://redditloans.com/loans.html?username={redditor.name}>) -** "
            f"**[Posts](<https://www.reddit.com/r/borrow/search?q=author%3A{redditor.name}&include_over_18=on&sort=new&t=all>) -** "
            f"**[Search](<https://www.reddit.com/r/borrow/search/?q={redditor.name}&include_over_18=on&t=all&sort=relevance>) -** "
            f"**[USL](<https://www.universalscammerlist.com/?username={redditor.name}>)**"
        )

        user_report = [f"**{redditor.name}**\n{loans} | **Karma:** *{karma}* | **Age:** *{age}*\n{links}\n"]

        if not activity:
            user_report.append("*Hidden profile*\n")
        else:
            for item in activity:
                text = getattr(item, 'title', getattr(item, 'body', '')).replace('\n', ' ')[:100]
                user_report.append(
                    f"[{format_time_ago(item.created_utc)}] **r/{item.subreddit.display_name}** *{text}*"
                )

        return "\n".join(user_report)

    except Exception as e:
        print(f"Error in get_user_info: {e}")
        return None

@tasks.loop(seconds=0.8)
async def check_posts():
    try:
        async for post in SUBREDDIT.new(limit=3):
            if post.id in HISTORY_IDS or post.created_utc < time.time() - 3600:
                continue

            title = post.title.lower()

            if ("req" not in title
                    or any(word in title for word in PREARRANGED_WORDS)
                    or not any(word in title for word in LOCATIONS)):
                continue

            amount_match = RE_AMOUNT.search(title)

            if (not amount_match
                    or int(amount_match.group()) > 500
                    or any(text in (post.selftext or "").lower() for text in PREARRANGED_SELFTEXT)):
                continue

            user_info = await get_user_info(post.author)
            if user_info is None:
                continue

            HISTORY_IDS.append(post.id)
            if len(HISTORY_IDS) > 3:
                HISTORY_IDS.pop(0)

            selftext = post.selftext or "None"

            message = (
                f"<@314300380051668994> [{post.id}]\n"
                f"**[{post.title}](<{post.url}>)**\n"
                f"*{selftext[:500]}*\n\n"
                f"{user_info}"
            )

            await MAIN_CHANNEL.send(message)

            asyncio.create_task(run_check_logic(str(post.author)))

    except Exception as e:
        print(f"Error in check_posts: {e}")

async def run_check_logic(username: str):
    try:
        redditor = await REDDIT.redditor(username)
        await redditor.load()

        loans_task = get_loans(username)

        unique_subs = set()

        async for item in redditor.new(limit=1000):
            unique_subs.add(item.subreddit.display_name)

        subreddit_list = []
        forbidden_list = []

        for sub in sorted(unique_subs, key=str.lower):
            if sub.lower() in FORBIDDEN_SUBS:
                forbidden_list.append(sub)
            else:
                subreddit_list.append(sub)

        loans = await loans_task
        karma = redditor.link_karma + redditor.comment_karma
        age = format_time_ago(redditor.created_utc)

        report = (
            f"**{username}**\n"
            f"{loans} | **Karma:** *{karma}* | **Age:** *{age}*\n\n"
            f"**Subreddits:**\n{', '.join(subreddit_list) if subreddit_list else 'None'}\n\n"
            f"**Forbidden Subreddits:**\n{', '.join(forbidden_list) if forbidden_list else 'None'}"
        )

        for i in range(0, len(report), 2000):
            await CHECK_CHANNEL.send(report[i:i + 2000])

    except Exception as e:
        print(f"Error executing lookups: {e}")

@bot.command()
async def check(ctx, username: str):
    await run_check_logic(username)

@bot.event
async def on_ready():
    global REDDIT, SUBREDDIT, MAIN_CHANNEL, CHECK_CHANNEL, HTTP_SESSION

    connector = aiohttp.TCPConnector(
        limit=100,
        ttl_dns_cache=300,
        enable_cleanup_closed=True
    )
    HTTP_SESSION = aiohttp.ClientSession(connector=connector)

    REDDIT = asyncpraw.Reddit(
        client_id=os.environ['CLIENT_ID'],
        client_secret=os.environ['CLIENT_SECRET'],
        user_agent="Discord-Borrow-Bot-v1"
    )

    SUBREDDIT = await REDDIT.subreddit("Borrow")

    MAIN_CHANNEL = bot.get_channel(1488789667313614930)
    CHECK_CHANNEL = bot.get_channel(1490949539367227432)

    async for m in MAIN_CHANNEL.history(limit=3):
        match = RE_HISTORY.search(m.content.lower())
        if match and m.author == bot.user:
            HISTORY_IDS.insert(0, match.group(1))

    await CHECK_CHANNEL.send("Booted Up!")
    check_posts.start()

webserver.keep_alive()
bot.run(os.environ['TOKEN'])
