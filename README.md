# XAUUSD Signal bot — @xauusd_signal_uz1_bot

Bot har 5 daqiqada XAUUSD ning yopilgan M15 shamlarini tekshiradi. Yangi signal yoki natija chiqsa, Telegram'ga yuboradi:

- **London Breakout (LB)**: Osiyo diapazonidan chiqish va 1H MACD
- **Oltin London Pro (OLP)**: London, kechki London va trend pullback
- **NexMW Gold v2.0**: W/M modeli va F1–F7 filtrlar
- **XAUUSD Signal Tizimi**: har ish kuni bir marta, Toshkent 11:00 dan keyin, faqat texnik holat (trend, darajalar, FVG). Fundamental tahlil va kirish zonasini Claude'dan "signal ber" deb so'raysiz.

Narxlar Dukascopy bid bo'yicha olinadi. Bot savdo ochmaydi.

## O'rnatish (GitHub Actions, bepul)

1. **Telegram:** @xauusd_signal_uz1_bot ga kirib `/start` yozing.
2. **GitHub:** github.com da akkaunt oching va **New repository** ni bosing. Nomi `xauusd-signal-bot`.
   - **Public**: Actions daqiqalari cheksiz va bepul, lekin kod hammaga ko'rinadi. Token esa sirligicha qoladi, chunki u Secrets'da saqlanadi.
   - **Private**: kod yashirin, lekin oyiga 2000 daqiqa bepul. Har 5 daqiqalik tekshiruv bu limitdan oshib ketadi, pastdagi eslatmaga qarang.
3. **Fayllarni yuklash:** repoda **Add file → Upload files** ni bosing. Arxivdagi hamma narsani, jumladan `.github` papkasini ham, sudrab tashlang va **Commit** qiling.
4. **Sirlar:** **Settings → Secrets and variables → Actions → New repository secret** orqali qo'shing:
   - `TG_TOKEN`: BotFather bergan token
   - `BALANCE`: hisobingiz balansi, masalan `1000` (ixtiyoriy, lot hisoblash uchun)
5. **Chat ID ni olish:** **Actions → XAUUSD signal → Run workflow** ni bosing, mode = `chatid`. Logda `{123456789: '...'}` ko'rinadi. Shu raqamni `TG_CHAT_ID` sirri sifatida qo'shing.
6. **Etalon tekshiruvi:** yana **Run workflow** ni bosing, mode = `etalon`. Log kod etalon signallarni topgan-topmaganini ko'rsatadi.
7. Shu bilan tayyor: jadval har 5 daqiqada o'zi ishlaydi. Birinchi ishga tushishda bot "ishga tushdi" xabarini yuboradi. Eski signallarni qayta yubormaydi.

## Eslatmalar

- GitHub jadvalni ba'zan 5–15 daqiqaga kechiktiradi. Signal kech kelsa, xabarda "⏱ Kechikish" yoziladi. NexMW uchun bu muhim: 5 daqiqa kech kirish PF ni 2.05 dan 1.82 ga tushiradi.
- 90 daqiqadan eski signal yuborilmaydi.
- Kod strategiyalarning yozma qoidalari asosida yozilgan, PDF dagi asl kod asosida emas. Real puldan oldin `etalon` natijasini tekshiring va 1–2 oy demo hisobda sinang.
- FOMC sanalari `strategies.py` dagi `FOMC` ro'yxatida turadi. 2027 sanalarini qo'shishni unutmang.
- Private repo uchun `.github/workflows/signal.yml` dagi `*/5` ni `*/15` ga o'zgartirsangiz, sarf oyiga taxminan 2200 daqiqa bo'ladi, bu ham limitdan biroz ko'p.

Bu moliyaviy maslahat emas.
