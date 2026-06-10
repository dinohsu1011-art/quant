"""
Fetch the current S&P 500 constituent list from Wikipedia.
Saves to data/tickers.csv for reproducibility.
"""
import io
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TICKERS_FILE


def fetch_sp500_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    # Wikipedia 403s requests lacking a browser-like User-Agent, so fetch the
    # HTML ourselves (requests is already a dependency) before handing to pandas.
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0]
    # Column is "Symbol" — clean up any dots (e.g. BRK.B → BRK-B for yfinance)
    tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
    return tickers


def save_tickers(tickers: list[str]) -> None:
    pd.DataFrame({"ticker": tickers}).to_csv(TICKERS_FILE, index=False)
    print(f"Saved {len(tickers)} tickers to {TICKERS_FILE}")


def load_tickers() -> list[str]:
    if not TICKERS_FILE.exists():
        print("tickers.csv not found, fetching from Wikipedia...")
        tickers = fetch_sp500_tickers()
        save_tickers(tickers)
        return tickers
    return pd.read_csv(TICKERS_FILE)["ticker"].tolist()


if __name__ == "__main__":
    tickers = fetch_sp500_tickers()
    save_tickers(tickers)
    print(tickers[:10])
