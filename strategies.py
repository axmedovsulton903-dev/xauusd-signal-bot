"""XAUUSD avto signal strategiyalari: London Breakout (LB), Oltin London Pro (OLP), NexMW Gold v2.0.
Qoidalar egasining (Shuxrat Musayev) v1.0 / v2.0 tavsifi asosida yozilgan.
Barcha funksiyalar faqat YOPILGAN M15 shamlardan signal chiqaradi; kirish = keyingi sham ochilishi.
"""
from __future__ import annotations
import datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd

NY = ZoneInfo("America/New_York")
TK = ZoneInfo("Asia/Tashkent")
M15 = pd.Timedelta(minutes=15)

FOMC = {  # NY sanalari; har yili federalreserve.gov dan yangilang
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
}


# ---------------- yordamchi ----------------
def ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(span=p, adjust=False).mean()


def atr(df: pd.DataFrame, p: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / p, adjust=False).mean()


def macd(close: pd.Series):
    m = ema(close, 12) - ema(close, 26)
    return m, ema(m, 9)


def resample_ny(df: pd.DataFrame, hours: int, anchor_hour: int) -> pd.DataFrame:
    """NY vaqti bo'yicha sham yig'ish. anchor_hour=17 -> kun NY 17:00 da boshlanadi, 0 -> yarim tunda.
    Natija indeksi: shamning NY boshlanish vaqti (naive), 'end_utc' ustuni - yopilish vaqti (UTC)."""
    ny = df.index.tz_convert(NY).tz_localize(None)
    shift = pd.Timedelta(hours=(24 - anchor_hour) % 24)
    key = (ny + shift).floor(f"{hours}h") - shift
    g = df.groupby(key)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last(),
                        "last_utc": g.apply(lambda x: x.index[-1])})
    return out


def closed_before(rs: pd.DataFrame, hours: int, t_ny_naive: dt.datetime) -> pd.DataFrame:
    """t momentigacha to'liq yopilgan shamlar (boshlanish + davomiylik <= t)."""
    return rs[rs.index + pd.Timedelta(hours=hours) <= t_ny_naive]


def _ny(ts) -> dt.datetime:
    return ts.tz_convert(NY).tz_localize(None)


def _at(day: dt.date, h: int, m: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(h, m))


def _next_open(m15_all: pd.DataFrame, t_utc):
    """Signal shamidan keyingi shamning ochilishi. Hali yo'q bo'lsa (None, True) - taxminiy."""
    nt = t_utc + M15
    if nt in m15_all.index:
        return float(m15_all.at[nt, "open"]), False
    return None, True


# ---------------- natija (TP/SL/vaqt) ----------------
def resolve_simple(m15: pd.DataFrame, s: dict):
    """LB/OLP: bitta TP, bitta SL, NY 16:45 da vaqt bo'yicha yopish. Bir shamda ikkalasi -> SL."""
    if s.get("approx"):
        return None
    bars = m15[m15.index >= s["entry_time"]]
    buy = s["dir"] == "BUY"
    for t, r in bars.iterrows():
        if _ny(t) >= s["close_at_ny"]:
            px = r["open"]
            pts = (px - s["entry"]) if buy else (s["entry"] - px)
            return {"res": "VAQT", "pts": round(pts, 2), "t": t}
        hit_sl = r["low"] <= s["sl"] if buy else r["high"] >= s["sl"]
        hit_tp = r["high"] >= s["tp"] if buy else r["low"] <= s["tp"]
        if hit_sl:
            return {"res": "SL", "pts": -round(abs(s["entry"] - s["sl"]), 2), "t": t}
        if hit_tp:
            return {"res": "TP", "pts": round(abs(s["tp"] - s["entry"]), 2), "t": t}
    return None


def resolve_nexmw(m15: pd.DataFrame, s: dict):
    """Order1 TP1 / Order2 TP2, SL umumiy; TP1 dan keyin Order2 SL -> BE. Bir shamda SL va TP -> SL."""
    if s.get("approx"):
        return None
    buy = s["dir"] == "BUY"
    e, sl, tp1, tp2 = s["entry"], s["sl"], s["tp1"], s["tp2"]
    o1 = None
    for t, r in m15[m15.index >= s["entry_time"]].iterrows():
        hi, lo = r["high"], r["low"]
        if o1 is None:
            if (lo <= sl) if buy else (hi >= sl):
                return {"res": "SL", "pts": -60.0, "t": t}
            if (hi >= tp1) if buy else (lo <= tp1):
                o1 = t
                if (hi >= tp2) if buy else (lo <= tp2):
                    return {"res": "TP1+TP2", "pts": 15.0, "t": t}
            continue
        if (lo <= e) if buy else (hi >= e):
            return {"res": "TP1+BE", "pts": 5.0, "t": t}
        if (hi >= tp2) if buy else (lo <= tp2):
            return {"res": "TP1+TP2", "pts": 15.0, "t": t}
    return {"res": "TP1", "pts": None, "t": o1, "partial": True} if o1 is not None else None


