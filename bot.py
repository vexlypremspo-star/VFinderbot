import secrets
import string
from dotenv import load_dotenv
import os
import re
from datetime import datetime, timezone

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import (
    init_db,
    ensure_user,
    add_keyword,
    remove_keyword,
    get_keywords,
    has_active_access,
    get_user_expiry,
    is_monitoring_enabled,
    pause_monitoring,
    resume_monitoring,
    create_access_code,
    activate_access_code,
    get_access_codes,
    get_customers,
    get_monitored_chats,
    get_admin_monitored_chats,
    set_admin_monitored_chat,
    find_monitored_chat,
    add_user_monitored_chat,
    remove_user_monitored_chat,
    get_user_monitored_chats,
    revoke_user_access,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Run setup.py first.")
if not ADMIN_USER_ID.isdigit():
    raise RuntimeError("ADMIN_USER_ID is missing or invalid. Run setup.py first.")
ADMIN_USER_ID = int(ADMIN_USER_ID)

init_db()


def is_admin(user_id):
    return bool(ADMIN_USER_ID) and int(user_id) == int(ADMIN_USER_ID)


def make_code():
    alphabet = string.ascii_uppercase + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))


def fmt_dt(value):
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S") if value else "-"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ensure_user(user_id)
    if has_active_access(user_id):
        expiry = get_user_expiry(user_id)
        state = "▶️ Monitoring is ON" if is_monitoring_enabled(user_id) else "⏸️ Monitoring is PAUSED"
        await update.message.reply_text(
            "👋 Welcome!\n\n"
            f"✅ Access is active until {fmt_dt(expiry)}.\n"
            f"{state}\n\n"
            "Use /addkeyword to add a keyword.\n"
            "Use /keywords to see your keywords.\n"
            "Use /removekeyword to remove one.\n"
            "Use /stop to pause monitoring.\n"
            "Use /resume to resume monitoring.\n"
            "Use /addmonitor to choose groups/channels to monitor.\n"
            "Use /monitored to see your monitored groups/channels.\n"
            "Use /removemonitor to remove one.\n"
            "Use /status to see your status."
        )
    else:
        await update.message.reply_text("👋 Welcome!\n\n🔐 Your access is not active.\nUse /access to enter your access code.")


async def access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_for_access_code"] = True
    await update.message.reply_text("🔐 Send your access code.\n\nExample: ABCD-1234")


async def addkeyword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_active_access(user_id):
        await update.message.reply_text("❌ Your access has expired or is not active.\nUse /access to enter a valid access code.")
        return
    if not is_monitoring_enabled(user_id):
        await update.message.reply_text("⏸️ Monitoring is paused. Use /resume first.")
        return
    context.user_data["waiting_for_keyword"] = True
    await update.message.reply_text("🔎 Send the keyword you want to monitor.")


async def keywords_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_active_access(user_id):
        await update.message.reply_text("❌ Your access has expired or is not active.\nUse /access to enter a valid access code.")
        return
    keywords = get_keywords(user_id)
    if not keywords:
        await update.message.reply_text("You don't have any keywords yet.")
        return
    await update.message.reply_text("🔎 Your keywords:\n" + "\n".join(f"• {keyword}" for keyword in keywords))


