from __future__ import annotations
import os
import shutil
import subprocess
import time
import json
import urllib.request
import asyncio
import re
import requests
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timedelta
from collections import Counter
from bs4 import BeautifulSoup

from config import URL, DEMODAY_URL, HEADERS

WANTED_STATUSES = ["YANGI", "TASDIQLANGAN", "KELDI"]

DAYS_BACK = 0
DAYS_AHEAD = 0

_p = urlparse(URL)
LIST_URL = urlunparse((_p.scheme, _p.netloc, _p.path, "", "", ""))

student_cache = {}


def _clean_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        return "998" + digits
    elif len(digits) == 12 and digits.startswith("998"):
        return digits
    elif len(digits) > 9:
        return digits
    return ""


def _clean_tg(tg_raw: str) -> str:
    if not tg_raw:
        return ""
    tg_str = tg_raw.strip()
    # Check invalid placeholders
    if any(neg in tg_str.lower() for neg in ["user yoq", "yoq", "none", "null", "—", "yo'q", "yooq"]):
        return ""
    # Check if it's just slashes/dots/dashes
    if re.fullmatch(r"[@/\.\-\s]+", tg_str):
        return ""
    # If it's a phone number in tg_username
    phone_in_tg = _clean_phone(tg_str)
    if phone_in_tg:
        return ""
    tg_name = tg_str.lstrip("@").strip()
    if len(tg_name) >= 3 and re.match(r"^[A-Za-z0-9_]+$", tg_name):
        return "@" + tg_name
    return ""


