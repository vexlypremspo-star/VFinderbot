import os
import logging
logging.basicConfig(format='[%(levelname)s %(asctime)s] %(name)s: %(message)s', level=logging.WARNING)
import re
import unicodedata
import asyncio
from html import escape

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest

from database import (
    init_db,
    get_all_active_keyword_users,
    upsert_monitored_chat,
    get_admin_monitored_chat_ids,
    get_user_monitored_chat_ids,
)

load_dotenv()

API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not API_ID.isdigit():
    raise RuntimeError("API_ID is missing or invalid. Run setup.py first.")
if not API_HASH:
    raise RuntimeError("API_HASH is missing. Run setup.py first.")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Run setup.py first.")

API_ID = int(API_ID)

TELEGRAM_SESSION = os.getenv("TELEGRAM_SESSION", "").strip()

if TELEGRAM_SESSION:
    client = TelegramClient(
        StringSession(TELEGRAM_SESSION),
        API_ID,
        API_HASH
    )
else:
    SESSION_NAME = "user_monitor_session"
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# Telegram Bot API identity. Messages sent by this bot must never be
# treated as source messages by the monitoring account.
BOT_USER_ID = None


def normalize_for_filter(text):
    """
    Normalize text so normal and many stylized Unicode fonts
    can be compared consistently.
    """
    normalized = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[^a-zA-Z]", "", normalized).lower()


def contains_standalone_lf(text):
    """
    Accept only a standalone LF marker.
    LFS, LFB, LFJ, LFMARKET, etc. do not qualify.
    Supports common stylized Unicode forms.
    """
    normalized = unicodedata.normalize("NFKC", text or "")

    replacements = {
        "ʟ": "l",
        "ᴌ": "l",
        "ʃ": "l",
        "ғ": "f",
        "ƒ": "f",
        "ꜰ": "f",
        "𝐥": "l",
        "𝗹": "l",
        "𝘭": "l",
        "𝙡": "l",
        "𝚕": "l",
        "𝐟": "f",
        "𝗳": "f",
        "𝘧": "f",
        "𝙛": "f",
        "𝚏": "f",
    }

    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    return bool(re.search(r"(?<![A-Za-z])LF(?![A-Za-z])", normalized, re.IGNORECASE))


def contains_fb_or_lfb(text):
    """
    Detect FB/LFB markers at the beginning of a post,
    including common stylized/decorative Unicode forms.
    """
    text = text or ""
    normalized = unicodedata.normalize("NFKC", text)

    replacements = {
        "ʟ": "l",
        "ᴌ": "l",
        "ʃ": "l",
        "ғ": "f",
        "ƒ": "f",
        "ꜰ": "f",
        "ʙ": "b",
        "ɓ": "b",
        "Ƅ": "b",
    }

    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    normalized = re.sub(r"[^a-zA-Z]", "", normalized).lower()

    return (
        normalized.startswith("lfb")
        or normalized.startswith("fb")
    )


def contains_lfj(text):
    """Filter LFJ posts, including many stylized Unicode versions."""
    normalized = normalize_for_filter(text)
    return "lfj" in normalized


def contains_pricelist(text):
    """Filter price-list / pricing posts, including stylized variants."""
    normalized = normalize_for_filter(text)

    price_list_patterns = (
        "pricelist",
        "pricinglist",
        "pricemenu",
        "ratelist",
        "ratecard",
    )

    for pattern in price_list_patterns:
        if pattern in normalized:
            return True

    if "pricing" in normalized:
        return True

    return False


def sender_should_be_filtered(sender_name):
    """Filter senders whose name contains Auto Plug or Plugger."""
    normalized = normalize_for_filter(sender_name)

    return (
        "autoplug" in normalized
        or "plugger" in normalized
    )


def remove_ignored_tags(text):
    """Ignore everything starting from 'tags (ignore):' when matching keywords."""
    match = re.search(
        r"tags\s*\(\s*ignore\s*\)\s*:",
        text or "",
        re.IGNORECASE
    )

    if match:
        return text[:match.start()]

    return text


def get_post_link(event):
    try:
        link = event.message.link
        if link:
            return link
    except Exception:
        pass

    try:
        chat = event.chat
        message_id = event.message.id
        username = getattr(chat, "username", None)
        if username and message_id:
            return f"https://t.me/{username}/{message_id}"
    except Exception:
        pass

    return None


def get_sender_info(event):
    sender_name = "Unknown"
    sender_link = None

    try:
        sender = event.sender
        if sender:
            first = getattr(sender, "first_name", "") or ""
            last = getattr(sender, "last_name", "") or ""
            username = getattr(sender, "username", None)
            full = f"{first} {last}".strip()
            sender_name = f"@{username}" if username else (full or "Unknown")

            if username:
                sender_link = f"https://t.me/{username}"
    except Exception:
        pass

    return sender_name, sender_link


