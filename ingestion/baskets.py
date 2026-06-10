"""
Build equal-weight, daily-rebalanced BASKET index series for AI/chip value-chain
themes that have no clean ETF. Each basket becomes a synthetic parquet (an index
level stored in the price columns) so it plugs straight into db.py views,
event_study, and the cube — queryable by its name (e.g. 'gpu', 'semicap').

Constituents not already in the dataset are pulled from yfinance first. The basket
return each day is the equal-weight mean of its available constituents' daily
returns (so the basket broadens as names IPO), compounded into a level from 100.

    python -m ingestion.baskets
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from config import DAILY_DIR, PRICE_SCALE
from ingestion.fetch import run
from ingestion.store import SCHEMA

BASKETS = {
    "gpu":        ["NVDA", "AMD"],
    "cpuasic":    ["INTC", "AMD", "AVGO", "MRVL"],
    "memory":     ["MU", "WDC", "STX"],
    "semicap":    ["AMAT", "LRCX", "KLAC", "ASML"],
    "powersemi":  ["ON", "MPWR", "STM"],
    "photonics":  ["COHR", "LITE", "FN"],
    "aiserver":   ["SMCI", "DELL", "HPE", "ANET", "VRT"],
    "hyperscale": ["MSFT", "GOOGL", "AMZN", "META", "ORCL"],
    "neocloud":   ["CRWV", "NBIS", "APLD"],
    "cdnedge":    ["NET", "AKAM", "FSLY"],
    "solutil":    ["FSLR", "NXT", "ARRY"],
    "solresi":    ["ENPH", "SEDG", "RUN"],
}


def _view(t):
    return t.lower().replace("-", "_")


def _views(conn):
    return {r[0] for r in conn.execute("select table_name from information_schema.tables").fetchall()}


def main():
    conn = db.connect()
    have = _views(conn)
    allc = sorted({t for ts in BASKETS.values() for t in ts})
    missing = [t for t in allc if _view(t) not in have]
    if missing:
        print("Pulling missing constituents:", missing)
        run(missing, skip_existing=False)
        conn = db.connect()
        have = _views(conn)

    print("\nBuilding baskets:")
    for name, tickers in BASKETS.items():
        cols, avail = {}, []
        for t in tickers:
            if _view(t) not in have:
                print(f"  [miss] {name}: {t} unavailable"); continue
            d = conn.execute(f'select date, close from "{_view(t)}" order by date').df()
            d["date"] = pd.to_datetime(d["date"])
            cols[t] = d.set_index("date")["close"]
            avail.append(t)
        if not cols:
            print(f"  [skip] {name}: no constituents available"); continue
        px = pd.concat(cols, axis=1, sort=False).sort_index()
        eq = px.pct_change().mean(axis=1, skipna=True).fillna(0.0)
        level = 100.0 * (1.0 + eq).cumprod()
        lvl = (level * PRICE_SCALE).round().astype("int64").to_numpy()
        df = pd.DataFrame({
            "date": [d.date() for d in level.index],
            "open": lvl, "high": lvl, "low": lvl, "close": lvl, "adj_close": lvl,
            "volume": np.zeros(len(level), dtype="int64"),
        })
        pq.write_table(pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False),
                       DAILY_DIR / f"{name}.parquet", compression="snappy")
        print(f"  {name:11} {','.join(avail):40} {str(level.index.min().date())}→  {len(level)} rows")


if __name__ == "__main__":
    main()
