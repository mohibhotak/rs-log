# Marknadsarkiv (MBH)

Skrivs varje vardagskväll av `daily_archive.py` (GitHub Actions, efter RS-körningen 22:15 UTC).

| Fil | Innehåll |
|---|---|
| `daily/ÅÅÅÅ/ÅÅÅÅ-MM-DD.csv.gz` | Rådata: en rad per aktie som handlades dagen, **inget urval**: sektor, bransch, open, high, low, close, föregående stängning, volym. Alla andra mått (SMA, ATR, 52v, Ext50 …) räknas om ur historiken. Ca 50 MB/år. |
| `index/ÅÅÅÅ/ÅÅÅÅ-MM-DD.csv` | Samma mått för SPY, QQQ, QQQE, RSP, IWM, IWO, MDY, DIA, SMH och ^VIX (TrendTracker-listan). |
| `breadth_daily.csv` | Bredd med fast definition, en rad per dag. |

## Breddurval U1 (ändras aldrig)
- Pris ≥ 5 USD, minst 200 staplar historik, känd sektor (inga ETF:er).
- De 3 000 aktierna med högst snittomsättning 50 dagar (close × volym) den dagen. Ingen ADR-gräns.
- Rangbaserat, så att urvalet inte glider med inflationen. `min_dvol50_musd` visar var gränsen låg den dagen.
- Nya 52v-toppar/-bottnar räknas bara på aktier med minst 252 staplar (`hl_base_n`).

Ska definitionen ändras: lägg till nya kolumner med nytt namn (U2 …). Skriv aldrig över gamla rader.

## Kända begränsningar
- Yahoo-priserna är split- och utdelningsjusterade per hämtningsdagen. Dagsfilen sparar värdena så som de såg ut den dagen.
- `backfill = 1`: dagen räknades i efterhand på dagens symbollista (avnoterade bolag saknas = överlevnadsbias). `backfill = 0`: räknad samma kväll.
- Universum = Nasdaqs symbollista (alla amerikanska börser), aktier utan ETF:er.
