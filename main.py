import os
import re
import time
import asyncio
import aiohttp
import asyncpraw
import webserver
import discord
from discord.ext import commands, tasks

USL_SUBS = frozenset({"aftershocktickets", "airsoftmarket", "airsoftmarketcanada", "animalcrossingamiibos", "animedeals", "appleswap", "assistance", "avatartrading", "avexchange", "campfloggnawbuysell", "canadianhardwareswap", "canadianknifeswap", "caps", "care", "cash4cash", "charity", "coinsales", "comicswap", "digitalcodesell", "discexchange", "disneypinswap", "donedirtcheap", "edcexchange", "fightsticksforsale", "flashlight", "flyfishingexchange", "food_pantry", "fragranceswap", "funkoswap", "gamesale", "gameswap", "gametrade", "gear4sale", "geartrade", "giftcardexchange", "giftofgames", "gofundme", "hardwareswap", "hardwareswapuk", "hireagirlfriend", "hockeyjerseys", "homelabsales", "hutcoinsales", "igsrep", "indiegameswap", "itunesdeals", "jewelryforsale", "knife_swap", "labubuswap", "legomarket", "letstradepedals", "lolboosting", "machinedpens", "mangaswap", "mechmarket", "mediaswap", "miniswap", "mousemarket", "nba2kmtselling", "nbarep", "need", "overwatchboosting", "pen_swap", "periodpantry", "phoneverification", "photomarket", "pkmntcgtrades", "playingcardsmarket", "pmsforsale", "pokemongotrade", "random_acts_of_amazon", "random_acts_of_pizza", "randomactsofchristmas", "randomactsofpetfood", "randomactsoftacobell", "randomkindness", "referral", "referrals", "rpgtrade", "sgsflair", "shave_bazaar", "signupsforpay", "silverbugbets", "slavelabour", "snackexchange", "sneakermarket", "starcitizen_trades", "steamgameswap", "thinkpadsforsale", "ulgeartrade", "universalscammerlist", "uvtrade", "vinylcollectors", "watchexchange", "watchexchangecanada", "ygomarketplace"})
FORBIDDEN_SUBS = frozenset({"borrownew", "loanhelp_", "loansharks", "loanspaydayonline", "simpleloans"})
LOCATIONS = frozenset({"usa", "u.s.a", "u.s.a.", "u.s.", "u.s", " us)", ",us)", "state", "america"})
PREARRANGED_WORDS = frozenset({"(pre", "pre ", "pre-", "arrange"})
PREARRANGED_SELFTEXT = frozenset({"pre arranged", "prearranged", "pre-arranged"})

INTERVALS = (('Y', 31536000), ('MO', 2592000), ('D', 86400), ('H', 3600), ('M', 60), ('S', 1))

HISTORY_IDS = []

RE_AMOUNT = re.compile(r"\d+")
RE_HISTORY = re.compile(r'\[(.*?)\]')

HTTP_SESSION = None
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

def format_time_ago(timestamp):
    diff = int(time.time() - timestamp)
    for label, seconds in INTERVALS:
        if diff >= seconds:
            return f"{diff // seconds}{label}"
    return "0s"

