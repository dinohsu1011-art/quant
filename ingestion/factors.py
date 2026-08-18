"""
Cross-sectional factor buckets over the tracked US universe.

Every US single stock is scored on eight price-only factors at each month end,
ranked against the others scored that day, and split into a top and bottom
decile. Each decile becomes a synthetic parquet — an index level in the price
columns — exactly like ingestion/baskets.py, so the buckets plug into db.py
views, the cube and the themes page with no special handling. A third series per
factor charts the top decile minus the bottom, the long-short spread.

The point is description, not backtesting. These lines answer "what have the
momentum leaders in my universe actually been doing", and the ticker list on a
bucket is a live screen. Read the track record with the caveats in CAVEATS below.

    python -m ingestion.factors          # score, print today's buckets
    python -m ingestion.factors --build  # also write the synthetic parquets
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.universe import load_prices, scan_universe, us_calendar
from config import DAILY_DIR, PRICE_SCALE, SYMBOL_ALIASES
from ingestion.store import SCHEMA

OUT_JSON = Path(__file__).parent.parent / "data" / "factor_buckets.json"

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
YEAR = 252              # sessions in "a year", matching analysis/setups.py
N_NAMES = 20            # names a side, fixed — not a decile, not a quintile. A
                        # percentage slice grows with the universe and lands on a
                        # basket nobody could actually hold; twenty is a book you
                        # can read down in one screen and trade as a list.
MIN_FRAC = 0.75         # of the tracked universe must be scoreable before any
                        # factor starts. See SURVIVORSHIP below — this is what
                        # sets the start date, and it is deliberately strict.
MIN_DOLLAR = 5e6        # median 20-day dollar volume
MIN_PRICE = 1.0
BENCH = "SPY"           # beta is measured against this

# Foreign listings run their own sessions. A cross-sectional rank on a given
# date would compare their fresh close against a US close from the day before
# (or the reverse), so they are scored nowhere. They keep their own rail lines.
FOREIGN = {v for k, v in SYMBOL_ALIASES.items()
           if k.endswith((".T", ".KS", ".DE", ".HE"))}

# SURVIVORSHIP, and why the history is short.
#
# The ticker file is *today's* S&P 500 plus today's themes. Every company that
# went bankrupt, was acquired, or was demoted out of the index is simply absent.
# Run from 1990 the buckets are not merely biased, they are fiction: the 159
# names alive and liquid in 1995 are the 159 oldest survivors of a list drawn in
# 2026, and a momentum decile of guaranteed survivors compounded to six thousand
# times its money. Nobody should read that number.
#
# Requiring 75% of the universe to be scoreable pushes the start into the mid
# 2010s. That does not remove the bias — nothing in this dataset can, because the
# deleted names were never downloaded — but it bounds the visible part of it: at
# the start date at most a quarter of today's names are missing, instead of
# three quarters. It also gives all eight factors one shared start, so their
# lines can actually be compared against each other on the chart.
CAVEATS = [
    "Survivorship: the ticker list is today's S&P 500 plus today's themes, so "
    "companies that went bankrupt or were acquired were never scored. Even over "
    "this window every bucket is flattered, and the bottom decile most of all.",
    "No trading costs. A momentum decile turns over heavily; real money pays for that.",
    "No sector control. A bucket can end up most of the way into one industry.",
    "Equal weight, rebalanced daily inside each month, matching every other basket "
    "here. Measured against simply holding to the next rebalance that convention adds "
    "about 3% over the whole window, so it is not what makes these lines steep.",
]


def _z(x):
    """Winsorised cross-sectional z-score. Bloomberg quotes factor values in
    sigma ('2.9σ'); this is the same statement, and the tails are clipped first
    so one 900% mover doesn't compress everyone else toward zero."""
    lo, hi = np.nanpercentile(x, [1, 99])
    x = np.clip(x, lo, hi)
    mu, sd = np.nanmean(x), np.nanstd(x)
    return (x - mu) / sd if sd > 0 else np.zeros_like(x)


