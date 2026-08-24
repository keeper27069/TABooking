from __future__ import annotations
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


def is_authenticated_crm_html(html: str) -> bool:
    if not html:
        return False
    if 'name="phone"' in html and 'name="pass"' in html:
        return False
    return 'tbr_' in html or 'demo_day' in html or '/logout' in html or 'table' in html


async def extract_fresh_cookie() -> str | None:
    chrome_base = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    if not os.path.exists(chrome_base):
        log("❌ Папка Google Chrome не найдена в ~/Library/Application Support/Google/Chrome")
        return None

    # Поиск всех возможных профилей Chrome (Default, Profile 1, Profile 2, etc.)
    profiles = ["Default"]
    for item in os.listdir(chrome_base):
        if item.startswith("Profile ") and os.path.isdir(os.path.join(chrome_base, item)):
            profiles.append(item)

    for prof in profiles:
        prof_cookies = os.path.join(chrome_base, prof, "Cookies")
        if not os.path.exists(prof_cookies):
            continue

        temp_dir = f"/tmp/chrome_cookie_sync_{prof.replace(' ', '_')}"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(os.path.join(temp_dir, "Default"), exist_ok=True)

        src_state = os.path.join(chrome_base, "Local State")
        if os.path.exists(src_state):
            shutil.copy2(src_state, os.path.join(temp_dir, "Local State"))

        shutil.copy2(prof_cookies, os.path.join(temp_dir, "Default", "Cookies"))

        chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not os.path.exists(chrome_bin):
            log("❌ Google Chrome не установлен в /Applications")
            return None

        port = 9228
        proc = subprocess.Popen([
            chrome_bin,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={temp_dir}",
            "--disable-gpu",
            "--no-first-run",
            "https://crm.junior-it.uz/account/ta_booking_requests/list?length=50"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        try:
            page_target = None
            for _ in range(15):
                await asyncio.sleep(0.3)
                try:
                    req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2)
                    targets = json.loads(req.read().decode())
                    for t in targets:
                        if "junior-it.uz" in t.get("url", ""):
                            page_target = t
                            break
                    if page_target:
                        break
                except Exception:
                    pass

            if page_target:
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
                        cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
                        # Check if valid session
                        test_headers = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"}
                        try:
                            r = requests.get("https://crm.junior-it.uz/account/ta_booking_requests/list?length=10", headers=test_headers, timeout=10)
                            if r.status_code == 200 and is_authenticated_crm_html(r.text):
                                log(f"✅ Успешно извлечён активный Cookie из профиля '{prof}'!")
                                return cookie_str
                            else:
                                log(f"ℹ️ Профиль '{prof}': Cookie есть, но пользователь не авторизован в CRM.")
                        except Exception:
                            pass
        except Exception as e:
            log(f"Ошибка проверки профиля '{prof}': {e}")
        finally:
            proc.terminate()

    return None


def run_sync() -> bool:
    log("Начало синхронизации cookie...")
    try:
        new_cookie = asyncio.run(extract_fresh_cookie())
        if not new_cookie or "PHPSESSID" not in new_cookie:
            log("❌ Не удалось извлечь активную сессию (PHPSESSID) из Chrome.")
            return False

        # Проверка валидности нового cookie
        test_headers = {
            "Cookie": new_cookie,
            "User-Agent": "Mozilla/5.0"
        }
        r = requests.get("https://crm.junior-it.uz/account/ta_booking_requests/list?length=50", headers=test_headers, timeout=15)
        if r.status_code != 200 or not is_authenticated_crm_html(r.text):
            log(f"❌ Извлечённый cookie не авторизован в CRM.")
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
