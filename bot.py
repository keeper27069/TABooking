from __future__ import annotations
import os
import subprocess
import sys
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from config import BOT_TOKEN, ADMIN_CHAT_ID
from crm import get_ta_bookings, get_demoday_bookings
from keyboards import (
    main_menu,
    bookings_list_keyboard,
    person_card_keyboard,
    persistent_menu,
    report_menu,
    language_keyboard,
    notify_keyboard,
    demo_result_keyboard,
    timeline_keyboard,
)
from utils import status_icon
from storage import load_messages, save_messages
from i18n import t
import marks

from datetime import datetime, timedelta
import asyncio
import re

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

user_cache = {}
sent_messages = load_messages()
reminded_lessons = set()

STATUS_ORDER = {
    "YANGI": 0,
    "TASDIQLANGAN": 1,
    "KELDI": 2,
}

last_snapshot = None


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
    return f"{btype}|{b['student']}|{b['group']}|{b['booking']}"


def has_lesson(value: str) -> bool:
    return (value or "").strip() not in ("", "-", "—", "–")


def _booking_dt(b: dict) -> datetime:
    raw = b.get("booking", "").strip()
    try:
        if "," in raw:
            return datetime.strptime(raw, "%d.%m.%Y, %H:%M")
        elif " - " in raw:
            return datetime.strptime(raw, "%d.%m.%Y - %H:%M")
    except (ValueError, KeyError):
        pass
    return datetime.max


CACHE_TTL_SECONDS = 45
bookings_cache = {"ta": None, "demo": None, "ts": None}


async def refresh_cache() -> tuple[list, list]:
    ta_data, demo_data = await asyncio.gather(
        asyncio.to_thread(get_ta_bookings),
        asyncio.to_thread(get_demoday_bookings),
    )
    bookings_cache["ta"] = ta_data
    bookings_cache["demo"] = demo_data
    bookings_cache["ts"] = datetime.now()
    return ta_data, demo_data


async def get_cached_section(section: str, force: bool = False) -> list:
    now = datetime.now()
    needs_refresh = (
        force or
        bookings_cache[section] is None or
        bookings_cache["ts"] is None or
        (now - bookings_cache["ts"]).total_seconds() > CACHE_TTL_SECONDS
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


def split_when(b: dict) -> tuple[str, str]:
    raw = b.get("booking", "")
    if "," in raw:
        parts = raw.split(",")
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
    elif " - " in raw:
        parts = raw.split(" - ")
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
    return raw, ""


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



async def send_notification(text_builder, key: str, b: dict):
    rowid = marks.ensure_row(key, b)
    mark = marks.get_mark(key)
    task_link = b.get("task_link", "")
    rec_link = b.get("record_link", "")
    phone = b.get("phone", "")
    tg = b.get("tg", "")

    admins = marks.get_all_admins()
    chat_ids = set([a["chat_id"] for a in admins])
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
        except Exception as e:
            print(f"Не удалось отправить уведомление в чат {cid}: {e}")


async def _safe_delete(msg: Message):
    try:
        await msg.delete()
    except Exception:
        pass


@dp.message(Command("start"))
async def start(message: Message):
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)

    marks.register_user(
        chat_id=user_id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        lang=lang
    )

    ta_items, demo_items = await asyncio.gather(
        fetch_today_section("ta"),
        fetch_today_section("demo"),
    )
    user_cache[user_id] = {"ta": ta_items, "demo": demo_items}

    m1 = await message.answer(t("start_msg", lang), reply_markup=persistent_menu(lang))
    m2 = await message.answer(
        t("choose_section", lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=lang)
    )

    remember_message(user_id, m1.message_id)
    remember_message(user_id, m2.message_id)



# --- Хэндлер "Hozirgi dars" (Текущий урок прямо сейчас) ---

@dp.callback_query(lambda c: c.data == "show_current_lesson")
async def current_lesson_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    await show_current_lesson(callback, user_id)


@dp.message(lambda m: m.text in ("⚡️ Hozirgi dars", "⚡️ Текущий урок", "/now", "/current"))
async def current_lesson_msg(message: Message):
    user_id = message.from_user.id
    await show_current_lesson(message, user_id)

