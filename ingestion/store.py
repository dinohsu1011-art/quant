"""
Normalize raw yfinance DataFrames and write to Parquet with int64 prices.

With auto_adjust=True, yfinance returns (ticker, column) MultiIndex and
no separate Adj Close — Close is already adjusted. We store it as both
close and adj_close for schema consistency.
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DAILY_DIR, PRICE_SCALE, DATA_THROUGH_DATE, file_stem

SCHEMA = pa.schema([
    ("date", pa.date32()),
    ("open", pa.int64()),
    ("high", pa.int64()),
    ("low", pa.int64()),
    ("close", pa.int64()),
    ("adj_close", pa.int64()),
    ("volume", pa.int64()),
])

PRICE_COLS = ["open", "high", "low", "close", "adj_close"]
MARKET_SESSIONS = {
    ".T": ("Asia/Tokyo", (15, 35)),
    ".KS": ("Asia/Seoul", (15, 35)),
}


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns from yfinance group_by='ticker' response."""
    if not isinstance(df.columns, pd.MultiIndex):
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        return df
    # MultiIndex is (ticker, PriceField) e.g. ("SPY", "Open")
    # Take level 1 (the price field name)
    df.columns = [c[1].lower().replace(" ", "_") for c in df.columns]
    return df


def normalize(
    df: pd.DataFrame,
    ticker: str,
    now_utc: datetime | None = None,
) -> pd.DataFrame | None:
    """Clean and convert a raw yfinance DataFrame to int64 prices."""
    df = df.copy()
    df = _flatten_columns(df)

    # With auto_adjust=True there is no "adj_close" — clone "close"
    if "adj_close" not in df.columns and "close" in df.columns:
        df["adj_close"] = df["close"]

    # Drop rows missing any price; volume can be absent for indices on old
    # dates, so fill rather than drop (losing 1987-era index rows would break
    # historical event studies).
    price_required = ["open", "high", "low", "close", "adj_close"]
    df = df.dropna(subset=price_required)
    df["volume"] = df["volume"].fillna(0)

    if df.empty:
        print(f"  [skip] {ticker}: no valid rows after dropping nulls")
        return None

    # Validate prices are positive
    for col in PRICE_COLS:
        if (df[col] <= 0).any():
            bad = (df[col] <= 0).sum()
            print(f"  [warn] {ticker}: {bad} non-positive {col} values — dropping those rows")
            df = df[df[col] > 0]

    # Repair inconsistent vendor bars (e.g. GC=F 2009-11-23 has high<low): clamp
    # high/low to the envelope of the bar's own prices. No-op for valid bars.
    inverted = int((df["high"] < df["low"]).sum())
    if inverted:
        print(f"  [warn] {ticker}: {inverted} inverted high/low bars — clamped to bar envelope")
    ohlc = df[["open", "high", "low", "close"]]
    df["high"], df["low"] = ohlc.max(axis=1), ohlc.min(axis=1)

    # Sort and reset index to get date as a column
    df = df.sort_index()
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # No exchange in this universe holds a Saturday or Sunday session, but Yahoo
    # stamps the Sunday-evening open of a continuous futures contract (GC=F and
    # friends) as a Sunday bar. Four such bars were enough to stretch the shared
    # calendar a weekend past the last equity close, so the site reported itself
    # as of a Sunday and the chart's right edge was two empty days.
    wd = pd.to_datetime(df["date"]).dt.dayofweek
    if (wd >= 5).any():
        df = df[wd < 5]

    # Reproducible historical refreshes may set an inclusive market-data cutoff.
    if DATA_THROUGH_DATE is not None:
        df = df[df["date"] <= DATA_THROUGH_DATE]

    # Drop a same-day partial bar using the listing exchange's clock. Applying
    # New York time to every symbol discards completed Tokyo/Seoul sessions
    # while the US market is still open.
    zone, close = ("America/New_York", (16, 5))
    for suffix, session in MARKET_SESSIONS.items():
        if ticker.endswith(suffix):
            zone, close = session
            break
    clock = (now_utc or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone))
    if (clock.hour, clock.minute) < close:
        df = df[df["date"] < clock.date()]
    else:
        df = df[df["date"] <= clock.date()]

    # Convert prices to int64
    for col in PRICE_COLS:
        df[col] = (df[col] * PRICE_SCALE).round().astype("int64")

    df["volume"] = df["volume"].astype("int64")

    return df[["date", "open", "high", "low", "close", "adj_close", "volume"]]


def write_parquet(df: pd.DataFrame, ticker: str) -> Path:
    path = DAILY_DIR / f"{file_stem(ticker)}.parquet"
    table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    pq.write_table(table, path, compression="snappy")
    return path


def store_ticker(df: pd.DataFrame, ticker: str) -> Path | None:
    normalized = normalize(df, ticker)
    if normalized is None:
        return None
    path = write_parquet(normalized, ticker)
    return path