# ---------------- London Breakout ----------------
def lb_signals(m15c: pd.DataFrame, m15_all: pd.DataFrame, h1c: pd.DataFrame) -> list[dict]:
    out = []
    ny = m15c.index.tz_convert(NY).tz_localize(None)
    m, sg = macd(h1c["close"])
    h1_end = h1c.index + pd.Timedelta(hours=1)
    for day in sorted(set(ny.date)):
        if day.weekday() >= 5:
            continue
        a0, a1 = _at(day - dt.timedelta(days=1), 18), _at(day, 2)
        asia = m15c[(ny >= a0) & (ny < a1)]
        if len(asia) < 20:
            continue
        H, L = float(asia["high"].max()), float(asia["low"].min())
        mid = (H + L) / 2
        win = m15c[(ny >= _at(day, 2)) & (ny < _at(day, 5))]
        for t, r in win.iterrows():
            c = r["close"]
            if L <= c <= H:
                continue
            d = "BUY" if c > H else "SELL"
            done = t + M15
            k = h1_end <= done
            if not k.any():
                break
            mv, sv = float(m[k].iloc[-1]), float(sg[k].iloc[-1])
            base = dict(id=f"LB-{day}", strat="LB", kind="London Breakout", dir=d, sig_time=t,
                        entry_time=t + M15, asia=(H, L, mid), macd=(mv, sv),
                        close_at_ny=_at(day, 16, 45))
            if (d == "BUY") != (mv > sv):
                out.append({**base, "skip": f"1H MACD {mv:.2f} / signal {sv:.2f} — yo'nalishga zid, bugun savdo yo'q"})
                break
            e, approx = _next_open(m15_all, t)
            if e is None:
                e = float(c)
            if (d == "BUY" and e <= mid) or (d == "SELL" and e >= mid):
                out.append({**base, "skip": "kirish narxi diapazon o'rtasining narigi tomonida (gap)"})
                break
            R = 1.5 * abs(e - mid)
            sl = e - R if d == "BUY" else e + R
            tp = e + 0.5 * R if d == "BUY" else e - 0.5 * R
            out.append({**base, "entry": round(e, 2), "sl": round(sl, 2), "tp": round(tp, 2), "approx": approx})
            break
    return out


# ---------------- Oltin London Pro ----------------
def olp_signals(m15c: pd.DataFrame, m15_all: pd.DataFrame, h1c: pd.DataFrame) -> list[dict]:
    out = []
    ny = m15c.index.tz_convert(NY).tz_localize(None)
    a14 = atr(m15c)
    e20, e50 = ema(m15c["close"], 20), ema(m15c["close"], 50)
    h4 = resample_ny(h1c, 4, 0)
    h4["ema50"] = ema(h4["close"], 50)
    d1 = resample_ny(h1c, 24, 0)
    d1 = d1[d1.index.dayofweek < 5]
    d1["ema20"] = ema(d1["close"], 20)
    pos = {t: i for i, t in enumerate(m15c.index)}
    for day in sorted(set(ny.date)):
        if day.weekday() >= 5:
            continue
        asia = m15c[(ny >= _at(day - dt.timedelta(days=1), 19)) & (ny < _at(day, 2))]
        if len(asia) < 15:
            continue
        H, L = float(asia["high"].max()), float(asia["low"].min())
        cands = []
        for t, r in m15c[(ny >= _at(day, 2)) & (ny < _at(day, 5))].iterrows():
            c = r["close"]
            if c > H or c < L:
                cands.append((t, "London", "BUY" if c > H else "SELL"))
                break
        for t, r in m15c[(ny >= _at(day, 5)) & (ny < _at(day, 8))].iterrows():
            i = pos[t]
            if i == 0:
                continue
            pc, c = m15c["close"].iloc[i - 1], r["close"]
            if L <= pc <= H and (c > H or c < L):
                cands.append((t, "Kechki London", "BUY" if c > H else "SELL"))
        for t, r in m15c[(ny >= _at(day, 11)) & (ny < _at(day, 14))].iterrows():
            tn = _ny(t + M15)
            h4c, d1c = closed_before(h4, 4, tn), d1[d1.index.date < day]
            if not len(h4c) or not len(d1c):
                continue
            up = (e20[t] > e50[t] and h4c["close"].iloc[-1] > h4c["ema50"].iloc[-1]
                  and d1c["close"].iloc[-1] > d1c["ema20"].iloc[-1])
            dn = (e20[t] < e50[t] and h4c["close"].iloc[-1] < h4c["ema50"].iloc[-1]
                  and d1c["close"].iloc[-1] < d1c["ema20"].iloc[-1])
            o, c, lo, hi = r["open"], r["close"], r["low"], r["high"]
            if up and lo <= e20[t] and c > o and c > e20[t]:
                cands.append((t, "Trend pullback", "BUY"))
            elif dn and hi >= e20[t] and c < o and c < e20[t]:
                cands.append((t, "Trend pullback", "SELL"))
        n = 0
        for t, kind, d in sorted(cands):
            if n >= 2:
                break
            A = float(a14[t])
            i = pos[t]
            if kind == "Trend pullback":
                w = m15c.iloc[max(0, i - 9): i + 1]
                sl = float(w["low"].min()) - 0.1 * A if d == "BUY" else float(w["high"].max()) + 0.1 * A
            else:
                sl = L - 0.1 * A if d == "BUY" else H + 0.1 * A
            e, approx = _next_open(m15_all, t)
            if e is None:
                e = float(m15c.at[t, "close"])
            base = dict(id=f"OLP-{t:%Y%m%d%H%M}", strat="OLP", kind=kind, dir=d, sig_time=t,
                        entry_time=t + M15, asia=(H, L), atr=A, close_at_ny=_at(day, 16, 45))
            if (d == "BUY" and e <= sl) or (d == "SELL" and e >= sl):
                out.append({**base, "skip": "gap SL ortida — savdo yo'q"})
                continue
            R = abs(e - sl)
            tp = e + 0.3 * R if d == "BUY" else e - 0.3 * R
            out.append({**base, "entry": round(e, 2), "sl": round(sl, 2), "tp": round(tp, 2), "approx": approx})
            n += 1
    return out