async def show_current_lesson(target_message: Message | CallbackQuery, user_id: int):
    lang = marks.get_user_lang(user_id)
    timeline = await get_today_timeline()
    now = datetime.now()

    if not timeline:
        msg = t("empty_section", lang, title=t("ta_booking", lang) + " / " + t("demo_day", lang))
        if isinstance(target_message, CallbackQuery):
            await target_message.answer()
            await target_message.message.edit_text(msg, reply_markup=main_menu(lang=lang))
        else:
            m = await target_message.answer(msg, reply_markup=main_menu(lang=lang))
            remember_message(user_id, m.message_id)
        return

    # 1. Отбираем не отмеченные уроки (НЕ KELDI, НЕ KELMADI, НЕ BEKOR)
    pending_lessons = [
        b for b in timeline
        if (b.get("status") or "").upper() not in ("KELDI", "KELMADI", "BEKOR QILINGAN", "RAD ETILGAN")
    ]

    # Если все уроки уже завершены (все KELDI/KELMADI)
    if not pending_lessons:
        text = t("no_more_lessons", lang)
        if isinstance(target_message, CallbackQuery):
            await target_message.answer()
            await target_message.message.edit_text(text, reply_markup=main_menu(lang=lang))
        else:
            m = await target_message.answer(text, reply_markup=main_menu(lang=lang))
            remember_message(user_id, m.message_id)
        return

    # 2. Ищем:
    # - ongoing_b: урок, который идет прямо сейчас (-10 <= diff <= 5)
    # - next_b: ближайший следующий урок в будущем (diff > 0)
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

    # Приоритет:
    # 1. Текущий урок (начался <= 10 мин назад или начнется <= 5 мин)
    # 2. Следующий предстоящий урок сегодня
    # 3. Если все предстоящие прошли (например вечер), берем последний ожидающий урок
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

    user_cache[user_id] = user_cache.get(user_id, {})
    user_cache[user_id]["timeline"] = timeline
    active_idx = timeline.index(active_booking)

    mark = marks.get_mark(booking_key(active_booking))
    card_txt = person_card_text(active_booking, mark, lang=lang, custom_header=badge_header)
    kb = person_card_keyboard(active_idx, 1, "timeline", mark, active_booking, lang=lang, from_timeline=True)

    if isinstance(target_message, CallbackQuery):
        await target_message.answer()
        await target_message.message.edit_text(card_txt, reply_markup=kb, parse_mode="HTML")
    else:
        m = await target_message.answer(card_txt, reply_markup=kb, parse_mode="HTML")
        remember_message(user_id, m.message_id)


# --- Хэндлер "Jadval (Timeline)" ---
async def show_timeline_page(target_message: Message | CallbackQuery, user_id: int, page: int = 1):
    lang = marks.get_user_lang(user_id)
    timeline = await get_today_timeline()

    if user_id not in user_cache:
        user_cache[user_id] = {}
    user_cache[user_id]["timeline"] = timeline

    today_str = datetime.now().strftime("%d.%m.%Y")
    text = t("timeline_title", lang, date=today_str, total=len(timeline))
    kb = timeline_keyboard(timeline, page=page, lang=lang)

    if isinstance(target_message, CallbackQuery):
        await target_message.answer()
        await target_message.message.edit_text(text, reply_markup=kb)
    else:
        m = await target_message.answer(text, reply_markup=kb)
        remember_message(user_id, m.message_id)


@dp.callback_query(lambda c: c.data.startswith("timeline_"))
async def timeline_cb(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    await show_timeline_page(callback, callback.from_user.id, page=page)


@dp.message(lambda m: m.text in ("⏰ Jadval", "⏰ Расписание", "⏰ Darslar jadvali", "⏰ Расписание уроков"))
async def timeline_msg(message: Message):
    await show_timeline_page(message, message.from_user.id, page=1)


@dp.message(Command("schedule"))
async def schedule_cmd(message: Message):
    await show_timeline_page(message, message.from_user.id, page=1)


@dp.callback_query(lambda c: c.data.startswith("tlperson_"))
async def show_timeline_person_cb(callback: CallbackQuery):
    await callback.answer()
    _, index, page = callback.data.split("_")
    index, page = int(index), int(page)

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    timeline = (user_cache.get(user_id) or {}).get("timeline") or await get_today_timeline()

    if index >= len(timeline):
        await callback.message.edit_text("⚠️ " + t("updated", lang), reply_markup=main_menu(lang=lang))
        return

    b = timeline[index]
    mark = marks.get_mark(booking_key(b))
    await callback.message.edit_text(
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, "timeline", mark, b, lang=lang, from_timeline=True),
    )


