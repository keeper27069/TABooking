#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автоматический ежедневный синхронизатор cookie из Google Chrome для CRM Junior IT.
Запускается каждый день в 08:00 утра через macOS launchd и внутренний планировщик бота.
"""

import os
import shutil
import subprocess
import time
import json
import urllib.request
import asyncio
import requests
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
LOG_PATH = os.path.join(BASE_DIR, "cookie_sync.log")

load_dotenv(ENV_PATH)


def log(msg: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{now_str}] {msg}"
    print(formatted)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


async def extract_fresh_cookie() -> str | None:
    temp_dir = "/tmp/chrome_morning_cookie_sync"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(os.path.join(temp_dir, "Default"), exist_ok=True)

    src_state = os.path.expanduser("~/Library/Application Support/Google/Chrome/Local State")
    if os.path.exists(src_state):
        shutil.copy2(src_state, os.path.join(temp_dir, "Local State"))

    src_cookies = os.path.expanduser("~/Library/Application Support/Google/Chrome/Default/Cookies")
    if os.path.exists(src_cookies):
        shutil.copy2(src_cookies, os.path.join(temp_dir, "Default", "Cookies"))

    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    proc = subprocess.Popen([
        chrome_bin,
        "--headless=new",
        "--remote-debugging-port=9226",
        f"--user-data-dir={temp_dir}",
        "--disable-gpu",
        "--no-first-run",
        "https://crm.junior-it.uz/account/ta_booking_requests/list?length=50"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        await asyncio.sleep(2.5)
        req = urllib.request.urlopen("http://127.0.0.1:9226/json")
        targets = json.loads(req.read().decode())
        page_target = None
        for t in targets:
            if "junior-it.uz" in t.get("url", ""):
                page_target = t
                break

        if not page_target:
            return None

        import websockets
        ws_url = page_target["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({
                "id": 1,
                "method": "Network.getCookies",
                "params": {"urls": ["https://crm.junior-it.uz/account/ta_booking_requests/list", "https://junior-it.uz"]}
            }))
            res = await ws.recv()
            cookies_list = json.loads(res).get("result", {}).get("cookies", [])

            cookie_dict = {}
            for c in cookies_list:
                cookie_dict[c["name"]] = c["value"]

            if "PHPSESSID" in cookie_dict:
                return "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
    except Exception as e:
        log(f"Ошибка извлечения cookie через CDP: {e}")
    finally:
        proc.terminate()
    return None


def run_sync() -> bool:
    log("Начало синхронизации cookie...")
    try:
        new_cookie = asyncio.run(extract_fresh_cookie())
        if not new_cookie or "PHPSESSID" not in new_cookie:
            log("❌ Не удалось извлечь PHPSESSID из Chrome.")
            return False

        # Проверка валидности нового cookie
        test_headers = {
            "Cookie": new_cookie,
            "User-Agent": "Mozilla/5.0"
        }
        r = requests.get("https://crm.junior-it.uz/account/ta_booking_requests/list?length=50", headers=test_headers, timeout=15)
        if r.status_code != 200 or "login" in r.url.lower():
            log(f"❌ Извлечённый cookie недействителен (status={r.status_code}, url={r.url})")
            return False

        # Обновление .env
        if os.path.exists(ENV_PATH):
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if line.startswith("COOKIE="):
                    new_lines.append(f"COOKIE={new_cookie}\n")
                else:
                    new_lines.append(line)
            with open(ENV_PATH, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

        log("✅ Cookie успешно обновлён и сохранён в .env!")

        # Оповещение всех зарегистрированных администраторов/менторов
        bot_token = os.getenv("BOT_TOKEN")
        if bot_token:
            chat_ids = set()
            try:
                import marks
                admins = marks.get_all_admins()
                for a in admins:
                    chat_ids.add(a["chat_id"])
            except Exception:
                pass

            env_admin = os.getenv("ADMIN_CHAT_ID")
            if env_admin:
                try:
                    chat_ids.add(int(env_admin))
                except ValueError:
                    pass

            today_str = datetime.now().strftime("%d.%m.%Y")
            for cid in chat_ids:
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={
                            "chat_id": cid,
                            "text": f"🔄 <b>[08:00 Avtosinxronizatsiya / Автосинхронизация]</b>\nCookie yangilandi / Cookie успешно обновлен ({today_str})!\nBot faol / Бот готов к работе.",
                            "parse_mode": "HTML"
                        },
                        timeout=10
                    )
                except Exception:
                    pass

        return True
    except Exception as e:
        log(f"Исключение при синхронизации: {e}")
        return False


if __name__ == "__main__":
    success = run_sync()
    exit(0 if success else 1)
