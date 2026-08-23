from __future__ import annotations
import re
from datetime import datetime
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from utils import status_icon
from i18n import t

PAGE_SIZE = 6


def main_menu(ta_count: int | None = None, demo_count: int | None = None, lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    ta_text = f"{t('ta_booking', lang)} ({ta_count})" if ta_count is not None else t("ta_booking", lang)
    demo_text = f"{t('demo_day', lang)} ({demo_count})" if demo_count is not None else t("demo_day", lang)

    # 1-qator: Tezkor Hozirgi dars va Jadval
    builder.button(text=t("current_lesson_btn", lang), callback_data="show_current_lesson")
    builder.button(text=t("timeline_btn", lang), callback_data="timeline_1")
    # 2-qator: Bo'limlar
    builder.button(text=ta_text, callback_data="ta_1")
    builder.button(text=demo_text, callback_data="demo_1")
    # 3-qator: Amallar
    builder.button(text=t("refresh", lang), callback_data="refresh_all")
    builder.button(text=t("report", lang), callback_data="report_menu")
    builder.button(text=t("lang_btn", lang), callback_data="choose_lang")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇺🇿 O'zbekcha", callback_data="setlang_uz")
    builder.button(text="🇷🇺 Русский", callback_data="setlang_ru")
    builder.button(text="⬅️ Orqaga / Назад", callback_data="to_menu")
    builder.adjust(2, 1)
    return builder.as_markup()


def report_menu(lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("report_today_btn", lang), callback_data="rep_today")
    builder.button(text=t("report_week_btn", lang), callback_data="rep_week")
    builder.button(text=t("report_30_btn", lang), callback_data="rep_30")
    builder.button(text=t("back_to_menu", lang), callback_data="to_menu")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def _parse_time(b: dict) -> datetime:
    raw = b.get("booking", "")
    try:
        if "," in raw:
            return datetime.strptime(raw.strip(), "%d.%m.%Y, %H:%M")
        elif " - " in raw:
            return datetime.strptime(raw.strip(), "%d.%m.%Y - %H:%M")
    except Exception:
        pass
    return datetime.max


def timeline_keyboard(timeline_items: list, page: int = 1, lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    now = datetime.now()

    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = timeline_items[start:end]

    for i, booking in enumerate(page_items):
        global_index = start + i
        dt = _parse_time(booking)
        time_str = dt.strftime("%H:%M") if dt != datetime.max else booking.get("booking", "")
        btype = "🎯 Demo" if booking.get("type") == "Demoday" else "📅 TA"
        student_name = booking.get("student", "")
        status = booking.get("status", "")
        s_icon = status_icon(status)

        diff_min = (dt - now).total_seconds() / 60.0 if dt != datetime.max else 9999

        # Agar dars o'tilmagan bo'lsa va ayni hozir vaqti bo'lsa
        extra_badge = ""
        if status not in ("KELDI", "KELMADI", "BEKOR QILINGAN", "RAD ETILGAN"):
            if -25 <= diff_min <= 10:
                extra_badge = " 🔴"
            elif 0 < diff_min <= 45:
                extra_badge = " ⏳"

        builder.button(
            text=f"{s_icon} {time_str} | {btype} | {student_name}{extra_badge}",
            callback_data=f"tlperson_{global_index}_{page}"
        )
    builder.adjust(1)

    total_pages = max(1, -(-len(timeline_items) // PAGE_SIZE))

    nav_builder = InlineKeyboardBuilder()
    if page > 1:
        nav_builder.button(text="⬅️", callback_data=f"timeline_{page - 1}")
    nav_builder.button(text=f"{page}/{total_pages}", callback_data="noop")
    if page < total_pages:
        nav_builder.button(text="➡️", callback_data=f"timeline_{page + 1}")
    nav_builder.adjust(3)
    builder.attach(nav_builder)

    bottom_builder = InlineKeyboardBuilder()
    bottom_builder.button(text=t("current_lesson_btn", lang), callback_data="show_current_lesson")
    bottom_builder.button(text=t("back_to_menu", lang), callback_data="to_menu")
    bottom_builder.adjust(2)
    builder.attach(bottom_builder)

    return builder.as_markup()


def bookings_list_keyboard(bookings: list, page: int, section: str, lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = bookings[start:end]

    for i, booking in enumerate(page_items):
        global_index = start + i
        raw_b = booking.get("booking", "")
        time_str = raw_b.split(",")[1].strip() if "," in raw_b else raw_b
        icon = status_icon(booking.get("status", ""))
        student_name = booking.get("student", "")
        builder.button(
            text=f"{icon} {global_index + 1}. {student_name} — {time_str}",
            callback_data=f"person_{section}_{global_index}_{page}"
        )
    builder.adjust(1)

    total_pages = max(1, -(-len(bookings) // PAGE_SIZE))

    nav_builder = InlineKeyboardBuilder()
    if page > 1:
        nav_builder.button(text="⬅️", callback_data=f"{section}_{page - 1}")
    nav_builder.button(text=f"{page}/{total_pages}", callback_data="noop")
    if page < total_pages:
        nav_builder.button(text="➡️", callback_data=f"{section}_{page + 1}")
    nav_builder.adjust(3)
    builder.attach(nav_builder)

    bottom_builder = InlineKeyboardBuilder()
    bottom_builder.button(text=t("refresh", lang), callback_data=f"refresh_{section}_{page}")
    bottom_builder.button(text=t("back_to_menu", lang), callback_data="to_menu")
    bottom_builder.adjust(2)
    builder.attach(bottom_builder)

    return builder.as_markup()


def person_card_keyboard(index: int, page: int, section: str, mark: dict | None = None, b: dict | None = None, lang: str = "uz", from_timeline: bool = False) -> InlineKeyboardMarkup:
    kind = (mark or {}).get("kind")
    result = (mark or {}).get("demo_result")

    prefix = "tl" if from_timeline else ""
    builder = InlineKeyboardBuilder()
    demo_lbl = ("✅ " if kind == "demo" else "") + t("demo_btn", lang)
    extra_lbl = ("✅ " if kind == "extra" else "") + t("extra_btn", lang)

    builder.button(text=demo_lbl, callback_data=f"{prefix}mkind_demo_{section}_{index}_{page}")
    builder.button(text=extra_lbl, callback_data=f"{prefix}mkind_extra_{section}_{index}_{page}")
    builder.adjust(2)

    if kind == "demo":
        res = InlineKeyboardBuilder()
        pass_lbl = ("✅ " if result == "pass" else "") + t("pass_btn", lang)
        fail_lbl = ("❌ " if result == "fail" else "") + t("fail_btn", lang)
        res.button(text=pass_lbl, callback_data=f"{prefix}mres_pass_{section}_{index}_{page}")
        res.button(text=fail_lbl, callback_data=f"{prefix}mres_fail_{section}_{index}_{page}")
        res.adjust(2)
        builder.attach(res)

    if mark and mark.get("kind"):
        clr = InlineKeyboardBuilder()
        clr.button(text=t("clear_mark_btn", lang), callback_data=f"{prefix}mclr_{section}_{index}_{page}")
        builder.attach(clr)

    # Telegram & links
    if b:
        action_links = InlineKeyboardBuilder()
        phone_digits = re.sub(r"\D", "", b.get("phone", ""))
        tg = b.get("tg", "")

        if tg and tg.startswith("@"):
            action_links.button(text=t("write_tg_btn", lang, info=tg), url=f"https://t.me/{tg.lstrip('@')}")
        elif phone_digits:
            action_links.button(text=t("write_tg_btn", lang, info=f"+{phone_digits}"), url=f"https://t.me/+{phone_digits}")

        if b.get("task_link"):
            action_links.button(text=t("task_file_btn", lang), url=b["task_link"])
        if b.get("record_link"):
            action_links.button(text=t("loom_rec_btn", lang), url=b["record_link"])

        action_links.adjust(1)
        builder.attach(action_links)

    back = InlineKeyboardBuilder()
    if from_timeline:
        back.button(text=t("back_to_timeline", lang), callback_data=f"timeline_{page}")
    else:
        back.button(text=t("back_to_list", lang), callback_data=f"{section}_{page}")
    builder.attach(back)

    return builder.as_markup()


def demo_result_keyboard(rowid: int, lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ " + t("pass_btn", lang), callback_data=f"nm_pass_{rowid}")
    builder.button(text="❌ " + t("fail_btn", lang), callback_data=f"nm_fail_{rowid}")
    builder.adjust(2)
    return builder.as_markup()


def notify_keyboard(rowid: int, mark: dict | None = None, task_link: str = "", record_link: str = "", phone: str = "", tg: str = "", lang: str = "uz") -> InlineKeyboardMarkup:
    kind = (mark or {}).get("kind")
    result = (mark or {}).get("demo_result")

    builder = InlineKeyboardBuilder()
    builder.button(text=("✅ " if kind == "demo" else "") + t("demo_btn", lang), callback_data=f"nm_demo_{rowid}")
    builder.button(text=("✅ " if kind == "extra" else "") + t("extra_btn", lang), callback_data=f"nm_extra_{rowid}")
    builder.adjust(2)

    if kind == "demo":
        res = InlineKeyboardBuilder()
        res.button(text=("✅ " if result == "pass" else "") + t("pass_btn", lang), callback_data=f"nm_pass_{rowid}")
        res.button(text=("❌ " if result == "fail" else "") + t("fail_btn", lang), callback_data=f"nm_fail_{rowid}")
        res.adjust(2)
        builder.attach(res)

    if kind:
        clr = InlineKeyboardBuilder()
        clr.button(text=t("clear_mark_btn", lang), callback_data=f"nm_clr_{rowid}")
        builder.attach(clr)

    action_links = InlineKeyboardBuilder()
    phone_digits = re.sub(r"\D", "", phone or "")
    if tg and tg.startswith("@"):
        action_links.button(text=t("write_tg_btn", lang, info=tg), url=f"https://t.me/{tg.lstrip('@')}")
    elif phone_digits:
        action_links.button(text=t("write_tg_btn", lang, info=f"+{phone_digits}"), url=f"https://t.me/+{phone_digits}")

    if task_link:
        action_links.button(text=t("task_file_btn", lang), url=task_link)
    if record_link:
        action_links.button(text=t("loom_rec_btn", lang), url=record_link)

    action_links.adjust(1)
    builder.attach(action_links)

    return builder.as_markup()


def persistent_menu(lang: str = "uz") -> ReplyKeyboardMarkup:
    now_btn = "⚡️ Hozirgi dars" if lang == "uz" else "⚡️ Текущий урок"
    tl_btn = "⏰ Jadval" if lang == "uz" else "⏰ Расписание"
    menu_btn = "📋 Menyu" if lang == "uz" else "📋 Меню"
    clear_btn = "🧹 Tozalash" if lang == "uz" else "🧹 Очистить"

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=now_btn), KeyboardButton(text=tl_btn)],
            [KeyboardButton(text=menu_btn), KeyboardButton(text=clear_btn)],
        ],
        resize_keyboard=True
    )
