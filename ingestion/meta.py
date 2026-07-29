"""Company name, sector and industry for every tracked stock, not just the
S&P 500 ones.

The membership table from Wikipedia labels the 503 index members and nothing
else, which leaves roughly a fifth of the tracked universe — ASML, TSM, ARM, the
Tokyo names, the neoclouds, most of the pre-profit power and space names —
unlabelled. On a screen that exists to roll a ranking up into groups, an
unlabelled name is worse than a missing one: it silently drops out of the sector
totals while still occupying a slot in the cohort.

So the gaps are filled from Yahoo, whose sector taxonomy is its own ("Technology",
"Consumer Cyclical") and is mapped onto the GICS 11 the index table uses. The two
sources must agree on a label or a sector count means nothing.

Results are cached in data/meta.csv and only unknown tickers are fetched, so the
daily run costs nothing until a basket gains a name.

    python -m ingestion.meta          # top up whatever is missing
    python -m ingestion.meta --all    # refetch everything
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_DIR, file_stem
from ingestion.tickers import load_ticker_meta

META_FILE = DATA_DIR / "meta.csv"
COLUMNS = ["stem", "symbol", "name", "sector", "industry"]

# Yahoo's sector names -> the GICS sectors the S&P table uses. Anything not
# listed is kept verbatim, which shows up as its own bar rather than silently
# merging into a neighbour.
SECTOR_MAP = {
    "Technology": "Information Technology",
    "Communication Services": "Communication Services",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Healthcare": "Health Care",
    "Financial Services": "Financials",
    "Basic Materials": "Materials",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
}


def _load_cache() -> pd.DataFrame:
    if not META_FILE.exists():
        return pd.DataFrame(columns=COLUMNS)
    d = pd.read_csv(META_FILE)
    for c in COLUMNS:
        if c not in d.columns:
            d[c] = ""
    return d[COLUMNS].fillna("")


def fetch(symbols, pause=0.15):
    """[{stem, symbol, name, sector, industry}] from Yahoo, skipping failures.

    A name that errors or returns nothing is simply left out, so it stays in the
    'missing' set and is retried on the next run instead of being cached blank.
    """
    import yfinance as yf
    out = []
    for i, sym in enumerate(symbols, 1):
        try:
            info = yf.Ticker(sym).info or {}
        except Exception as e:
            print(f"  {sym}: {type(e).__name__}")
            continue
        name = info.get("longName") or info.get("shortName") or ""
        sector = info.get("sector") or ""
        if not name and not sector:
            print(f"  {sym}: no info")
            continue
        out.append({
            "stem": file_stem(sym),
            "symbol": sym,
            "name": name,
            "sector": SECTOR_MAP.get(sector, sector),
            "industry": info.get("industry") or "",
        })
        if i % 25 == 0:
            print(f"  {i}/{len(symbols)}…", flush=True)
        time.sleep(pause)
    return out


def refresh(symbols, force=False):
    """Fetch the symbols not already cached (or all of them) and save."""
    cache = _load_cache()
    known = set(cache["stem"])
    want = [s for s in symbols if force or file_stem(s) not in known]
    if not want:
        print(f"meta: nothing to fetch, {len(cache)} names cached")
        return cache
    print(f"meta: fetching {len(want)} names from Yahoo")
    rows = fetch(want)
    if rows:
        cache = pd.concat([cache[~cache["stem"].isin({r['stem'] for r in rows})],
                           pd.DataFrame(rows)], ignore_index=True)
        cache = cache.sort_values("stem")[COLUMNS]
        DATA_DIR.mkdir(exist_ok=True)
        cache.to_csv(META_FILE, index=False)
    print(f"meta: {len(rows)} fetched, {len(cache)} cached -> {META_FILE}")
    return cache


def load_meta() -> pd.DataFrame:
    """stem -> name / sector / industry, index members first.

    The S&P table wins where both have a name: it is the source the sector counts
    are defined against, and mixing two taxonomies on the same axis would split
    one sector into two bars.
    """
    gics = load_ticker_meta()
    gics.index = [file_stem(t) for t in gics.index]
    extra = _load_cache().set_index("stem")[["name", "sector", "industry"]]
    extra = extra[~extra.index.isin(gics.index)]
    return pd.concat([gics[["name", "sector", "industry"]], extra])


if __name__ == "__main__":
    from analysis.universe import scan_universe
    from ingestion.baskets import BASKETS
    from ingestion.recos import reco_tickers
    # every real symbol the repo tracks, in its yfinance form (the stems can't be
    # queried — '6674.T' is fetchable, 'JP6674' is not)
    syms = sorted({t for ts in BASKETS.values() for t in ts} | set(reco_tickers())
                  | set(load_ticker_meta().index))
    have = set(scan_universe())
    syms = [s for s in syms if file_stem(s) in have]
    refresh(syms, force="--all" in sys.argv)
    m = load_meta()
    print(f"{len(m)} labelled, {(m['sector'] == '').sum()} without a sector")
