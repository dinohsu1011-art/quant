"""
Export a COMPACT data bundle for the Trader Profile HTML.

Runs the regime / event-study analyses against the full parquet dataset (which
stays in this repo) and writes only the small results the charts need into a
`trader-profile-data.js` next to the HTML, as `window.QUANT_DATA = {...}`. The
HTML loads it via a <script> tag, so it works on a plain double-click (file://),
offline. Re-run this script to refresh.

    python -m export.trader_profile            # default reports dir (~/Desktop/...)
    python -m export.trader_profile /some/dir  # custom output dir

Contents (all point-in-time, next *trading* session, close-to-close):
  1. dip_by_trend        SPY drop <= -3%, next-day, split by 200-DMA trend regime
  2. sector_bounce_vix   each sector ETF <= -2% while VIX>30, next-day, ranked
  3. crash_next_day_dist SPY next-day return distribution after a drop <= -2.5%
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from analysis.events import event_study, compare_regimes, summarize_event, SECTORS

DEFAULT_OUT = Path.home() / "Desktop/Obsidian/trading-brain/reports"

SECTOR_NAMES = {
    "xlk": "Technology", "xlf": "Financials", "xlv": "Health Care",
    "xle": "Energy", "xli": "Industrials", "xly": "Cons. Disc.",
    "xlc": "Comm. Services", "xlp": "Cons. Staples", "xlu": "Utilities",
    "xlre": "Real Estate", "xlb": "Materials",
}


def _f(x, nd=2):
    """JSON-safe rounded float (handles numpy / NaN)."""
    if x is None or (isinstance(x, float) and x != x):
        return None
    return round(float(x), nd)


def build(conn):
    as_of = conn.execute("select max(date) from spy").fetchone()[0]

    # 1) Dip-buying by trend regime — SPY single-day drop <= -3%
    reg = compare_regimes(conn, "spy", {
        "All drops": None,
        "Uptrend (>200DMA)": "spy>spy_200dma",
        "Downtrend (<200DMA)": "spy<spy_200dma",
    }, threshold=-0.03)
    dip_by_trend = {
        "title": "Does buying the dip depend on the trend?",
        "subtitle": "SPY single-day drop ≤ −3%, next-session outcome · 1993–now",
        "regimes": [{
            "label": r["label"], "n": int(r["n"]),
            "up_pct": _f(r["win_rate"] * 100, 1), "mean_pct": _f(r["mean_pct"]),
            "t": _f(r["t_stat"]), "ci": [_f(r["ci_95_lo"]), _f(r["ci_95_hi"])],
        } for _, r in reg.iterrows()],
    }

    # 2) Sector bounce under a VIX spike — sector ETF <= -2% while VIX>30
    secs = []
    for s in SECTORS:
        st = summarize_event(event_study(conn, s, threshold=-0.02, when="vix>30"), s)
        secs.append({
            "ticker": s.upper(), "name": SECTOR_NAMES[s], "n": int(st["n"]),
            "up_pct": _f(st["win_rate"] * 100, 1), "mean_pct": _f(st["mean_pct"]),
        })
    secs.sort(key=lambda d: (d["mean_pct"] is not None, d["mean_pct"]), reverse=True)
    sector_bounce_vix = {
        "title": "Which sectors bounce hardest after a fear spike?",
        "subtitle": "Sector ETF day ≤ −2% while VIX > 30 · next-session return, ranked",
        "sectors": secs,
    }

    # 3) Crash next-day distribution — SPY next-day after a drop <= -2.5%
    ev = event_study(conn, "spy", threshold=-0.025)
    nxt = (ev["outcome_ret"].dropna().to_numpy(dtype="float64")) * 100.0
    lo, hi = np.floor(nxt.min()), np.ceil(nxt.max())
    edges = np.arange(lo, hi + 1, 1.0)
    counts, edges = np.histogram(nxt, bins=edges)
    base_up = conn.execute("""
        with r as (select close/lag(close) over (order by date)-1 ret from spy)
        select avg((ret>0)::int) from r where ret is not null""").fetchone()[0]
    crash_next_day_dist = {
        "title": "What happens the day after a crash?",
        "subtitle": "SPY next-session return after a single-day drop ≤ −2.5%",
        "n": int(len(nxt)),
        "up_pct": _f(float((nxt > 0).mean()) * 100, 1),
        "mean_pct": _f(float(nxt.mean())),
        "base_rate_up_pct": _f(float(base_up) * 100, 1),
        "bins": [{"lo": _f(edges[i], 1), "hi": _f(edges[i + 1], 1), "count": int(counts[i])}
                 for i in range(len(counts))],
    }

    return {
        "meta": {
            "as_of": str(as_of),
            "source": "quant repo · yfinance daily closes (metals = COMEX continuous futures)",
            "method": "close-to-close price returns; next = next trading day (holiday-robust); "
                      "regimes point-in-time as of the trigger close",
        },
        "dip_by_trend": dip_by_trend,
        "sector_bounce_vix": sector_bounce_vix,
        "crash_next_day_dist": crash_next_day_dist,
    }


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    data = build(conn)
    payload = "window.QUANT_DATA = " + json.dumps(data, indent=2) + ";\n"
    out = out_dir / "trader-profile-data.js"
    out.write_text(payload)
    print(f"\nWrote {out}  ({len(payload):,} bytes)")
    print(f"  as_of {data['meta']['as_of']}")
    print(f"  dip_by_trend: {len(data['dip_by_trend']['regimes'])} regimes")
    print(f"  sector_bounce_vix: {len(data['sector_bounce_vix']['sectors'])} sectors")
    print(f"  crash_next_day_dist: n={data['crash_next_day_dist']['n']}, "
          f"{len(data['crash_next_day_dist']['bins'])} hist bins")


if __name__ == "__main__":
    main()
