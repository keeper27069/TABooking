# 🤖 Junior IT — TA Booking & Demo Day Telegram Bot

To'liq avtomatlashtirilgan Telegram bot: CRM platformasidagi **TA Booking** va **Demo Day** bronlarini kuzatish, o'quvchilar telefon raqamini avtomatik aniqlash, natijalarni belgilash (Demo / Qo'shimcha dars) va 24/7 avtonom ishlash uchun.

---

## 🇷🇺 Что передавать коллеге / получателю?

Вам **НЕ нужно** передавать ИИ-ассистента или что-то настраивать вручную.
Достаточно передать **только папку `TABooking`** (в виде `.zip` архива или через флешку/Telegram).

### 📁 Список файлов внутри папки:
- `bot.py` — Главный сервис бота и обработчики команд.
- `crm.py` — Парсер CRM (TA Booking + Demo Day + извлечение номеров + самовосстановление).
- `sync_cookie.py` — Автосинхронизатор сессии из Chrome в 08:00 утра.
- `keyboards.py` — Кнопки, карточки, ссылки на Telegram учеников.
- `i18n.py` — Многоязычность (🇺🇿 O'zbekcha / 🇷🇺 Русский).
- `marks.py` — База данных отметок (демо/доп уроки/язык).
- `storage.py` — Хранилище сообщений для быстрой очистки (`/clear`).
- `utils.py` — Иконки статусов.
- `config.py` — Загрузчик настроек.
- `requirements.txt` — Список библиотек Python.
- `.env.example` — Шаблон настроек (токен и chat ID).
- `setup_mac.sh` — Скрипт автоматической установки в 1 клик.

---

## 🚀 Инструкция по запуску (для нового пользователя)

### Шаг 1. Настройка `.env`
1. В папке скопируйте `.env.example` и переименуйте в `.env` (или скрипт сделает это сам).
2. Откройте `.env` в любом текстовом редакторе и укажите:
   ```env
   # Токен вашего бота от @BotFather в Telegram:
   BOT_TOKEN=8812420582:AAG...

   # Ваш Telegram Chat ID (можно узнать через бота @userinfobot):
   ADMIN_CHAT_ID=8066973747

   # Ссылки на CRM:
   CRM_URL=https://crm.junior-it.uz/account/ta_booking_requests/list?length=50
   DEMODAY_URL=https://crm.junior-it.uz/account/demo_day/list

   # Начальный Cookie (после этого бот обновляет его сам):
   COOKIE=PHPSESSID=...
   ```

### Шаг 2. Запуск в 1 клик на Mac
Откройте **Терминал**, перейдите в папку и запустите скрипт:
```bash
cd ~/Desktop/TABooking
bash setup_mac.sh
```

✨ **Скрипт автоматически:**
1. Создаст виртуальное окружение Python (`.venv`).
2. Установит все необходимые библиотеки (`aiogram`, `requests`, `beautifulsoup4`, `websockets`).
3. Зарегистрирует системные службы macOS `launchd`:
   - Бот будет работать **24/7 в фоне**, даже если закрыть терминал или перезагрузить Mac.
   - Каждое утро в **08:00** cookie будет автоматически обновляться из Google Chrome.

---

## 🇺🇿 O'rnatish qo'llanmasi (O'zbek tilida)

### 1-qadam. Sozlamalar (`.env`)
`.env` faylini oching va quyidagi ma'lumotlarni kiriting:
1. `BOT_TOKEN` — [@BotFather](https://t.me/BotFather) dan olingan bot tokeni.
2. `ADMIN_CHAT_ID` — [@userinfobot](https://t.me/userinfobot) orqali olingan sizning Telegram ID raqamingiz.

### 2-qadam. Ishga tushirish
Terminalni oching va buyruqni yuboring:
```bash
cd ~/Desktop/TABooking
bash setup_mac.sh
```

---

## 🛠 Полезные команды управления (macOS)

- **Перезапустить бота вручную:**
  ```bash
  killall -9 Python
  ```
  *(macOS `launchd` автоматически перезапустит бота за 1 секунду)*

- **Остановить фоновую службу:**
  ```bash
  launchctl unload ~/Library/LaunchAgents/com.zafar.tabooking.plist
  launchctl unload ~/Library/LaunchAgents/com.zafar.tabooking.cookiesync.plist
  ```

- **Запустить фоновую службу:**
  ```bash
  launchctl load -w ~/Library/LaunchAgents/com.zafar.tabooking.plist
  launchctl load -w ~/Library/LaunchAgents/com.zafar.tabooking.cookiesync.plist
  ```

- **Посмотреть логи бота:**
  ```bash
  tail -f ~/Desktop/TABooking/bot_error.log
  tail -f ~/Desktop/TABooking/cookie_sync.log
  ```
