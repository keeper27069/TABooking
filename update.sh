#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "🔄 Yangilanishlar tekshirilmoqda / Проверка обновлений..."

if [ -d ".git" ]; then
    git pull origin main || git pull || true
fi

if [ -d ".venv" ]; then
    .venv/bin/pip install -r requirements.txt -q || true
fi

# launchd avtomatik qayta ishga tushirishi uchun processni to'xtatamiz
killall -9 Python 2>/dev/null || true

echo "=================================================="
echo "✅ Bot muvaffaqiyatli yangilandi va qayta ishga tushdi!"
echo "=================================================="
