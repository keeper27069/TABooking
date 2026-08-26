# -*- coding: utf-8 -*-
"""
crm.py — Фасад модуля CRM: объединяет асинхронные методы crm_async и синхронные обёртки
для обратной совместимости со скриптами диагностики и CLI.
"""
from __future__ import annotations

import asyncio
import aiohttp
from config import URL, DEMODAY_URL, HEADERS
from crm_async import (
    WANTED_STATUSES,
    _clean_phone,
    _clean_tg,
    is_authenticated_crm_html,
    fetch_student_info,
    get_ta_bookings_async,
    get_demoday_bookings_async,
    fetch_crm_analytics_safe,
    student_cache,
)


def _date_range(days_back: int = 0, days_ahead: int = 0):
    from datetime import datetime, timedelta
    today = datetime.now()
    dfrom = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    dto = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    return dfrom, dto


def get_student_info(detail_url: str) -> dict:
    if not detail_url:
        return {"phone": "", "tg": ""}
    if detail_url in student_cache:
        return student_cache[detail_url]

    async def _runner():
        async with aiohttp.ClientSession() as sess:
            return await fetch_student_info(sess, detail_url)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return {"phone": "", "tg": ""}
        return loop.run_until_complete(_runner())
    except Exception:
        return asyncio.run(_runner())


def get_ta_bookings(dfrom: str = None, dto: str = None) -> list:
    async def _runner():
        async with aiohttp.ClientSession() as sess:
            return await get_ta_bookings_async(sess, dfrom, dto)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _runner()).result()
        return loop.run_until_complete(_runner())
    except Exception:
        return asyncio.run(_runner())


def get_demoday_bookings(dfrom: str = None, dto: str = None) -> list:
    async def _runner():
        async with aiohttp.ClientSession() as sess:
            return await get_demoday_bookings_async(sess, dfrom, dto)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _runner()).result()
        return loop.run_until_complete(_runner())
    except Exception:
        return asyncio.run(_runner())


def get_bookings():
    return get_ta_bookings() + get_demoday_bookings()


async def fetch_crm_analytics(d_from: str, d_to: str) -> dict:
    return await fetch_crm_analytics_safe(d_from, d_to)


if __name__ == "__main__":
    dfrom, dto = _date_range()
    print(f"Диапазон дат: {dfrom} … {dto}")
    ta = get_ta_bookings(dfrom, dto)
    demos = get_demoday_bookings(dfrom, dto)
    print(f"Найдено TA броней: {len(ta)}")
    for i, b in enumerate(ta, 1):
        phone_s = f" [+{b['phone']}]" if b.get("phone") else ""
        print(f"  {i}. {b.get('student')}{phone_s} ({b.get('group')}) - {b.get('lesson')} @ {b.get('booking')} [{b.get('status')}]")
    print(f"\nНайдено Demo Day броней: {len(demos)}")
    for i, b in enumerate(demos, 1):
        phone_s = f" [+{b['phone']}]" if b.get("phone") else ""
        print(f"  {i}. {b.get('student')}{phone_s} ({b.get('group')}) - {b.get('lesson')} @ {b.get('booking')} [{b.get('status')}]")