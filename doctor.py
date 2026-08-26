#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TABooking Bot - Comprehensive Diagnostic & Self-Repair Tool (Async Engine)
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import aiohttp
import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


async def main_async():
    print("=" * 60)
    print("🔍 TABOOKING BOT TIZIMINI TEKSHIRISH / КОМПЛЕКСНАЯ ДИАГНОСТИКА")
    print("=" * 60)

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

    # 2. Check Cookie with Auto-Recovery
    is_valid_cookie = "PHPSESSID" in cookie and "your_session_id" not in cookie
    if not is_valid_cookie:
        print("🔄 Cookie topilmadi. Google Chrome dan faol sessiya qidirilmoqda...")
        import sync_cookie
        if sync_cookie.run_sync():
            load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
            cookie = os.getenv("COOKIE", "").strip()
            is_valid_cookie = "PHPSESSID" in cookie and "your_session_id" not in cookie

    cookie_status = f"✅ Mavjud ({cookie[:25]}...)" if is_valid_cookie else "❌ Noto'g'ri / Не найден"
    print(f"🍪 Cookie: {cookie_status}")
    if not is_valid_cookie:
        print("   👉 ILTIMOS: Google Chrome brauzerida crm.junior-it.uz ga kiring va login qiling!")

    # 3. Check Port 49200 (Single Instance Lock)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 49200))
        sock.close()
        print("🔒 Single-Instance Port 49200: ✅ Bo'sh (Готов к запуску)")
    except socket.error:
        print("⚠️ Single-Instance Port 49200: 🔴 Boshqa bot jarayoni hozir ishlamoqda (Бот уже запущен в фоне)")

    # 4. Check SQLite DB
    try:
        import marks
        marks.init_db()
        admins = marks.get_all_admins()
        print(f"💾 SQLite marks.db: ✅ Faol (Adminlar soni: {len(admins)}, WAL mode yoqilgan)")
    except Exception as e:
        print(f"❌ SQLite xatosi: {e}")

    # 5. Check Telegram connection
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
    else:
        print("❌ Telegram Bot Token kiritilmagan (.env faylini tekshiring)")

    # 6. Check CRM connection
    if is_valid_cookie:
        import crm_async
        async with aiohttp.ClientSession() as sess:
            try:
                ta = await crm_async.get_ta_bookings_async(sess)
                demo = await crm_async.get_demoday_bookings_async(sess)
                print(f"📊 CRM Async Engine: ✅ Muvaffaqiyatli! TA Bookings = {len(ta)} ta, Demo Day = {len(demo)} ta")
            except Exception as e:
                print(f"⚠️ CRM Async Engine xatosi: {e}")
    else:
        print("⚠️ CRM tekshiruvi o'tkazib yuborildi (Cookie yo'qligi sababli)")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main_async())
