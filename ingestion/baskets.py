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

# Theme baskets (user's categorization, 2026-06-10). US listings only — foreign
# exchanges (KRX 000660/005930, ASX BHP, SWX ABBN, OTC SMERY/SBGSY) are excluded
# for trading-calendar alignment; HG excluded (Hamilton Insurance, mis-tagged).
# Overlaps across baskets (AMD, ANET, VRT, ...) are deliberate.
BASKETS = {
    # chips & AI value chain
    "gpu":          ["NVDA", "AMD", "TSM"],
    "cpuasic":      ["INTC", "AMD", "AVGO", "MRVL"],
    "aiinference":  ["QCOM", "AMD", "MRVL", "ARM", "AVGO"],
    "memory":       ["MU", "WDC", "STX", "SNDK"],
    "semicap":      ["AMAT", "LRCX", "KLAC", "ASML", "PENG"],
    "powersemi":    ["ON", "MPWR", "STM", "POWI", "ALGM", "WOLF", "NXPI", "DIOD", "AOSL", "VSH"],
    "photonics":    ["COHR", "LITE", "FN", "AXTI", "AAOI", "GLW", "VIAV"],
    "connectivity": ["CRDO", "ALAB"],
    "networking":   ["CSCO", "ANET"],
    # compute, cloud & software
    "aiserver":     ["SMCI", "DELL", "HPE", "ANET", "VRT", "AAPL", "IBM"],
    "hyperscale":   ["MSFT", "GOOGL", "AMZN", "META", "ORCL"],
    "neocloud":     ["CRWV", "NBIS", "APLD", "IREN", "DOCN", "CIFR"],
    "cdnedge":      ["NET", "AKAM", "FSLY"],
    "software":     ["DDOG", "SNOW"],
    "cyber":        ["PANW", "CRWD", "S", "OKTA", "ZS"],
    # physical economy / electrification
    "elecind":      ["ETN", "GEV", "VRT", "CAT", "CMI", "AME", "HUBB", "GNRC", "MOD", "ENS", "POWL"],
    "epc":          ["PWR", "EME", "MTZ", "FIX", "STRL", "PRIM", "IESC", "MYRG", "FLR", "J", "ECG"],
    "nuclear":      ["CCJ", "CEG", "BWXT", "OKLO", "NXE", "LEU", "SMR", "UUUU", "XE"],
    "solutil":      ["FSLR", "NXT", "ARRY", "SHLS", "FLNC", "EOSE", "CWEN", "BE", "PLUG", "FCEL", "BEP", "SOLS"],
    "solresi":      ["ENPH", "SEDG", "RUN"],
    # aero, defense & frontier
    "defense":      ["LMT", "RTX", "NOC", "GD", "LHX", "HII", "BA", "TXT", "LDOS", "TDG", "HEI",
                     "CW", "OSK", "KTOS", "MRCY", "PLTR", "AVAV", "RCAT", "UMAC", "HWM"],
    "space":        ["IRDM", "RKLB", "ASTS", "LUNR", "RDW", "PL", "FLY"],
    "robotics":     ["ROK", "EMR", "PH", "APH", "ZBRA", "CGNX", "NOVT", "LSCC", "AMBA", "MBLY",
                     "SYM", "AUR", "OUST", "AEVA", "INDI", "KLIC", "TSLA", "XPEV", "SERV", "RR",
                     "ARBE", "KITT", "ALNT", "VPG", "ATOM", "MRAM", "BOT", "AMBQ"],
    # resources
    "miners":       ["FCX", "SCCO", "NEM", "TECK", "HBM"],
    "materials":    ["MP", "ALB", "NUE", "STLD", "CLF", "FMC", "USAR"],
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