# Each scorer takes the close matrix C (dates x names, numpy), the row index `i`
# of the rebalance date, and returns one raw score per name. Higher is always
# "more of the thing the label says", so no scorer flips a sign: the top bucket
# is read straight off the label.
def s_mom121(C, i, ctx):
    """Twelve-month return skipping the most recent month.

    The last month is dropped because it carries the opposite pattern: over a
    year winners persist, over a few weeks they give some back. Leaving it in
    mixes a slow signal with a fast one pointing the other way, and ranks a
    stock that just gapped on a rumour alongside one that has ground higher all
    year. Dropping it also makes this factor independent of `mom1` below.
    """
    return C[i - 21] / C[i - YEAR] - 1.0


def s_mom12(C, i, ctx):
    """The same twelve months with the recent month left in — shipped so the
    chart can settle whether the skip earns its keep in this universe."""
    return C[i] / C[i - YEAR] - 1.0


def s_mom1(C, i, ctx):
    """Last month's return, raw.

    Deliberately not negated into a 'reversal' score. Named for what it measures,
    the chart then shows whether last month's losers actually bounce — an answer,
    not an assumption baked into the label.
    """
    return C[i] / C[i - 21] - 1.0


def s_offhigh(C, i, ctx):
    """Distance below the highest close of the last year (always <= 0). Where the
    stock is standing right now."""
    return C[i] / np.nanmax(C[i - YEAR + 1:i + 1], axis=0) - 1.0


def s_vol(C, i, ctx):
    """Annualised standard deviation of the last three months of daily returns.
    Three months rather than a year so it reacts while a regime is still on."""
    r = ctx["R"][i - 62:i + 1]
    return np.nanstd(r, axis=0) * np.sqrt(YEAR)


def s_beta(C, i, ctx):
    """Slope of daily returns against SPY over the last year."""
    r = ctx["R"][i - YEAR + 1:i + 1]
    b = ctx["RB"][i - YEAR + 1:i + 1]
    b = b - np.nanmean(b)
    var = np.nansum(b * b)
    if var <= 0:
        return np.full(C.shape[1], np.nan)
    return np.nansum((r - np.nanmean(r, axis=0)) * b[:, None], axis=0) / var


def s_ddepth(C, i, ctx):
    """Worst peak-to-trough fall inside the last year (<= 0; higher = smoother).

    Not the same statement as `offhigh`: that one asks where the price is today,
    this one asks how ugly the year got. A stock can close at its high having
    round-tripped forty percent on the way.
    """
    w = C[i - YEAR + 1:i + 1]
    return np.nanmin(w / np.maximum.accumulate(w, axis=0) - 1.0, axis=0)


def s_trend(C, i, ctx):
    """Average distance above the 20-, 50- and 200-day moving averages."""
    p = C[i]
    return np.nanmean([p / np.nanmean(C[i - n + 1:i + 1], axis=0) - 1.0
                       for n in (20, 50, 200)], axis=0)


# key, rail label, sessions of history required, scorer, chart window.
#
# The window is the span the page jumps to when you click one of these lines. A
# screen is a claim about a stretch of tape: ranking the last month and then
# judging the result over three years asks a different question than the one the
# rank answered. Clicking the bucket should show you the tape it was built from.
FACTORS = [
    ("mom121",  "Momentum 12-1",      YEAR, s_mom121,  "1Y"),
    ("mom12",   "Momentum 12M",       YEAR, s_mom12,   "1Y"),
    ("mom1",    "1-month move",         21, s_mom1,    "1M"),
    ("offhigh", "Off 52-week high",   YEAR, s_offhigh, "1Y"),
    ("vol",     "Volatility",           63, s_vol,     "3M"),
    ("beta",    "Beta vs SPY",        YEAR, s_beta,    "1Y"),
    ("ddepth",  "Drawdown depth",     YEAR, s_ddepth,  "1Y"),
    ("trend",   "Trend stack",         200, s_trend,   "1Y"),
]
# top 20 / bottom 20 / top-minus-bottom, per factor
SIDES = [("hi", "top 20"), ("lo", "bottom 20"), ("ls", "top − bottom")]


