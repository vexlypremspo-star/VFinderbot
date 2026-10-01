import os
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

api_id = os.getenv("API_ID", "").strip()
api_hash = os.getenv("API_HASH", "").strip()

if not api_id.isdigit() or not api_hash:
    raise RuntimeError("Run setup.py first.")

client = TelegramClient("monitor_session", int(api_id), api_hash)


async def main():
    me = await client.get_me()
    print("Telegram login successful!")
    print(f"Logged in as: {getattr(me, 'username', None) or getattr(me, 'first_name', 'Telegram user')}")


with client:
    client.loop.run_until_complete(main())