def build_alert(event, keyword):
    raw_text = event.raw_text.strip()
    sender_name, sender_link = get_sender_info(event)

    try:
        chat = event.chat
        group_name = (
            getattr(chat, "title", None)
            or getattr(chat, "username", None)
            or "Unknown"
        )

        if getattr(chat, "username", None):
            group_name = f"@{chat.username}"
    except Exception:
        group_name = "Unknown"

    message_time = event.message.date
    time_text = (
        message_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if message_time.tzinfo
        else message_time.strftime("%Y-%m-%d %H:%M:%S")
    )

    post_link = get_post_link(event)

    if len(raw_text) > 1200:
        raw_text = raw_text[:1200] + "…"

    lines = [
        f"🔔 <b>MATCH:</b> {escape(keyword)}",
        "",
        f"👤 <b>BUYER:</b> {escape(sender_name)}",
        f"👥 <b>GROUP:</b> {escape(group_name)}",
        f"🕐 <b>TIME:</b> {escape(time_text)}",
        "",
        "<b>MESSAGE:</b>",
        escape(raw_text),
    ]

    buttons = []

    if post_link:
        buttons.append(
            InlineKeyboardButton("🔗 VIEW POST", url=post_link)
        )

    if sender_link:
        buttons.append(
            InlineKeyboardButton("💬 MESSAGE BUYER", url=sender_link)
        )

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None

    return "\n".join(lines), keyboard


async def send_one_alert(bot, user_id, keyword, alert, keyboard):
    try:
        await bot.send_message(
            chat_id=user_id,
            text=alert,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        print(f"ALERT SENT -> user {user_id} -> {keyword}")
    except Exception as e:
        print(f"Failed to send alert to {user_id}: {e}")


async def send_alerts(event, keyword_users, bot):
    original_text = event.raw_text or ""

    # Never process messages sent by Telegram bots. This is based on
    # Telegram's actual sender.bot flag, not the sender's username.
    sender = await event.get_sender()
    if sender is not None:
        if getattr(sender, "bot", False):
            return
        if BOT_USER_ID is not None and getattr(sender, "id", None) == BOT_USER_ID:
            return

    # Never process outgoing messages from the monitoring account.
    if getattr(event, "out", False):
        return

    # LF is required before any keyword can match.
    # Messages without a standalone LF are ignored.
    if not contains_standalone_lf(original_text):
        return

    # Existing filters are intentionally unchanged.
    sender_name, _ = get_sender_info(event)

    if contains_fb_or_lfb(original_text):
        return

    if contains_lfj(original_text):
        return

    if contains_pricelist(original_text):
        return

    if sender_should_be_filtered(sender_name):
        return

    text = remove_ignored_tags(original_text)

    # Source gate: only admin-permanent sources or that user's optional sources
    # are eligible. Being present in the monitoring account's Telegram dialogs
    # is NOT enough.
    # Normalize Telethon marked chat/channel IDs to the positive IDs stored in the database.
    event_chat_id = int(event.chat_id)
    if event_chat_id <= -1000000000000:
        event_chat_id = abs(event_chat_id) - 1000000000000
    elif event_chat_id < 0:
        event_chat_id = abs(event_chat_id)

    admin_monitored_ids = get_admin_monitored_chat_ids()

    alert_jobs = []

    for user_id, keywords in keyword_users.items():
        user_monitored_ids = get_user_monitored_chat_ids(user_id)
        if event_chat_id not in admin_monitored_ids and event_chat_id not in user_monitored_ids:
            continue
        matched_keyword = None

        for keyword in keywords:
            if keyword.strip().lower() in text.lower():
                matched_keyword = keyword
                break

        if not matched_keyword:
            continue

        alert, keyboard = build_alert(event, matched_keyword)

        # Send to all matching users concurrently instead of waiting
        # for each Telegram API request one-by-one.
        alert_jobs.append(
            send_one_alert(
                bot,
                user_id,
                matched_keyword,
                alert,
                keyboard,
            )
        )

    if alert_jobs:
        await asyncio.gather(*alert_jobs)


async def record_monitored_dialogs():
    count = 0

    async for dialog in client.iter_dialogs():
        entity = dialog.entity

        if (
            getattr(entity, "megagroup", False)
            or getattr(entity, "broadcast", False)
            or entity.__class__.__name__ in {"Chat", "Channel"}
        ):
            if getattr(entity, "title", None):
                chat_type = (
                    "channel"
                    if getattr(entity, "broadcast", False)
                    else "group"
                )

                upsert_monitored_chat(
                    getattr(entity, "id", 0),
                    getattr(entity, "title", "Unknown"),
                    getattr(entity, "username", None),
                    chat_type,
                )

                count += 1

    print(
        f"Recorded {count} groups/channels available to the monitoring account."
    )


# One persistent Bot API connection for the lifetime of the monitor.
BOT_REQUEST = HTTPXRequest(
    connect_timeout=60,
    read_timeout=60,
    write_timeout=30,
    pool_timeout=30,
    httpx_kwargs={"trust_env": False},
)

BOT = Bot(BOT_TOKEN, request=BOT_REQUEST)


@client.on(events.NewMessage(incoming=True))
async def new_message(event):
    print(
        f"INCOMING MESSAGE -> chat_id={event.chat_id}, "
        f"sender_id={getattr(event.sender, 'id', None)}"
    )

    keyword_users = get_all_active_keyword_users()

    if not keyword_users:
        print("No active keyword users.")
        return

    await send_alerts(event, keyword_users, BOT)

async def main():
    init_db()

    print("Monitor is starting...")
    print("Only messages with standalone LF are eligible.")
    print("Telegram bot messages and self/outgoing messages are ignored.")
    print("Waiting for matching messages...")

    await client.start()
    await BOT.initialize()

    global BOT_USER_ID
    bot_me = await BOT.get_me()
    BOT_USER_ID = bot_me.id
    print(f"Ignoring Telegram bot sender: @{bot_me.username or 'unknown'} (id={BOT_USER_ID})")

    try:
        await record_monitored_dialogs()
        await client.run_until_disconnected()
    finally:
        await BOT.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
