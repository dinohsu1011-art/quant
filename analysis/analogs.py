"""
Analog engine: match a target's trailing weekly price path against every
historical window in the library (all tickers, all eras), rank by shape
similarity, and project the top matches' subsequent paths forward in dollar
space — an objective version of the "analog model" overlay
(current chart vs. dotcom-QQQ / 2017 / COVID-rally / silver etc.).

Canonical example — top analogs for QQQ's last 2 years, projected 1 year out:

    import db
    from analysis.analogs import analogs, render, chart
    conn = db.connect()
    res = analogs(conn, "qqq", window=104, horizon=52, topk=15)
    print(render(res))
    chart(conn, "qqq", res, out="~/Desktop/analogs_qqq.png")

Notes
-----
* Matching happens on LOG price paths (Pearson correlation), so shape
  similarity is percent-scaled and era/price-level invariant. Projection is
  applied in linear dollar space: each match's forward cumulative % return is
  scaled onto the target's last close.
* Windows are weekly (W-FRI last close) on split/dividend-adjusted closes
  (the ingest uses auto_adjust=True). Weekly kills daily noise and matches
  the long-term-model timeframe.
* A match must have `horizon` weeks of subsequent history (we need its
  future), and target-ticker windows overlapping the target's own trailing
  window are excluded. Overlapping windows of the same ticker are deduped
  greedily (best correlation wins) so the top-k spans distinct episodes.
* This is a shape matcher, not statistical inference — overlapping windows of
  correlated series make classical significance meaningless. The output is a
  scenario fan, read it as such.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

# Non-equity / macro views that make poor price analogs for a stock chart
# (rates, vol indices). Metals and oil are kept — silver was cited as
# "a great analog" and commodity manias rhyme with stock manias.
DEFAULT_EXCLUDE = {"vix"}


@dataclass
class AnalogResult:
    symbol: str
    window: int              # match window, weeks
    horizon: int             # projection horizon, weeks
    last_date: pd.Timestamp  # end of target window
    last_close: float
    target: pd.Series        # weekly closes of target window (date-indexed)
    matches: pd.DataFrame    # ticker, start, end, corr, fwd stats
    paths: pd.DataFrame      # dollar projection paths, one column per match
    fan: pd.DataFrame = field(default=None)  # median / p25 / p75 of paths


def weekly_closes(conn, view: str) -> pd.Series:
    """Weekly (Friday) closes for a DuckDB view, date-indexed."""
    df = conn.execute(
        f'SELECT date, close FROM "{view}" ORDER BY date'
    ).df()
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["close"].resample("W-FRI").last().dropna()
    return s


def _zscore_rows(m: np.ndarray) -> np.ndarray:
    """Z-score each row; rows with ~zero variance become NaN (dropped later)."""
    mu = m.mean(axis=1, keepdims=True)
    sd = m.std(axis=1, keepdims=True)
    sd[sd < 1e-12] = np.nan
    return (m - mu) / sd


def _sliding(a: np.ndarray, w: int) -> np.ndarray:
    """All length-w windows of a 1-D array as a (n-w+1, w) view."""
    return np.lib.stride_tricks.sliding_window_view(a, w)


def analogs(conn, symbol: str, window: int = 104, horizon: int = 52,
            topk: int = 15, stride: int = 2, min_weeks: int = 260,
            exclude=DEFAULT_EXCLUDE, tickers=None) -> AnalogResult:
    """Rank historical analogs for `symbol`'s trailing `window` weeks.

    stride     candidate window spacing in weeks (2 = every other week)
    min_weeks  skip series with less weekly history than this
    tickers    optional iterable of view names to restrict the library
    """
    view = symbol.strip().lstrip("^").lower().replace("-", "_").replace(".", "_")
    tgt_weekly = weekly_closes(conn, view)
    if len(tgt_weekly) < window:
        raise ValueError(f"{symbol}: only {len(tgt_weekly)} weeks, need {window}")
    target = tgt_weekly.iloc[-window:]
    tgt_z = _zscore_rows(np.log(target.values)[None, :])[0]
    tgt_start = target.index[0]

    if tickers is None:
        tickers = [r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_type='VIEW'"
        ).fetchall()]
    tickers = [t for t in tickers if t not in exclude]

    rows = []           # (ticker, end_idx, corr)
    series_cache = {}   # ticker -> weekly Series (kept for projection step)
    for tkr in tickers:
        try:
            s = weekly_closes(conn, tkr)
        except Exception:
            continue
        if len(s) < max(min_weeks, window + horizon + 1):
            continue
        logp = np.log(s.values)
        wins = _sliding(logp, window)                    # ends at idx window-1 .. n-1
        n_end = len(logp) - 1
        # window end index e must leave `horizon` weeks of future
        ends = np.arange(window - 1, n_end - horizon + 1, stride)
        if len(ends) == 0:
            continue
        wz = _zscore_rows(wins[ends - (window - 1)].astype(np.float64))
        corr = np.nansum(wz * tgt_z, axis=1) / window
        # target's own trailing window can't be its own analog
        if tkr == view:
            end_dates = s.index[ends]
            corr[end_dates >= tgt_start] = np.nan
        keep = ~np.isnan(corr)
        series_cache[tkr] = s
        rows.extend(zip([tkr] * int(keep.sum()), ends[keep], corr[keep]))

    if not rows:
        raise RuntimeError("no candidate windows found")
    cand = pd.DataFrame(rows, columns=["ticker", "end_idx", "corr"])
    cand = cand.sort_values("corr", ascending=False)

    # Greedy dedupe: same ticker, window-ends closer than window/2 → one episode
    chosen = []
    for _, r in cand.iterrows():
        if any(c["ticker"] == r["ticker"] and abs(c["end_idx"] - r["end_idx"]) < window // 2
               for c in chosen):
            continue
        chosen.append(r)
        if len(chosen) >= topk:
            break

    last_close = float(target.iloc[-1])
    last_date = target.index[-1]
    match_rows, path_cols = [], {}
    future_index = pd.date_range(last_date, periods=horizon + 1, freq="W-FRI")
    for r in chosen:
        s = series_cache[r["ticker"]]
        e = int(r["end_idx"])
        fwd = s.values[e:e + horizon + 1] / s.values[e]      # 1.0 .. cum growth
        path = pd.Series(fwd * last_close, index=future_index)
        label = f'{r["ticker"].upper()} {s.index[e].date()}'
        path_cols[label] = path
        match_rows.append({
            "ticker": r["ticker"].upper(),
            "start": s.index[e - window + 1].date(),
            "end": s.index[e].date(),
            "corr": round(float(r["corr"]), 3),
            "fwd_ret": fwd[-1] - 1,
            "fwd_max": fwd.max() - 1,
            "fwd_min": fwd.min() - 1,
        })

    matches = pd.DataFrame(match_rows)
    paths = pd.DataFrame(path_cols)
    fan = pd.DataFrame({
        "median": paths.median(axis=1),
        "p25": paths.quantile(0.25, axis=1),
        "p75": paths.quantile(0.75, axis=1),
    })
    return AnalogResult(symbol=symbol.upper(), window=window, horizon=horizon,
                        last_date=last_date, last_close=last_close,
                        target=target, matches=matches, paths=paths, fan=fan)


def render(res: AnalogResult) -> str:
    """Text table of the ranked analogs."""
    m = res.matches.copy()
    for c in ("fwd_ret", "fwd_max", "fwd_min"):
        m[c] = (m[c] * 100).map("{:+.1f}%".format)
    head = (f"{res.symbol} analogs — {res.window}w window ending {res.last_date.date()}"
            f" (close {res.last_close:,.2f}), {res.horizon}w forward\n")
    return head + m.to_string(index=False)


def chart(conn, symbol: str, res: AnalogResult, out: str,
          history_weeks: int = 260) -> str:
    """Target history + analog projection fan → PNG. Returns the output path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    view = symbol.strip().lstrip("^").lower().replace("-", "_").replace(".", "_")
    hist = weekly_closes(conn, view).iloc[-history_weeks:]

    fig, ax = plt.subplots(figsize=(12, 6.5), facecolor="#fafafa")
    ax.set_facecolor("#fafafa")
    ax.plot(hist.index, hist.values, color="#0a0a0a", lw=1.6, zorder=5,
            label=f"{res.symbol} weekly close")
    for col in res.paths.columns:
        ax.plot(res.paths.index, res.paths[col].values, color="#8a8a8a",
                lw=0.7, alpha=0.45, zorder=2)
    ax.fill_between(res.fan.index, res.fan["p25"], res.fan["p75"],
                    color="#54627f", alpha=0.18, zorder=1, label="p25–p75")
    ax.plot(res.fan.index, res.fan["median"].values, color="#a8532f", lw=2.2,
            zorder=6, label=f"median of top {len(res.paths.columns)} analogs")
    ax.axvline(res.last_date, color="#a2977c", lw=0.8, ls="--", zorder=3)
    ax.set_title(f"{res.symbol} — analog projection fan "
                 f"({res.window}w match, {res.horizon}w forward)",
                 fontsize=13, loc="left")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.grid(alpha=0.25, lw=0.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    out = str(Path(out).expanduser())
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


if __name__ == "__main__":
    import argparse
    import db

    p = argparse.ArgumentParser(description="Historical analog projection")
    p.add_argument("symbol", nargs="?", default="qqq")
    p.add_argument("--window", type=int, default=104)
    p.add_argument("--horizon", type=int, default=52)
    p.add_argument("--topk", type=int, default=15)
    p.add_argument("--stride", type=int, default=2)
    p.add_argument("--chart", default=None, help="PNG output path")
    args = p.parse_args()

    conn = db.connect()
    res = analogs(conn, args.symbol, window=args.window, horizon=args.horizon,
                  topk=args.topk, stride=args.stride)
    print(render(res))
    if args.chart:
        print("chart →", chart(conn, args.symbol, res, args.chart))
