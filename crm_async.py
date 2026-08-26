# -*- coding: utf-8 -*-
"""
crm_async.py — Высокопроизводительный асинхронный клиент CRM LMS с connection pooling,
параллельным сбором профилей через Semaphore и защитой от зависаний Chrome CDP.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse

import aiohttp
from bs4 import BeautifulSoup
from config import URL, DEMODAY_URL, HEADERS

logger = logging.getLogger("bot.crm")

WANTED_STATUSES = ["YANGI", "TASDIQLANGAN", "KELDI"]
_p = urlparse(URL)
LIST_URL = urlunparse((_p.scheme, _p.netloc, _p.path, "", "", ""))

student_cache: dict[str, dict[str, str]] = {}
_sem = asyncio.Semaphore(6)  # Ограничение параллельных HTTP-запросов к CRM


def _clean_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        return "998" + digits
    elif len(digits) >= 12 and digits.startswith("998"):
        return digits
    return digits if len(digits) > 9 else ""


def _clean_tg(tg_raw: str) -> str:
    if not tg_raw:
        return ""
    tg_str = tg_raw.strip()
    if any(neg in tg_str.lower() for neg in ["user yoq", "yoq", "none", "null", "—", "yo'q", "yooq"]):
        return ""
    if re.fullmatch(r"[@/\.\-\s]+", tg_str):
        return ""
    if _clean_phone(tg_str):
        return ""
    tg_name = tg_str.lstrip("@").strip()
    if len(tg_name) >= 3 and re.match(r"^[A-Za-z0-9_]+$", tg_name):
        return "@" + tg_name
    return ""


def is_authenticated_crm_html(html: str) -> bool:
    if not html:
        return False
    if 'name="phone"' in html and 'name="pass"' in html:
        return False
    return any(marker in html for marker in ["tbr_", "demo_day", "/logout", "table"])


async def fetch_student_info(session: aiohttp.ClientSession, detail_url: str) -> dict[str, str]:
    if not detail_url:
        return {"phone": "", "tg": ""}
    if detail_url in student_cache:
        return student_cache[detail_url]

    full_url = "https://crm.junior-it.uz" + detail_url
    async with _sem:
        try:
            async with session.get(full_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    soup = BeautifulSoup(text, "html.parser")
                    btn = soup.find("button", attrs={"data-json": True})
                    phone, tg = "", ""
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
                    res = {"phone": phone, "tg": tg}
                    student_cache[detail_url] = res
                    return res
        except Exception as e:
            logger.debug(f"Не удалось получить данные студента {detail_url}: {e}")
    return {"phone": "", "tg": ""}


async def _parse_ta_async(session: aiohttp.ClientSession, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table.table tbody tr")

    raw_items = []
    fetch_tasks = []

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

        rec = cells[7].find("a")
        record_link = rec.get("href") if rec and rec.get("href") else ""

        raw_items.append({
            "type": "TA",
            "student": student_name,
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
        if detail_link:
            fetch_tasks.append(fetch_student_info(session, detail_link))
        else:
            fetch_tasks.append(asyncio.sleep(0, result={"phone": "", "tg": ""}))

    # Параллельное получение данных студентов с сохранением порядка
    info_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    bookings = []
    for item, info in zip(raw_items, info_results):
        info_dict = info if isinstance(info, dict) else {"phone": "", "tg": ""}
        item["phone"] = info_dict.get("phone", "")
        item["tg"] = info_dict.get("tg", "")
        bookings.append(item)

    return bookings


async def _parse_demoday_async(session: aiohttp.ClientSession, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table")
    if not table:
        return []

    raw_items = []
    fetch_tasks = []

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

        phone_el = cells[1].find("div", class_="text-muted")
        raw_phone = phone_el.get_text(strip=True) if phone_el else ""
        phone = _clean_phone(raw_phone)

        task_el = cells[3].find("a")
        task_name = task_el.get_text(strip=True) if task_el else cells[3].get_text(strip=True)
        task_link = task_el.get("href") if task_el and task_el.get("href") else ""

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

        raw_booking = cells[7].get_text(strip=True).replace(" - ", ", ")
        rec_el = cells[8].find("a")
        rec_link = rec_el.get("href") if rec_el and rec_el.get("href") else ""

        item_dict = {
            "type": "Demoday",
            "student": student_name,
            "phone": phone,
            "tg": "",
            "student_link": detail_link,
            "group": cells[2].get_text(strip=True),
            "task": task_name,
            "task_link": task_link,
            "mentor": cells[4].get_text(strip=True),
            "lesson": lesson,
            "admin": cells[6].get_text(strip=True),
            "booking": raw_booking,
            "record_link": rec_link,
            "status": status,
        }
        raw_items.append(item_dict)

        if not phone and detail_link:
            fetch_tasks.append(fetch_student_info(session, detail_link))
        else:
            fetch_tasks.append(asyncio.sleep(0, result={"phone": phone, "tg": ""}))

    info_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    bookings = []
    for item, info in zip(raw_items, info_results):
        info_dict = info if isinstance(info, dict) else {}
        if not item["phone"]:
            item["phone"] = info_dict.get("phone", "")
        item["tg"] = info_dict.get("tg", "")
        bookings.append(item)

    return bookings


async def get_ta_bookings_async(session: aiohttp.ClientSession, dfrom: str = None, dto: str = None, retried: bool = False) -> list[dict]:
    if not dfrom or not dto:
        today = datetime.now().strftime("%Y-%m-%d")
        dfrom, dto = today, today

    ph = dict(HEADERS)
    ph["Referer"] = LIST_URL
    timeout = aiohttp.ClientTimeout(total=15, connect=5)

    try:
        await session.post(
            LIST_URL,
            headers=ph,
            data={"tbr_apply_filters": "1", "tbr_status": "", "tbr_date_from": dfrom, "tbr_date_to": dto},
            timeout=timeout,
        )

        async with session.get(URL, headers=HEADERS, timeout=timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"CRM TA Status Code: {resp.status}")
            text = await resp.text()
            if not is_authenticated_crm_html(text):
                if not retried:
                    logger.warning("Cookie устарел. Запуск синхронизации...")
                    from sync_cookie import extract_fresh_cookie
                    new_c = await extract_fresh_cookie()
                    if new_c:
                        HEADERS["Cookie"] = new_c
                        return await get_ta_bookings_async(session, dfrom, dto, retried=True)
                raise RuntimeError("Cookie устарела.")
            return await _parse_ta_async(session, text)
    except Exception as e:
        logger.error(f"Ошибка получения TA броней: {e}")
        return []


async def get_demoday_bookings_async(session: aiohttp.ClientSession, dfrom: str = None, dto: str = None, retried: bool = False) -> list[dict]:
    if not dfrom or not dto:
        today = datetime.now().strftime("%Y-%m-%d")
        dfrom, dto = today, today

    url = f"{DEMODAY_URL}?date_from={dfrom}&date_to={dto}"
    timeout = aiohttp.ClientTimeout(total=15, connect=5)

    try:
        async with session.get(url, headers=HEADERS, timeout=timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"CRM DemoDay Status Code: {resp.status}")
            text = await resp.text()
            if not is_authenticated_crm_html(text):
                if not retried:
                    logger.warning("Cookie устарел для Demo Day. Запуск синхронизации...")
                    from sync_cookie import extract_fresh_cookie
                    new_c = await extract_fresh_cookie()
                    if new_c:
                        HEADERS["Cookie"] = new_c
                        return await get_demoday_bookings_async(session, dfrom, dto, retried=True)
                raise RuntimeError("Cookie устарела.")
            return await _parse_demoday_async(session, text)
    except Exception as e:
        logger.error(f"Ошибка получения Demo Day броней: {e}")
        return []


def find_chrome_binary() -> str | None:
    """Кроссплатформенный поиск исполняемого файла Google Chrome / Chromium."""
    if os.getenv("CHROME_BIN") and os.path.exists(os.getenv("CHROME_BIN")):
        return os.getenv("CHROME_BIN")
    for bin_name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"]:
        p = shutil.which(bin_name)
        if p and os.path.exists(p):
            return p
    mac_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(mac_bin):
        return mac_bin
    for lin_path in ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"]:
        if os.path.exists(lin_path):
            return lin_path
    return None


def find_chrome_user_data_dir() -> str | None:
    """Кроссплатформенный поиск директории профилей Chrome."""
    if os.getenv("CHROME_USER_DATA") and os.path.exists(os.getenv("CHROME_USER_DATA")):
        return os.getenv("CHROME_USER_DATA")
    candidates = [
        os.path.expanduser("~/Library/Application Support/Google/Chrome"),
        os.path.expanduser("~/Library/Application Support/Chromium"),
        os.path.expanduser("~/.config/google-chrome"),
        os.path.expanduser("~/.config/chromium"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


async def fetch_crm_analytics_safe(d_from: str, d_to: str) -> dict:
    """Извлечение аналитики через Chrome CDP с гарантированным тайм-аутом и безопасной очисткой процессов"""
    chrome_bin = find_chrome_binary()
    if not chrome_bin:
        logger.error("Исполняемый файл Google Chrome/Chromium не найден на этой системе.")
        return {}

    port = 9255
    temp_dir = f"/tmp/chrome_analytics_safe_{d_from}_{d_to}"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(os.path.join(temp_dir, "Default"), exist_ok=True)

    chrome_base = find_chrome_user_data_dir()
    if chrome_base:
        src_state = os.path.join(chrome_base, "Local State")
        if os.path.exists(src_state):
            shutil.copy2(src_state, os.path.join(temp_dir, "Local State"))
        src_cookies = os.path.join(chrome_base, "Default", "Cookies")
        if os.path.exists(src_cookies):
            shutil.copy2(src_cookies, os.path.join(temp_dir, "Default", "Cookies"))

    proc = await asyncio.create_subprocess_exec(
        chrome_bin,
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={temp_dir}",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "https://crm.junior-it.uz/account/ta_booking_analytics/list",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    try:
        return await asyncio.wait_for(_run_cdp_extraction(port, d_from, d_to), timeout=20.0)
    except asyncio.TimeoutError:
        logger.error("Таймаут выполнения Chrome CDP аналитики.")
        return {}
    except Exception as e:
        logger.error(f"Ошибка получения аналитики: {e}")
        return {}
    finally:
        try:
            proc.terminate()
            await asyncio.sleep(0.2)
            if proc.returncode is None:
                proc.kill()
        except Exception:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)


async def _run_cdp_extraction(port: int, d_from: str, d_to: str) -> dict:
    import websockets

    # Ожидаем запуск порта Chrome
    targets = []
    async with aiohttp.ClientSession() as http_sess:
        for _ in range(12):
            await asyncio.sleep(0.3)
            try:
                async with http_sess.get(f"http://127.0.0.1:{port}/json", timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status == 200:
                        targets = await r.json()
                        if any("junior-it.uz" in t.get("url", "") for t in targets):
                            break
            except Exception:
                pass

    if not targets:
        return {}

    page_target = [t for t in targets if "junior-it.uz" in t.get("url", "")][0]
    ws_url = page_target["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, ping_interval=5, ping_timeout=5) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await asyncio.wait_for(ws.recv(), timeout=4.0)
        await ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
        await asyncio.wait_for(ws.recv(), timeout=4.0)

        js_submit = f"""
        (() => {{
            const f = document.querySelector("input[name='tba_date_from']");
            const t = document.querySelector("input[name='tba_date_to']");
            if (f && t) {{
                f.value = "{d_from}";
                t.value = "{d_to}";
                document.querySelector("button[type='submit']").click();
            }}
        }})()
        """
        await ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {"expression": js_submit}}))

        for _ in range(25):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
            if msg.get("method") == "Page.loadEventFired":
                break

        await asyncio.sleep(0.8)
        js_extract = """
        (() => {
            const text = document.body.innerText;
            const rows = [];
            document.querySelectorAll("table tr").forEach(tr => {
                const tds = Array.from(tr.querySelectorAll("td")).map(td => td.innerText.trim());
                if (tds.length >= 4 && /^\\d+$/.test(tds[0])) {
                    rows.push({ num: tds[0], lesson: tds[1] || '', course: tds[2] || '', count: tds[3] || '', percent: tds[4] || '' });
                }
            });
            return JSON.stringify({ text, rows });
        })()
        """
        await ws.send(json.dumps({"id": 4, "method": "Runtime.evaluate", "params": {"expression": js_extract}}))

        raw_json = "{}"
        for _ in range(15):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=4.0))
            if msg.get("id") == 4:
                raw_json = msg.get("result", {}).get("result", {}).get("value", "{}")
                break

        payload = json.loads(raw_json)
        lines = [l.strip() for l in payload.get("text", "").split("\n") if l.strip()]
        data = {
            "date_from": d_from,
            "date_to": d_to,
            "mentor": "",
            "kutilmoqda": "0",
            "yaratilgan": "0",
            "kelgan": "0",
            "kelmadi": "0",
            "rad_etilgan": "0",
            "foiz": "0%",
            "top_lessons": payload.get("rows", []),
        }

        for i, line in enumerate(lines):
            if line == "Kutilmoqda" and i + 1 < len(lines):
                data["kutilmoqda"] = lines[i + 1]
                if i > 0 and not any(x in lines[i - 1] for x in ["Analitika", "Menyu", "Filtr"]):
                    data["mentor"] = lines[i - 1]
            elif line == "Yaratilgan" and i + 1 < len(lines):
                data["yaratilgan"] = lines[i + 1]
            elif line == "Kelgan" and i + 1 < len(lines):
                data["kelgan"] = lines[i + 1]
            elif line == "Kelmadi" and i + 1 < len(lines):
                data["kelmadi"] = lines[i + 1]
            elif line == "Rad etilgan" and i + 1 < len(lines):
                data["rad_etilgan"] = lines[i + 1]
            elif line == "Foiz" and i + 1 < len(lines):
                data["foiz"] = lines[i + 1]
        return data