@dp.callback_query(lambda c: c.data.startswith("tlmkind_"))
async def tl_set_mark_kind_cb(callback: CallbackQuery):
    parts = callback.data.split("_")
    kind = parts[1]
    index = int(parts[3])
    page = int(parts[4])

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    timeline = (user_cache.get(user_id) or {}).get("timeline") or await get_today_timeline()

    if index >= len(timeline):
        await callback.answer("...", show_alert=True)
        return
    b = timeline[index]
    marks.set_kind(booking_key(b), b, kind)
    await callback.answer(t("demo_btn", lang) if kind == "demo" else t("extra_btn", lang))
    mark = marks.get_mark(booking_key(b))
    await callback.message.edit_text(
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, "timeline", mark, b, lang=lang, from_timeline=True),
    )


@dp.callback_query(lambda c: c.data.startswith("tlmres_"))
async def tl_set_mark_result_cb(callback: CallbackQuery):
    parts = callback.data.split("_")
    result = parts[1]
    index = int(parts[3])
    page = int(parts[4])

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    timeline = (user_cache.get(user_id) or {}).get("timeline") or await get_today_timeline()

    if index >= len(timeline):
        await callback.answer("...", show_alert=True)
        return
    b = timeline[index]
    marks.set_demo_result(booking_key(b), b, result)
    await callback.answer(t("pass_btn", lang) if result == "pass" else t("fail_btn", lang))
    mark = marks.get_mark(booking_key(b))
    await callback.message.edit_text(
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, "timeline", mark, b, lang=lang, from_timeline=True),
    )


@dp.callback_query(lambda c: c.data.startswith("tlmclr_"))
async def tl_clear_mark_cb(callback: CallbackQuery):
    parts = callback.data.split("_")
    index = int(parts[2])
    page = int(parts[3])

    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    timeline = (user_cache.get(user_id) or {}).get("timeline") or await get_today_timeline()

    if index >= len(timeline):
        await callback.answer("...", show_alert=True)
        return
    b = timeline[index]
    marks.clear_mark(booking_key(b))
    await callback.answer(t("clear_mark_btn", lang))
    mark = marks.get_mark(booking_key(b))
    await callback.message.edit_text(
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, "timeline", mark, b, lang=lang, from_timeline=True),
    )


@dp.message(Command("lang"))
async def lang_command(message: Message):
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)
    m = await message.answer(t("choose_lang", lang), reply_markup=language_keyboard())
    remember_message(user_id, m.message_id)


@dp.callback_query(lambda c: c.data == "choose_lang")
async def choose_lang_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await callback.answer()
    await callback.message.edit_text(t("choose_lang", lang), reply_markup=language_keyboard())


@dp.callback_query(lambda c: c.data in ("setlang_uz", "setlang_ru"))
async def set_lang_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_lang = "uz" if callback.data == "setlang_uz" else "ru"
    marks.set_user_lang(user_id, new_lang)

    ta_items = (user_cache.get(user_id) or {}).get("ta") or []
    demo_items = (user_cache.get(user_id) or {}).get("demo") or []

    await callback.answer(t("lang_chosen", new_lang))
    await callback.message.answer(t("lang_chosen", new_lang), reply_markup=persistent_menu(new_lang))
    await callback.message.edit_text(
        t("choose_section", new_lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=new_lang)
    )


@dp.message(lambda m: m.text in ("📋 Menyu", "📋 Меню"))
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
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=lang)
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
        except Exception:
            pass

    sent_messages[str(user_id)] = []
    save_messages(sent_messages)

    confirm = await message.answer(t("deleted_count", lang, count=deleted), reply_markup=persistent_menu(lang))
    remember_message(user_id, confirm.message_id)


@dp.message(Command("clear"))
async def clear_command(message: Message):
    await do_clear(message)


@dp.message(lambda m: m.text in ("🧹 Tozalash", "🧹 Очистить"))
async def clear_button(message: Message):
    await do_clear(message)


