"""XAUUSD Signal bot (@xauusd_signal_uz1_bot).
Har ishga tushganda: Dukascopy dan XAUUSD M15/H1 oladi -> LB, OLP, NexMW signallarini hisoblaydi ->
yangi signal va natijalarni Telegramga yuboradi; kuniga bir marta XAUUSD Signal Tizimi texnik holatini yuboradi.

Ishlatish:
  python bot.py            # bir marta tekshirish (GitHub Actions shunday ishlatadi)
  python bot.py --dry      # Telegramga yubormay, xabarlarni ekranga chiqaradi
  python bot.py --loop     # har 60 soniyada tekshiradi (VPS uchun)
  python bot.py --chatid   # botga /start yozgandan keyin chat ID ni ko'rsatadi
  python bot.py --etalon   # kodni etalon signallar bilan solishtiradi
Muhit o'zgaruvchilari: TG_TOKEN, TG_CHAT_ID (vergul bilan bir nechta), BALANCE (ixtiyoriy), SNAPSHOT_HOUR_TK (standart 11)
"""
from __future__ import annotations
import argparse, datetime as dt, json, math, os, sys, time
import pandas as pd
import requests
import dukascopy_python as dk
from dukascopy_python.instruments import INSTRUMENT_FX_METALS_XAU_USD as XAU
import strategies as S

STATE = os.environ.get("STATE_FILE", "state.json")
STALE_MIN = 90  # bundan eski signal yuborilmaydi (bot o'chib qolgan bo'lsa)


# ---------------- ma'lumot ----------------
def load(interval, start, end):
    df = dk.fetch(XAU, interval, dk.OFFER_SIDE_BID, start, end)
    df = df[["open", "high", "low", "close"]].astype(float)
    return df[~df.index.duplicated()].sort_index()


def get_data(now_utc: dt.datetime, m15_days=12, h1_days=330):
    end = now_utc + dt.timedelta(days=2)
    m15_all = load(dk.INTERVAL_MIN_15, now_utc - dt.timedelta(days=m15_days), end)
    h1_all = load(dk.INTERVAL_HOUR_1, now_utc - dt.timedelta(days=h1_days), end)
    now = pd.Timestamp(now_utc)
    m15c = m15_all[m15_all.index + pd.Timedelta(minutes=15) <= now]
    h1c = h1_all[h1_all.index + pd.Timedelta(hours=1) <= now]
    return m15_all, m15c, h1c


def all_signals(m15_all, m15c, h1c):
    sig = S.lb_signals(m15c, m15_all, h1c) + S.olp_signals(m15c, m15_all, h1c) + S.nexmw_signals(m15c, m15_all, h1c)
    for s in sig:
        if "skip" in s:
            continue
        s["result"] = (S.resolve_nexmw if s["strat"] == "NexMW" else S.resolve_simple)(m15c, s)
    return sorted(sig, key=lambda s: s["sig_time"])


# ---------------- matn ----------------
def tk(t) -> str:
    return pd.Timestamp(t).tz_convert(S.TK).strftime("%d.%m %H:%M")


def lot_text(s, balance):
    if not balance:
        return "Lot: balansning ≤1% riski — lot = (balans×1%) ÷ (SL punkt×100)."
    if s["strat"] == "NexMW":
        lot = max(0.05, 0.05 * math.floor(balance / 1000))
        a = math.ceil(lot / 2 * 100) / 100
        return f"Lot (sizning sxema, balans ${balance:,.0f}): {lot:.2f} = {a:.2f} (TP1) + {lot - a:.2f} (TP2)"
    dist = abs(s["entry"] - s["sl"])
    lot = math.floor(balance * 0.01 / (dist * 100) / 0.01 + 1e-9) * 0.01
    if lot < 0.01:
        return f"⚠️ Balans ${balance:,.0f} da 0.01 lot ham 1% dan katta risk (SL {dist:.1f} punkt = ${dist:.0f})."
    return f"Lot (1% risk, balans ${balance:,.0f}): {lot:.2f} → SL urilsa ≈ -${lot * dist * 100:,.0f}"


