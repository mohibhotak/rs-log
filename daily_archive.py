#!/usr/bin/env python
# daily_archive.py -- MBH:s permanenta marknadsarkiv (v1.0, 2026-11-19)
#
# Kors i GitHub Actions direkt efter RS-korningen (relative-strength.py), som redan har hamtat
# ~18 manader dagsstaplar for alla aktier i Nasdaqs symbollista (data/price_history.json).
#
# Skriver (committas i repot):
#   archive/daily/YYYY/YYYY-MM-DD.csv.gz  RADATA: en rad per aktie som handlades dagen, INGET urval.
#                                          Kurs, volym, SMA20/50/200, ATR14, 52v topp/botten m.m.
#                                          Bredden kan raknas om med vilken definition som helst i efterhand.
#   archive/index/YYYY/YYYY-MM-DD.csv     Index-ETF:er (TrendTracker-listan + VIX) med samma matt.
#   archive/breadth_daily.csv             Bredd med FAST definition (BREADTH_RULES nedan), en rad per dag.
#
# Regler som aldrig ska andras (andras de: ny kolumnuppsattning med nytt versionsnamn, aldrig skriv over):
#   Breddurval "U1": pris >= 5 USD, minst 200 staplar historik, sektor kand (inga ETF:er),
#                    de 3000 aktierna med hogst snittomsattning 50 dagar (close x volym) den dagen.
#                    Ingen ADR-grans. Rangbaserat sa att urvalet inte glider med inflationen.
#
# Kanda begransningar (star ocksa i archive/README.md):
#   - Yahoo-priser ar split- och utdelningsjusterade (auto_adjust) per hamtningsdagen. Dagsfilen
#     sparar varden sa som de sag ut den dagen ("point in time").
#   - Bakatfyllda dagar (backfill = 1) raknas pa dagens symbollista: avnoterade bolag saknas
#     (overlevnadsbias). Dagar raknade samma kvall de hande har backfill = 0.

import gzip
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

DIR = os.path.dirname(os.path.realpath(__file__))
PRICE_FILE = os.path.join(DIR, "data", "price_history.json")
ARCH = os.path.join(DIR, "archive")
VERSION = "1.0"

BREADTH_RULES = {"name": "U1", "min_price": 5.0, "min_bars": 200, "top_n": 3000}
INDEX_TICKERS = ["SPY", "QQQ", "QQQE", "RSP", "IWM", "IWO", "MDY", "DIA", "SMH", "^VIX"]
SUPER = {
    "Basic Materials": "Cyclical", "Consumer Cyclical": "Cyclical", "Financial Services": "Cyclical", "Real Estate": "Cyclical",
    "Communication Services": "Sensitive", "Energy": "Sensitive", "Industrials": "Sensitive", "Technology": "Sensitive",
    "Consumer Defensive": "Defensive", "Healthcare": "Defensive", "Utilities": "Defensive",
}
MAX_BACKFILL_DAYS = 400   # bakatfyllning forsta gangen (bara dagar med full historik for matten)


