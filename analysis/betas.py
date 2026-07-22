"""
Build a local beta database from daily price parquets.

Default output:
  data/betas/stock_betas.parquet
  data/betas/stock_betas.csv

Beta definition:
  covariance(stock daily close-to-close returns, benchmark returns)
  divided by variance(benchmark returns)

Usage:
  ./.venv/bin/python -m analysis.betas
  ./.venv/bin/python -m analysis.betas --ticker RDDT
  ./.venv/bin/python -m analysis.betas --benchmark GSPC --windows ytd,1y,2y,full
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DAILY_DIR, DATA_DIR, PRICE_SCALE


OUT_DIR = DATA_DIR / "betas"
DEFAULT_WINDOWS = ["ytd", "1y", "2y", "3y", "5y", "full"]
TRADING_DAYS = {
    "1y": 252,
    "2y": 504,
    "3y": 756,
    "5y": 1260,
}


@dataclass(frozen=True)
class ReturnSeries:
    ticker: str
    returns: pd.Series
    first_price_date: pd.Timestamp
    last_price_date: pd.Timestamp


def view_name(stem: str) -> str:
    return stem.lower().replace("-", "_").replace("^", "")


def read_returns(path: Path) -> ReturnSeries:
    df = pd.read_parquet(path, columns=["date", "close"]).sort_values("date")
    df["date"] = pd.to_datetime(df["date"])
    close = df["close"].astype("float64") / PRICE_SCALE
    ret = close.pct_change()
    ret.index = df["date"]
    ret = ret.dropna()
    return ReturnSeries(
        ticker=path.stem,
        returns=ret,
        first_price_date=df["date"].iloc[0],
        last_price_date=df["date"].iloc[-1],
    )


def windowed_sample(stock: pd.Series, bench: pd.Series, window: str) -> pd.DataFrame:
    sample = pd.concat({"stock_ret": stock, "benchmark_ret": bench}, axis=1, sort=False).dropna()
    if sample.empty:
        return sample
    if window == "full":
        return sample
    if window == "ytd":
        last_date = sample.index.max()
        start = pd.Timestamp(year=last_date.year, month=1, day=1)
        return sample[sample.index >= start]
    if window in TRADING_DAYS:
        return sample.tail(TRADING_DAYS[window])
    raise ValueError(f"unknown window: {window}")


def calc_beta_row(
    ticker: str,
    window: str,
    sample: pd.DataFrame,
    first_price_date: pd.Timestamp,
    last_price_date: pd.Timestamp,
    benchmark: str,
    min_obs: int,
) -> dict[str, object]:
    if len(sample) < min_obs:
        beta = alpha_daily = corr = r2 = np.nan
        stock_vol = bench_vol = stock_return = bench_return = np.nan
    else:
        stock = sample["stock_ret"].astype("float64")
        bench = sample["benchmark_ret"].astype("float64")
        bench_var = float(np.var(bench, ddof=1))
        beta = float(np.cov(stock, bench, ddof=1)[0, 1] / bench_var) if bench_var > 0 else np.nan
        alpha_daily = float(stock.mean() - beta * bench.mean()) if math.isfinite(beta) else np.nan
        corr = float(stock.corr(bench))
        r2 = corr * corr if math.isfinite(corr) else np.nan
        stock_vol = float(stock.std(ddof=1) * math.sqrt(252))
        bench_vol = float(bench.std(ddof=1) * math.sqrt(252))
        stock_return = float((1 + stock).prod() - 1)
        bench_return = float((1 + bench).prod() - 1)

    return {
        "ticker": ticker,
        "view": view_name(ticker),
        "benchmark": benchmark,
        "benchmark_view": view_name(benchmark),
        "window": window,
        "n_obs": int(len(sample)),
        "sample_start": sample.index.min().date().isoformat() if len(sample) else None,
        "sample_end": sample.index.max().date().isoformat() if len(sample) else None,
        "first_price_date": first_price_date.date().isoformat(),
        "last_price_date": last_price_date.date().isoformat(),
        "beta": beta,
        "alpha_daily": alpha_daily,
        "corr": corr,
        "r2": r2,
        "stock_vol_ann": stock_vol,
        "benchmark_vol_ann": bench_vol,
        "stock_return": stock_return,
        "benchmark_return": bench_return,
    }


def build_beta_database(
    benchmark: str = "GSPC",
    tickers: list[str] | None = None,
    windows: list[str] | None = None,
    min_obs: int = 60,
) -> pd.DataFrame:
    windows = windows or DEFAULT_WINDOWS
    benchmark_path = DAILY_DIR / f"{benchmark}.parquet"
    if not benchmark_path.exists():
        raise FileNotFoundError(f"benchmark parquet missing: {benchmark_path}")
    bench = read_returns(benchmark_path)

    wanted = {t.upper() for t in tickers} if tickers else None
    rows = []
    for path in sorted(DAILY_DIR.glob("*.parquet")):
        if path.stem == benchmark:
            continue
        if wanted is not None and path.stem.upper() not in wanted and view_name(path.stem).upper() not in wanted:
            continue
        try:
            stock = read_returns(path)
        except Exception as exc:
            print(f"[skip] {path.stem}: {exc}")
            continue
        for window in windows:
            sample = windowed_sample(stock.returns, bench.returns, window)
            rows.append(
                calc_beta_row(
                    ticker=stock.ticker,
                    window=window,
                    sample=sample,
                    first_price_date=stock.first_price_date,
                    last_price_date=stock.last_price_date,
                    benchmark=benchmark,
                    min_obs=min_obs,
                )
            )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["ticker", "window"]).reset_index(drop=True)
    return df


def write_outputs(df: pd.DataFrame, basename: str = "stock_betas") -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUT_DIR / f"{basename}.parquet"
    csv_path = OUT_DIR / f"{basename}.csv"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    return parquet_path, csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build stock beta database versus a benchmark.")
    parser.add_argument("--benchmark", default="GSPC", help="Benchmark parquet stem, default GSPC (^GSPC).")
    parser.add_argument("--ticker", action="append", help="Limit to one ticker. Can be passed multiple times.")
    parser.add_argument("--windows", default=",".join(DEFAULT_WINDOWS), help="Comma-separated windows: ytd,1y,2y,3y,5y,full.")
    parser.add_argument("--min-obs", type=int, default=60, help="Minimum overlapping return observations required.")
    parser.add_argument("--basename", default="stock_betas", help="Output basename under data/betas/.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    windows = [w.strip().lower() for w in args.windows.split(",") if w.strip()]
    df = build_beta_database(
        benchmark=args.benchmark,
        tickers=args.ticker,
        windows=windows,
        min_obs=args.min_obs,
    )
    parquet_path, csv_path = write_outputs(df, basename=args.basename)
    print(f"wrote {len(df):,} rows")
    print(parquet_path)
    print(csv_path)

    if args.ticker and not df.empty:
        cols = ["ticker", "window", "n_obs", "sample_start", "sample_end", "beta", "corr", "r2", "stock_return", "benchmark_return"]
        print(df[cols].to_string(index=False, formatters={
            "beta": "{:.4f}".format,
            "corr": "{:.4f}".format,
            "r2": "{:.4f}".format,
            "stock_return": lambda x: "" if pd.isna(x) else f"{x:.2%}",
            "benchmark_return": lambda x: "" if pd.isna(x) else f"{x:.2%}",
        }))


if __name__ == "__main__":
    main()
