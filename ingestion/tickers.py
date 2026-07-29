"""
Fetch the current S&P 500 constituent list from Wikipedia.
Saves to data/tickers.csv for reproducibility.

The same table carries each name's GICS sector and sub-industry, so it is kept
too. That is the only sector label in the repo, and it is what lets a ranking of
single stocks be rolled up into "which groups are actually leading" rather than
just a list of tickers.
"""
import io
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TICKERS_FILE

COLUMNS = ["ticker", "name", "sector", "industry"]


def fetch_sp500_table() -> pd.DataFrame:
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
    df = pd.read_html(io.StringIO(resp.text))[0]
    out = pd.DataFrame({
        # Column is "Symbol" — clean up any dots (e.g. BRK.B → BRK-B for yfinance)
        "ticker": df["Symbol"].str.replace(".", "-", regex=False),
        "name": df["Security"],
        "sector": df["GICS Sector"],
        "industry": df["GICS Sub-Industry"],
    })
    return out[COLUMNS]


def fetch_sp500_tickers() -> list[str]:
    return fetch_sp500_table()["ticker"].tolist()


def save_tickers(table) -> None:
    """Accepts the full table, or a bare ticker list from an older caller."""
    df = table if isinstance(table, pd.DataFrame) else pd.DataFrame({"ticker": list(table)})
    df.to_csv(TICKERS_FILE, index=False)
    print(f"Saved {len(df)} tickers to {TICKERS_FILE}")


def load_tickers() -> list[str]:
    if not TICKERS_FILE.exists():
        print("tickers.csv not found, fetching from Wikipedia...")
        table = fetch_sp500_table()
        save_tickers(table)
        return table["ticker"].tolist()
    return pd.read_csv(TICKERS_FILE)["ticker"].tolist()


def load_ticker_meta() -> pd.DataFrame:
    """The membership table with sector labels, indexed by ticker.

    Files written before sectors were captured only have a ticker column, so the
    extra columns are filled rather than assumed — a stale csv degrades to blank
    labels instead of raising.
    """
    if not TICKERS_FILE.exists():
        table = fetch_sp500_table()
        save_tickers(table)
    else:
        table = pd.read_csv(TICKERS_FILE)
    for c in COLUMNS:
        if c not in table.columns:
            table[c] = ""
    return table[COLUMNS].fillna("").set_index("ticker")


if __name__ == "__main__":
    table = fetch_sp500_table()
    save_tickers(table)
    print(table.head().to_string(index=False))
