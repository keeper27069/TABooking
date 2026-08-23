import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIE = os.getenv("COOKIE")
URL = os.getenv("CRM_URL")
DEMODAY_URL = os.getenv("DEMODAY_URL", "https://crm.junior-it.uz/account/demo_day/list")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

HEADERS = {
    "Cookie": COOKIE,
    "User-Agent": "Mozilla/5.0"
}

if not BOT_TOKEN or not COOKIE or not URL:
    raise RuntimeError("Проверь .env — не заданы BOT_TOKEN, COOKIE или CRM_URL")
