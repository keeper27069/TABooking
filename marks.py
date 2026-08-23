"""Хранилище пометок к броням: демо / доп урок + результат демо + настройки пользователя (язык).

Одна бронь = одна запись (ключ booking_key = student|group|booking).
Всё лежит в SQLite-файле marks.db рядом с ботом.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "marks.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    with _conn() as c:
        c.executescript(
            """
            
            CREATE TABLE IF NOT EXISTS admins (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                lang    TEXT DEFAULT 'uz',
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                lang    TEXT DEFAULT 'uz',
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS marks (
                booking_key TEXT PRIMARY KEY,
                student     TEXT,
                grp         TEXT,
                date_iso    TEXT,   -- YYYY-MM-DD, для фильтра по диапазону
                date_raw    TEXT,   -- как в CRM: "16.07.2026, 18:40"
                kind        TEXT,   -- 'demo' | 'extra' | NULL
                demo_result TEXT,   -- 'pass' | 'fail' | NULL
                updated_at  TEXT
            );
            """
        )


def get_user_lang(user_id: int) -> str:
    with _conn() as c:
        row = c.execute("SELECT lang FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        if row and row["lang"]:
            return row["lang"]
        return "uz"


def set_user_lang(user_id: int, lang: str):
    with _conn() as c:
        c.execute(
            """
            INSERT INTO user_settings (user_id, lang, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang, updated_at=excluded.updated_at
            """,
            (user_id, lang, _now()),
        )


def _date_iso(date_raw: str) -> str:
    # "16.07.2026, 18:40" -> "2026-07-16"
    day = (date_raw or "").split(",")[0].strip()
    try:
        return datetime.strptime(day, "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def get_mark(booking_key: str):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM marks WHERE booking_key = ?", (booking_key,)
        ).fetchone()
        return dict(row) if row else None


def _upsert(booking_key: str, booking: dict, **fields):
    existing = get_mark(booking_key) or {}
    data = {
        "student": booking.get("student") or existing.get("student"),
        "grp": booking.get("group") or existing.get("grp"),
        "date_iso": _date_iso(booking.get("booking", "")) or existing.get("date_iso", ""),
        "date_raw": booking.get("booking") or existing.get("date_raw", ""),
        "kind": existing.get("kind"),
        "demo_result": existing.get("demo_result"),
    }
    data.update(fields)
    data["updated_at"] = _now()

    with _conn() as c:
        c.execute(
            """
            INSERT INTO marks (booking_key, student, grp, date_iso, date_raw, kind, demo_result, updated_at)
            VALUES (:booking_key, :student, :grp, :date_iso, :date_raw, :kind, :demo_result, :updated_at)
            ON CONFLICT(booking_key) DO UPDATE SET
                student=excluded.student, grp=excluded.grp,
                date_iso=excluded.date_iso, date_raw=excluded.date_raw,
                kind=excluded.kind, demo_result=excluded.demo_result,
                updated_at=excluded.updated_at
            """,
            {"booking_key": booking_key, **data},
        )


def set_kind(booking_key: str, booking: dict, kind: str):
    demo_result = None
    if kind == "demo":
        ex = get_mark(booking_key)
        demo_result = ex.get("demo_result") if ex else None
    _upsert(booking_key, booking, kind=kind, demo_result=demo_result)


def set_demo_result(booking_key: str, booking: dict, result: str):
    _upsert(booking_key, booking, kind="demo", demo_result=result)


def clear_mark(booking_key: str):
    with _conn() as c:
        c.execute("DELETE FROM marks WHERE booking_key = ?", (booking_key,))


def ensure_row(booking_key: str, booking: dict) -> int:
    _upsert(booking_key, booking)
    with _conn() as c:
        row = c.execute("SELECT rowid FROM marks WHERE booking_key = ?", (booking_key,)).fetchone()
        return row["rowid"]


def get_by_rowid(rowid: int):
    with _conn() as c:
        row = c.execute("SELECT rowid, * FROM marks WHERE rowid = ?", (rowid,)).fetchone()
        return dict(row) if row else None


def set_kind_by_id(rowid: int, kind: str):
    demo_result = None
    if kind == "demo":
        row = get_by_rowid(rowid)
        demo_result = row.get("demo_result") if row else None
    with _conn() as c:
        c.execute(
            "UPDATE marks SET kind=?, demo_result=?, updated_at=? WHERE rowid=?",
            (kind, demo_result, _now(), rowid),
        )


def set_result_by_id(rowid: int, result: str):
    with _conn() as c:
        c.execute(
            "UPDATE marks SET kind='demo', demo_result=?, updated_at=? WHERE rowid=?",
            (result, _now(), rowid),
        )


def clear_by_id(rowid: int):
    with _conn() as c:
        c.execute(
            "UPDATE marks SET kind=NULL, demo_result=NULL, updated_at=? WHERE rowid=?",
            (_now(), rowid),
        )


def report(date_from_iso: str, date_to_iso: str) -> dict:
    with _conn() as c:
        rows = c.execute(
            "SELECT kind, demo_result FROM marks WHERE date_iso >= ? AND date_iso <= ?",
            (date_from_iso, date_to_iso),
        ).fetchall()

    demos = sum(1 for r in rows if r["kind"] == "demo")
    demos_pass = sum(1 for r in rows if r["kind"] == "demo" and r["demo_result"] == "pass")
    demos_fail = sum(1 for r in rows if r["kind"] == "demo" and r["demo_result"] == "fail")
    extras = sum(1 for r in rows if r["kind"] == "extra")

    return {
        "demos": demos,
        "demos_pass": demos_pass,
        "demos_fail": demos_fail,
        "demos_unknown": demos - demos_pass - demos_fail,
        "extras": extras,
    }


def register_user(chat_id: int, username: str = "", first_name: str = "", lang: str = "uz"):
    with _conn() as c:
        c.execute(
            """
            INSERT INTO admins (chat_id, username, first_name, lang, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                lang=excluded.lang
            """,
            (chat_id, username or "", first_name or "", lang, _now()),
        )
        c.execute(
            """
            INSERT INTO user_settings (user_id, lang, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang, updated_at=excluded.updated_at
            """,
            (chat_id, lang, _now()),
        )


def get_all_admins() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM admins").fetchall()
        return [dict(r) for r in rows]
