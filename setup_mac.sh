#!/bin/bash
set -e

echo "=================================================="
echo "🚀 TABooking Bot - Avtomatik o'rnatish / Автоустановка"
echo "=================================================="

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# 1. Python tekshiruvi
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 topilmadi! Iltimos, Python 3 o'rnating."
    exit 1
fi

# 2. Virtual environment (.venv)
if [ ! -d ".venv" ]; then
    echo "📦 Virtual muhit yaratilmoqda (.venv)..."
    python3 -m venv .venv
fi

echo "📦 Kutubxonalar o'rnatilmoqda..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# 3. .env fayli tekshiruvi
if [ ! -f ".env" ]; then
    echo "⚙️ .env fayli yaratilmoqda..."
    cp .env.example .env
fi

# 4. Foydalanuvchining o'z Chrome brauzeridan cookie ni tortib olish
echo "🔄 Chrome brauzeringizdan shaxsiy LMS sessiyasi (Cookie) olinmoqda..."
.venv/bin/python sync_cookie.py || true

# 5. launchd servislarini sozlash (24/7 avtostart va 08:00 cookie yangilash)
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

# Bot demoni
cat << PLIST > "$LAUNCH_DIR/com.zafar.tabooking.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zafar.tabooking</string>
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
    <true/>
    <key>StandardOutPath</key>
    <string>$DIR/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/bot_error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
PLIST

# 08:00 Cookie avtosinxronizatori
cat << PLIST > "$LAUNCH_DIR/com.zafar.tabooking.cookiesync.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zafar.tabooking.cookiesync</string>
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

# Servislarni yuklash
launchctl unload "$LAUNCH_DIR/com.zafar.tabooking.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_DIR/com.zafar.tabooking.cookiesync.plist" 2>/dev/null || true
launchctl load -w "$LAUNCH_DIR/com.zafar.tabooking.plist"
launchctl load -w "$LAUNCH_DIR/com.zafar.tabooking.cookiesync.plist"

echo "=================================================="
echo "✅ Barcha sozlamalar muvaffaqiyatli yakunlandi!"
echo "🤖 Bot 24/7 rejimda avtomatik ishga tushdi."
echo "📱 Endi Telegramda botingizga kiring va /start bosing."
echo "=================================================="
