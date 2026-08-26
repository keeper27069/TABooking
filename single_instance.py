# -*- coding: utf-8 -*-
"""
single_instance.py
Гарантирует запуск ровно одного экземпляра бота во избежание TelegramConflictError (409).
"""
import socket
import sys
import logging

logger = logging.getLogger("bot.instance")
_lock_socket = None

def ensure_single_instance(port: int = 49200) -> None:
    """Биндит локальный TCP сокет. Если порт занят — другой процесс бота уже работает."""
    global _lock_socket
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Исключаем сокеты в состоянии TIME_WAIT / переиспользование
    _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        _lock_socket.bind(("127.0.0.1", port))
        _lock_socket.listen(1)
        logger.info(f"Синглтон-лок успешно захвачен на 127.0.0.1:{port}")
    except socket.error:
        print(
            f"\n[CRITICAL] Другой экземпляр бота уже запущен на порту {port}!\n"
            "Завершение текущего процесса во избежание TelegramConflictError (409 Conflict).\n",
            file=sys.stderr
        )
        logger.critical(
            f"Другой экземпляр бота уже запущен на порту {port}! "
            "Завершение текущего процесса во избежание 409 Conflict Error."
        )
        sys.exit(0)
