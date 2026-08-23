# 🤖 Junior IT — TA Booking & Demo Day Telegram Bot

To'liq avtomatlashtirilgan Telegram bot: CRM platformasidagi **TA Booking** va **Demo Day** bronlarini kuzatish, o'quvchilar telefon raqamini avtomatik aniqlash, natijalarni belgilash (Demo / Qo'shimcha dars), **⚡️ Hozirgi dars** va **⏰ Jadval** bilan 24/7 avtonom ishlash uchun.

🔗 **GitHub Repozitoriy:** [https://github.com/keeper27069/TABooking](https://github.com/keeper27069/TABooking)

---

## 🚀 Yangi mentorni 1 daqiqada ulash / Установка для нового ментора

### 1-qadam. Telegramda o'z botingizni yarating (30 soniya)
1. Telegramda **[@BotFather](https://t.me/BotFather)** ga kiring.
2. `/newbot` buyrug'ini yuboring va botingizga nom bering (masalan: `Mening TA Botim`).
3. Berilgan `BOT_TOKEN` ni nusxalab oling.

### 2-qadam. Terminalda 1 ta buyruq bilan o'rnating:
Terminalni oching va quyidagi buyruqni yuboring:
```bash
git clone https://github.com/keeper27069/TABooking.git ~/Desktop/TABooking
cd ~/Desktop/TABooking
bash setup_mac.sh
```

### 3-qadam. Botingizga kiring va `/start` bosing
- Ochilgan `.env` fayliga o'zingizning `BOT_TOKEN`ingizni qo'ying.
- Botingizga kirib **`/start`** bosing — bot sizning **Chat ID**ingizni va Chrome'dagi LMS hisobingizni avtomatik taniydi!

---

## 🔄 Avtomatik yangilanishlar / Автоматические обновления

Endi zip fayl yuborish shart emas! Barcha yangilanishlar to'g'ridan-to'g'ri bulutdan keladi:
- **Telegram orqali yangilash:** Bot ichida **/update** buyrug'ini yuboring.
- **Terminal orqali yangilash:**
  ```bash
  cd ~/Desktop/TABooking && bash update.sh
  ```
- **Har kuni ertalab 08:00 da:** Bot o'zi avtomatik tarzda eng so'nggi yangilanishlarni tekshiradi va cookie ni yangilaydi!

---

## ✨ Asosiy imkoniyatlar / Возможности

1. **⚡️ Hozirgi dars (Текущий урок):** Ayni hozir kimning darsi borligini bir bosishda ko'rsatadi, to'g'ridan-to'g'ri Telegramga o'tish tugmasi bilan.
2. **⏰ Darslar jadvali (Timeline):** Kunlik barcha 23 ta darsni xronologik tartibda (`🔴 HOZIR`, `🟡 KEYINGI`, `✅ KELDI`) ko'rsatadi.
3. **🔔 5 daqiqalik eslatmalar:** Har bir dars boshlanishidan 5 daqiqa oldin avtomatik eslatma yuboradi.
4. **📞 O'quvchining raqami va Telegrami:** CRM profildan toza 998... formatda olinadi va silliq ko'rsatiladi.
5. **🌐 Ikki tilli interfeys:** 🇺🇿 O'zbekcha va 🇷🇺 Русский tillari.
