"""
Bulk downloader: fetches daily OHLCV from yfinance and writes to Parquet.

Usage:
    python -m ingestion.fetch            # full S&P 500
    python -m ingestion.fetch SPY QQQ    # specific tickers
"""
import time
import sys
from pathlib import Path

import yfinance as yf
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import START_DATE, BATCH_SIZE, BATCH_DELAY_SECONDS, MAX_RETRIES, DAILY_DIR, file_stem
from ingestion.tickers import load_tickers
from ingestion.store import store_ticker


def fetch_batch(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    """Download a batch of tickers. Returns {ticker: df}."""
    raw = yf.download(
        tickers,
        start=start,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    results = {}
    if len(tickers) == 1:
        # Single ticker returns flat DataFrame
        results[tickers[0]] = raw
    else:
        for ticker in tickers:
            try:
                results[ticker] = raw[ticker].dropna(how="all")
            except KeyError:
                print(f"  [miss] {ticker}: not in response")
    return results


def fetch_with_retry(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch_batch(tickers, start)
        except Exception as e:
            print(f"  [retry {attempt}/{MAX_RETRIES}] batch failed: {e}")
            time.sleep(2 ** attempt)
    print(f"  [fail] batch exhausted retries: {tickers[:3]}...")
    return {}


def run(tickers: list[str], start: str = START_DATE, skip_existing: bool = True) -> None:
    if skip_existing:
        existing = {p.stem for p in DAILY_DIR.glob("*.parquet")}
        to_fetch = [t for t in tickers if file_stem(t) not in existing]
        skipped = len(tickers) - len(to_fetch)
        if skipped:
            print(f"Skipping {skipped} already-downloaded tickers (use skip_existing=False to re-fetch)")
    else:
        to_fetch = tickers

    print(f"Fetching {len(to_fetch)} tickers in batches of {BATCH_SIZE}...")

    ok, fail = 0, 0
    for i in range(0, len(to_fetch), BATCH_SIZE):
        batch = to_fetch[i : i + BATCH_SIZE]
        print(f"Batch {i // BATCH_SIZE + 1}: {batch[0]} … {batch[-1]}")
        data = fetch_with_retry(batch, start)

        for ticker, df in data.items():
            if df.empty:
                print(f"  [empty] {ticker}")
                fail += 1
                continue
            path = store_ticker(df, ticker)
            if path:
                ok += 1
            else:
                fail += 1

        if i + BATCH_SIZE < len(to_fetch):
            time.sleep(BATCH_DELAY_SECONDS)

    print(f"\nDone. {ok} saved, {fail} failed.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        tickers = sys.argv[1:]
    else:
        tickers = load_tickers()
    run(tickers)
