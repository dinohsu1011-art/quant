"""Pre-compute the weekend review → `cube/weekend.js` (`window.QUANT_WEEKEND`).

One pass over the single-stock universe produces everything the page needs: the
index panel, the theme leaderboard, this week's volume-edge names, whatever high
tight flags exist, and the gauge history behind the risk-on/risk-off read. The
page is static and offline, like the rest of Market Lab.

    python -m export.weekend [outdir]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.breadth import (MA_WINDOWS, breadth_series, index_panel,
                              percentile_of_last, ratio_series)
from analysis.risk import risk_panel
from analysis.setups import (VOL_WINDOW, counts_through_time, high_tight_flags,
                             volume_edge)
from analysis.universe import load_prices, scan_universe, sp500_members, us_calendar
from export.themes import GROUPS
from ingestion.baskets import BASKETS

REPORTS = Path.home() / "Desktop/Obsidian/trading-brain/reports"
GAUGE_START = "2010-01-01"

# The three indexes the routine reviews, plus the two that say whether a move is
# broad or just the mega caps.
INDEXES = [("spy", "S&P 500"), ("qqq", "Nasdaq-100"), ("rut", "Russell 2000"),
           ("mdy", "S&P Midcap 400"), ("rsp", "S&P 500 Equal Weight")]

# Two different questions, so two sets. The first asks whether a move is the whole
# market or the top of it; the second asks whether risk is being taken at all.
RATIOS = [("iwm", "spy", "IWM / SPY", "small caps vs large"),
          ("rsp", "spy", "RSP / SPY", "broad participation vs mega-cap"),
          ("xlp", "spy", "XLP / SPY", "defensives — a risk-off tell"),
          ("xlu", "spy", "XLU / SPY", "utilities — the other one")]

RISK_RATIOS = [("qqq", "spy", "QQQ / SPY", "tech vs the market"),
               ("smh", "spy", "SMH / SPY", "semis — the high-beta engine"),
               ("arkk", "spy", "ARKK / SPY", "long-duration speculation")]

# Coverage books are personal watchlists, not themes; they have their own page.
NOT_A_THEME = {"mycoverage", "coverage1", "fredcoverage", "fredcoverage1"}
SECTORS = ["xlk", "xlc", "xly", "xli", "xlf", "xlv", "xle", "xlb", "xlu", "xlp", "xlre"]


def labels():
    return {sid: lb for _, items in GROUPS for sid, lb in items}


def theme_leaderboard(px):
    """Themes ranked by the week, with the rank change that shows rotation."""
    lab = labels()
    ids = [b for b in BASKETS if b not in NOT_A_THEME] + SECTORS
    rows = []
    for sid in ids:
        d = px.get(sid)
        if d is None or len(d) < 70:
            continue
        c = d["close"].astype("float64")
        rows.append({
            "id": sid, "label": lab.get(sid, sid.upper()),
            "kind": "sector" if sid in SECTORS else "basket",
            "n": len(BASKETS.get(sid, [])) or None,
            "r1w": float(c.iloc[-1] / c.iloc[-6] - 1),
            "r1m": float(c.iloc[-1] / c.iloc[-22] - 1),
            "r3m": float(c.iloc[-1] / c.iloc[-64] - 1),
            # the same 1-month measure a month ago, so the ranking can be compared
            "r1m_prev": float(c.iloc[-22] / c.iloc[-43] - 1),
        })
    # Δrank on the 1-month measure: where a theme ranks now vs where it ranked a
    # month ago. Positive means money moved in.
    now = {r["id"]: i for i, r in enumerate(sorted(rows, key=lambda r: -r["r1m"]))}
    prev = {r["id"]: i for i, r in enumerate(sorted(rows, key=lambda r: -r["r1m_prev"]))}
    for r in rows:
        r["rank"] = now[r["id"]] + 1
        r["drank"] = prev[r["id"]] - now[r["id"]]
        del r["r1m_prev"]
    rows.sort(key=lambda r: -r["r1w"])
    return rows


def scoreboard(bre, gauges):
    """Six gauges, each with today's value and where it sits in its own history."""
    last = bre.iloc[-1]
    out = []
    for w in MA_WINDOWS:
        col = f"pct_above_{w}"
        out.append({"id": col, "label": f"% above {w}-day", "unit": "%",
                    "value": round(float(last[col]), 1),
                    "pct": percentile_of_last(bre[col], 1260),
                    "note": "S&P members"})
    out.append({"id": "net_highs", "label": "52-week highs − lows", "unit": "",
                "value": int(last["net_highs"]),
                "pct": percentile_of_last(bre["net_highs"], 1260),
                "note": f"{int(last['new_highs'])} up, {int(last['new_lows'])} down"})
    g = gauges.iloc[-1]
    out.append({"id": "flags", "label": "High tight flags", "unit": "",
                "value": int(g["flags"]),
                "pct": percentile_of_last(gauges["flags"], 1260),
                "note": "speculative appetite"})
    wk = int(gauges["volhighs"].iloc[-VOL_WINDOW:].sum())
    out.append({"id": "volhighs", "label": "Volume highs this week", "unit": "",
                "value": wk,
                "pct": percentile_of_last(gauges["volhighs"].rolling(VOL_WINDOW).sum(), 1260),
                "note": "participation"})
    return out


