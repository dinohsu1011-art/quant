# quant

Daily-prices research repo: 585 series (S&P 500 constituents, indices, sector /
sub-sector / industry ETFs, AI-chip single-stock baskets, macro cross-asset) stored
as per-ticker parquet, queried in place by DuckDB, with an event-study engine and
an interactive panel embedded in the Obsidian trader profile.

## Layout

| Path | What |
|---|---|
| `data/daily/*.parquet` | One file per series. int64 prices ×100,000 (`PRICE_SCALE`), columns `date open high low close adj_close volume` |
| `data/tickers.csv` | S&P 500 membership snapshot (see Caveats) |
| `config.py` | Paths, `PRICE_SCALE`, index symbols, `SYMBOL_ALIASES` (`GC=F`→GOLD, `^VIX`→VIX, …) |
| `db.py` | `connect()` → DuckDB with every parquet as a de-scaled view + `returns('tkr')` macro |
| `ingestion/` | `fetch.py` (yfinance bulk), `store.py` (normalize: int64 scale, bar repair, partial-bar drop), `tickers.py` (Wikipedia S&P list), `baskets.py` (equal-weight theme baskets) |
| `analysis/events.py` | `event_study()` (trigger/weekday/horizon/`when=` regime gate/`measure_field`), `sequence()` (multi-day chains), `compare_regimes()` |
| `export/cube.py` | Pre-computes ~90k event-study combos → `trader-profile-cube.js` (offline panel data) |
| `export/trader_profile.py` | Static regime charts → `trader-profile-data.js` |
| `serve.py` | Optional localhost backend: serves the reports dir + live `/api/event` (all 585 series, arbitrary params) |
| `validate.py` | Integrity scan (staleness, dup dates, bad bars, gaps, collisions, as_of drift). Exit 1 on failure |
| `update.py` | **The one command to refresh everything** (fetch → baskets → cube → bundle → validate) |

Outputs land in `~/Desktop/Obsidian/trading-brain/reports/` next to `trader-profile.html`.

## Usage

```bash
./.venv/bin/python update.py                 # refresh data + all artifacts + validate
./.venv/bin/python validate.py               # integrity scan only
./.venv/bin/python -m analysis.events        # canonical NDX "terrible Fridays" table
./.venv/bin/python serve.py                  # live backend → http://localhost:8765/trader-profile.html
```

```python
import db
from analysis.events import event_study, sequence, FRI
conn = db.connect()
event_study(conn, "spy", day=FRI, threshold=-0.025, when="vix>30")    # regime-gated study
sequence(conn, ["spy_ret<=-0.025", "spy_ret<0"], "xle", anchor_day=FRI)  # Fri crash → red Mon → Tue
```

## Update discipline

`update.py` is a **full refresh by design** — closes are downloaded with
`auto_adjust=True`, so any dividend/split rescales the entire back-history;
incremental appends would silently corrupt it. Baskets, cube, and the data bundle
must regenerate after every fetch (baskets compound full history). Run after the
US close; `store.py` drops same-day partial bars if run while the session is open.

## Caveats

- **Survivorship / look-ahead bias** — `data/tickers.csv` is a *current* S&P 500
  membership snapshot applied to history back to 1990. Constituent-level
  cross-sections are biased; the curated index/ETF/basket subjects are not affected.
- **Baskets** (`gpu`, `semicap`, `hyperscale`, …) are equal-weight, daily-rebalanced
  synthetic indices that **broaden as constituents IPO** (early history = oldest
  members only) and store **flat OHLC** (high==low==close) — `measure_field`
  hi/lo/range is blocked for them by a guard in `events.py`.
- **Metals/energy are COMEX/NYMEX continuous futures** (GC=F, SI=F, HG=F, CL=F),
  not cash spot. WTI's 2020-04-20 negative-price bar is dropped by normalization.
- **Conditioner truncation** — `when=` gates referencing short-history series
  (`vix3m` 2006-07+, `hyg` 2007+, `uup` 2007+, `ibit` 2024+) silently shrink the
  sample to that series' start; `event_study`/`sequence` emit a warning when this
  happens.
- **`adj_close == close` by construction** (auto_adjust) — the column is kept for
  schema stability only.
- **SOXX / IBB** parquets stay on disk (and refresh) but are off the cube menu —
  SMH / XBI are the canonical semis/biotech series.
