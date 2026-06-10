"""
Overnight gap study.

Gap = (open - prev_close) / prev_close
Fill = gap-up day where low < prev_close (or gap-down where high > prev_close)
OTC  = (close - open) / open  (open-to-close return)

Run:
    python -m analysis.gaps               # SPY only
    python -m analysis.gaps SPY QQQ AAPL  # specific tickers
    python -m analysis.gaps --all         # all tickers in data/daily/
"""
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from analysis.stats import summarize

# Gap size buckets (as decimals)
BUCKETS = [
    ("large_down",  float("-inf"), -0.03),
    ("mid_down",    -0.03,         -0.01),
    ("small_down",  -0.01,         -0.005),
    ("small_up",     0.005,         0.01),
    ("mid_up",       0.01,          0.03),
    ("large_up",     0.03,          float("inf")),
]


def load_gaps(ticker: str, conn) -> pd.DataFrame:
    sql = f"""
        SELECT
            date,
            open,
            high,
            low,
            close,
            LAG(close) OVER (ORDER BY date) AS prev_close
        FROM {ticker.lower().replace('-','_')}
        ORDER BY date
    """
    df = conn.execute(sql).df()
    df = df.dropna(subset=["prev_close"])

    df["gap_pct"] = (df["open"] - df["prev_close"]) / df["prev_close"]
    df["otc_return"] = (df["close"] - df["open"]) / df["open"]
    df["next_day_return"] = df["close"].pct_change().shift(-1)

    # Fill detection
    df["gap_filled"] = np.where(
        df["gap_pct"] > 0,
        df["low"] < df["prev_close"],    # up gap filled if price dipped back
        df["high"] > df["prev_close"],   # down gap filled if price bounced back
    )
    return df


def analyze_gaps(tickers: list[str], conn=None) -> pd.DataFrame:
    if conn is None:
        conn = db.connect()

    all_rows = []
    for ticker in tickers:
        try:
            df = load_gaps(ticker, conn)
            all_rows.append(df.assign(ticker=ticker))
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")

    if not all_rows:
        print("No data loaded.")
        return pd.DataFrame()

    combined = pd.concat(all_rows, ignore_index=True)
    # Exclude near-zero gaps (noise / no gap days)
    gapped = combined[combined["gap_pct"].abs() >= 0.005].copy()

    results = []
    for name, lo, hi in BUCKETS:
        mask = (gapped["gap_pct"] > lo) & (gapped["gap_pct"] <= hi)
        bucket = gapped[mask]
        if len(bucket) < 10:
            continue
        otc = bucket["otc_return"].dropna().values
        s = summarize(otc, label=name)
        s["fill_rate"] = round(bucket["gap_filled"].mean(), 4)
        s["mean_gap_pct"] = round(bucket["gap_pct"].mean() * 100, 3)
        results.append(s)

    return pd.DataFrame(results)


if __name__ == "__main__":
    args = sys.argv[1:]
    conn = db.connect()

    if "--all" in args:
        from config import DAILY_DIR
        tickers = [p.stem for p in sorted(DAILY_DIR.glob("*.parquet"))]
    elif args:
        tickers = args
    else:
        tickers = ["SPY"]

    print(f"Running gap study on {len(tickers)} ticker(s)...\n")
    results = analyze_gaps(tickers, conn)
    if not results.empty:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 120)
        print(results.to_string(index=False))
