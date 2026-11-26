#!/usr/bin/env python
# alpaca_reserv.py — Alpaca som reservkälla för rs-log (MBH 2026-11-26, steg 3).
#
# Används BARA för tickers som Yahoo inte levererade (batch-fel eller saknad data).
# Fungerar Yahoo används Alpaca inte alls.
#   - Nycklar: miljövariablerna ALPACA_KEY_ID / ALPACA_SECRET (GitHub-secrets). Saknas de: hoppa över.
#   - Data: https://data.alpaca.markets/v2/stocks/bars, timeframe 1Day, adjustment=all
#     (split + utdelning, som yfinance auto_adjust=True), feed=sip, end = nu - 20 min
#     (Basic-planen ger inte SIP för de senaste 15 min).
#   - Format: samma candle-dict som rs_data.parse_batch_download (datetime = midnatt UTC för handelsdagen,
#     samma som yfinance ignore_tz=True på GitHub-runnern som kör i UTC).
#   - 200 anrop/min på Basic: 0,35 s paus mellan anrop.

import os
import re
import time
import datetime as dt

import requests

ALPACA_URL = "https://data.alpaca.markets/v2/stocks/bars"
CHUNK = 100          # symboler per anrop
PAUS_S = 0.35        # håller oss under 200 anrop/min
TIMEOUT_S = 30
GILTIG = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")


def har_nyckel():
    return bool(os.environ.get("ALPACA_KEY_ID")) and bool(os.environ.get("ALPACA_SECRET"))


def _headers():
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET"],
    }


def alpaca_sym(ticker):
    """Yahoo/NASDAQ-form -> Alpaca-form (BRK-B / BRK.B -> BRK.B)."""
    return ticker.strip().upper().replace("-", ".")


def _dag_ts(t_iso):
    """Alpaca-tidsstämpel ('2026-11-25T05:00:00Z') -> midnatt UTC för New York-handelsdagen."""
    d = dt.date.fromisoformat(t_iso[:10])
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def _hamta(symboler, start, slut, statistik):
    """Ett anrop (med sidor). Returnerar {alpaca_sym: [candles]} eller kastar vid HTTP-fel."""
    ut = {}
    token = None
    while True:
        params = {
            "symbols": ",".join(symboler),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": slut.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "adjustment": "all",
            "feed": "sip",
            "limit": 10000,
        }
        if token:
            params["page_token"] = token
        r = requests.get(ALPACA_URL, headers=_headers(), params=params, timeout=TIMEOUT_S)
        statistik["anrop"] += 1
        time.sleep(PAUS_S)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        j = r.json()
        for sym, bars in (j.get("bars") or {}).items():
            lista = ut.setdefault(sym, [])
            for b in bars:
                if b.get("c") is None:
                    continue
                lista.append({
                    "open": float(b["o"]) if b.get("o") is not None else None,
                    "close": float(b["c"]),
                    "low": float(b["l"]) if b.get("l") is not None else None,
                    "high": float(b["h"]) if b.get("h") is not None else None,
                    "volume": float(b["v"]) if b.get("v") is not None else None,
                    "datetime": _dag_ts(b["t"]),
                })
        token = j.get("next_page_token")
        if not token:
            return ut


def _hamta_delbar(symboler, start, slut, statistik):
    """Vid HTTP 400 (t.ex. okänd symbol) delas listan i två tills felet är isolerat."""
    try:
        return _hamta(symboler, start, slut, statistik)
    except RuntimeError as e:
        if "HTTP 400" in str(e) and len(symboler) > 1:
            mitt = len(symboler) // 2
            a = _hamta_delbar(symboler[:mitt], start, slut, statistik)
            b = _hamta_delbar(symboler[mitt:], start, slut, statistik)
            a.update(b)
            return a
        if len(symboler) == 1:
            statistik["avvisade"].append(symboler[0])
            return {}
        raise


def hamta_reserv(tickers, start_date):
    """
    tickers: lista med originaltickers (som i rs_data) som Yahoo inte levererade.
    start_date: datetime.date (samma 18 månader som Yahoo-hämtningen).
    Returnerar ({original_ticker: [candles]}, statistik).
    """
    statistik = {"begarda": len(tickers), "anrop": 0, "avvisade": [], "fel": None, "levererade": 0}
    if not tickers:
        return {}, statistik
    if not har_nyckel():
        statistik["fel"] = "ALPACA_KEY_ID/ALPACA_SECRET saknas - reserv avstangd"
        return {}, statistik

    slut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)
    till_original = {}
    giltiga = []
    for t in tickers:
        s = alpaca_sym(t)
        if GILTIG.match(s):
            till_original[s] = t
            giltiga.append(s)
        else:
            statistik["avvisade"].append(t)

    resultat = {}
    for i in range(0, len(giltiga), CHUNK):
        del_ = giltiga[i:i + CHUNK]
        try:
            data = _hamta_delbar(del_, start_date, slut, statistik)
        except Exception as e:  # nätverk/401/429 - stoppa reserven, låt Yahoo-resultatet stå
            statistik["fel"] = f"{type(e).__name__}: {str(e)[:200]}"
            break
        for sym, candles in data.items():
            if candles and sym in till_original:
                candles.sort(key=lambda c: c["datetime"])
                resultat[till_original[sym]] = candles

    statistik["levererade"] = len(resultat)
    return resultat, statistik
