#!/bin/bash
set -e

echo "=================================================="
echo "🚀 TABooking Bot - Avtomatik o'rnatish / Автоустановка"
echo "=================================================="

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# 1. Python tekshiruvi
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 topilmadi! Iltimos, https://www.python.org saytidan Python 3 o'rnating."
    exit 1
fi

# 2. Virtual environment (.venv)
if [ ! -d ".venv" ]; then
    echo "📦 Virtual muhit yaratilmoqda (.venv)..."
    python3 -m venv .venv
fi

echo "📦 Kerakli kutubxonalar o'rnatilmoqda..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# 3. .env fayli tekshiruvi
if [ ! -f ".env" ]; then
    echo "⚙️ .env fayli yaratilmoqda..."
    cp .env.example .env
fi

# 4. Telegram Bot Token & Admin Chat ID tekshiruvi
CURRENT_TOKEN=$(grep -E "^BOT_TOKEN=" .env | cut -d '=' -f2- | tr -d ' "')
if [ -z "$CURRENT_TOKEN" ] || [ "$CURRENT_TOKEN" = "YOUR_TELEGRAM_BOT_TOKEN_HERE" ]; then
    echo ""
    echo "🔑 1. Telegram Bot Tokeningizni kiriting (@BotFather dan olingan):"
    read -r USER_BOT_TOKEN
    if [ -n "$USER_BOT_TOKEN" ]; then
        sed -i '' "s|^BOT_TOKEN=.*|BOT_TOKEN=$USER_BOT_TOKEN|" .env
    fi

    echo "🆔 2. O'zingizning Telegram Chat ID ingizni kiriting (@userinfobot dan):"
    read -r USER_CHAT_ID
    if [ -n "$USER_CHAT_ID" ]; then
        sed -i '' "s|^ADMIN_CHAT_ID=.*|ADMIN_CHAT_ID=$USER_CHAT_ID|" .env
    fi
fi

# 5. Chrome brauzerdan Cookie ni avtomatik olish
echo "🔄 Google Chrome brauzeridan LMS (CRM) sessiyangiz olinmoqda..."
.venv/bin/python sync_cookie.py || true

# 6. launchd servislarini sozlash (24/7 avtostart va 08:00 cookie yangilash)
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

cat << PLIST > "$LAUNCH_DIR/com.tabooking.bot.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tabooking.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$DIR/.venv/bin/python</string>
        <string>$DIR/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>$DIR/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/bot_error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>PATH</key>
        <string>$DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
PLIST

cat << PLIST > "$LAUNCH_DIR/com.tabooking.cookiesync.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tabooking.cookiesync</string>
    <key>ProgramArguments</key>
    <array>
        <string>$DIR/.venv/bin/python</string>
        <string>$DIR/sync_cookie.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$DIR/cookie_sync.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/cookie_sync_error.log</string>
</dict>
</plist>
PLIST

# Servislarni ishga tushirish
launchctl unload "$LAUNCH_DIR/com.tabooking.bot.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_DIR/com.tabooking.cookiesync.plist" 2>/dev/null || true
launchctl load -w "$LAUNCH_DIR/com.tabooking.bot.plist"
launchctl load -w "$LAUNCH_DIR/com.tabooking.cookiesync.plist"

echo "=================================================="
echo "✅ Barcha sozlamalar muvaffaqiyatli yakunlandi!"
echo "🤖 Bot 24/7 fonda ishlamoqda."
echo "📱 Endi Telegramda botingizga kiring va /start bosing."
echo "=================================================="
