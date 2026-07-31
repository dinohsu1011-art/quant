"""Cache historical earnings timestamps for equities exposed in Theme Returns.

Yahoo's earnings calendar currently supplies roughly six years of quarterly
events, including the local-market timestamp. The timestamp matters: a result
released after the close belongs to the next trading session's price move.

The cache is deliberately local, like the parquet price database. A normal
refresh only revisits symbols whose cache is at least one week old; use
``--force`` for a complete backfill.

    python -m ingestion.earnings
    python -m ingestion.earnings --force --workers 6
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import DATA_DIR
from export.themes import SINGLE_NAMES, pe_tickers
from ingestion.baskets import BASKETS
from ingestion.recos import reco_tickers

CACHE_FILE = DATA_DIR / "earnings_dates.json"
SPECIAL_SYMBOLS = {
    "kr005930": "005930.KS",
    "kr000660": "000660.KS",
    "siemens_energy": "ENR.DE",
}


def theme_equities() -> dict[str, str]:
    """Theme Returns series id -> yfinance symbol."""
    ids = (
        {ticker for members in BASKETS.values() for ticker in members}
        | set(reco_tickers())
        | set(pe_tickers())
        | set(SINGLE_NAMES)
    )
    return {series_id: SPECIAL_SYMBOLS.get(series_id, series_id) for series_id in sorted(ids)}


def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {"meta": {"source": "yfinance earnings calendar"}, "series": {}}
    return json.loads(CACHE_FILE.read_text())


def save_cache(payload: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload["meta"]["updated"] = datetime.now().isoformat(timespec="seconds")
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    tmp.replace(CACHE_FILE)


def fetch_one(series_id: str, symbol: str) -> tuple[str, dict]:
    try:
        frame = yf.Ticker(symbol).get_earnings_dates(limit=100)
    except KeyError:
        # Yahoo returns a malformed empty table for a handful of thinly covered
        # names. Cache the absence so the daily pipeline does not retry forever.
        frame = None
    events = []
    if frame is not None and not frame.empty:
        frame = frame.sort_index()
        for stamp, row in frame.iterrows():
            ts = pd.Timestamp(stamp)
            reported = bool(pd.notna(row.get("Reported EPS")))
            events.append({
                "ts": ts.isoformat(),
                # Yahoo sometimes stamps a nominal 15:00 for an after-close
                # release. Noon is the safe boundary between pre-market and
                # post-close reaction sessions.
                "after_close": bool(ts.hour >= 12),
                "reported": reported,
            })
    return series_id, {
        "symbol": symbol,
        "checked": date.today().isoformat(),
        "events": events,
    }


def refresh(force=False, workers=6, stale_days=7, only=None) -> dict:
    payload = load_cache()
    payload.setdefault("meta", {"source": "yfinance earnings calendar"})
    payload.setdefault("series", {})
    universe = theme_equities()
    if only:
        wanted = {x.upper() for x in only}
        universe = {
            sid: symbol for sid, symbol in universe.items()
            if sid.upper() in wanted or symbol.upper() in wanted
        }
    cutoff = date.today() - timedelta(days=stale_days)
    queue = []
    for sid, symbol in universe.items():
        cached = payload["series"].get(sid, {})
        checked = cached.get("checked")
        stale = not checked or date.fromisoformat(checked) <= cutoff
        if force or stale:
            queue.append((sid, symbol))
    print(f"earnings: {len(universe)} equities, {len(queue)} to refresh", flush=True)
    if not queue:
        return payload

    ok = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_one, sid, symbol): (sid, symbol) for sid, symbol in queue}
        for future in as_completed(futures):
            sid, symbol = futures[future]
            try:
                key, record = future.result()
                payload["series"][key] = record
                ok += 1
            except Exception as exc:
                failed += 1
                print(f"  {symbol}: {type(exc).__name__}: {exc}", flush=True)
            if (ok + failed) % 25 == 0:
                save_cache(payload)
                print(f"  {ok + failed}/{len(queue)} · {ok} cached · {failed} failed", flush=True)
    save_cache(payload)
    print(f"earnings: {ok} refreshed, {failed} failed -> {CACHE_FILE}", flush=True)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument("--tickers", nargs="*")
    args = parser.parse_args()
    refresh(args.force, args.workers, args.stale_days, args.tickers)


if __name__ == "__main__":
    main()