@dp.callback_query(lambda c: c.data == "to_menu")
async def to_menu_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    ta_items, demo_items = await asyncio.gather(
        fetch_today_section("ta"),
        fetch_today_section("demo"),
    )
    user_cache[user_id] = {"ta": ta_items, "demo": demo_items}
    await callback.answer()
    await callback.message.edit_text(
        t("choose_section", lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=lang)
    )


@dp.callback_query(lambda c: c.data == "refresh_all")
async def refresh_all_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    ta_items, demo_items = await asyncio.gather(
        fetch_today_section("ta", force=True),
        fetch_today_section("demo", force=True),
    )
    user_cache[user_id] = {"ta": ta_items, "demo": demo_items}
    await callback.answer(t("updated", lang))
    await callback.message.edit_text(
        t("choose_section", lang),
        reply_markup=main_menu(len(ta_items), len(demo_items), lang=lang)
    )


@dp.callback_query(lambda c: c.data.startswith("ta_") or c.data.startswith("demo_") or c.data.startswith("refresh_ta_") or c.data.startswith("refresh_demo_"))
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
    items = await fetch_today_section(section, force=is_refresh)
    if user_id not in user_cache:
        user_cache[user_id] = {}
    user_cache[user_id][section] = items

    if is_refresh:
        await callback.answer(t("updated", lang))
    else:
        await callback.answer()

    title_name = t("demo_day", lang) if section == "demo" else t("ta_booking", lang)
    if not items:
        await callback.message.edit_text(
            t("empty_section", lang, title=title_name),
            reply_markup=main_menu(lang=lang)
        )
        return

    today_date = datetime.now().strftime("%d.%m.%Y")
    text = f"{title_name} ({today_date})\n\n{t('total', lang)}: {len(items)}"
    await callback.message.edit_text(
        text,
        reply_markup=bookings_list_keyboard(items, page, section, lang=lang)
    )


async def render_card(callback: CallbackQuery, section: str, index: int, page: int):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    user_data = user_cache.get(user_id, {})
    items = user_data.get(section)

    if items is None:
        items = await fetch_today_section(section)
        if user_id not in user_cache:
            user_cache[user_id] = {}
        user_cache[user_id][section] = items

    if index >= len(items):
        await callback.message.edit_text("⚠️ " + t("updated", lang), reply_markup=main_menu(lang=lang))
        return False

    b = items[index]
    mark = marks.get_mark(booking_key(b))
    await callback.message.edit_text(
        person_card_text(b, mark, lang=lang),
        reply_markup=person_card_keyboard(index, page, section, mark, b, lang=lang),
    )
    return True


@dp.callback_query(lambda c: c.data.startswith("person_"))
async def show_card_cb(callback: CallbackQuery):
    await callback.answer()
    _, section, index, page = callback.data.split("_")
    await render_card(callback, section, int(index), int(page))


@dp.callback_query(lambda c: c.data.startswith("mkind_"))
async def set_mark_kind_cb(callback: CallbackQuery):
    _, kind, section, index, page = callback.data.split("_")
    index, page = int(index), int(page)
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    user_data = user_cache.get(user_id, {})
    items = user_data.get(section, [])
    if not items or index >= len(items):
        await callback.answer("...", show_alert=True)
        return
    b = items[index]
    marks.set_kind(booking_key(b), b, kind)
    await callback.answer(t("demo_btn", lang) if kind == "demo" else t("extra_btn", lang))
    await render_card(callback, section, index, page)


@dp.callback_query(lambda c: c.data.startswith("mres_"))
async def set_mark_result_cb(callback: CallbackQuery):
    _, result, section, index, page = callback.data.split("_")
    index, page = int(index), int(page)
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    user_data = user_cache.get(user_id, {})
    items = user_data.get(section, [])
    if not items or index >= len(items):
        await callback.answer("...", show_alert=True)
        return
    b = items[index]
    marks.set_demo_result(booking_key(b), b, result)
    await callback.answer(t("pass_btn", lang) if result == "pass" else t("fail_btn", lang))
    await render_card(callback, section, index, page)