def msg_signal(s, now, balance):
    arrow = "🟢 BUY" if s["dir"] == "BUY" else "🔴 SELL"
    late = (pd.Timestamp(now) - s["entry_time"]).total_seconds() / 60
    L = [f"<b>{arrow} XAUUSD — {s['strat']}</b> ({s['kind']})",
         f"Signal shami: {tk(s['sig_time'])} · kirish: {tk(s['entry_time'])} (Toshkent)"]
    ap = " (taxminiy — keyingi sham ochilishi hali yo'q)" if s.get("approx") else ""
    L.append(f"Kirish: <b>{s['entry']:.2f}</b>{ap}")
    if s["strat"] == "NexMW":
        md = s["model"]
        L += [f"TP1: {s['tp1']:.2f} (+5) · TP2: {s['tp2']:.2f} (+10)",
              f"SL: {s['sl']:.2f} (-30) · TP1 dan keyin Order2 SL → BE",
              f"Model: bo'yin {md['neck']:.2f}, h {md['h']:.2f}, ATR14 {s['atr']:.2f}"]
    else:
        L += [f"SL: {s['sl']:.2f} ({abs(s['entry'] - s['sl']):.1f} p) · TP: {s['tp']:.2f} ({abs(s['tp'] - s['entry']):.1f} p)",
              f"Yopish: TP/SL yoki NY 16:45 ({tk(pd.Timestamp(s['close_at_ny'], tz=S.NY))} Toshkent)"]
        if s["strat"] == "LB":
            H, Lo, mid = s["asia"]
            L.append(f"Osiyo diapazoni: {H:.2f} / {Lo:.2f}, o'rta {mid:.2f} · 1H MACD {s['macd'][0]:.2f} > / < {s['macd'][1]:.2f}")
        else:
            L.append(f"Osiyo diapazoni: {s['asia'][0]:.2f} / {s['asia'][1]:.2f} · ATR14 {s['atr']:.2f}")
    if late > 20:
        L.append(f"⏱ Kechikish: kirishdan {late:.0f} daqiqa o'tgan — narx o'zgargan bo'lishi mumkin, quvmang.")
    L.append(lot_text(s, balance))
    L.append("<i>Narx: Dukascopy bid, brokerda 0.5–2 punkt farq. Moliyaviy maslahat emas.</i>")
    return "\n".join(L)


def msg_result(s):
    r = s["result"]
    icon = {"TP": "✅", "TP1+TP2": "✅", "TP1+BE": "☑️", "SL": "❌", "VAQT": "⏹", "TP1": "🔸"}.get(r["res"], "•")
    if r.get("partial"):
        return (f"{icon} {s['strat']} {s['dir']} {s['entry']:.2f} ({tk(s['entry_time'])}): TP1 olindi (+5). "
                f"Order2 SL ni kirishga ({s['entry']:.2f}) ko'chiring.")
    pts = f"{r['pts']:+.1f} punkt" if r["pts"] is not None else ""
    return f"{icon} {s['strat']} {s['dir']} {s['entry']:.2f} ({tk(s['entry_time'])}) → <b>{r['res']}</b> {pts} · {tk(r['t'])}"


def snapshot(m15c, h1c):
    """XAUUSD Signal Tizimi — faqat texnik qism (fundamental va zona tanlovi qo'lda qilinadi)."""
    d1 = S.resample_ny(h1c, 24, 17)
    h4 = S.resample_ny(h1c, 4, 17)
    def trend(c):
        a, b, g = (S.ema(c, p).iloc[-1] for p in (20, 50, 200))
        return "BULL" if a > b > g else "BEAR" if a < b < g else "MIXED", a, b, g
    rows = []
    for name, df in (("D1", d1.iloc[:-1]), ("H4", h4.iloc[:-1]), ("H1", h1c), ("M15", m15c)):
        tr, a, b, g = trend(df["close"])
        rows.append(f"{name}: <b>{tr}</b> ({a:.0f}/{b:.0f}/{g:.0f})")
    c = float(m15c["close"].iloc[-1])
    dc = d1.iloc[:-1]
    pdh, pdl = dc["high"].iloc[-1], dc["low"].iloc[-1]
    h60 = h4.iloc[-60:]
    hi, lo = h60["high"].max(), h60["low"].min()
    pd_pct = (c - lo) / (hi - lo) * 100
    rsi_d = h1c["close"].diff()
    g = rsi_d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    l = (-rsi_d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    rsi = 100 - 100 / (1 + g / l)
    H, L, C = h1c["high"].to_numpy(), h1c["low"].to_numpy(), h1c["close"].to_numpy()
    fv = []
    for i in range(len(C) - 60, len(C)):
        if L[i] > H[i - 2] and L[i + 1:].min(initial=1e9) > H[i - 2]:
            fv.append(("bull", H[i - 2], min(L[i], L[i + 1:].min(initial=1e9))))
        if H[i] < L[i - 2] and H[i + 1:].max(initial=-1e9) < L[i - 2]:
            fv.append(("bear", max(H[i], H[i + 1:].max(initial=-1e9)), L[i - 2]))
    above = sorted([f for f in fv if f[1] > c], key=lambda f: f[1])[:2]
    below = sorted([f for f in fv if f[2] < c], key=lambda f: -f[2])[:2]
    t = pd.Timestamp(m15c.index[-1] + pd.Timedelta(minutes=15)).tz_convert(S.TK)
    out = [f"📊 <b>XAUUSD texnik holat</b> — {t:%d.%m.%Y %H:%M} Toshkent",
           f"Narx: {c:.2f} (Dukascopy bid)", "<b>Trend (EMA 20/50/200):</b>", *rows,
           f"H1 RSI14: {rsi:.1f} · H1 ATR14: {S.atr(h1c).iloc[-1]:.1f} · M15 ATR14: {S.atr(m15c).iloc[-1]:.1f}",
           f"PDH/PDL: {pdh:.2f} / {pdl:.2f}",
           f"5 kun H/L: {dc['high'].iloc[-5:].max():.2f} / {dc['low'].iloc[-5:].min():.2f} · 20 kun: {dc['high'].iloc[-20:].max():.2f} / {dc['low'].iloc[-20:].min():.2f}",
           f"H4 (60 sham) {lo:.2f}–{hi:.2f}: narx {pd_pct:.0f}% → {'PREMIUM' if pd_pct > 50 else 'DISCOUNT'}"]
    if above or below:
        out.append("Ochiq H1 FVG: " + "; ".join(f"{k} {a:.2f}–{b:.2f}" for k, a, b in above + below))
    out.append("<i>Faqat texnik qism. Fundamental va aniq kirish zonasi uchun Claude'dan \"signal ber\" deb so'rang.</i>")
    return "\n".join(out)


# ---------------- Telegram ----------------
def tg_send(text, dry=False):
    if dry:
        print("-----\n" + text)
        return True
    tok, chats = os.environ["TG_TOKEN"], os.environ["TG_CHAT_ID"].split(",")
    ok = True
    for c in chats:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": c.strip(), "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=20)
        if not r.ok:
            print("Telegram xato:", r.status_code, r.text[:200], file=sys.stderr)
            ok = False
    return ok