def day_of(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def frame_from_candles(candles):
    df = pd.DataFrame(candles)
    if df.empty:
        return df
    df["date"] = df["datetime"].map(day_of)
    df = df.dropna(subset=["close", "high", "low"]).drop_duplicates("date", keep="last").set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def metrics(df):
    """Alla matt per dag for en aktie. Bara data t.o.m. respektive dag anvands (ingen framtid)."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"].fillna(0)
    out = pd.DataFrame(index=df.index)
    out["open"], out["high"], out["low"], out["close"], out["volume"] = df["open"], h, l, c, v
    out["prev_close"] = c.shift(1)
    out["chg_pct"] = 100 * (c / out["prev_close"] - 1)
    out["dollar_vol"] = c * v
    for n in (20, 50, 200):
        out[f"sma{n}"] = c.rolling(n, min_periods=n).mean()
    out["ema10"] = c.ewm(span=10, adjust=False).mean()
    out["ema20"] = c.ewm(span=20, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    out["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()          # Wilder
    out["adr20_pct"] = 100 * ((h / l).rolling(20, min_periods=20).mean() - 1)
    out["hi52"] = h.rolling(252, min_periods=1).max()
    out["lo52"] = l.rolling(252, min_periods=1).min()
    out["new_hi52"] = (h >= out["hi52"]) & (h.expanding().count() >= 252)
    out["new_lo52"] = (l <= out["lo52"]) & (l.expanding().count() >= 252)
    out["avgvol30"] = v.rolling(30, min_periods=30).mean()
    out["avgvol50"] = v.rolling(50, min_periods=50).mean()
    out["dvol50"] = (c * v).rolling(50, min_periods=50).mean()
    out["ext50_atr"] = ((c - out["sma50"]).abs() / out["sma50"]) / (out["atr14"] / c)   # Swing Data-formeln
    out["bars"] = c.expanding().count()
    return out


def load():
    """En stor tabell: en rad per aktie och dag (index = datum)."""
    raw = json.load(open(PRICE_FILE, encoding="utf-8"))
    parts = []
    for t, d in raw.items():
        cs = d.get("candles") or []
        if len(cs) < 2:
            continue
        df = frame_from_candles(cs)
        if df.empty:
            continue
        m = metrics(df)
        m.insert(0, "industry", d.get("industry") or "")
        m.insert(0, "sector", d.get("sector") or "")
        m.insert(0, "ticker", t)
        parts.append(m)
    big = pd.concat(parts)
    big.index.name = "date"
    return big.sort_index(kind="stable")


DAILY_COLS = ["ticker", "sector", "industry", "open", "high", "low", "close", "prev_close", "chg_pct", "volume", "dollar_vol",
              "sma20", "sma50", "sma200", "ema10", "ema20", "atr14", "adr20_pct", "hi52", "lo52", "new_hi52", "new_lo52",
              "avgvol30", "avgvol50", "dvol50", "ext50_atr", "bars"]


def day_table(big, day):
    try:
        tab = big.loc[[day]]
    except KeyError:
        return pd.DataFrame(columns=DAILY_COLS)
    return tab.reset_index(drop=True)[DAILY_COLS]


def breadth_row(tab, day, backfill):
    known = tab["sector"].isin(SUPER.keys())
    u = tab[known & (tab["close"] >= BREADTH_RULES["min_price"]) & (tab["bars"] >= BREADTH_RULES["min_bars"]) & tab["dvol50"].notna()]
    u = u.sort_values("dvol50", ascending=False).head(BREADTH_RULES["top_n"])
    u = u[u["chg_pct"].notna()]
    n = len(u)
    if n == 0:
        return None
    ch = u["chg_pct"]
    pct = lambda mask, base=None: round(100.0 * mask.sum() / (len(base) if base is not None else n), 2) if n else None
    upv, dnv = u.loc[ch > 0, "volume"].sum(), u.loc[ch < 0, "volume"].sum()
    adv, dec = int((ch > 0).sum()), int((ch < 0).sum())
    s20, s50, s200 = u[u["sma20"].notna()], u[u["sma50"].notna()], u[u["sma200"].notna()]
    hl = u[u["bars"] >= 252]
    row = {
        "date": day, "rules": BREADTH_RULES["name"], "backfill": int(backfill), "n": n,
        "min_dvol50_musd": round(u["dvol50"].min() / 1e6, 2),
        "adv": adv, "dec": dec, "unch": int((ch == 0).sum()),
        "up4": int((ch >= 4).sum()), "dn4": int((ch <= -4).sum()),
        "new_hi52": int(hl["new_hi52"].sum()), "new_lo52": int(hl["new_lo52"].sum()), "hl_base_n": len(hl),
        "net_nh_pct": round(100.0 * (hl["new_hi52"].sum() - hl["new_lo52"].sum()) / len(hl), 2) if len(hl) else None,
        "pct_above_sma20": round(100.0 * (s20["close"] > s20["sma20"]).mean(), 2) if len(s20) else None,
        "pct_above_sma50": round(100.0 * (s50["close"] > s50["sma50"]).mean(), 2) if len(s50) else None,
        "pct_above_sma200": round(100.0 * (s200["close"] > s200["sma200"]).mean(), 2) if len(s200) else None,
        "ext50_10x_n": int(((u["ext50_atr"] >= 10) & (u["close"] > u["sma50"])).sum()),
        "upvol_pct": round(100.0 * upv / (upv + dnv), 2) if (upv + dnv) > 0 else None,
        "trin": round((adv / dec) / (upv / dnv), 3) if dec and upv and dnv else None,
        "median_chg_pct": round(float(ch.median()), 3),
    }
    for sname in ("Defensive", "Cyclical", "Sensitive"):
        m = u["sector"].map(SUPER) == sname
        row[f"{sname.lower()}_avg_chg"] = round(float(ch[m].mean()), 3) if m.any() else None
    for sec in sorted(SUPER.keys()):
        m = u["sector"] == sec
        key = sec.lower().replace(" ", "_")
        row[f"{key}_n"] = int(m.sum())
        row[f"{key}_avg_chg"] = round(float(ch[m].mean()), 3) if m.any() else None
        row[f"{key}_pct_above_sma50"] = round(100.0 * (u.loc[m, "close"] > u.loc[m, "sma50"]).mean(), 2) if m.any() else None
    row["version"] = VERSION
    return row


def fetch_indexes():
    try:
        import yfinance as yf
        df = yf.download(tickers=INDEX_TICKERS, period="2y", auto_adjust=True, progress=False, group_by="ticker", ignore_tz=True)
    except Exception as e:
        print(f"Index-hamtning misslyckades: {e}")
        return {}
    out = {}
    for t in INDEX_TICKERS:
        try:
            sub = df[t].dropna(subset=["Close"]).copy()
            sub.index = [d.strftime("%Y-%m-%d") for d in sub.index]
            sub.columns = [c.lower() for c in sub.columns]
            out[t] = metrics(sub[["open", "high", "low", "close", "volume"]].astype(float))
        except Exception as e:
            print(f"Index {t} saknas: {e}")
    return out


def write_csv_gz(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        df.to_csv(f, index=False, float_format="%.6g")


def main(today_only=False):
    big = load()
    spy = big[big["ticker"] == "SPY"]
    if spy.empty:
        print("SPY saknas i price_history -- avbryter")
        sys.exit(1)
    days = sorted(spy.index.unique())
    data = big
    last = days[-1]
    bpath = os.path.join(ARCH, "breadth_daily.csv")
    have = set()
    if os.path.exists(bpath):
        have = set(pd.read_csv(bpath, usecols=["date"])["date"].astype(str))

    # 1) radata for senaste dagen (point in time) -- skrivs aldrig over
    dpath = os.path.join(ARCH, "daily", last[:4], f"{last}.csv.gz")
    if not os.path.exists(dpath):
        tab = day_table(data, last)
        write_csv_gz(tab, dpath)
        print(f"Radata {last}: {len(tab)} aktier -> {dpath}")
    else:
        print(f"Radata {last} finns redan")

    # 2) index (TrendTracker-listan)
    idx = fetch_indexes()
    if idx:
        rows = []
        for t, m in idx.items():
            if last in m.index:
                r = m.loc[last]
                rows.append([t] + [r[k] for k in DAILY_COLS[3:]])
        if rows:
            ipath = os.path.join(ARCH, "index", last[:4], f"{last}.csv")
            os.makedirs(os.path.dirname(ipath), exist_ok=True)
            pd.DataFrame(rows, columns=["ticker"] + DAILY_COLS[3:]).to_csv(ipath, index=False, float_format="%.6g")

    # 3) bredd: dagens rad (backfill 0) + bakatfyllning av saknade dagar forsta gangen (backfill 1)
    new_rows = []
    todo = [d for d in days[-MAX_BACKFILL_DAYS:] if d not in have]
    if today_only:
        todo = [d for d in todo if d == last]
    for d in todo:
        r = breadth_row(day_table(data, d), d, backfill=(d != last))
        if r and (r["pct_above_sma200"] is not None or d == last):
            new_rows.append(r)
    if new_rows:
        nb = pd.DataFrame(new_rows)
        if os.path.exists(bpath):
            nb = pd.concat([pd.read_csv(bpath), nb], ignore_index=True)
        nb = nb.drop_duplicates("date", keep="first").sort_values("date")
        os.makedirs(ARCH, exist_ok=True)
        nb.to_csv(bpath, index=False)
        print(f"Bredd: {len(new_rows)} nya dagar ({new_rows[0]['date']} .. {new_rows[-1]['date']}) -> {bpath}")
    else:
        print("Bredd: inga nya dagar")


if __name__ == "__main__":
    main(today_only=("--today-only" in sys.argv))
