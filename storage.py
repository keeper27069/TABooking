# -*- coding: utf-8 -*-
"""
storage.py — Отказоустойчивое сохранение ID отправленных сообщений с атомарной записью.
"""
import json
import os
import tempfile
import logging

logger = logging.getLogger("bot.storage")
STORAGE_FILE = "sent_messages.json"


def load_messages() -> dict[str, list[int]]:
    if not os.path.exists(STORAGE_FILE):
        return {}
    try:
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"Ошибка чтения {STORAGE_FILE} (файл поврежден?): {e}. Создан пустой кэш.")
        return {}


def save_messages(data: dict[str, list[int]]):
    """Атомарная запись через временный файл для защиты от повреждения при сбоях."""
    try:
        dir_name = os.path.dirname(os.path.abspath(STORAGE_FILE))
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=False)
            temp_name = tf.name
        os.replace(temp_name, STORAGE_FILE)
    except Exception as e:
        logger.error(f"Ошибка атомарной записи сообщений в {STORAGE_FILE}: {e}")