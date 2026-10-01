TELEGRAM KEYWORD ALERT BOT
==========================

What this project does
----------------------
1. Customers enter a one-time access code.
2. Each access code gives 24 hours of access after activation.
3. Customers add their own keywords.
4. The monitoring Telegram account receives messages.
5. Matching messages are sent to the customer through your Bot API bot.
6. Messages containing the standalone term "LFB" are ignored.
7. Each customer only receives alerts for their own keywords.
8. SQLite stores users, keywords, access codes, and expiry times.

Important
---------
This is an MVP starter. It monitors messages that the Telethon account
can actually receive. It does not bypass Telegram access controls.

Setup
-----
1. Put all files in one folder.
2. Open Command Prompt in that folder.
3. Install dependencies:

   pip install -r requirements.txt

4. Run:

   python setup.py

   Enter:
   - BotFather bot token
   - Telegram API ID
   - Telegram API hash
   - Your Telegram numeric user ID

5. Log in the monitoring Telegram account:

   python login.py

6. Start the bot:

   python bot.py

7. Start the monitor in another Command Prompt:

   python monitor.py

Admin
-----
Your Telegram account is the admin account configured in .env.

Generate a 24-hour access code with:

   /generatecode

The code is single-use. The 24-hour period starts when the customer
redeems the code.

Customer commands
-----------------
/start
/access
/addkeyword
/keywords
/status

Alert filtering
---------------
If a message contains LFB as a standalone word, it is ignored.

Examples:
  "netflix"              -> match
  "LF netflix"           -> match
  "looking for netflix"  -> match
  "LFB netflix"          -> ignored
  "lfb: netflix"         -> ignored

Security
--------
Never share:
- BotFather bot token
- Telegram API hash
- monitor_session.session

If a bot token is exposed, revoke it with BotFather and create a new one.

Production notes
----------------
For a real paid service, add:
- PostgreSQL instead of SQLite
- admin web panel
- payment/subscription handling
- rate limits and abuse controls
- alert deduplication
- logging and error monitoring
- backup/restore
- source/group management
- stronger access-code administration
- proper deployment with process supervision


Access-code durations:
Use /generatecode followed by a duration: 30m, 6h, 1d, 7d, 4w. The duration starts when the customer redeems the one-time code.


ADMIN CUSTOMER MANAGEMENT
-------------------------
/customers
Shows all users who have interacted with the bot, their active/expired status,
expiry time, and keyword count.

/customer <telegram_user_id>
Shows details for one customer.

/revoke <telegram_user_id>
Immediately removes that customer's access.

Only ADMIN_USER_ID can use these commands.
