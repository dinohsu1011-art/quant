"""
Volume anomaly study.

Identifies days where volume < threshold * 50-day rolling average.
Measures forward 5/10/20-day returns from those days.

Run:
    python -m analysis.volume               # SPY only
    python -m analysis.volume SPY QQQ       # specific tickers
    python -m analysis.volume --all         # all tickers
"""
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from analysis.stats import summarize

VOLUME_THRESHOLD = 0.50   # flag days below 50% of 50-day avg
ROLLING_WINDOW = 50
FORWARD_WINDOWS = [5, 10, 20]


def load_volume_data(ticker: str, conn) -> pd.DataFrame:
    sql = f"""
        SELECT date, close, volume
        FROM {ticker.lower().replace('-','_')}
        ORDER BY date
    """
    return conn.execute(sql).df()


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values("date").reset_index(drop=True)
    df["vol_ma50"] = df["volume"].rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma50"]
    df["low_volume"] = df["vol_ratio"] < VOLUME_THRESHOLD

    for fw in FORWARD_WINDOWS:
        df[f"fwd_{fw}d"] = df["close"].pct_change(fw).shift(-fw)

    return df.dropna(subset=["vol_ma50"])


def analyze_volume(tickers: list[str], conn=None) -> pd.DataFrame:
    if conn is None:
        conn = db.connect()

    all_rows = []
    for ticker in tickers:
        try:
            df = load_volume_data(ticker, conn)
            df = compute_signals(df)
            all_rows.append(df.assign(ticker=ticker))
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")

    if not all_rows:
        return pd.DataFrame()

    combined = pd.concat(all_rows, ignore_index=True)
    low_vol = combined[combined["low_volume"]]
    all_days = combined

    results = []
    for fw in FORWARD_WINDOWS:
        col = f"fwd_{fw}d"

        lv_returns = low_vol[col].dropna().values
        all_returns = all_days[col].dropna().values

        s = summarize(lv_returns, label=f"low_volume_fwd{fw}d")
        s["episodes"] = len(lv_returns)
        s["baseline_win_rate"] = round((all_returns > 0).mean(), 4)
        s["baseline_mean_pct"] = round(all_returns.mean() * 100, 4)
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

    print(f"Running volume study on {len(tickers)} ticker(s)...\n")
    results = analyze_volume(tickers, conn)
    if not results.empty:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 140)
        print(results.to_string(index=False))
