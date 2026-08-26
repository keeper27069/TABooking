#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "🔄 Yangilanishlar yuklanmoqda / Загрузка обновлений..."

if [ -d ".git" ]; then
    git fetch origin main 2>/dev/null || true
    git reset --hard origin/main 2>/dev/null || git pull || true
fi

if [ -d ".venv" ]; then
    .venv/bin/pip install -r requirements.txt -q || true
fi

# To'xtatamiz va toza qayta ishga tushiramiz
pkill -9 -f "bot.py" || true
sleep 1

# LaunchAgent / Systemd qayta yuklash
LAUNCH_PLIST="$HOME/Library/LaunchAgents/com.tabooking.bot.plist"
LAUNCH_OLD="$HOME/Library/LaunchAgents/com.zafar.tabooking.plist"

if [ -f "$LAUNCH_PLIST" ]; then
    launchctl unload "$LAUNCH_PLIST" 2>/dev/null || true
    launchctl load -w "$LAUNCH_PLIST" 2>/dev/null || true
elif [ -f "$LAUNCH_OLD" ]; then
    launchctl unload "$LAUNCH_OLD" 2>/dev/null || true
    launchctl load -w "$LAUNCH_OLD" 2>/dev/null || true
elif command -v systemctl &> /dev/null && systemctl list-unit-files 2>/dev/null | grep -q "tabooking.service"; then
    sudo systemctl restart tabooking.service 2>/dev/null || true
fi

# Tekshirish: agar launchd ishga tushirmagan bo'lsa, to'g'ridan-to'g'ri fonda ishga tushirish
sleep 1
if ! ps aux | grep -i "bot.py" | grep -v grep > /dev/null; then
    nohup "$DIR/.venv/bin/python" "$DIR/bot.py" > "$DIR/bot.log" 2>&1 &
fi

echo "=================================================="
echo "✅ Bot muvaffaqiyatli yangilandi va ishga tushdi!"
echo "=================================================="