def bucket_ids():
    return [f"fac_{k}_{s}" for k, _, _, _, _ in FACTORS for s, _ in SIDES]


def _panel():
    """Wide close / adj_close / dollar-volume frames on the US calendar."""
    stems = [s for s in scan_universe() if s not in FOREIGN]
    px = load_prices(stems + [BENCH], columns=("close", "adj_close", "volume"))
    cal, _ = us_calendar(px)
    names = sorted(s for s in stems if s in px)
    C = pd.DataFrame({n: px[n]["close"] for n in names}).reindex(cal)
    A = pd.DataFrame({n: px[n]["adj_close"] for n in names}).reindex(cal)
    D = pd.DataFrame({n: px[n]["close"] * px[n]["volume"] for n in names}).reindex(cal)
    B = px[BENCH]["close"].reindex(cal)
    return cal, names, C, A, D, B


def build_membership():
    """Score every month end and return (dates, names, C, A, picks, snapshot).

    `picks[key][i] = (hi_idx, lo_idx)` for the rebalance at calendar row i.
    """
    cal, names, C, A, D, B = _panel()
    Cv, Av = C.to_numpy(float), A.to_numpy(float)
    R = np.vstack([np.full((1, Cv.shape[1]), np.nan), Cv[1:] / Cv[:-1] - 1.0])
    RA = np.vstack([np.full((1, Av.shape[1]), np.nan), Av[1:] / Av[:-1] - 1.0])
    RB = B.pct_change().to_numpy(float)
    ctx = {"R": R, "RB": RB}
    Dv = D.rolling(20, min_periods=10).median().to_numpy(float)

    # last trading day of each month, and never the final partial month: a
    # bucket formed today would hold for zero sessions.
    ends = pd.Series(range(len(cal)), index=cal).groupby(
        pd.PeriodIndex(cal, freq="M")).last().to_numpy()
    ends = [int(i) for i in ends if i < len(cal) - 1]

    # a name is scoreable at all only once it has a real first bar
    first = np.array([np.argmax(np.isfinite(Cv[:, j])) for j in range(Cv.shape[1])])

    def eligible(i, need):
        return (first <= i - need) & np.isfinite(Cv[i]) & (Cv[i] >= MIN_PRICE) \
               & np.isfinite(Dv[i]) & (Dv[i] >= MIN_DOLLAR)

    # One shared start for all eight, set by the most demanding lookback. Judging
    # a factor against its neighbours only means something if they were measured
    # over the same stretch of tape.
    need_max = max(n for _, _, n, _, _ in FACTORS)
    floor = MIN_FRAC * len(names)
    ends = [i for i in ends if eligible(i, need_max).sum() >= floor]

    picks = {k: {} for k, _, _, _, _ in FACTORS}
    snapshot = {}
    for key, label, need, fn, win in FACTORS:
        for i in ends:
            live = eligible(i, need)
            # A name that has not listed yet is an all-NaN slice inside the
            # lookback window; numpy says so loudly and the `live` mask on the
            # next line drops it anyway.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                raw = np.asarray(fn(Cv, i, ctx), dtype=float)
            raw = np.where(live & np.isfinite(raw), raw, np.nan)
            ok = np.flatnonzero(np.isfinite(raw))
            z = np.full(len(raw), np.nan)
            z[ok] = _z(raw[ok])
            order = ok[np.argsort(-z[ok], kind="stable")]
            n_cut = min(N_NAMES, len(order) // 2)

            picks[key][i] = (order[:n_cut], order[-n_cut:])
        if picks[key]:
            i = max(picks[key])
            hi, lo = picks[key][i]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                raw = np.asarray(fn(Cv, i, ctx), dtype=float)
            ok = np.flatnonzero(np.isfinite(raw) & (first <= i - need))
            z = np.full(len(raw), np.nan)
            z[ok] = _z(raw[ok])
            snapshot[key] = {
                "label": label, "win": win, "rebalanced": str(cal[i].date()),
                "scored": int(len(ok)), "per_side": int(len(hi)),
                "hi": [[names[j], round(float(z[j]), 2)] for j in hi],
                "lo": [[names[j], round(float(z[j]), 2)] for j in lo],
            }
    return cal, names, R, RA, picks, snapshot


def _levels(cal, R, RA, sel):
    """Chain a rebalance schedule into price- and total-return index levels.

    Members chosen at the close of row i earn the returns of rows i+1..j, where
    j is the next rebalance. Nothing a bucket holds was chosen using a price it
    then earns, so there is no look-ahead. Inside the window the bucket is equal
    weight, rebalanced daily — the same convention as every other basket on the
    site, so the lines are comparable.
    """
    rows = sorted(sel)
    out_p = pd.Series(np.nan, index=cal)
    out_t = pd.Series(np.nan, index=cal)
    for a, b in zip(rows, rows[1:] + [len(cal) - 1]):
        idx = sel[a]
        if b <= a:
            continue
        out_p.iloc[a + 1:b + 1] = np.nanmean(R[a + 1:b + 1][:, idx], axis=1)
        out_t.iloc[a + 1:b + 1] = np.nanmean(RA[a + 1:b + 1][:, idx], axis=1)
    return out_p, out_t


def build_series(cal, R, RA, picks):
    """{bucket id: (price level, total-return level)}, both starting at 100."""
    out = {}
    for key, _, _, _, _ in FACTORS:
        sel = picks[key]
        if not sel:
            continue
        hp, ht = _levels(cal, R, RA, {i: v[0] for i, v in sel.items()})
        lp, lt = _levels(cal, R, RA, {i: v[1] for i, v in sel.items()})
        for side, (rp, rt) in (("hi", (hp, ht)), ("lo", (lp, lt)),
                               ("ls", (hp - lp, ht - lt))):
            r = rp.dropna()
            t = rt.reindex(r.index)
            # A dollar-neutral spread has no dividend basis of its own: both legs
            # are financed against each other, so the toggle leaves it alone.
            if side == "ls":
                t = r
            out[f"fac_{key}_{side}"] = (
                100.0 * (1.0 + r.fillna(0.0)).cumprod(),
                100.0 * (1.0 + t.fillna(0.0)).cumprod(),
            )
    return out


def write_parquets(series):
    for name, (lvl, adj) in series.items():
        a = (lvl * PRICE_SCALE).round().astype("int64").to_numpy()
        b = (adj.reindex(lvl.index) * PRICE_SCALE).round().astype("int64").to_numpy()
        df = pd.DataFrame({
            "date": [d.date() for d in lvl.index],
            "open": a, "high": a, "low": a, "close": a, "adj_close": b,
            "volume": np.zeros(len(lvl), dtype="int64"),
        })
        pq.write_table(pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False),
                       DAILY_DIR / f"{name}.parquet", compression="snappy")
        print(f"  {name:20} {str(lvl.index.min().date())}→  "
              f"{len(lvl):5} rows  last {lvl.iloc[-1]:9.2f}")


def main():
    cal, names, R, RA, picks, snapshot = build_membership()
    series = build_series(cal, R, RA, picks)
    for key, label, _, _, _ in FACTORS:
        s = snapshot.get(key)
        if not s:
            print(f"{label}: not enough history")
            continue
        print(f"\n{label}  ({s['scored']} scored, {s['per_side']}/side, "
              f"rebalanced {s['rebalanced']})")
        print("  top ", ", ".join(f"{t}" for t, _ in s["hi"][:12]))
        print("  bot ", ", ".join(f"{t}" for t, _ in s["lo"][:12]))
    if "--build" in sys.argv:
        print()
        write_parquets(series)
        OUT_JSON.write_text(json.dumps(
            {"rebalance": "month end", "n": N_NAMES, "min_dollar": MIN_DOLLAR,
             "start": str(cal[min(min(v) for v in picks.values() if v)].date()),
             "caveats": CAVEATS, "factors": snapshot},
            indent=1))
        print(f"  wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