# ---------------- NexMW Gold v2.0 ----------------
def nexmw_signals(m15c: pd.DataFrame, m15_all: pd.DataFrame, h1c: pd.DataFrame) -> list[dict]:
    O, H, L, C = (m15c[k].to_numpy() for k in ("open", "high", "low", "close"))
    T = m15c.index
    n = len(C)
    A = atr(m15c).to_numpy()
    h4 = resample_ny(h1c, 4, 17)
    h4["ema50"] = ema(h4["close"], 50)
    d1 = resample_ny(h1c, 24, 17)
    d1["ema50"] = ema(d1["close"], 50)

    lows = [i for i in range(2, n - 2) if L[i] == min(L[i - 2:i + 3])]
    highs = [i for i in range(2, n - 2) if H[i] == max(H[i - 2:i + 3])]

    def models(sw, is_w):
        res = []
        for a, b in zip(sw, sw[1:]):
            if not (3 <= b - a <= 40):
                continue
            if is_w:
                neck = max(H[a + 1:b]); ext = min(L[a], L[b]); h = neck - ext
                if h <= 0 or abs(L[a] - L[b]) > 0.25 * h:
                    continue
            else:
                neck = min(L[a + 1:b]); ext = max(H[a], H[b]); h = ext - neck
                if h <= 0 or abs(H[a] - H[b]) > 0.25 * h:
                    continue
            last = b + max(4, b - a)
            for u in range(b + 1, min(last, n - 1) + 1):
                if is_w and C[u] < ext or (not is_w) and C[u] > ext:
                    break
                if u < b + 2:
                    continue
                if is_w and C[u] > O[u] and C[u] > neck or (not is_w) and C[u] < O[u] and C[u] < neck:
                    res.append(dict(u=u, a=a, b=b, neck=float(neck), ext=float(ext), h=float(h),
                                    dir="BUY" if is_w else "SELL", model="W" if is_w else "M"))
                    break
        return res

    cand = {}
    for mdl in models(highs, False) + models(lows, True):  # W keyin yoziladi -> bir shamda W ustun
        cand[mdl["u"]] = mdl
    out, busy_until = [], None
    for u in sorted(cand):
        md = cand[u]
        t = T[u]
        et = t + M15
        tn = _ny(et)
        base = dict(id=f"NEX-{t:%Y%m%d%H%M}", strat="NexMW", kind=f"{md['model']} modeli", dir=md["dir"],
                    sig_time=t, entry_time=et, model=md)
        h4c = closed_before(h4, 4, tn)
        d1c = closed_before(d1, 24, tn)
        why = []
        if len(h4c) and len(d1c):
            f1 = h4c["close"].iloc[-1] > h4c["ema50"].iloc[-1]
            f2 = d1c["close"].iloc[-1] > d1c["ema50"].iloc[-1]
            if f1 != (md["dir"] == "BUY"): why.append("F1 H4 trend")
            if f2 != (md["dir"] == "BUY"): why.append("F2 kunlik trend")
        else:
            why.append("trend ma'lumoti yetarli emas")
        if 2 <= tn.hour < 12: why.append("F3 kirish vaqti yopiq")
        if tn.strftime("%Y-%m-%d") in FOMC and dt.time(13, 30) <= tn.time() <= dt.time(15, 0): why.append("F4 FOMC")
        if md["u"] - md["b"] > 3: why.append("F5 kech buzilish")
        if md["h"] < 1.25 * A[u]: why.append("F6 model kichik")
        if busy_until is not None and (busy_until is True or et < busy_until): why.append("F7 ochiq pozitsiya bor")
        if why:
            out.append({**base, "skip": ", ".join(why)})
            continue
        e, approx = _next_open(m15_all, t)
        if e is None:
            e = float(C[u])
        k = 1 if md["dir"] == "BUY" else -1
        s = {**base, "entry": round(e, 2), "tp1": round(e + 5 * k, 2), "tp2": round(e + 10 * k, 2),
             "sl": round(e - 30 * k, 2), "approx": approx, "atr": float(A[u])}
        out.append(s)
        r = resolve_nexmw(m15c, s)
        busy_until = True if (r is None or r.get("partial")) else r["t"] + M15
    return out