async def get_loans(username):
    headers = {"User-Agent": "Discord-Borrow-Bot-v1"}
    base_url = "https://redditloans.com/api/loans"

    try:
        async with HTTP_SESSION.get(
            base_url,
            params={"borrower_name": username, "limit": 10, "order": "id_desc"},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=3),
            ssl=False
        ) as r:
            if r.status != 200:
                return "Error fetching loans"
            loan_ids = await r.json()

    except Exception:
        return "Error fetching loans"

    if not loan_ids:
        return "**Total:** $0 | **Open:** $0"

    async def fetch_loan(lid):
        try:
            async with HTTP_SESSION.get(
                f"{base_url}/{lid}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=3),
                ssl=False
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
        except Exception:
            return None

    loans_data = await asyncio.gather(*(fetch_loan(lid) for lid in loan_ids))

    total = 0
    open_loans = []

    for loan in loans_data:
        principal = loan.get("principal_minor") or 0
        total += principal

        if not (
            loan.get("repaid_at")
            or loan.get("unpaid_at")
            or loan.get("deleted_at")
        ):
            open_loans.append(f"${principal / 100:.0f}")

    open_str = " ".join(open_loans) if open_loans else "$0"
    return f"**Total:** ${total / 100:.0f} | **Open:** {open_str}"

async def get_user_info(redditor):
    try:
        await redditor.load()
        
        loans = await get_loans(redditor.name)
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

        user_info = f"**{redditor.name}**\n{loans} | **Karma:** {karma} | **Age:** {age}\n{links}\n\n"

        usl_list = set()
        forbidden_list = set()
        activity = []

        async for item in redditor.new(limit=1000):
            sub_name = item.subreddit.display_name.lower()
            
            if sub_name != "borrow" and len(activity) < 5:
                text = (getattr(item, "title", None) or getattr(item, "body", "")).replace("\n", " ")[:100]
                activity.append(f"[{format_time_ago(item.created_utc)}] **r/{item.subreddit.display_name}** *{text}*")

            if sub_name in USL_SUBS:
                usl_list.add(sub_name)
            elif sub_name in FORBIDDEN_SUBS:
                forbidden_list.add(sub_name)

        subreddits = f"**USL Subreddits: **{', '.join(usl_list) if usl_list else 'None'}\n**Forbidden Subreddits: **{', '.join(forbidden_list) if forbidden_list else 'None'}\n\n"

        if not activity:
            user_info = user_info + subreddits + "Hidden profile"
        else:
            user_info = user_info + subreddits + "\n".join(activity[:5])

        return user_info

    except Exception as e:
        print(f"Error in get_user_combined_info: {e}")
        return None

@tasks.loop(seconds=0.8)
async def check_posts():
    try:
        now = time.time()
        async for post in SUBREDDIT.new(limit=3):
            if post.id in HISTORY_IDS or post.created_utc < now - 3600:
                continue

            title = post.title.lower()
            if ("req" not in title
                    or any(word in title for word in PREARRANGED_WORDS)
                    or not any(word in title for word in LOCATIONS)):
                continue

            amount = int(RE_AMOUNT.search(title).group())
            selftext_l = post.selftext.lower()
            if (not amount 
                    or amount <= 10
                    or amount > 500
                    or any(text in selftext_l for text in PREARRANGED_SELFTEXT)):
                continue

            HISTORY_IDS.append(post.id)
            if len(HISTORY_IDS) > 3:
                HISTORY_IDS.pop(0)

            user_info_task = asyncio.create_task(get_user_info(post.author))

            selftext = post.selftext or "None"
            message = (
                f"<@314300380051668994> [{post.id}]\n"
                f"**[{post.title}](<{post.url}>)**\n"
                f"*{selftext[:500]}*"
            )
            
            sent_message = await MAIN_CHANNEL.send(message)
            user_info = await user_info_task
            
            await sent_message.edit(content=f"{message}\n\n{user_info}")

    except Exception as e:
        print(f"Error in check_posts: {e}")

@bot.command()
async def check(ctx, username: str):
    try:
        loans_task = asyncio.create_task(get_loans(username))
        
        redditor = await REDDIT.redditor(username)
        await redditor.load()

        usl_subreddits = set()
        forbidden_subreddits = set()
        subreddits = []

        async for item in redditor.new(limit=1000):
            sub_name = item.subreddit.display_name.lower()

            if sub_name in USL_SUBS and sub_name not in usl_subreddits:
                usl_subreddits.add(sub_name)
            elif sub_name in FORBIDDEN_SUBS and sub_name not in forbidden_subreddits:
                forbidden_subreddits.add(sub_name)
            elif sub_name not in subreddits and sub_name not in (usl_subreddits | forbidden_subreddits):
                subreddits.append(sub_name)

        subreddits = sorted(subreddits)

        loans = await loans_task
        karma = redditor.link_karma + redditor.comment_karma
        age = format_time_ago(redditor.created_utc)

        report = (
            f"**{username}**\n"
            f"{loans} | **Karma:** {karma} | **Age:** {age}\n\n"
            f"**Subreddits:**\n{', '.join(subreddits) if subreddits else 'None'}\n\n"
            f"**USL Subreddits:**\n{', '.join(usl_subreddits) if usl_subreddits else 'None'}\n\n"
            f"**Forbidden Subreddits:**\n{', '.join(forbidden_subreddits) if forbidden_subreddits else 'None'}"
        )

        for i in range(0, len(report), 2000):
            await CHECK_CHANNEL.send(report[i:i + 2000])

    except Exception as e:
        print(f"Error in check: {e}")

@bot.event
async def on_ready():
    global REDDIT, SUBREDDIT, MAIN_CHANNEL, CHECK_CHANNEL, HTTP_SESSION

    connector = aiohttp.TCPConnector(
        limit=100,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
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
