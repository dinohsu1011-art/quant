"""The two weekend scans: high volume edge, and high tight flags.

Each scan is defined once, as a boolean mask over a ticker's whole history, and
read two ways — the last few bars give this weekend's list, the full mask gives
the count through time. Defining "today's hits" separately from "how often this
fires" is how the two quietly drift apart, so they share one definition here.

Design notes, each of which the output depends on:

* The volume scan runs over the trailing WEEK, not the last bar. Measured on the
  current 628-name universe, a 252-day volume high fires on 0.51% of
  name-sessions — about three a day, so a one-bar scan is empty most Saturdays
  and a five-bar scan returns a reviewable list.
* Volume in this data is split-adjusted (verified on NVDA's 2024 10-for-1: the
  pre-split bars carry actual shares x10 against the adjusted close), so raw
  share counts compare cleanly across a split and need no normalisation.
* A high tight flag requires the run's peak to be within 5% of the 52-week high.
  Without that, the scan returns names doubling off a crash low, which is the
  opposite setup. It cut the match list from 14 to 1 on the S&P universe.
* On a universe with no small caps, the flag scan is a market-state gauge, not a
  screen. The COUNT is informative (0 through the 2022 bear, 12 in June 2026);
  the NAMES are large caps that happen to fit the geometry.

    python -m analysis.setups            # this week's hits on the live universe
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.universe import load_prices, scan_universe, us_calendar

# --- volume edge ------------------------------------------------------------
VOL_YEAR = 252          # sessions in the "in a year" window
VOL_MIN_BARS = 60       # don't call it a high until there's something to top
VOL_MIN_DOLLAR = 10e6   # a volume high in an untraded name is not an edge
VOL_WINDOW = 5          # sessions of the week just closed

# --- high tight flag --------------------------------------------------------
HTF_RUN = 40            # sessions the run may take (~8 weeks)
HTF_GAIN = 1.00         # ...to double
HTF_HOLDS = range(10, 36)   # flag length, in sessions
HTF_PULL = 0.25         # deepest the flag may retrace off the peak
HTF_PEAK_AT_HIGH = 0.05  # the run must top within 5% of the 52-week high
HTF_STILL_UP = 0.15     # ...and today must still be within 15% of it


def volume_masks(d):
    """(hv_year, hv_ever, rvol, dollar) aligned to a ticker's own bars."""
    v = d["volume"].astype("float64")
    c = d["close"].astype("float64")
    yr = v.rolling(VOL_YEAR, min_periods=VOL_MIN_BARS).max()
    hv_year = (v >= yr) & v.gt(0)
    hv_ever = (v >= v.expanding(min_periods=VOL_MIN_BARS).max()) & v.gt(0)
    rvol = v / v.rolling(51, min_periods=20).median().shift(1)
    return hv_year, hv_ever, rvol, v * c


def flag_mask(d):
    """Boolean Series: is this bar sitting in a high tight flag?

    Vectorised over every flag length at once, so the same call answers "is one
    here today" and "how many were there on any past date".
    """
    c = d["close"].astype("float64")
    v = d["volume"].astype("float64")
    n = len(c)
    out = pd.Series(False, index=c.index)
    detail = pd.Series(np.nan, index=c.index, dtype="float64")   # winning gain
    hold_of = pd.Series(np.nan, index=c.index, dtype="float64")
    if n < VOL_YEAR + HTF_RUN:
        return out, detail, hold_of
    hi52 = c.rolling(VOL_YEAR, min_periods=VOL_YEAR).max()
    base_run = c.rolling(HTF_RUN, min_periods=HTF_RUN).min()
    vol_run = v.rolling(HTF_RUN, min_periods=HTF_RUN).mean()
    still_up = c >= hi52 * (1 - HTF_STILL_UP)
    for h in HTF_HOLDS:
        peak = c.shift(h)                       # last close of the run
        base = base_run.shift(h)                # low of the 40 sessions into it
        gain = peak / base - 1
        pull = 1 - c.rolling(h, min_periods=h).min() / peak
        peak_at_high = peak >= hi52.shift(h) * (1 - HTF_PEAK_AT_HIGH)
        m = (gain >= HTF_GAIN) & (pull <= HTF_PULL) & peak_at_high & still_up
        m = m.fillna(False)
        # keep the biggest run when several flag lengths fit the same bar
        better = m & (detail.isna() | (gain > detail))
        detail = detail.where(~better, gain)
        hold_of = hold_of.where(~better, h)
        out |= m
    return out, detail, hold_of