def get_student_info(detail_url: str) -> dict:
    if not detail_url:
        return {"phone": "", "tg": ""}
    if detail_url in student_cache:
        return student_cache[detail_url]

    full_url = "https://crm.junior-it.uz" + detail_url
    try:
        r = requests.get(full_url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            btn = soup.find("button", attrs={"data-json": True})
            phone = ""
            tg = ""
            if btn:
                u = btn.get("data-username", "").strip()
                if u and u.startswith("998"):
                    phone = _clean_phone(u)
                try:
                    d = json.loads(btn["data-json"])
                    if not phone:
                        phone = _clean_phone(d.get("PHONE", ""))
                    tg = _clean_tg(d.get("TG_USERNAME", ""))
                except Exception:
                    pass
            student_cache[detail_url] = {"phone": phone, "tg": tg}
            return student_cache[detail_url]
    except Exception:
        pass
    return {"phone": "", "tg": ""}


def auto_sync_cookie_from_chrome() -> bool:
    try:
        import websockets

        async def _extract():
            temp_dir = "/tmp/chrome_auto_cookie_sync"
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
                "--remote-debugging-port=9225",
                f"--user-data-dir={temp_dir}",
                "--disable-gpu",
                "--no-first-run",
                "https://crm.junior-it.uz/account/ta_booking_requests/list?length=50"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            try:
                await asyncio.sleep(2.5)
                req = urllib.request.urlopen("http://127.0.0.1:9225/json")
                targets = json.loads(req.read().decode())
                page_target = None
                for t in targets:
                    if "junior-it.uz" in t.get("url", ""):
                        page_target = t
                        break

                if not page_target:
                    return None

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

                    return "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
            finally:
                proc.terminate()

        new_cookie = asyncio.run(_extract())
        if new_cookie and "PHPSESSID" in new_cookie:
            HEADERS["Cookie"] = new_cookie
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                new_lines = []
                for line in lines:
                    if line.startswith("COOKIE="):
                        new_lines.append(f"COOKIE={new_cookie}\n")
                    else:
                        new_lines.append(line)
                with open(env_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
            return True
    except Exception as e:
        print(f"Ошибка автосинхронизации cookie: {e}")
    return False


def _date_range(days_back: int = DAYS_BACK, days_ahead: int = DAYS_AHEAD):
    today = datetime.now()
    dfrom = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    dto = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    return dfrom, dto


def _parse_ta(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table.table tbody tr")

    bookings = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 10:
            continue

        status = cells[9].get_text(strip=True).upper()
        if status not in WANTED_STATUSES:
            continue

        student_el = cells[1].find("a")
        student_name = student_el.get_text(strip=True) if student_el else cells[1].get_text(strip=True)
        detail_link = student_el.get("href") if student_el and student_el.get("href") else ""

        # Fetch student phone/tg from profile
        info = get_student_info(detail_link) if detail_link else {"phone": "", "tg": ""}

        rec = cells[7].find("a")
        record_link = rec.get("href") if rec and rec.get("href") else ""

        bookings.append({
            "type": "TA",
            "student": student_name,
            "phone": info.get("phone", ""),
            "tg": info.get("tg", ""),
            "student_link": detail_link,
            "group": cells[2].get_text(strip=True),
            "admin": cells[3].get_text(strip=True),
            "mentor": cells[4].get_text(strip=True),
            "lesson": cells[5].get_text(strip=True),
            "task": "",
            "task_link": "",
            "booking": cells[6].get_text(strip=True),
            "record_link": record_link,
            "status": status,
        })
    return bookings


def _parse_demoday(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table")
    if not table:
        return []

    bookings = []
    for r in table.select("tbody tr"):
        cells = r.find_all("td")
        if len(cells) < 10:
            continue

        status = cells[9].get_text(strip=True).upper()
        if status not in WANTED_STATUSES:
            continue

        student_el = cells[1].find("a")
        student_name = student_el.get_text(strip=True) if student_el else cells[1].get_text(strip=True)
        detail_link = student_el.get("href") if student_el and student_el.get("href") else ""

        # Extract phone directly from table row or student profile
        phone_el = cells[1].find("div", class_="text-muted")
        raw_phone = phone_el.get_text(strip=True) if phone_el else ""
        phone = _clean_phone(raw_phone)
        tg = ""

        if not phone and detail_link:
            info = get_student_info(detail_link)
            phone = info.get("phone", "")
            tg = info.get("tg", "")

        group = cells[2].get_text(strip=True)

        task_el = cells[3].find("a")
        task_name = task_el.get_text(strip=True) if task_el else cells[3].get_text(strip=True)
        task_link = task_el.get("href") if task_el and task_el.get("href") else ""

        mentor = cells[4].get_text(strip=True)

        mod_strong = cells[5].find("strong")
        mod_name = mod_strong.get_text(strip=True) if mod_strong else ""
        sub_desc = cells[5].find("div", class_="text-muted")
        sub_desc_text = sub_desc.get_text(strip=True) if sub_desc else ""
        if mod_name and sub_desc_text:
            lesson = f"{mod_name} — {sub_desc_text}"
        elif mod_name:
            lesson = mod_name
        else:
            lesson = cells[5].get_text(strip=True)

        admin = cells[6].get_text(strip=True)

        raw_booking = cells[7].get_text(strip=True)
        booking = raw_booking.replace(" - ", ", ")

        rec_el = cells[8].find("a")
        rec_link = rec_el.get("href") if rec_el and rec_el.get("href") else ""

        bookings.append({
            "type": "Demoday",
            "student": student_name,
            "phone": phone,
            "tg": tg,
            "student_link": detail_link,
            "group": group,
            "task": task_name,
            "task_link": task_link,
            "mentor": mentor,
            "lesson": lesson,
            "admin": admin,
            "booking": booking,
            "record_link": rec_link,
            "status": status,
        })
    return bookings


def get_ta_bookings(dfrom: str = None, dto: str = None, retried: bool = False) -> list:
    if not dfrom or not dto:
        dfrom, dto = _date_range()

    ph = dict(HEADERS)
    ph["Referer"] = LIST_URL

    requests.post(
        LIST_URL,
        headers=ph,
        data={
            "tbr_apply_filters": "1",
            "tbr_status": "",
            "tbr_date_from": dfrom,
            "tbr_date_to": dto,
        },
        timeout=20,
    )

    response = requests.get(URL, headers=HEADERS, timeout=20)
    if "login" in response.url.lower() and not retried:
        print("Cookie устарел. Запуск автосинхронизации...")
        if auto_sync_cookie_from_chrome():
            return get_ta_bookings(dfrom, dto, retried=True)
        raise Exception("Cookie устарела.")

    if response.status_code != 200:
        raise Exception(f"Ошибка подключения к TA Booking: {response.status_code}")

    return _parse_ta(response.text)


def get_demoday_bookings(dfrom: str = None, dto: str = None, retried: bool = False) -> list:
    if not dfrom or not dto:
        dfrom, dto = _date_range()

    url = f"{DEMODAY_URL}?date_from={dfrom}&date_to={dto}"
    response = requests.get(url, headers=HEADERS, timeout=20)
    if "login" in response.url.lower() and not retried:
        print("Cookie устарел для Demo Day. Запуск автосинхронизации...")
        if auto_sync_cookie_from_chrome():
            return get_demoday_bookings(dfrom, dto, retried=True)
        raise Exception("Cookie устарела.")

    if response.status_code != 200:
        raise Exception(f"Ошибка подключения к Demo Day: {response.status_code}")

    return _parse_demoday(response.text)


def get_bookings():
    return get_ta_bookings() + get_demoday_bookings()


if __name__ == "__main__":
    dfrom, dto = _date_range()
    print(f"Диапазон дат: {dfrom} … {dto}")
    ta = get_ta_bookings()
    demos = get_demoday_bookings()
    print(f"Найдено TA броней: {len(ta)}")
    for i, b in enumerate(ta, 1):
        phone_s = f" [+{b['phone']}]" if b['phone'] else ""
        print(f"  {i}. {b['student']}{phone_s} ({b['group']}) - {b['lesson']} @ {b['booking']} [{b['status']}]")
    print(f"\nНайдено Demo Day броней: {len(demos)}")
    for i, b in enumerate(demos, 1):
        phone_s = f" [+{b['phone']}]" if b['phone'] else ""
        print(f"  {i}. {b['student']}{phone_s} ({b['group']}) - {b['lesson']} @ {b['booking']} [{b['status']}]")
