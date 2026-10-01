from pathlib import Path
import getpass

ENV_FILE = Path(".env")


def ask(label, secret=False):
    value = getpass.getpass(label) if secret else input(label)
    return value.strip()


print("=" * 60)
print("Telegram Keyword Alert Bot - Setup")
print("=" * 60)
print()
print("This will create your .env file.")
print("Do not send your tokens or API hash to anyone.")
print()

bot_token = ask("BotFather bot token: ", secret=True)
api_id = ask("Telegram API ID: ")
api_hash = ask("Telegram API hash: ", secret=True)
admin_user_id = ask("Your Telegram numeric user ID: ")

ENV_FILE.write_text(
    f"BOT_TOKEN={bot_token}\n"
    f"API_ID={api_id}\n"
    f"API_HASH={api_hash}\n"
    f"ADMIN_USER_ID={admin_user_id}\n",
    encoding="utf-8",
)

print()
print("Setup complete. .env was created.")
print("Next install requirements with:")
print("    pip install -r requirements.txt")
print()
print("Then run:")
print("    python bot.py")
print()
print("The first time you run monitor.py, Telethon may ask you to")
print("log in to the Telegram account used for monitoring.")
