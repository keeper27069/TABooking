#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TABooking Bot - Diagnostic & Self-Repair Tool
"""
from __future__ import annotations
import os, sys, requests, asyncio
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

def main():
    print("=" * 55)
    print("🔍 TABOOKING BOT TIZIMINI TEKSHIRISH / ДИАГНОСТИКА")
    print("=" * 55)

    # 1. Check .env
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        print("❌ .env fayli topilmadi! / Файл .env не найден.")
        return

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_id = os.getenv("ADMIN_CHAT_ID", "").strip()
    cookie = os.getenv("COOKIE", "").strip()

    token_status = "✅ Mavjud" if bot_token and "YOUR" not in bot_token else "❌ Kiritilmagan / Не указан"
    print(f"🔑 Bot Token: {token_status}")

    admin_status = f"✅ {admin_id}" if admin_id and "YOUR" not in admin_id else "❌ Kiritilmagan / Не указан"
    print(f"🆔 Admin Chat ID: {admin_status}")

    cookie_status = f"✅ Mavjud ({cookie[:20]}...)" if "PHPSESSID" in cookie else "❌ Noto'g'ri / Не найден"
    print(f"🍪 Cookie: {cookie_status}")

    # 2. Check Telegram connection
    if bot_token and "YOUR" not in bot_token:
        try:
            r = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
            data = r.json()
            if data.get("ok"):
                bot_user = data["result"]["username"]
                print(f"🤖 Telegram Bot: ✅ @{bot_user} ga muvaffaqiyatli ulandi!")
            else:
                print(f"❌ Telegram Bot xatosi: {data.get('description')}")
        except Exception as e:
            print(f"❌ Telegramga ulanishda xatolik: {e}")

    # 3. Check CRM Cookie connection
    def is_auth(html):
        if not html:
            return False
        if 'name="phone"' in html and 'name="pass"' in html:
            return False
        return 'tbr_' in html or 'demo_day' in html or '/logout' in html or 'table' in html

    is_valid_session = False
    if "PHPSESSID" in cookie:
        try:
            headers = {"Cookie": cookie, "User-Agent": "Mozilla/5.0"}
            r_ta = requests.get("https://crm.junior-it.uz/account/ta_booking_requests/list?length=50", headers=headers, timeout=15)
            if r_ta.status_code == 200 and is_auth(r_ta.text):
                is_valid_session = True
        except Exception:
            pass

    if not is_valid_session:
        print("⚠️ CRM LMS Cookie eskirgan yoki foydalanuvchi tizimga kirmagan!")
        print("🔄 Google Chrome brauzeridan faol sessiya qidirilmoqda...")
        import sync_cookie
        sync_ok = sync_cookie.run_sync()
        if sync_ok:
            load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
            cookie = os.getenv("COOKIE", "").strip()
            headers = {"Cookie": cookie, "User-Agent": "Mozilla/5.0"}
            r_ta = requests.get("https://crm.junior-it.uz/account/ta_booking_requests/list?length=50", headers=headers, timeout=15)
            if r_ta.status_code == 200 and is_auth(r_ta.text):
                is_valid_session = True
                print("✅ Cookie Google Chrome dan muvaffaqiyatli yangilandi!")
            else:
                print("❌ Chrome da CRM ochilmagan yoki login qilinmagan.")
        else:
            print("❌ Google Chrome da faol login topilmadi. Iltimos Chrome da crm.junior-it.uz ga kiring va login qiling.")

    if is_valid_session:
        print("🌐 CRM LMS Sessiyasi: ✅ Faol va to'g'ri ishlamoqda!")
        try:
            import crm
            ta = crm.get_ta_bookings()
            demo = crm.get_demoday_bookings()
            print(f"📊 Yuklangan darslar: TA Bookings = {len(ta)} ta, Demo Day = {len(demo)} ta")
        except Exception as e:
            print(f"⚠️ Darslarni yuklashda xatolik: {e}")
    else:
        print("❌ CRM ga ulanib bo'lmadi. Iltimos Google Chrome da crm.junior-it.uz ga kirib, o'z hisobingizga kiring!")

    print("=" * 55)

if __name__ == "__main__":
    main()