@dp.callback_query(lambda c: c.data.startswith("mclr_"))
async def clear_mark_cb(callback: CallbackQuery):
    _, section, index, page = callback.data.split("_")
    index, page = int(index), int(page)
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    user_data = user_cache.get(user_id, {})
    items = user_data.get(section, [])
    if not items or index >= len(items):
        await callback.answer("...", show_alert=True)
        return
    b = items[index]
    marks.clear_mark(booking_key(b))
    await callback.answer(t("clear_mark_btn", lang))
    await render_card(callback, section, index, page)


@dp.callback_query(lambda c: c.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("nm_"))
async def notify_mark_handler(callback: CallbackQuery):
    parts = callback.data.split("_")
    action = parts[1]
    rowid = int(parts[2])
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)

    row = marks.get_by_rowid(rowid)
    if not row:
        await callback.answer("...", show_alert=True)
        return

    if action == "clr":
        marks.clear_by_id(rowid)
        await callback.answer(t("clear_mark_btn", lang))
        await _safe_delete(callback.message)
    elif action == "extra":
        marks.set_kind_by_id(rowid, "extra")
        await callback.answer("➕ " + t("extra_btn", lang))
        await _safe_delete(callback.message)
    elif action == "demo":
        marks.set_kind_by_id(rowid, "demo")
        await callback.answer("🎯 Demo")
        student = row.get("student") or ""
        await callback.message.edit_text(
            f"🎯 Demo — {student}\nNatija? / Результат?",
            reply_markup=demo_result_keyboard(rowid, lang=lang),
        )
    elif action in ("pass", "fail"):
        marks.set_result_by_id(rowid, action)
        await callback.answer("✅ " + t("pass_btn", lang) if action == "pass" else "❌ " + t("fail_btn", lang))
        await _safe_delete(callback.message)
    else:
        await callback.answer()


def format_crm_report(data: dict, lang: str = "uz") -> str:
    if not data:
        return f"⚠️ {t('empty_section', lang, title='Analitika')}"

    try:
        d_from_dt = datetime.strptime(data["date_from"], "%Y-%m-%d")
        d_to_dt = datetime.strptime(data["date_to"], "%Y-%m-%d")
        if data["date_from"] != data["date_to"]:
            period_str = f"{d_from_dt.strftime('%d.%m.%Y')} — {d_to_dt.strftime('%d.%m.%Y')}"
        else:
            period_str = d_from_dt.strftime('%d.%m.%Y')
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


@dp.callback_query(lambda c: c.data == "report_menu")
async def report_menu_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await callback.answer()
    await callback.message.edit_text(
        t("report_intro", lang),
        reply_markup=report_menu(lang=lang),
        parse_mode="HTML"
    )


@dp.callback_query(lambda c: c.data == "rep_today")
async def report_today_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await callback.answer("⏳...")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    from crm import fetch_crm_analytics
    data = await fetch_crm_analytics(today_str, today_str)
    report_text = format_crm_report(data, lang=lang)
    
    await callback.message.edit_text(
        report_text,
        reply_markup=report_menu(lang=lang),
        parse_mode="HTML"
    )


