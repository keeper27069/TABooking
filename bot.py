# -*- coding: utf-8 -*-
"""
bot.py — Отказоустойчивый Telegram-бот на aiogram 3.x с глобальным логированием,
single-instance защитой, rate-limiting, error middleware и безопасными вызовами Telegram API.
"""
from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ErrorEvent, Message

from config import BOT_TOKEN, ADMIN_CHAT_ID
import crm_async
from i18n import t
from keyboards import (
    bookings_list_keyboard,
    demo_result_keyboard,
    language_keyboard,
    main_menu,
    notify_keyboard,
    person_card_keyboard,
    persistent_menu,
    report_menu,
    timeline_keyboard,
)
import marks
from single_instance import ensure_single_instance
from storage import load_messages, save_messages
from utils import status_icon

# --- 1. Настройка логирования с ротацией файлов ---
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s"
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()

file_handler = RotatingFileHandler(
    "bot.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(file_handler)

if sys.stdout.isatty():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(console_handler)

logger = logging.getLogger("bot.main")

# --- 2. Инициализация aiogram ---
session = AiohttpSession(timeout=30.0)
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

http_session: aiohttp.ClientSession | None = None

user_cache: dict[int, dict] = {}
sent_messages = load_messages()

STATUS_ORDER = {
    "YANGI": 0,
    "TASDIQLANGAN": 1,
    "KELDI": 2,
}

CACHE_TTL_SECONDS = 45
bookings_cache = {"ta": None, "demo": None, "ts": None}
_cache_lock = asyncio.Lock()


# --- 3. Безопасные хелперы Telegram API ---

async def safe_edit_text(message: Message, text: str, reply_markup=None, parse_mode=ParseMode.HTML):
    """Безопасно редактирует сообщение, игнорируя 'message is not modified'."""
    try:
        await message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            logger.debug("Игнорируем TelegramBadRequest: message is not modified")
        elif "message to edit not found" in err_msg:
            logger.warning("Сообщение для редактирования не найдено (удалено).")
        else:
            logger.error(f"TelegramBadRequest в safe_edit_text: {e}")
    except TelegramRetryAfter as e:
        logger.warning(f"Flood control: ожидание {e.retry_after} сек.")
        await asyncio.sleep(e.retry_after)
        await safe_edit_text(message, text, reply_markup, parse_mode)
    except Exception as e:
        logger.error(f"Ошибка в safe_edit_text: {e}")


async def safe_answer_cb(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Мгновенно отвечает на callback query, снимая спиннер загрузки."""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest as e:
        if "query is too old" in str(e).lower():
            logger.debug("Callback query устарел (query is too old).")
        else:
            logger.error(f"Ошибка callback.answer: {e}")
    except Exception as e:
        logger.error(f"Исключение в callback.answer: {e}")


async def _safe_delete(msg: Message):
    try:
        await msg.delete()
    except Exception:
        pass


def remember_message(user_id: int, message_id: int):
    key = str(user_id)
    sent_messages.setdefault(key, []).append(message_id)
    save_messages(sent_messages)


def forget_message(user_id: int, message_id: int):
    key = str(user_id)
    if key in sent_messages and message_id in sent_messages[key]:
        sent_messages[key].remove(message_id)
        save_messages(sent_messages)


def booking_key(b: dict) -> str:
    btype = b.get("type", "TA")
    return f"{btype}|{b.get('student', '')}|{b.get('group', '')}|{b.get('booking', '')}"


def has_lesson(value: str) -> bool:
    return (value or "").strip() not in ("", "-", "—", "–")


def _booking_dt(b: dict) -> datetime:
    raw = b.get("booking", "").strip()
    try:
        if "," in raw:
            return datetime.strptime(raw, "%d.%m.%Y, %H:%M")
        elif " - " in raw:
            return datetime.strptime(raw, "%d.%m.%Y - %H:%M")
    except Exception:
        pass
    return datetime.max


def split_when(b: dict) -> tuple[str, str]:
    raw = b.get("booking", "")
    if "," in raw:
        parts = raw.split(",")
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
    elif " - " in raw:
        parts = raw.split(" - ")
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
    return raw, ""


def mark_line(mark: dict | None, lang: str = "uz") -> str:
    if not mark or not mark.get("kind"):
        return f"🏷 {t('mark', lang)}: {t('mark_none', lang)}"
    if mark["kind"] == "extra":
        return f"🏷 {t('mark', lang)}: {t('mark_extra', lang)}"
    res = mark.get("demo_result")
    if res == "pass":
        return f"🏷 {t('mark', lang)}: {t('mark_demo_pass', lang)}"
    if res == "fail":
        return f"🏷 {t('mark', lang)}: {t('mark_demo_fail', lang)}"
    return f"🏷 {t('mark', lang)}: {t('mark_demo_none', lang)}"


def person_card_text(b: dict, mark: dict | None, lang: str = "uz", custom_header: str = "") -> str:
    date_part, time_part = split_when(b)
    is_demo = b.get("type") == "Demoday"
    header = custom_header or (t("demo_day", lang) if is_demo else t("ta_booking", lang))

    phone_clean = re.sub(r"\D", "", b.get("phone", ""))
    phone_display = f"+{phone_clean}" if phone_clean else t("not_specified", lang)

    lesson_val = b.get("lesson") or "—"
    status_val = b.get("status") or "—"

    lines = [
        f"{header}\n",
        f"👤 <b>{t('student', lang)}:</b> {b.get('student', '—')}",
        f"📞 <b>{t('phone', lang)}:</b> {phone_display}",
    ]
    if b.get("tg"):
        lines.append(f"💬 <b>Telegram:</b> {b['tg']}")

    lines.append(f"👥 <b>{t('group', lang)}:</b> {b.get('group', '—')}\n")

    if is_demo:
        lines.append(f"📚 <b>{t('lesson', lang)} (Modul):</b> <b>{lesson_val}</b>")
        if b.get("task"):
            lines.append(f"📝 <b>{t('task', lang)}:</b> {b['task']}")
        if b.get("mentor"):
            lines.append(f"👨 <b>{t('mentor', lang)}:</b> {b['mentor']}")
        if b.get("admin"):
            lines.append(f"👩 <b>{t('curator', lang)}:</b> {b['admin']}")
    else:
        lines.append(f"📚 <b>{t('lesson', lang)}:</b> <b>{lesson_val}</b>")
        if b.get("admin"):
            lines.append(f"👨 <b>{t('admin', lang)}:</b> {b['admin']}")
        if b.get("mentor"):
            lines.append(f"👨 <b>{t('mentor', lang)}:</b> {b['mentor']}")

    lines.append(f"\n📅 <b>{t('date', lang)}:</b> {date_part}")
    lines.append(f"🕒 <b>{t('time', lang)}:</b> {time_part}\n")
    lines.append(f"📌 <b>{t('status', lang)}:</b> {status_icon(status_val)} {status_val}\n")
    lines.append(f"{mark_line(mark, lang)}")

    return "\n".join(lines)


# --- 4. Кэш данных CRM ---

async def refresh_cache() -> tuple[list, list]:
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()

    async with _cache_lock:
        try:
            ta_data, demo_data = await asyncio.gather(
                crm_async.get_ta_bookings_async(http_session),
                crm_async.get_demoday_bookings_async(http_session),
            )
            bookings_cache["ta"] = ta_data
            bookings_cache["demo"] = demo_data
            bookings_cache["ts"] = datetime.now()
            return ta_data, demo_data
        except Exception as e:
            logger.error(f"Ошибка обновления кэша CRM: {e}")
            return bookings_cache.get("ta") or [], bookings_cache.get("demo") or []


async def get_cached_section(section: str, force: bool = False) -> list:
    now = datetime.now()
    needs_refresh = (
        force
        or bookings_cache[section] is None
        or bookings_cache["ts"] is None
        or (now - bookings_cache["ts"]).total_seconds() > CACHE_TTL_SECONDS
    )
    if needs_refresh:
        await refresh_cache()
    return bookings_cache.get(section) or []


async def fetch_today_section(section: str, force: bool = False) -> list:
    items = await get_cached_section(section, force=force)
    today_date = datetime.now().strftime("%d.%m.%Y")
    today_items = [b for b in items if today_date in b.get("booking", "")]
    today_items.sort(key=lambda b: (STATUS_ORDER.get(b.get("status"), 99), _booking_dt(b)))
    return today_items


async def get_today_timeline(force: bool = False) -> list:
    ta_items = await get_cached_section("ta", force=force)
    demo_items = await get_cached_section("demo", force=force)
    today_date = datetime.now().strftime("%d.%m.%Y")
    all_today = [b for b in (ta_items + demo_items) if today_date in b.get("booking", "")]
    all_today.sort(key=_booking_dt)
    return all_today


async def send_notification(text_builder, key: str, b: dict):
    rowid = marks.ensure_row(key, b)
    mark = marks.get_mark(key)
    task_link = b.get("task_link", "")
    rec_link = b.get("record_link", "")
    phone = b.get("phone", "")
    tg = b.get("tg", "")

    admins = marks.get_all_admins()
    chat_ids = {a["chat_id"] for a in admins}
    if ADMIN_CHAT_ID:
        try:
            chat_ids.add(int(ADMIN_CHAT_ID))
        except ValueError:
            pass

    for cid in chat_ids:
        try:
            u_lang = marks.get_user_lang(cid)
            msg_text = text_builder(u_lang) if callable(text_builder) else text_builder
            await bot.send_message(
                chat_id=cid,
                text=msg_text,
                reply_markup=notify_keyboard(rowid, mark, task_link, rec_link, phone, tg, lang=u_lang),
            )
            await asyncio.sleep(0.05)  # Anti-flood
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление в чат {cid}: {e}")


# --- 5. Глобальный Error Handler ---

@dp.error()
async def global_error_handler(event: ErrorEvent):
    logger.exception(
        f"🔥 Необработанная ошибка при обработке апдейта {event.update.update_id}: {event.exception}"
    )
    if event.update.callback_query:
        await safe_answer_cb(
            event.update.callback_query,
            "⚠️ Xatolik yuz berdi / Произошла ошибка.",
            show_alert=True,
        )
    elif event.update.message:
        try:
            await event.update.message.answer(
                "⚠️ Texnik nosozlik yuz berdi. Iltimos, qaytadan urinib ko'ring."
            )
        except Exception:
            pass


# --- 6. Хэндлеры бота ---

@dp.message(Command("start"))
async def start(message: Message):
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)

    marks.register_user(
        chat_id=user_id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        lang=lang,
    )

    ta_items, demo_items = await asyncio.gather(
        fetch_today_section("ta"),
        fetch_today_section("demo"),
    )
    user_cache[user_id] = {"ta": ta_items, "demo": demo_items}

    m1 = await message.answer(t("start_msg", lang), reply_markup=persistent_menu(lang))
    m2 = await message.answer(
        t("choose_section", lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=lang),
    )

    remember_message(user_id, m1.message_id)
    remember_message(user_id, m2.message_id)


# --- Хэндлер "Hozirgi dars" ---

@dp.callback_query(F.data == "show_current_lesson")
async def current_lesson_cb(callback: CallbackQuery):
    await safe_answer_cb(callback)
    await show_current_lesson(callback, callback.from_user.id)


@dp.message(F.text.in_({"⚡️ Hozirgi dars", "⚡️ Текущий урок", "/now", "/current"}))
async def current_lesson_msg(message: Message):
    await show_current_lesson(message, message.from_user.id)


async def show_current_lesson(target_message: Message | CallbackQuery, user_id: int):
    lang = marks.get_user_lang(user_id)
    timeline = await get_today_timeline()
    now = datetime.now()

    if not timeline:
        msg = t("empty_section", lang, title=t("ta_booking", lang) + " / " + t("demo_day", lang))
        if isinstance(target_message, CallbackQuery):
            await safe_edit_text(target_message.message, msg, reply_markup=main_menu(lang=lang))
        else:
            m = await target_message.answer(msg, reply_markup=main_menu(lang=lang))
            remember_message(user_id, m.message_id)
        return

    pending_lessons = [
        b for b in timeline
        if (b.get("status") or "").upper() not in ("KELDI", "KELMADI", "BEKOR QILINGAN", "RAD ETILGAN")
    ]

    if not pending_lessons:
        text = t("no_more_lessons", lang)
        if isinstance(target_message, CallbackQuery):
            await safe_edit_text(target_message.message, text, reply_markup=main_menu(lang=lang))
        else:
            m = await target_message.answer(text, reply_markup=main_menu(lang=lang))
            remember_message(user_id, m.message_id)
        return

    ongoing_b = None
    next_b = None
    next_diff = 999999

    for b in pending_lessons:
        dt = _booking_dt(b)
        if dt == datetime.max:
            continue
        diff = (dt - now).total_seconds() / 60.0
        if -10 <= diff <= 5 and ongoing_b is None:
            ongoing_b = b
        elif diff > 0 and diff < next_diff:
            next_b = b
            next_diff = diff

    active_booking = ongoing_b or next_b or pending_lessons[0]
    dt = _booking_dt(active_booking)
    diff = (dt - now).total_seconds() / 60.0 if dt != datetime.max else 9999
    btype_s = t("demo_day", lang) if active_booking.get("type") == "Demoday" else t("ta_booking", lang)
    status_s = active_booking.get("status", "")

    if -10 <= diff <= 5:
        badge_header = f"🔴 <b>{t('now_badge', lang)} ({btype_s}) — {status_icon(status_s)} {status_s}</b>"
    elif diff > 0:
        badge_header = f"🟡 <b>{t('next_badge', lang)} ({t('in_min', lang, min=int(diff))}) — {status_icon(status_s)} {status_s}</b>"
    else:
        badge_header = f"⏳ <b>{btype_s} ({status_icon(status_s)} {status_s})</b>"

    user_cache.setdefault(user_id, {})["timeline"] = timeline
    active_idx = timeline.index(active_booking)

    mark = marks.get_mark(booking_key(active_booking))
    card_txt = person_card_text(active_booking, mark, lang=lang, custom_header=badge_header)
    kb = person_card_keyboard(active_idx, 1, "timeline", mark, active_booking, lang=lang, from_timeline=True)

    if isinstance(target_message, CallbackQuery):
        await safe_edit_text(target_message.message, card_txt, reply_markup=kb)
    else:
        m = await target_message.answer(card_txt, reply_markup=kb)
        remember_message(user_id, m.message_id)


# --- Хэндлер "Jadval (Timeline)" ---

async def show_timeline_page(target_message: Message | CallbackQuery, user_id: int, page: int = 1):
    lang = marks.get_user_lang(user_id)
    timeline = await get_today_timeline()

    user_cache.setdefault(user_id, {})["timeline"] = timeline

    today_str = datetime.now().strftime("%d.%m.%Y")
    text = t("timeline_title", lang, date=today_str, total=len(timeline))
    kb = timeline_keyboard(timeline, page=page, lang=lang)

    if isinstance(target_message, CallbackQuery):
        await safe_edit_text(target_message.message, text, reply_markup=kb)
    else:
        m = await target_message.answer(text, reply_markup=kb)
        remember_message(user_id, m.message_id)


@dp.callback_query(F.data.startswith("timeline_"))
async def timeline_cb(callback: CallbackQuery):
    await safe_answer_cb(callback)
    page = int(callback.data.split("_")[1])
    await show_timeline_page(callback, callback.from_user.id, page=page)


@dp.message(F.text.in_({"⏰ Jadval", "⏰ Расписание", "⏰ Darslar jadvali", "⏰ Расписание уроков"}))
async def timeline_msg(message: Message):
    await show_timeline_page(message, message.from_user.id, page=1)


@dp.message(Command("schedule"))
async def schedule_cmd(message: Message):
    await show_timeline_page(message, message.from_user.id, page=1)


@dp.callback_query(F.data.startswith("tlperson_"))
async def show_timeline_person_cb(callback: CallbackQuery):
    await safe_answer_cb(callback)
    _, index, page = callback.data.split("_")
    index, page = int(index), int(page)

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    timeline = (user_cache.get(user_id) or {}).get("timeline") or await get_today_timeline()

    if index >= len(timeline):
        await safe_edit_text(callback.message, "⚠️ " + t("updated", lang), reply_markup=main_menu(lang=lang))
        return

    b = timeline[index]
    mark = marks.get_mark(booking_key(b))
    await safe_edit_text(
        callback.message,
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, "timeline", mark, b, lang=lang, from_timeline=True),
    )


@dp.callback_query(F.data.startswith("tlmkind_"))
async def tl_set_mark_kind_cb(callback: CallbackQuery):
    parts = callback.data.split("_")
    kind = parts[1]
    index = int(parts[3])
    page = int(parts[4])

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    timeline = (user_cache.get(user_id) or {}).get("timeline") or await get_today_timeline()

    if index >= len(timeline):
        await safe_answer_cb(callback, "...", show_alert=True)
        return
    b = timeline[index]
    marks.set_kind(booking_key(b), b, kind)
    await safe_answer_cb(callback, t("demo_btn", lang) if kind == "demo" else t("extra_btn", lang))
    mark = marks.get_mark(booking_key(b))
    await safe_edit_text(
        callback.message,
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, "timeline", mark, b, lang=lang, from_timeline=True),
    )


@dp.callback_query(F.data.startswith("tlmres_"))
async def tl_set_mark_result_cb(callback: CallbackQuery):
    parts = callback.data.split("_")
    result = parts[1]
    index = int(parts[3])
    page = int(parts[4])

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    timeline = (user_cache.get(user_id) or {}).get("timeline") or await get_today_timeline()

    if index >= len(timeline):
        await safe_answer_cb(callback, "...", show_alert=True)
        return
    b = timeline[index]
    marks.set_demo_result(booking_key(b), b, result)
    await safe_answer_cb(callback, t("pass_btn", lang) if result == "pass" else t("fail_btn", lang))
    mark = marks.get_mark(booking_key(b))
    await safe_edit_text(
        callback.message,
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, "timeline", mark, b, lang=lang, from_timeline=True),
    )


@dp.callback_query(F.data.startswith("tlmclr_"))
async def tl_clear_mark_cb(callback: CallbackQuery):
    parts = callback.data.split("_")
    index = int(parts[2])
    page = int(parts[3])

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    timeline = (user_cache.get(user_id) or {}).get("timeline") or await get_today_timeline()

    if index >= len(timeline):
        await safe_answer_cb(callback, "...", show_alert=True)
        return
    b = timeline[index]
    marks.clear_mark(booking_key(b))
    await safe_answer_cb(callback, t("clear_mark_btn", lang))
    mark = marks.get_mark(booking_key(b))
    await safe_edit_text(
        callback.message,
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, "timeline", mark, b, lang=lang, from_timeline=True),
    )


@dp.message(Command("lang"))
async def lang_command(message: Message):
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)
    m = await message.answer(t("choose_lang", lang), reply_markup=language_keyboard())
    remember_message(user_id, m.message_id)


@dp.callback_query(F.data == "choose_lang")
async def choose_lang_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await safe_answer_cb(callback)
    await safe_edit_text(callback.message, t("choose_lang", lang), reply_markup=language_keyboard())


@dp.callback_query(F.data.in_({"setlang_uz", "setlang_ru"}))
async def set_lang_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_lang = "uz" if callback.data == "setlang_uz" else "ru"
    marks.set_user_lang(user_id, new_lang)

    ta_items = (user_cache.get(user_id) or {}).get("ta") or []
    demo_items = (user_cache.get(user_id) or {}).get("demo") or []

    await safe_answer_cb(callback, t("lang_chosen", new_lang))
    await callback.message.answer(t("lang_chosen", new_lang), reply_markup=persistent_menu(new_lang))
    await safe_edit_text(
        callback.message,
        t("choose_section", new_lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=new_lang),
    )


@dp.message(F.text.in_({"📋 Menyu", "📋 Меню"}))
async def menu_button(message: Message):
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)
    ta_items, demo_items = await asyncio.gather(
        fetch_today_section("ta"),
        fetch_today_section("demo"),
    )
    user_cache[user_id] = {"ta": ta_items, "demo": demo_items}

    m = await message.answer(
        t("choose_section", lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=lang),
    )
    remember_message(user_id, m.message_id)


async def do_clear(message: Message):
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)
    ids = sent_messages.get(str(user_id), [])

    deleted = 0
    for msg_id in ids:
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg_id)
            deleted += 1
            await asyncio.sleep(0.04)  # Rate limiting для удаления
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            pass

    sent_messages[str(user_id)] = []
    save_messages(sent_messages)

    confirm = await message.answer(t("deleted_count", lang, count=deleted), reply_markup=persistent_menu(lang))
    remember_message(user_id, confirm.message_id)


@dp.message(Command("clear"))
async def clear_command(message: Message):
    await do_clear(message)


@dp.message(F.text.in_({"🧹 Tozalash", "🧹 Очистить"}))
async def clear_button(message: Message):
    await do_clear(message)


@dp.callback_query(F.data == "to_menu")
async def to_menu_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    ta_items, demo_items = await asyncio.gather(
        fetch_today_section("ta"),
        fetch_today_section("demo"),
    )
    user_cache[user_id] = {"ta": ta_items, "demo": demo_items}
    await safe_answer_cb(callback)
    await safe_edit_text(
        callback.message,
        t("choose_section", lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=lang),
    )


@dp.callback_query(F.data == "refresh_all")
async def refresh_all_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await safe_answer_cb(callback, t("updated", lang))
    ta_items, demo_items = await asyncio.gather(
        fetch_today_section("ta", force=True),
        fetch_today_section("demo", force=True),
    )
    user_cache[user_id] = {"ta": ta_items, "demo": demo_items}
    await safe_edit_text(
        callback.message,
        t("choose_section", lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=lang),
    )


@dp.callback_query(F.data.startswith(("ta_", "demo_", "refresh_ta_", "refresh_demo_")))
async def show_section_page(callback: CallbackQuery):
    parts = callback.data.split("_")
    if callback.data.startswith("refresh_"):
        section = parts[1]
        page = int(parts[2])
        is_refresh = True
    else:
        section = parts[0]
        page = int(parts[1])
        is_refresh = False

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    if is_refresh:
        await safe_answer_cb(callback, t("updated", lang))
    else:
        await safe_answer_cb(callback)

    items = await fetch_today_section(section, force=is_refresh)
    user_cache.setdefault(user_id, {})[section] = items

    title_name = t("demo_day", lang) if section == "demo" else t("ta_booking", lang)
    if not items:
        await safe_edit_text(
            callback.message,
            t("empty_section", lang, title=title_name),
            reply_markup=main_menu(lang=lang),
        )
        return

    today_date = datetime.now().strftime("%d.%m.%Y")
    text = f"{title_name} ({today_date})\n\n{t('total', lang)}: {len(items)}"
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=bookings_list_keyboard(items, page, section, lang=lang),
    )


async def render_card(callback: CallbackQuery, section: str, index: int, page: int):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    user_data = user_cache.get(user_id, {})
    items = user_data.get(section)

    if items is None:
        items = await fetch_today_section(section)
        user_cache.setdefault(user_id, {})[section] = items

    if index >= len(items):
        await safe_edit_text(callback.message, "⚠️ " + t("updated", lang), reply_markup=main_menu(lang=lang))
        return False

    b = items[index]
    mark = marks.get_mark(booking_key(b))
    await safe_edit_text(
        callback.message,
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, section, mark, b, lang=lang),
    )
    return True


@dp.callback_query(F.data.startswith("person_"))
async def show_card_cb(callback: CallbackQuery):
    await safe_answer_cb(callback)
    _, section, index, page = callback.data.split("_")
    await render_card(callback, section, int(index), int(page))


@dp.callback_query(F.data.startswith("mkind_"))
async def set_mark_kind_cb(callback: CallbackQuery):
    _, kind, section, index, page = callback.data.split("_")
    index, page = int(index), int(page)
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    user_data = user_cache.get(user_id, {})
    items = user_data.get(section, [])
    if not items or index >= len(items):
        await safe_answer_cb(callback, "...", show_alert=True)
        return
    b = items[index]
    marks.set_kind(booking_key(b), b, kind)
    await safe_answer_cb(callback, t("demo_btn", lang) if kind == "demo" else t("extra_btn", lang))
    await render_card(callback, section, index, page)


@dp.callback_query(F.data.startswith("mres_"))
async def set_mark_result_cb(callback: CallbackQuery):
    _, result, section, index, page = callback.data.split("_")
    index, page = int(index), int(page)
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    user_data = user_cache.get(user_id, {})
    items = user_data.get(section, [])
    if not items or index >= len(items):
        await safe_answer_cb(callback, "...", show_alert=True)
        return
    b = items[index]
    marks.set_demo_result(booking_key(b), b, result)
    await safe_answer_cb(callback, t("pass_btn", lang) if result == "pass" else t("fail_btn", lang))
    await render_card(callback, section, index, page)


@dp.callback_query(F.data.startswith("mclr_"))
async def clear_mark_cb(callback: CallbackQuery):
    _, section, index, page = callback.data.split("_")
    index, page = int(index), int(page)
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    user_data = user_cache.get(user_id, {})
    items = user_data.get(section, [])
    if not items or index >= len(items):
        await safe_answer_cb(callback, "...", show_alert=True)
        return
    b = items[index]
    marks.clear_mark(booking_key(b))
    await safe_answer_cb(callback, t("clear_mark_btn", lang))
    await render_card(callback, section, index, page)


@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await safe_answer_cb(callback)


@dp.callback_query(F.data.startswith("nm_"))
async def notify_mark_handler(callback: CallbackQuery):
    parts = callback.data.split("_")
    action = parts[1]
    rowid = int(parts[2])
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)

    row = marks.get_by_rowid(rowid)
    if not row:
        await safe_answer_cb(callback, "...", show_alert=True)
        return

    if action == "clr":
        marks.clear_by_id(rowid)
        await safe_answer_cb(callback, t("clear_mark_btn", lang))
        await _safe_delete(callback.message)
    elif action == "extra":
        marks.set_kind_by_id(rowid, "extra")
        await safe_answer_cb(callback, "➕ " + t("extra_btn", lang))
        await _safe_delete(callback.message)
    elif action == "demo":
        marks.set_kind_by_id(rowid, "demo")
        await safe_answer_cb(callback, "🎯 Demo")
        student = row.get("student") or ""
        await safe_edit_text(
            callback.message,
            f"🎯 Demo — {student}\nNatija? / Результат?",
            reply_markup=demo_result_keyboard(rowid, lang=lang),
        )
    elif action in ("pass", "fail"):
        marks.set_result_by_id(rowid, action)
        await safe_answer_cb(callback, "✅ " + t("pass_btn", lang) if action == "pass" else "❌ " + t("fail_btn", lang))
        await _safe_delete(callback.message)
    else:
        await safe_answer_cb(callback)


# --- Отчеты и Аналитика ---

def format_crm_report(data: dict, lang: str = "uz") -> str:
    if not data:
        return f"⚠️ {t('empty_section', lang, title='Analitika')}"

    try:
        d_from_dt = datetime.strptime(data["date_from"], "%Y-%m-%d")
        d_to_dt = datetime.strptime(data["date_to"], "%Y-%m-%d")
        if data["date_from"] != data["date_to"]:
            period_str = f"{d_from_dt.strftime('%d.%m.%Y')} — {d_to_dt.strftime('%d.%m.%Y')}"
        else:
            period_str = d_from_dt.strftime("%d.%m.%Y")
    except Exception:
        period_str = f"{data.get('date_from', '')} — {data.get('date_to', '')}"

    mentor_str = data.get("mentor") or "—"
    base_text = t(
        "report_analytics_header",
        lang,
        period=period_str,
        mentor=mentor_str,
        foiz=data.get("foiz", "0%"),
        yaratilgan=data.get("yaratilgan", "0"),
        kelgan=data.get("kelgan", "0"),
        kelmadi=data.get("kelmadi", "0"),
        kutilmoqda=data.get("kutilmoqda", "0"),
        rad_etilgan=data.get("rad_etilgan", "0"),
    )

    top_lessons = data.get("top_lessons") or []
    if top_lessons:
        base_text += t("report_top_lessons_title", lang)
        for item in top_lessons[:5]:
            count_unit = "ta" if lang == "uz" else "уроков"
            base_text += f"\n• <b>{item['lesson']}</b> — {item['count']} {count_unit} ({item['percent']})"

    return base_text


@dp.callback_query(F.data == "report_menu")
async def report_menu_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await safe_answer_cb(callback)
    await safe_edit_text(
        callback.message,
        t("report_intro", lang),
        reply_markup=report_menu(lang=lang),
    )


@dp.callback_query(F.data == "rep_today")
async def report_today_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await safe_answer_cb(callback, "⏳...")

    today_str = datetime.now().strftime("%Y-%m-%d")
    data = await crm_async.fetch_crm_analytics_safe(today_str, today_str)
    report_text = format_crm_report(data, lang=lang)

    await safe_edit_text(
        callback.message,
        report_text,
        reply_markup=report_menu(lang=lang),
    )


@dp.callback_query(F.data == "rep_week")
async def report_week_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await safe_answer_cb(callback, "⏳...")

    now = datetime.now()
    mon = now - timedelta(days=now.weekday())
    today = now

    data = await crm_async.fetch_crm_analytics_safe(mon.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
    report_text = format_crm_report(data, lang=lang)

    await safe_edit_text(
        callback.message,
        report_text,
        reply_markup=report_menu(lang=lang),
    )


@dp.callback_query(F.data == "rep_30")
async def report_30_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await safe_answer_cb(callback, "⏳...")

    date_to = datetime.now()
    date_from = date_to - timedelta(days=29)

    data = await crm_async.fetch_crm_analytics_safe(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    report_text = format_crm_report(data, lang=lang)

    await safe_edit_text(
        callback.message,
        report_text,
        reply_markup=report_menu(lang=lang),
    )


@dp.message(Command("report"))
async def report_command(message: Message):
    if not message.text:
        return
    parts = message.text.split()
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)

    if len(parts) == 1:
        m = await message.answer(
            t("report_intro", lang),
            reply_markup=report_menu(lang=lang),
        )
        remember_message(user_id, m.message_id)
        return
    elif len(parts) == 3:
        try:
            date_from = datetime.strptime(parts[1], "%d.%m.%Y")
            date_to = datetime.strptime(parts[2], "%d.%m.%Y")
        except ValueError:
            m = await message.answer("⚠️ Format: /report 17.08.2026 22.08.2026")
            remember_message(user_id, m.message_id)
            return
        if date_from > date_to:
            date_from, date_to = date_to, date_from
    else:
        m = await message.answer("⚠️ Format: /report 17.08.2026 22.08.2026")
        remember_message(user_id, m.message_id)
        return

    wait_m = await message.answer("⏳...")
    data = await crm_async.fetch_crm_analytics_safe(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    report_text = format_crm_report(data, lang=lang)

    await safe_edit_text(wait_m, report_text, reply_markup=report_menu(lang=lang))
    remember_message(user_id, wait_m.message_id)


# --- Команда обновления бота ---

@dp.message(Command("update"))
async def update_command(message: Message):
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)
    wait_msg = await message.answer("🔄 Yangilanishlar yuklanmoqda... / Загрузка обновлений...")
    remember_message(user_id, wait_msg.message_id)

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))

        proc_fetch = await asyncio.create_subprocess_exec(
            "git", "fetch", "origin", "main",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=script_dir,
        )
        await proc_fetch.communicate()

        proc_pull = await asyncio.create_subprocess_exec(
            "git", "reset", "--hard", "origin/main",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=script_dir,
        )
        out_pull, _ = await proc_pull.communicate()
        pull_str = out_pull.decode("utf-8", errors="ignore").strip()

        venv_pip = os.path.join(script_dir, ".venv", "bin", "pip")
        if os.path.exists(venv_pip):
            proc_pip = await asyncio.create_subprocess_exec(
                venv_pip, "install", "-r", "requirements.txt", "--quiet",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=script_dir,
            )
            await proc_pip.communicate()

        success_msg = (
            "✅ <b>Bot muvaffaqiyatli yangilandi va qayta ishga tushdi!</b>\n\n"
            + f"<code>{pull_str}</code>"
            if lang == "uz"
            else "✅ <b>Бот успешно обновлён и перезапущен!</b>\n\n"
            + f"<code>{pull_str}</code>"
        )

        await safe_edit_text(wait_msg, success_msg)
        await asyncio.sleep(1.5)
        os._exit(0)

    except Exception as e:
        await safe_edit_text(wait_msg, f"⚠️ Yangilashda xatolik: {e}")


# --- 7. Фоновый цикл проверки и напоминаний ---

async def background_poller():
    """Фоновый поллинг CRM и рассылка напоминаний за 5 минут."""
    logger.info("Фоновый поллер запущен.")
    while True:
        try:
            await asyncio.sleep(45)
            await refresh_cache()
            marks.clear_old_reminders()

            timeline = await get_today_timeline()
            now = datetime.now()

            for b in timeline:
                st = (b.get("status") or "").upper()
                if st in ("KELDI", "KELMADI", "BEKOR QILINGAN", "RAD ETILGAN"):
                    continue
                dt = _booking_dt(b)
                if dt == datetime.max:
                    continue

                diff = (dt - now).total_seconds() / 60.0
                if 2.0 <= diff <= 5.5:
                    b_key = booking_key(b)
                    if not marks.is_reminded_5m(b_key):
                        marks.set_reminded_5m(b_key)
                        admins = marks.get_all_admins()
                        chat_ids = {a["chat_id"] for a in admins}
                        if ADMIN_CHAT_ID:
                            try:
                                chat_ids.add(int(ADMIN_CHAT_ID))
                            except ValueError:
                                pass

                        for cid in chat_ids:
                            try:
                                u_lang = marks.get_user_lang(cid)
                                dt_str = dt.strftime("%H:%M")
                                b_type = t("demo_day", u_lang) if b.get("type") == "Demoday" else t("ta_booking", u_lang)
                                rem_text = t(
                                    "reminder_5m",
                                    u_lang,
                                    min=int(diff),
                                    student=b.get("student", "—"),
                                    phone=re.sub(r"\D", "", b.get("phone", "")),
                                    group=b.get("group", "—"),
                                    lesson=b.get("lesson", "—"),
                                    time=dt_str,
                                    status=f"{b_type} — {status_icon(st)} {st}",
                                )
                                await bot.send_message(cid, rem_text, parse_mode=ParseMode.HTML)
                                await asyncio.sleep(0.05)  # Anti-flood delay
                            except TelegramRetryAfter as e:
                                await asyncio.sleep(e.retry_after)
                            except Exception as e:
                                logger.error(f"Ошибка отправки напоминания пользователю {cid}: {e}")

        except asyncio.CancelledError:
            logger.info("Фоновый поллер остановлен.")
            break
        except Exception as e:
            logger.error(f"Неожиданная ошибка в background_poller: {e}")
            await asyncio.sleep(15)


# --- 8. Точка входа с Single Instance и Graceful Shutdown ---

async def main():
    global http_session
    ensure_single_instance(port=49200)

    marks.init_db()
    http_session = aiohttp.ClientSession()

    logger.info("Предзагрузка кэша CRM...")
    await refresh_cache()
    logger.info("Кэш CRM успешно подготовлен.")

    poller_task = asyncio.create_task(background_poller())

    try:
        logger.info("Запуск Telegram Long Polling (drop_pending_updates=True)...")
        await dp.start_polling(
            bot,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
        )
    finally:
        logger.info("Завершение работы (Graceful Shutdown)...")
        poller_task.cancel()
        if http_session and not http_session.closed:
            await http_session.close()
        await bot.session.close()
        logger.info("Все соединения закрыты.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")