def flag_volratio(d, h):
    """Average flag volume over average run volume — under 1.0 is the dry-up."""
    v = d["volume"].astype("float64").values
    if len(v) < HTF_RUN + h:
        return np.nan
    run = v[-(h + HTF_RUN):-h].mean()
    return float(v[-h:].mean() / run) if run else np.nan


def volume_edge(px, window=VOL_WINDOW, min_dollar=VOL_MIN_DOLLAR):
    """Names printing a volume high in the last `window` sessions."""
    rows = []
    for s, d in px.items():
        if len(d) < VOL_MIN_BARS + 5:
            continue
        hv_year, hv_ever, rvol, dollar = volume_masks(d)
        tail = slice(-window, None)
        hit = hv_year.iloc[tail] & (dollar.iloc[tail] >= min_dollar)
        if not hit.any():
            continue
        i = hit[hit].index[-1]                      # most recent qualifying bar
        c = d["close"]
        pos = d.index.get_loc(i)
        hi52 = c.iloc[max(0, pos - VOL_YEAR + 1):pos + 1].max()
        rows.append({
            "t": s, "date": i.strftime("%Y-%m-%d"),
            "hv_year": True,
            "hv_ever": bool(hv_ever.loc[i]),
            "hv_ipo": bool(hv_ever.loc[i] and len(d) < VOL_YEAR),
            "rvol": float(rvol.loc[i]) if np.isfinite(rvol.loc[i]) else None,
            "chg": float(c.iloc[pos] / c.iloc[pos - 1] - 1) if pos else None,
            "off_high": float(c.iloc[-1] / hi52 - 1),
            "dvol_m": float(d["volume"].loc[i] * c.loc[i] / 1e6),
            "r1w": float(c.iloc[-1] / c.iloc[-6] - 1) if len(c) > 6 else None,
        })
    rows.sort(key=lambda r: -(r["rvol"] or 0))
    return rows


def high_tight_flags(px):
    """Names sitting in a high tight flag right now."""
    rows = []
    for s, d in px.items():
        m, gain, hold = flag_mask(d)
        if not len(m) or not bool(m.iloc[-1]):
            continue
        h = int(hold.iloc[-1])
        c = d["close"]
        hi52 = c.iloc[-VOL_YEAR:].max()
        peak = float(c.iloc[-1 - h])
        rows.append({
            "t": s, "gain": float(gain.iloc[-1]), "hold": h,
            "pull": float(1 - c.iloc[-h:].min() / peak),
            "volratio": flag_volratio(d, h),
            "off_high": float(c.iloc[-1] / hi52 - 1),
        })
    rows.sort(key=lambda r: -r["gain"])
    return rows


def counts_through_time(px, calendar, start=None):
    """Daily count of names in a flag, and of names at a 252-day volume high.

    Both are reindexed onto one calendar and summed across the universe, so the
    result is a market-state series rather than a snapshot.
    """
    idx = calendar if start is None else calendar[calendar >= pd.Timestamp(start)]
    flags = pd.Series(0, index=idx, dtype="int64")
    vols = pd.Series(0, index=idx, dtype="int64")
    for s, d in px.items():
        m, _, _ = flag_mask(d)
        if m.any():
            flags = flags.add(m.reindex(idx, fill_value=False).astype("int64"), fill_value=0)
        hv, _, _, dollar = volume_masks(d)
        hv = hv & (dollar >= VOL_MIN_DOLLAR)
        if hv.any():
            vols = vols.add(hv.reindex(idx, fill_value=False).astype("int64"), fill_value=0)
    return pd.DataFrame({"flags": flags.astype(int), "volhighs": vols.astype(int)})


def main():
    px = load_prices()
    cal, us = us_calendar(px)
    print(f"universe: {len(px)} single stocks, {len(us)} on the US calendar")
    print(f"as of {cal[-1].date()}\n")

    ve = volume_edge(px)
    print(f"=== volume edge — last {VOL_WINDOW} sessions: {len(ve)} names ===")
    for r in ve:
        tags = " ".join(k for k in ("hv_ever", "hv_ipo") if r[k])
        print(f"  {r['t']:<7} {r['date']}  rvol {r['rvol']:>5.2f}  day {100*r['chg']:>+6.1f}%"
              f"  ${r['dvol_m']:>7,.0f}m  {100*r['off_high']:>+6.1f}% off high  {tags}")

    ht = high_tight_flags(px)
    print(f"\n=== high tight flags: {len(ht)} ===")
    for r in ht:
        print(f"  {r['t']:<7} +{100*r['gain']:>4.0f}% run, {r['hold']:>2}d flag, "
              f"{100*r['pull']:>2.0f}% pull, vol x{r['volratio']:.2f}")


if __name__ == "__main__":
    main()