@dp.callback_query(lambda c: c.data == "rep_week")
async def report_week_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await callback.answer("⏳...")

    now = datetime.now()
    mon = now - timedelta(days=now.weekday())
    today = now

    from crm import fetch_crm_analytics
    data = await fetch_crm_analytics(mon.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
    report_text = format_crm_report(data, lang=lang)

    await callback.message.edit_text(
        report_text,
        reply_markup=report_menu(lang=lang),
        parse_mode="HTML"
    )


@dp.callback_query(lambda c: c.data == "rep_30")
async def report_30_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = marks.get_user_lang(user_id)
    await callback.answer("⏳...")

    date_to = datetime.now()
    date_from = date_to - timedelta(days=29)

    from crm import fetch_crm_analytics
    data = await fetch_crm_analytics(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    report_text = format_crm_report(data, lang=lang)

    await callback.message.edit_text(
        report_text,
        reply_markup=report_menu(lang=lang),
        parse_mode="HTML"
    )


@dp.message(Command("report"))
async def report_command(message: Message):
    parts = message.text.split()
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)

    if len(parts) == 1:
        m = await message.answer(
            t("report_intro", lang),
            reply_markup=report_menu(lang=lang),
            parse_mode="HTML"
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
    from crm import fetch_crm_analytics
    data = await fetch_crm_analytics(date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))
    report_text = format_crm_report(data, lang=lang)

    await wait_m.edit_text(report_text, reply_markup=report_menu(lang=lang), parse_mode="HTML")
    remember_message(user_id, wait_m.message_id)


# --- Фоновая проверка изменений и автоматические напоминания за 5 минут ---
async def check_updates():
    global last_snapshot

    while True:
        try:
            ta_data, demo_data = await refresh_cache()
            all_bookings = ta_data + demo_data
            by_key = {booking_key(b): b for b in all_bookings}
            current_snapshot = {
                k: {"status": b.get("status"), "lesson": b.get("lesson")}
                for k, b in by_key.items()
            }

            now = datetime.now()

            # 1. Автоматические напоминания за 5 минут до урока
            for b in all_bookings:
                dt = _booking_dt(b)
                if dt == datetime.max:
                    continue
                diff = (dt - now).total_seconds() / 60.0
                bkey = booking_key(b)
                # Если урок начнется через 2-7 минут и напоминание еще не отправлялось
                if 2 <= diff <= 7 and bkey not in reminded_lessons:
                    reminded_lessons.add(bkey)
                    def make_remind_text(u_lang):
                        phone_clean = re.sub(r"\D", "", b.get("phone", ""))
                        _, time_part = split_when(b)
                        lesson_text = b.get("lesson") or t("not_specified", u_lang)
                        return t(
                            "reminder_5m",
                            u_lang,
                            min=int(diff),
                            student=b["student"],
                            phone=phone_clean,
                            group=b["group"],
                            lesson=lesson_text,
                            time=time_part,
                            status=b.get("status", "")
                        )
                    await send_notification(make_remind_text, bkey, b)

            # 2. Проверка изменений в CRM
            if last_snapshot is not None and all_bookings:
                for key, snap in current_snapshot.items():
                    b = by_key[key]
                    status = snap["status"]
                    lesson = snap["lesson"]
                    date_part, time_part = split_when(b)
                    is_demo = b.get("type") == "Demoday"

                    prev = last_snapshot.get(key)

                    if prev is None:
                        def make_new_text(u_lang):
                            tag = t("demo_day", u_lang) if is_demo else t("ta_booking", u_lang)
                            lesson_text = lesson if has_lesson(lesson) else t("not_specified", u_lang)
                            phone_clean = re.sub(r"\D", "", b.get("phone", ""))
                            phone_line = f"\n📞 +{phone_clean}" if phone_clean else ""
                            tg_line = f"\n💬 {b['tg']}" if b.get("tg") else ""
                            task_line = f"\n📝 {b['task']}" if b.get("task") else ""
                            return (
                                f"{t('notify_new', u_lang, tag=tag)}\n\n"
                                f"👤 {b['student']}{phone_line}{tg_line}\n"
                                f"👥 {b['group']}\n\n"
                                f"📚 {lesson_text}{task_line}\n"
                                f"📅 {date_part}\n"
                                f"🕒 {time_part}\n\n"
                                f"{status_icon(status)} {status}"
                            )
                        await send_notification(make_new_text, key, b)

                    elif not has_lesson(prev["lesson"]) and has_lesson(lesson):
                        def make_lesson_text(u_lang):
                            tag = t("demo_day", u_lang) if is_demo else t("ta_booking", u_lang)
                            return (
                                f"{t('notify_lesson', u_lang, tag=tag)}\n\n"
                                f"👤 {b['student']}\n"
                                f"👥 {b['group']}\n\n"
                                f"📚 {lesson}\n"
                                f"📅 {date_part}\n"
                                f"🕒 {time_part}\n\n"
                                f"{status_icon(status)} {status}"
                            )
                        await send_notification(make_lesson_text, key, b)

                    elif prev["status"] != status:
                        old_status = prev["status"]
                        def make_status_text(u_lang):
                            tag = t("demo_day", u_lang) if is_demo else t("ta_booking", u_lang)
                            return (
                                f"{t('notify_status', u_lang, tag=tag)}\n\n"
                                f"👤 {b['student']}\n"
                                f"👥 {b['group']}\n\n"
                                f"📅 {date_part}\n"
                                f"🕒 {time_part}\n\n"
                                f"{status_icon(old_status)} {old_status}\n"
                                f"⬇️\n"
                                f"{status_icon(status)} {status}"
                            )
                        await send_notification(make_status_text, key, b)

            last_snapshot = current_snapshot

        except Exception as e:
            print(f"Ошибка в фоновой проверке: {e}")

        # Проверяем каждые 2 минуты для точных 5-минутных напоминаний
        await asyncio.sleep(120)


async def daily_morning_sync():
    while True:
        try:
            now = datetime.now()
            target = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            from sync_cookie import run_sync
            await asyncio.to_thread(run_sync)
            await refresh_cache()
            reminded_lessons.clear()
        except Exception as e:
            print(f"Ошибка в daily_morning_sync: {e}")
            await asyncio.sleep(60)



@dp.message(Command("update"))
async def update_command(message: Message):
    import os, subprocess, asyncio
    user_id = message.from_user.id
    lang = marks.get_user_lang(user_id)
    wait_msg = await message.answer("🔄 Yangilanishlar yuklanmoqda... / Загрузка обновлений...")
    remember_message(user_id, wait_msg.message_id)

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 1. Fetch & Reset
        proc_fetch = await asyncio.create_subprocess_exec(
            "git", "fetch", "origin", "main",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=script_dir
        )
        await proc_fetch.communicate()

        proc_pull = await asyncio.create_subprocess_exec(
            "git", "reset", "--hard", "origin/main",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=script_dir
        )
        out_pull, _ = await proc_pull.communicate()
        pull_str = out_pull.decode("utf-8", errors="ignore").strip()

        # 2. Install requirements if any
        venv_pip = os.path.join(script_dir, ".venv", "bin", "pip")
        if os.path.exists(venv_pip):
            proc_pip = await asyncio.create_subprocess_exec(
                venv_pip, "install", "-r", "requirements.txt", "--quiet",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=script_dir
            )
            await proc_pip.communicate()

        success_msg = (
            "✅ <b>Bot muvaffaqiyatli yangilandi va qayta ishga tushdi!</b>\n\n" +
            f"<code>{pull_str}</code>"
            if lang == "uz" else
            "✅ <b>Бот успешно обновлён и перезапущен!</b>\n\n" +
            f"<code>{pull_str}</code>"
        )
        
        await wait_msg.edit_text(
            success_msg,
            parse_mode="HTML"
        )
        
        # 3. Graceful restart after message is sent
        await asyncio.sleep(1.5)
        os._exit(0)

    except Exception as e:
        await wait_msg.edit_text(f"⚠️ Yangilashda xatolik: {e}")

async def poll_loop(bot: Bot):
    """Фоновое обновление кэша и напоминания за 5 минут"""
    while True:
        try:
            await asyncio.sleep(45)
            await refresh_cache()
            
            # Check 5 min reminders
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
                if 4.0 <= diff <= 5.5:
                    b_key = booking_key(b)
                    if not marks.is_reminded_5m(b_key):
                        marks.set_reminded_5m(b_key)
                        admins = marks.get_all_admins()
                        chat_ids = set([a["chat_id"] for a in admins])
                        if ADMIN_CHAT_ID:
                            try:
                                chat_ids.add(int(ADMIN_CHAT_ID))
                            except ValueError:
                                pass
                        for cid in chat_ids:
                            u_lang = marks.get_user_lang(cid)
                            dt_str = dt.strftime("%H:%M")
                            b_type = t("demo_day", u_lang) if b.get("type") == "Demoday" else t("ta_booking", u_lang)
                            phone_s = b.get("phone", "")
                            rem_text = t(
                                "reminder_5m", u_lang,
                                min=5,
                                student=b.get("student", "—"),
                                phone=phone_s,
                                group=b.get("group", "—"),
                                lesson=b.get("lesson", "—"),
                                time=dt_str,
                                status=f"{b_type} — {status_icon(st)} {st}"
                            )
                            await bot.send_message(cid, rem_text, parse_mode="HTML")
        except Exception:
            await asyncio.sleep(30)


async def main():
    bot = Bot(token=BOT_TOKEN)
    marks.init_db()
    print("Preloading CRM data into memory cache...")
    try:
        await refresh_cache()
        print("CRM cache ready! Ultra-fast responses enabled.")
    except Exception as e:
        print("Cache preload note:", e)

    asyncio.create_task(poll_loop(bot))
    print("Bot polling started cleanly.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())