def show_chat_ids():
    r = requests.get(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/getUpdates", timeout=20).json()
    seen = {}
    for u in r.get("result", []):
        m = u.get("message") or u.get("channel_post") or {}
        ch = m.get("chat", {})
        if ch:
            seen[ch["id"]] = ch.get("title") or ch.get("username") or ch.get("first_name")
    print(seen or "Hech narsa yo'q: avval botga Telegram'da /start yozing, keyin qayta ishga tushiring.")


# ---------------- asosiy ----------------
def run_once(dry=False):
    now = dt.datetime.now(dt.timezone.utc)
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    sent, done = set(st.get("sent", [])), set(st.get("results", []))
    balance = float(os.environ.get("BALANCE") or 0)
    m15_all, m15c, h1c = get_data(now)
    sigs = [s for s in all_signals(m15_all, m15c, h1c) if "skip" not in s]
    boot = not st
    for s in sigs:
        rk = s["id"] + ":" + s["result"]["res"] if s.get("result") else None
        if s["id"] in sent:
            if rk and rk not in done and (boot or tg_send(msg_result(s), dry)):
                done.add(rk)
            continue
        if s.get("approx") and not boot:
            continue  # keyingi sham ochilishini kutamiz (aniq kirish narxi uchun)
        old = (pd.Timestamp(now) - s["entry_time"]).total_seconds() / 60 > STALE_MIN
        closed = rk is not None and not s["result"].get("partial")
        if boot or old or closed:
            sent.add(s["id"])  # birinchi ishga tushish, eski yoki allaqachon yopilgan — yubormaymiz
            if rk:
                done.add(rk)
            continue
        if tg_send(msg_signal(s, now, balance), dry):
            sent.add(s["id"])
    tk_now = pd.Timestamp(now).tz_convert(S.TK)
    snap_h = int(os.environ.get("SNAPSHOT_HOUR_TK") or 11)
    today = tk_now.strftime("%Y-%m-%d")
    if tk_now.weekday() < 5 and tk_now.hour >= snap_h and st.get("snap") != today:
        if tg_send(snapshot(m15c, h1c), dry):
            st["snap"] = today
    if boot:
        tg_send("🤖 XAUUSD Signal bot ishga tushdi. Strategiyalar: London Breakout, Oltin London Pro, NexMW Gold "
                "+ har kuni XAUUSD Signal Tizimi texnik holati. Signallar faqat yopilgan M15 shamlar bo'yicha.", dry)
    st["sent"] = sorted(sent)[-400:]
    st["results"] = sorted(done)[-400:]
    if not dry:
        json.dump(st, open(STATE, "w"), indent=1, sort_keys=True)
    print(f"{now:%Y-%m-%d %H:%M} UTC: {len(sigs)} signal (12 kun), yuborilganlar {len(sent)}")


ETALON = [  # (strategiya, NY kirish vaqti, yo'nalish, kirish, natija) — egasining etalon ro'yxati
    ("LB", "2026-09-28 02:30", "SELL", 4169.57, "TP"), ("LB", "2026-09-29 02:15", "BUY", 4146.60, "TP"),
    ("LB", "2026-09-30 03:00", "BUY", 4190.43, "TP"), ("LB", "2026-10-02 02:15", "BUY", 4191.94, "TP"),
    ("LB", "2026-10-05 04:15", "BUY", 4168.23, "SL"), ("LB", "2026-10-06 04:45", "BUY", 4152.44, "TP"),
    ("LB", "2026-10-07 04:30", "SELL", 4125.94, "TP"), ("LB", "2026-10-12 04:15", "SELL", 4176.98, "TP"),
    ("LB", "2026-10-14 04:45", "SELL", 4144.05, "TP"), ("LB", "2026-10-16 03:30", "BUY", 4187.43, "SL"),
    ("OLP", "2026-10-07 11:15", "SELL", 4103.28, "TP"), ("OLP", "2026-10-12 04:15", "SELL", 4176.98, "TP"),
    ("OLP", "2026-10-12 06:45", "SELL", 4178.88, "TP"), ("OLP", "2026-10-14 04:45", "SELL", 4144.05, "TP"),
    ("OLP", "2026-10-16 03:30", "BUY", 4187.43, "VAQT"), ("OLP", "2026-10-19 06:45", "SELL", 4165.02, "TP"),
    ("OLP", "2026-10-19 08:00", "SELL", 4161.17, "TP"), ("OLP", "2026-10-20 06:00", "SELL", 4112.56, "SL"),
    ("OLP", "2026-10-21 07:30", "BUY", 4130.24, "TP"), ("OLP", "2026-10-22 07:30", "SELL", 4062.03, "TP"),
    ("NexMW", "2026-08-10 22:00", "BUY", 4429.19, "TP1+BE"), ("NexMW", "2026-08-12 14:45", "BUY", 4413.32, "TP1+TP2"),
    ("NexMW", "2026-08-16 20:30", "BUY", 4389.52, "TP1+TP2"), ("NexMW", "2026-09-01 20:30", "SELL", 4325.57, "TP1+BE"),
    ("NexMW", "2026-09-01 21:00", "SELL", 4315.52, "TP1+TP2"), ("NexMW", "2026-10-04 23:00", "SELL", 4142.56, "TP1+BE"),
    ("NexMW", "2026-10-07 00:45", "SELL", 4136.76, "TP1+BE"), ("NexMW", "2026-10-21 01:00", "SELL", 4114.48, "TP1+BE"),
    ("NexMW", "2026-10-22 21:45", "SELL", 4010.55, "TP1+TP2"),
]


def etalon():
    """Kod etalon signallarni topadimi — tekshiradi. Natija: mos / farq / topilmadi."""
    end = dt.datetime(2026, 10, 24, tzinfo=dt.timezone.utc)
    m15_all = load(dk.INTERVAL_MIN_15, dt.datetime(2026, 7, 20, tzinfo=dt.timezone.utc), end)
    h1 = load(dk.INTERVAL_HOUR_1, dt.datetime(2025, 9, 1, tzinfo=dt.timezone.utc), end)
    sigs = all_signals(m15_all, m15_all, h1)
    got = {(s["strat"], S._ny(s["entry_time"]).strftime("%Y-%m-%d %H:%M")): s for s in sigs}
    ok = 0
    for st_, t, d, e, res in ETALON:
        s = got.get((st_, t))
        if s is None:
            near = [k for k in got if k[0] == st_ and k[1][:10] == t[:10]]
            print(f"TOPILMADI {st_} {t} {d} {e} | o'sha kuni kodda: {[(k[1], got[k].get('dir'), got[k].get('skip')) for k in near]}")
            continue
        if "skip" in s:
            print(f"O'TKAZILDI {st_} {t} {d} — kod sababi: {s['skip']}")
            continue
        r = (s.get("result") or {}).get("res")
        same = s["dir"] == d and abs(s["entry"] - e) < 0.6 and r == res
        ok += same
        print(f"{'MOS ' if same else 'FARQ'} {st_} {t} etalon {d} {e} {res} | kod {s['dir']} {s['entry']} {r} SL {s['sl']}")
    n_code = {k: sum(1 for s in sigs if s["strat"] == k and "skip" not in s and s["entry_time"] >= pd.Timestamp("2026-09-28", tz="UTC")) for k in ("LB", "OLP")}
    print(f"\nJami: {ok}/{len(ETALON)} mos. Kodda 28.09–23.10 orasida signallar: {n_code}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true"); ap.add_argument("--loop", action="store_true")
    ap.add_argument("--chatid", action="store_true"); ap.add_argument("--etalon", action="store_true")
    a = ap.parse_args()
    if a.chatid:
        show_chat_ids()
    elif a.etalon:
        etalon()
    elif a.loop:
        while True:
            try:
                run_once(a.dry)
            except Exception as ex:
                print("xato:", ex, file=sys.stderr)
            time.sleep(60)
    else:
        run_once(a.dry)