def build(outdir=REPORTS):
    outdir = Path(outdir)
    px = load_prices()
    cal, us = us_calendar(px)
    as_of = cal[-1]
    print(f"universe {len(px)} stocks · as of {as_of.date()}")

    # index/ratio/theme series live outside the scan universe, so load them too
    extra = [sid for sid, _ in INDEXES] + ["iwm", "xlp", "xlu", "smh", "arkk"] + SECTORS \
        + [b for b in BASKETS if b not in NOT_A_THEME]
    market = load_prices([s for s in dict.fromkeys(extra)])

    bre = breadth_series(px, cal, members=sp500_members())
    print(f"  breadth: {bre['pct_above_50'].iloc[-1]:.1f}% above the 50-day")

    members = sp500_members()
    risk, risk_ser = risk_panel(px, cal, members)
    print("  risk: " + ", ".join(
        f"{g['id']} {g['value']}{g['unit']} ({g['pct']:.0f}th)" for g in risk))

    gauges = counts_through_time(px, cal, start=GAUGE_START)
    print(f"  gauges: {len(gauges)} sessions, {int(gauges['flags'].iloc[-1])} flags today")

    ve = volume_edge(px)
    ht = high_tight_flags(px)
    th = theme_leaderboard(market)
    print(f"  volume edge {len(ve)} · flags {len(ht)} · themes {len(th)}")

    gi = gauges.index
    bre_w = bre.reindex(gi)
    payload = {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "week": {"start": cal[-VOL_WINDOW].strftime("%Y-%m-%d"),
                 "end": as_of.strftime("%Y-%m-%d"), "sessions": VOL_WINDOW},
        "universe": {"stocks": len(px), "sp500": len(sp500_members())},
        "indexes": index_panel(market, INDEXES),
        "ratios": [dict(id=f"{a}_{b}", label=lb, note=note, **r)
                   for a, b, lb, note in RATIOS
                   if (r := ratio_series(market, a, b))],
        "risk_ratios": [dict(id=f"{a}_{b}", label=lb, note=note, **r)
                        for a, b, lb, note in RISK_RATIOS
                        if (r := ratio_series(market, a, b))],
        "risk": risk,
        "risk_series": risk_ser,
        "themes": th,
        "volume": ve,
        "flags": ht,
        "scoreboard": scoreboard(bre, gauges),
        "gauges": {
            "dates": [d.strftime("%Y-%m-%d") for d in gi],
            "flags": [int(v) for v in gauges["flags"]],
            "volhighs": [int(v) for v in gauges["volhighs"]],
            **{f"pct{w}": [None if pd.isna(v) else round(float(v), 1)
                           for v in bre_w[f"pct_above_{w}"]] for w in MA_WINDOWS},
            "net_highs": [None if pd.isna(v) else int(v) for v in bre_w["net_highs"]],
        },
    }

    (outdir / "cube").mkdir(parents=True, exist_ok=True)
    out = outdir / "cube" / "weekend.js"
    txt = "window.QUANT_WEEKEND = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    out.write_text(txt)
    print(f"wrote {out}  ({len(txt)/1e6:.2f} MB)")
    return payload


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else REPORTS)
