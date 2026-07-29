"""The single-stock scan universe, and a loader for it.

Everything the weekend scans read is a real listed company — never a synthetic
basket, an ETF, or an index. Those are built from the stocks below, so scanning
them would double-count the same tape and produce a "volume high" on an index
whose volume field is a composite of its members.

The universe is assembled from what the repo already tracks: the S&P 500
membership snapshot, every basket constituent, and every name a reco book has
ever pointed at. 628 names today.

    from analysis.universe import scan_universe, load_prices
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DAILY_DIR, PRICE_SCALE, file_stem
from ingestion.baskets import BASKETS
from ingestion.recos import LEDGER, reco_tickers
from ingestion.tickers import load_tickers

# Series that are built FROM the universe rather than being part of it.
SYNTHETIC = set(BASKETS) | {f"{k}_reco" for k in LEDGER}


def scan_universe():
    """Sorted parquet stems of every real single stock on disk."""
    want = {file_stem(t) for t in
            set(load_tickers()) | {t for ts in BASKETS.values() for t in ts} | reco_tickers()}
    have = {f.stem for f in DAILY_DIR.glob("*.parquet")}
    return sorted((want & have) - SYNTHETIC)


def sp500_members():
    """The S&P names specifically — the membership set breadth is measured on."""
    have = {f.stem for f in DAILY_DIR.glob("*.parquet")}
    return sorted({file_stem(t) for t in load_tickers()} & have)


def load_prices(stems=None, columns=("close", "volume")):
    """{stem: DataFrame indexed by date} with prices de-scaled to float.

    Reads parquet directly rather than through DuckDB: the scans want whole
    columns as numpy arrays, not a query per ticker.
    """
    stems = list(stems) if stems is not None else scan_universe()
    cols = ["date"] + [c for c in columns]
    out = {}
    for s in stems:
        f = DAILY_DIR / f"{s}.parquet"
        if not f.exists():
            continue
        d = pq.read_table(f, columns=cols).to_pandas()
        if not len(d):
            continue
        d["date"] = pd.to_datetime(d["date"])
        for c in ("open", "high", "low", "close", "adj_close"):
            if c in d.columns:
                d[c] = d[c] / PRICE_SCALE
        out[s] = d.set_index("date").sort_index()
    return out


def us_calendar(px):
    """The trading calendar of the US-session names.

    The '.T' / '.KS' / '.DE' listings run their own sessions. They stay in the
    scans, which only ever compare a name to its own history, but they are kept
    out of breadth, where a name that simply wasn't open would otherwise read as
    a name that failed to participate.
    """
    # The dominant latest date is the US session. A small number of Tokyo or
    # Seoul listings can already have tomorrow's close while New York is still
    # on the prior session, so the absolute maximum date is not a US calendar.
    last_counts = Counter(d.index[-1] for d in px.values())
    dominant = max(last_counts.values())
    last = max(d for d, count in last_counts.items() if count == dominant)
    us = [s for s in px if px[s].index[-1] == last]
    ref = max((px[s] for s in us), key=lambda d: len(d)).index
    return ref, us
