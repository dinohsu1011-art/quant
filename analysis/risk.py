"""Risk appetite — measured on the names that carry risk, not on the index.

Index breadth cannot answer "is the market risk-on". A rotation out of high-beta
into staples, utilities and energy leaves most names above their moving averages,
so breadth reads healthy while risk appetite is falling. On 2026-07-24 the S&P
sat at 66% above its 50-day (68th percentile of five years) while the high-beta
cohort was having its worst month against low-beta in those five years. Both
numbers were right; only one of them was about risk.

So risk is measured here on cohorts, ranked out of the universe itself rather
than hand-picked:

* HIGH BETA vs LOW BETA — equal-weight top-quintile beta over bottom-quintile
  beta. The cleanest read, because beta is what "risk" means mechanically and
  the cohort is rebuilt from the data every day.
* MOMENTUM LEADERS — the top quintile by 6-month return, lagged a month so the
  cohort isn't selected on the window it's scored over. Its breadth against the
  whole index is the rotation tell: negative spread means the index is being
  held up by names that were not leading it.

One caveat this module cannot fix, and which matters: leadership itself rotates.
When defensives have led for six months they enter the momentum cohort, and
"leaders" stops meaning "trendy names". That is why beta is the primary gauge
and momentum is the secondary one.

    python -m analysis.risk
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.universe import load_prices, sp500_members, us_calendar

BETA_WINDOW = 126       # sessions of daily returns behind each beta estimate
MOM_WINDOW = 126        # the 6-month return that defines leadership
MOM_GAP = 21            # ...measured to a month ago, not to today
QUINTILE = 0.20
MA = 50
START = "2008-01-01"    # enough warm-up for a 5-year percentile from 2010


def panel(px, calendar, members):
    """Close prices as one date x name frame, trimmed to the modelled era."""
    idx = calendar[calendar >= pd.Timestamp(START)]
    keep = [s for s in members if s in px]
    return pd.DataFrame({s: px[s]["close"].astype("float64") for s in keep}).reindex(idx)


def _ew(ret, mask):
    """Equal-weight cumulative index of the names a mask selects each day."""
    r = ret.where(mask.shift(1)).mean(axis=1)
    return (1 + r.fillna(0)).cumprod()


def cohorts(C, bench):
    """(beta_ratio, leader_breadth, all_breadth, leader_rel) as daily Series.

    `bench` is the benchmark close aligned to C's index.
    """
    ret = C.pct_change()
    br = bench.pct_change()

    # --- beta, ranked cross-sectionally each day
    cov = ret.rolling(BETA_WINDOW).cov(br)
    var = br.rolling(BETA_WINDOW).var()
    beta = cov.div(var, axis=0)
    bq = beta.rank(axis=1, pct=True)
    hi = _ew(ret, bq >= 1 - QUINTILE)
    lo = _ew(ret, bq <= QUINTILE)
    beta_ratio = hi / lo

    # --- momentum leadership
    mom = C.shift(MOM_GAP) / C.shift(MOM_GAP + MOM_WINDOW) - 1
    mq = mom.rank(axis=1, pct=True)
    lead = mq >= 1 - QUINTILE

    ma = C.rolling(MA).mean()
    above = C > ma
    have = ma.notna()
    lead_breadth = 100 * (above & lead & have).sum(axis=1) / (lead & have).sum(axis=1).replace(0, np.nan)
    all_breadth = 100 * (above & have).sum(axis=1) / have.sum(axis=1).replace(0, np.nan)
    leader_rel = _ew(ret, lead) / bench

    return beta_ratio, lead_breadth, all_breadth, leader_rel


def chg(s, k):
    """k-session change of a level series, or None if there isn't the history."""
    x = s.dropna()
    if len(x) <= k:
        return None
    return float(x.iloc[-1] / x.iloc[-1 - k] - 1)


def risk_panel(px, calendar, members, bench_stem="spy"):
    """Everything the weekend page needs about risk appetite.

    Returns (measures, series) — a list of gauge dicts, and the daily lines
    behind them for charting.
    """
    from analysis.breadth import percentile_of_last

    C = panel(px, calendar, members)
    bench = load_prices([bench_stem])[bench_stem]["close"].astype("float64") \
        .reindex(C.index).ffill()
    beta_ratio, lead_b, all_b, lead_rel = cohorts(C, bench)

    # A ratio's *change* is the risk signal, not its level — the level drifts with
    # the long-run beta premium and would sit at a percentile that means nothing.
    beta_1m = beta_ratio / beta_ratio.shift(21) - 1
    lead_1m = lead_rel / lead_rel.shift(21) - 1
    spread = lead_b - all_b

    measures = [
        {"id": "beta", "label": "High-beta vs low-beta", "unit": "%",
         "value": round(100 * chg(beta_ratio, 21), 1),
         "pct": percentile_of_last(beta_1m, 1260),
         "note": "1 month, equal-weight quintiles",
         "extra": {"1w": chg(beta_ratio, 5), "2w": chg(beta_ratio, 10),
                   "3m": chg(beta_ratio, 63)}},
        {"id": "lead_breadth", "label": "Leaders above 50-day", "unit": "%",
         "value": round(float(lead_b.iloc[-1]), 1),
         "pct": percentile_of_last(lead_b, 1260),
         "note": "top-quintile 6m momentum"},
        {"id": "spread", "label": "Leaders less index breadth", "unit": "pt",
         "value": round(float(spread.iloc[-1]), 1),
         "pct": percentile_of_last(spread, 1260),
         "note": "negative = defensives carrying it"},
        {"id": "lead_rel", "label": "Leaders vs index", "unit": "%",
         "value": round(100 * chg(lead_rel, 21), 1),
         "pct": percentile_of_last(lead_1m, 1260),
         "note": "1 month, equal-weight cohort"},
    ]

    i = C.index
    keep = i >= pd.Timestamp("2010-01-01")
    ser = {
        "dates": [d.strftime("%Y-%m-%d") for d in i[keep]],
        "beta": [None if not np.isfinite(v) else round(float(v), 4)
                 for v in (beta_ratio / beta_ratio[keep].dropna().iloc[0] * 100)[keep]],
        "lead_breadth": [None if pd.isna(v) else round(float(v), 1) for v in lead_b[keep]],
        "all_breadth": [None if pd.isna(v) else round(float(v), 1) for v in all_b[keep]],
    }
    return measures, ser


def main():
    px = load_prices()
    cal, _ = us_calendar(px)
    m, s = risk_panel(px, cal, sp500_members())
    print(f"risk appetite as of {s['dates'][-1]}\n")
    for g in m:
        p = "—" if g["pct"] is None else f"{g['pct']:.0f}th"
        print(f"  {g['label']:<28} {g['value']:>7}{g['unit']:<3} {p:>6} pct   {g['note']}")


if __name__ == "__main__":
    main()