async def removekeyword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_active_access(user_id):
        await update.message.reply_text("❌ Your access is not active.\nUse /access to activate access.")
        return
    if len(context.args) >= 1:
        keyword = " ".join(context.args).strip()
        if remove_keyword(user_id, keyword):
            await update.message.reply_text(f"✅ Keyword removed: {keyword}")
        else:
            await update.message.reply_text(f"❌ Keyword not found: {keyword}")
        return
    context.user_data["waiting_for_remove_keyword"] = True
    await update.message.reply_text("🗑️ Send the keyword you want to remove.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_active_access(user_id):
        await update.message.reply_text("❌ Access is not active.\nUse /access to activate a code.")
        return
    expiry = get_user_expiry(user_id)
    state = "▶️ Monitoring ON" if is_monitoring_enabled(user_id) else "⏸️ Monitoring PAUSED"
    await update.message.reply_text(
        "✅ Access active\n"
        f"{state}\n"
        f"⏰ Access expires: {fmt_dt(expiry)}\n"
        f"🔎 Keywords: {len(get_keywords(user_id))}"
    )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ok, reason = pause_monitoring(user_id)
    if not ok:
        messages = {
            "no_access": "❌ You don't have active access.",
            "expired": "❌ Your access has already expired.",
            "already_paused": "⏸️ Monitoring is already paused.",
        }
        await update.message.reply_text(messages.get(reason, "❌ Could not pause monitoring."))
        return
    expiry = get_user_expiry(user_id)
    await update.message.reply_text(
        "⏸️ Monitoring paused.\n\n"
        f"Your access expiry remains {fmt_dt(expiry)} while paused.\n"
        "Use /resume when you want to continue."
    )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ok, reason, expiry = resume_monitoring(user_id)
    if not ok:
        messages = {
            "no_access": "❌ You don't have active access.",
            "already_running": f"▶️ Monitoring is already running.\n⏰ Expires: {fmt_dt(expiry)}",
            "not_paused": "❌ Monitoring is not paused.",
        }
        await update.message.reply_text(messages.get(reason, "❌ Could not resume monitoring."))
        return
    await update.message.reply_text(
        "▶️ Monitoring resumed.\n\n"
        f"⏰ Your paused time was added back. New expiry: {fmt_dt(expiry)}"
    )



def format_chat(chat):
    name = f"@{chat['username']}" if chat.get("username") else chat["title"]
    return f"• {name} [{chat.get('chat_type') or 'chat'}]\n  ID: {chat['chat_id']}"


async def monitored_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if is_admin(user_id):
        chats = get_admin_monitored_chats()
        if not chats:
            await update.message.reply_text(
                "📡 No permanent monitoring sources are configured yet.\n\n"
                "Use /addmonitor <group/channel> to permanently monitor a source for all active users."
            )
            return

        lines = ["📡 PERMANENTLY MONITORED SOURCES", ""]
        lines.extend(format_chat(chat) for chat in chats)
        lines.append(f"\nTotal: {len(chats)}")
        await update.message.reply_text("\n".join(lines))
        return

    if not has_active_access(user_id):
        await update.message.reply_text("❌ Access is not active.\nUse /access to activate an access code.")
        return

    chats = get_user_monitored_chats(user_id)
    if not chats:
        await update.message.reply_text(
            "📡 You have no extra monitoring sources.\n\n"
            "The admin's permanent sources are monitored automatically.\n"
            "Use /addmonitor <group/channel> only if you want an additional source."
        )
        return

    lines = ["📡 YOUR EXTRA MONITORED SOURCES", ""]
    lines.extend(format_chat(chat) for chat in chats)
    lines.append(f"\nTotal extra sources: {len(chats)}")
    await update.message.reply_text("\n".join(lines))


async def addmonitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if is_admin(user_id):
        if not context.args:
            chats = get_monitored_chats()
            if not chats:
                await update.message.reply_text(
                    "📡 No groups/channels are available yet.\n\n"
                    "Start monitor.py so it can refresh the monitoring account's available sources."
                )
                return

            lines = [
                "📡 AVAILABLE GROUPS / CHANNELS",
                "",
                "Permanent = monitored for all active users.",
                "Use /addmonitor <ID/@username/exact title> to add a permanent source.",
                "",
            ]
            for chat in chats:
                name = f"@{chat['username']}" if chat.get("username") else chat["title"]
                status = "✅ PERMANENT" if chat.get("admin_monitored") else "➖ optional"
                lines.append(
                    f"• {name} [{chat.get('chat_type') or 'chat'}]\n"
                    f"  ID: {chat['chat_id']}\n"
                    f"  {status}"
                )
            text = "\n".join(lines)
            chunks = []
            current = []
            current_len = 0
            for line in text.splitlines():
                add_len = len(line) + (1 if current else 0)
                if current and current_len + add_len > 4000:
                    chunks.append("\n".join(current))
                    current = [line]
                    current_len = len(line)
                else:
                    current.append(line)
                    current_len += add_len
            if current:
                chunks.append("\n".join(current))

            for chunk in chunks:
                await update.message.reply_text(chunk)
            return

        # Admin bulk mode:
        # /addmonitor all
        # /addmonitor @source1 @source2 123456789
        if len(context.args) > 1 or (context.args and context.args[0].lower() == "all"):
            chats = get_monitored_chats()
            if not chats:
                await update.message.reply_text("❌ No available groups/channels were recorded yet.")
                return

            if context.args[0].lower() == "all":
                targets = chats
                label = "all available sources"
            else:
                targets = []
                not_found = []
                for arg in context.args:
                    chat = find_monitored_chat(arg)
                    if chat:
                        targets.append(chat)
                    else:
                        not_found.append(arg)

                if not targets:
                    await update.message.reply_text("❌ None of the specified sources were found.")
                    return
                label = f"{len(targets)} specified source(s)"

            changed = 0
            already = 0
            for chat in targets:
                if chat.get("admin_monitored"):
                    already += 1
                    continue
                if set_admin_monitored_chat(chat["chat_id"], True):
                    changed += 1

            lines = [
                f"✅ Permanent monitoring updated for {label}.",
                f"Added: {changed}",
                f"Already permanent: {already}",
            ]
            if context.args[0].lower() != "all" and not_found:
                lines.append(f"Not found: {', '.join(not_found)}")
            lines.append("\nAll active users with matching keywords can now receive alerts from these permanent sources.")
            await update.message.reply_text("\n".join(lines))
            return

        value = " ".join(context.args).strip()
        chat = find_monitored_chat(value)
        if not chat:
            await update.message.reply_text(
                "❌ Group/channel not found in the monitoring account's available list.\n\n"
                "Use /addmonitor without an argument to see available sources."
            )
            return

        if chat.get("admin_monitored"):
            await update.message.reply_text("ℹ️ That source is already permanently monitored.")
            return

        if set_admin_monitored_chat(chat["chat_id"], True):
            name = f"@{chat['username']}" if chat.get("username") else chat["title"]
            await update.message.reply_text(
                f"✅ Permanently monitored: {name}\n\n"
                "All active users with matching keywords can now receive alerts from this source."
            )
        else:
            await update.message.reply_text("❌ Could not add that source.")
        return

    # Normal users may optionally add extra sources for themselves.
    if not has_active_access(user_id):
        await update.message.reply_text("❌ Access is not active.\nUse /access to activate an access code.")
        return

    if not context.args:
        chats = get_monitored_chats()
        if not chats:
            await update.message.reply_text(
                "📡 No groups/channels are available yet.\n\n"
                "The monitoring account must have access to the group/channel. "
                "Start monitor.py so it can refresh the available list."
            )
            return

        lines = [
            "📡 AVAILABLE EXTRA SOURCES",
            "",
            "The admin's permanent sources are already monitored for you.",
            "Use /addmonitor <ID/@username/exact title> to add an optional extra source just for yourself.",
            "",
        ]
        lines.extend(format_chat(chat) for chat in chats)
        await update.message.reply_text("\n".join(lines))
        return

    value = " ".join(context.args).strip()
    chat = find_monitored_chat(value)
    if not chat:
        await update.message.reply_text(
            "❌ Group/channel not found in the monitoring account's available list.\n\n"
            "Use /addmonitor without an argument to see available sources."
        )
        return

    if chat.get("admin_monitored"):
        await update.message.reply_text(
            "ℹ️ That source is already permanently monitored for all active users. "
            "You do not need to add it."
        )
        return

    if add_user_monitored_chat(user_id, chat["chat_id"]):
        name = f"@{chat['username']}" if chat.get("username") else chat["title"]
        await update.message.reply_text(f"✅ Added as your optional extra source: {name}")
    else:
        await update.message.reply_text("ℹ️ That source is already in your extra monitoring list.")


async def removeoptional_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if len(context.args) != 1 or context.args[0].strip().lower() != "all":
        await update.message.reply_text("Usage: /removeoptional all")
        return

    chats = get_user_monitored_chats(user_id)
    if not chats:
        await update.message.reply_text("📡 You have no optional extra sources to remove.")
        return

    removed = 0
    for chat in chats:
        if remove_user_monitored_chat(user_id, chat["chat_id"]):
            removed += 1

    await update.message.reply_text(
        f"✅ Removed {removed} optional source{'s' if removed != 1 else ''} from your personal monitoring list.\n\n"
        "Permanent/admin monitoring sources were not changed."
    )


async def removemonitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if is_admin(user_id):
        if not context.args:
            chats = get_admin_monitored_chats()
            if not chats:
                await update.message.reply_text("📡 No permanent monitoring sources are configured.")
                return

            lines = [
                "🗑️ PERMANENT MONITORING SOURCES",
                "",
                "Use /removemonitor <ID/@username/exact title> to stop permanent monitoring.",
                "",
            ]
            lines.extend(format_chat(chat) for chat in chats)
            await update.message.reply_text("\n".join(lines))
            return

        # Admin bulk mode:
        # /removemonitor all
        # /removemonitor @source1 @source2 123456789
        if len(context.args) > 1 or (context.args and context.args[0].lower() == "all"):
            chats = get_admin_monitored_chats()
            if not chats:
                await update.message.reply_text("ℹ️ No permanent monitoring sources are configured.")
                return

            if context.args[0].lower() == "all":
                targets = chats
                label = "all permanent sources"
            else:
                targets = []
                not_found = []
                for arg in context.args:
                    chat = find_monitored_chat(arg)
                    if chat:
                        targets.append(chat)
                    else:
                        not_found.append(arg)

                if not targets:
                    await update.message.reply_text("❌ None of the specified sources were found.")
                    return
                label = f"{len(targets)} specified source(s)"

            changed = 0
            not_permanent = 0
            for chat in targets:
                if not chat.get("admin_monitored"):
                    not_permanent += 1
                    continue
                if set_admin_monitored_chat(chat["chat_id"], False):
                    changed += 1

            lines = [
                f"✅ Permanent monitoring updated for {label}.",
                f"Removed: {changed}",
                f"Already not permanent: {not_permanent}",
            ]
            if context.args[0].lower() != "all" and not_found:
                lines.append(f"Not found: {', '.join(not_found)}")
            lines.append("\nThose sources remain available as optional sources for individual users.")
            await update.message.reply_text("\n".join(lines))
            return

        value = " ".join(context.args).strip()
        chat = find_monitored_chat(value)
        if not chat:
            await update.message.reply_text("❌ Group/channel not found.")
            return

        if not chat.get("admin_monitored"):
            await update.message.reply_text("ℹ️ That source is not permanently monitored.")
            return

        if set_admin_monitored_chat(chat["chat_id"], False):
            name = f"@{chat['username']}" if chat.get("username") else chat["title"]
            await update.message.reply_text(
                f"✅ Removed from permanent monitoring: {name}\n\n"
                "It can still be monitored by individual users who explicitly added it."
            )
        else:
            await update.message.reply_text("❌ Could not remove that source.")
        return

    if not has_active_access(user_id):
        await update.message.reply_text("❌ Access is not active.\nUse /access to activate an access code.")
        return

    if not context.args:
        chats = get_user_monitored_chats(user_id)
        if not chats:
            await update.message.reply_text("📡 You have no optional extra sources.")
            return
        lines = [
            "🗑️ YOUR EXTRA MONITORED SOURCES",
            "",
            "Use /removemonitor <ID/@username/exact title> to remove one.",
            "",
        ]
        lines.extend(format_chat(chat) for chat in chats)
        await update.message.reply_text("\n".join(lines))
        return

    value = " ".join(context.args).strip()
    chat = find_monitored_chat(value)
    if not chat:
        await update.message.reply_text("❌ Group/channel not found.")
        return

    if remove_user_monitored_chat(user_id, chat["chat_id"]):
        name = f"@{chat['username']}" if chat.get("username") else chat["title"]
        await update.message.reply_text(f"✅ Removed your optional extra source: {name}")
    else:
        await update.message.reply_text("❌ That source is not in your optional extra monitoring list.")



def parse_duration(value):
    match = re.fullmatch(r"(\d+)\s*([mhdw])", value.strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    if amount <= 0:
        return None
    return amount * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[match.group(2)]


def format_duration(seconds):
    units = [(604800, "week"), (86400, "day"), (3600, "hour"), (60, "minute")]
    for size, name in units:
        if seconds % size == 0:
            amount = seconds // size
            return f"{amount} {name}{'' if amount == 1 else 's'}"
    return f"{seconds} seconds"


async def generatecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /generatecode <duration>\n\nExamples: /generatecode 30m, /generatecode 6h, /generatecode 1d, /generatecode 7d, /generatecode 4w")
        return
    duration_seconds = parse_duration(context.args[0])
    if duration_seconds is None:
        await update.message.reply_text("❌ Invalid duration. Use a positive number followed by m, h, d, or w.")
        return
    code = make_code()
    create_access_code(code, datetime.now(timezone.utc), duration_seconds)
    duration_text = format_duration(duration_seconds)
    await update.message.reply_text(
        f"🔐 New access code ({duration_text}):\n\n`{code}`\n\nGive this code to one customer. Their {duration_text} starts when they redeem it.",
        parse_mode="Markdown",
    )


async def accesscodes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    codes = get_access_codes()
    if not codes:
        await update.message.reply_text("🔐 No access codes created yet.")
        return
    lines = ["🔐 ACCESS CODES", ""]
    claimed = available = 0
    for item in codes:
        if item["activated_by"] is None:
            status = "AVAILABLE"
            available += 1
            who = "-"
            expiry = "Starts when claimed"
        else:
            status = "CLAIMED"
            claimed += 1
            who = str(item["activated_by"])
            expiry = item["expires_at"] or "-"
        lines.extend([
            f"Code: {item['code']}",
            f"Status: {status}",
            f"User: {who}",
            f"Expiry: {expiry}",
            f"Duration: {format_duration(int(item['duration_seconds']))}",
            "",
        ])
    lines.append(f"Total: {len(codes)} | Claimed: {claimed} | Available: {available}")
    await update.message.reply_text("\n".join(lines))


async def customers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    customers = get_customers()
    if not customers:
        await update.message.reply_text("No customers yet.")
        return
    lines = ["👥 Customers", ""]
    for customer in customers:
        expiry = customer["access_expires_at"]
        if expiry:
            expiry_dt = datetime.fromisoformat(expiry)
            active = expiry_dt > datetime.now(timezone.utc)
            status_text = "ACTIVE" if active else "EXPIRED"
            expiry_text = fmt_dt(expiry_dt)
        else:
            status_text = "REVOKED / EXPIRED"
            expiry_text = "-"
        monitor = "ON" if customer["monitoring_enabled"] else "PAUSED"
        lines.append(f"ID: {customer['user_id']} | {status_text} | monitor: {monitor} | expires: {expiry_text} | keywords: {customer['keyword_count']}")
    await update.message.reply_text("\n".join(lines))


async def customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /customer <user_id>")
        return
    user_id = int(context.args[0])
    customer = next((c for c in get_customers() if int(c["user_id"]) == user_id), None)
    if not customer:
        await update.message.reply_text("❌ Customer not found.")
        return
    keywords = get_keywords(user_id)
    expiry = customer["access_expires_at"]
    expiry_dt = datetime.fromisoformat(expiry) if expiry else None
    status_text = "ACTIVE" if expiry_dt and expiry_dt > datetime.now(timezone.utc) else ("EXPIRED" if expiry_dt else "REVOKED / EXPIRED")
    await update.message.reply_text(
        f"👤 Customer\n\nUser ID: {user_id}\nStatus: {status_text}\n"
        f"Monitoring: {'ON' if customer['monitoring_enabled'] else 'PAUSED'}\n"
        f"Expires: {fmt_dt(expiry_dt)}\nKeywords ({len(keywords)}):\n"
        + ("\n".join(f"• {k}" for k in keywords) if keywords else "• None")
    )


async def removeuserkeyword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    if len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /removeuserkeyword <user_id> <keyword>")
        return
    user_id = int(context.args[0])
    keyword = " ".join(context.args[1:]).strip()
    if remove_keyword(user_id, keyword):
        await update.message.reply_text(f"✅ Removed keyword '{keyword}' from user {user_id}.")
    else:
        await update.message.reply_text(f"❌ Keyword '{keyword}' was not found for user {user_id}.")


async def monitoring_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    chats = get_monitored_chats()
    if not chats:
        await update.message.reply_text(
            "📡 No groups/channels have been recorded yet.\n\n"
            "Start monitor.py. It records groups/channels the monitoring Telegram account can access."
        )
        return

    lines = [
        "📡 MONITORING SOURCES",
        "",
        "✅ PERMANENT = monitored for all active users.",
        "➖ OPTIONAL = available for users to add individually.",
        "",
    ]
    for chat in chats:
        name = f"@{chat['username']}" if chat.get("username") else chat["title"]
        status = "✅ PERMANENT" if chat.get("admin_monitored") else "➖ OPTIONAL"
        lines.append(
            f"• {name} [{chat.get('chat_type') or 'chat'}]\n"
            f"  ID: {chat['chat_id']}\n"
            f"  {status}"
        )

    lines.append(
        "\nAdmin:\n"
        "/addmonitor <source> — make permanent\n"
        "/removemonitor <source> — remove from permanent monitoring"
    )

    # Telegram limits a text message to 4096 characters. Split the
    # monitoring list by lines so every chunk stays safely below the limit.
    chunks = []
    current_lines = []
    current_len = 0
    max_len = 3900

    for line in lines:
        line_len = len(line) + (1 if current_lines else 0)
        if current_lines and current_len + line_len > max_len:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
            line_len = len(line)

        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append("\n".join(current_lines))

    for chunk in chunks:
        await update.message.reply_text(chunk)




async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /revoke <user_id>")
        return
    user_id = int(context.args[0])
    if revoke_user_access(user_id):
        await update.message.reply_text(f"✅ Access revoked for {user_id}.")
    else:
        await update.message.reply_text("❌ Customer not found.")


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if context.user_data.get("waiting_for_access_code"):
        context.user_data["waiting_for_access_code"] = False
        activated_at = datetime.now(timezone.utc)
        ok, reason, expires_at = activate_access_code(text.upper(), user_id, activated_at)
        if not ok:
            await update.message.reply_text("❌ That access code has already been used." if reason == "used" else "❌ Invalid access code.")
            return
        await update.message.reply_text(f"✅ Access granted!\n\n⏰ Expires: {fmt_dt(expires_at)}\n\nYou can now use /addkeyword.")
        return

    if context.user_data.get("waiting_for_remove_keyword"):
        context.user_data["waiting_for_remove_keyword"] = False
        if not has_active_access(user_id):
            await update.message.reply_text("❌ Your access has expired.\nUse /access to activate a new code.")
            return
        if remove_keyword(user_id, text):
            await update.message.reply_text(f"✅ Keyword removed: {text}")
        else:
            await update.message.reply_text(f"❌ Keyword not found: {text}")
        return

    if context.user_data.get("waiting_for_keyword"):
        if not has_active_access(user_id):
            context.user_data["waiting_for_keyword"] = False
            await update.message.reply_text("❌ Your access has expired.\nUse /access to activate a new code.")
            return
        if not is_monitoring_enabled(user_id):
            context.user_data["waiting_for_keyword"] = False
            await update.message.reply_text("⏸️ Monitoring is paused. Use /resume first.")
            return
        context.user_data["waiting_for_keyword"] = False
        if add_keyword(user_id, text):
            await update.message.reply_text(f"✅ Keyword saved: {text}")
        else:
            await update.message.reply_text("ℹ️ That keyword is already in your list.")
        return

    await update.message.reply_text("Use /addkeyword to add a keyword, /keywords to view them, or /access to activate access.")


def main():
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30, pool_timeout=30)
    app = Application.builder().token(BOT_TOKEN).request(request).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("access", access))
    app.add_handler(CommandHandler("addkeyword", addkeyword_command))
    app.add_handler(CommandHandler("keywords", keywords_command))
    app.add_handler(CommandHandler("removekeyword", removekeyword_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("monitored", monitored_command))
    app.add_handler(CommandHandler("addmonitor", addmonitor_command))
    app.add_handler(CommandHandler("removemonitor", removemonitor_command))
    app.add_handler(CommandHandler("removeoptional", removeoptional_command))
    app.add_handler(CommandHandler("generatecode", generatecode))
    app.add_handler(CommandHandler("accesscodes", accesscodes_command))
    app.add_handler(CommandHandler("customers", customers_command))
    app.add_handler(CommandHandler("customer", customer_command))
    app.add_handler(CommandHandler("removeuserkeyword", removeuserkeyword_command))
    app.add_handler(CommandHandler("monitoring", monitoring_command))
    app.add_handler(CommandHandler("revoke", revoke_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))
    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
