#!/bin/bash
# ==============================================================================
# TABooking Bot — Linux VPS (Ubuntu/Debian) Systemd Auto-Deploy Script
# ==============================================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=================================================="
echo "🚀 TABooking Bot - O'rnatish / Установка на Linux"
echo "=================================================="

# 1. Обновление пакетов и установка Python + Chromium
if command -v apt-get &> /dev/null; then
    echo "📦 Tizim paketlarini yangilash va Chromium o'rnatish..."
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-venv python3-pip chromium-browser curl git
fi

# 2. Виртуальное окружение
if [ ! -d ".venv" ]; then
    echo "📦 Virtual muhit (.venv) yaratilmoqda..."
    python3 -m venv .venv
fi

echo "📦 Python kutubxonalarini o'rnatish..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# 3. Файл .env
if [ ! -f ".env" ]; then
    echo "⚙️ .env fayli nusxalanmoqda..."
    cp .env.example .env
    echo "⚠️ Iltimos, .env fayliga BOT_TOKEN, ADMIN_CHAT_ID va COOKIE ni kiriting!"
fi

# 4. Создание Systemd Service
CURRENT_USER=$(whoami)
SERVICE_NAME="tabooking"

echo "⚙️ Systemd servis yaratilmoqda (/etc/systemd/system/${SERVICE_NAME}.service)..."

sudo bash -c "cat << EOF > /etc/systemd/system/${SERVICE_NAME}.service
[Unit]
Description=TABooking Telegram Production Bot
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${DIR}
ExecStart=${DIR}/.venv/bin/python ${DIR}/bot.py
Restart=always
RestartSec=5s
KillMode=mixed
TimeoutStopSec=15s
StandardOutput=append:${DIR}/bot.log
StandardError=append:${DIR}/bot_error.log
Environment=PYTHONUNBUFFERED=1
Environment=PATH=${DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF"

# 5. Активация и запуск сервиса
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}.service
sudo systemctl restart ${SERVICE_NAME}.service

echo "=================================================="
echo "✅ Bot muvaffaqiyatli ishga tushirildi (24/7 rejimida)!"
echo "📊 Holatini tekshirish: sudo systemctl status ${SERVICE_NAME}"
echo "📜 Loglarni ko'rish: tail -f bot.log"
echo "=================================================="
