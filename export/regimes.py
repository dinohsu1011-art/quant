"""Ship daily macro REGIME MASKS as a static JS file, so
`market-lab-heatmaps.html` can slice any series' returns by market condition
with no backend.

This is deliberately tiny. The heatmap page already loads `cube/themes.js` for
every series' level history, so all it needs from here is: on each trading day,
which regimes were in force. Each regime is one bit per day, shipped as a '0'/'1'
string (~7 KB per regime vs ~55 KB as a JSON array), and the page recomputes
every cell in-browser — which is what lets the date window stay adjustable
instead of baking one fixed sample into the payload.

Regimes come in mutually-exclusive PAIRS within a family (e.g. rates rising vs
falling). Days that satisfy neither side (inside a deadband, or before the
defining series existed) are simply excluded from both — a cell's `n` is always
the honest count of days that actually qualified.

    python -m export.regimes [/some/dir]
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from export.themes import START, close_series

DEFAULT_OUT = Path.home() / "Desktop/Obsidian/trading-brain/reports"

# Lookback for "is this trending up or down" tests, in trading days. One quarter
# — long enough that a single week's noise doesn't flip the regime, short enough
# that a cell still reflects the conditions a position was actually held under.
LOOK = 63

# Deadbands. A regime pair should describe conditions that are meaningfully
# different, not split a coin-flip down the middle, so moves smaller than this
# fall into neither side. Expressed as a fraction (0.02 = 2% over the lookback);
# TNX is in yield points, so its band is absolute.
BAND = 0.02
TNX_BAND = 0.25


def _chg(s, cal):
    """Fractional change over LOOK sessions, on the shared calendar."""
    x = s.reindex(cal).ffill()
    return x.pct_change(LOOK)


def _diff(s, cal):
    """Absolute change over LOOK sessions (for series quoted in points)."""
    x = s.reindex(cal).ffill()
    return x.diff(LOOK)


def build_regimes(conn, cal):
    """Return a list of regime dicts, each with a boolean Series over `cal`."""
    px = {}
    for sid in ("spy", "vix", "tnx", "uup", "wti", "gold", "hyg", "lqd"):
        s = close_series(conn, sid)
        if s is not None:
            px[sid] = s

    out = []

    def pair(family, defs):
        """defs = [(id, label, short, boolean Series), ...] — one family, both sides.

        `short` is the column header on the heatmap, where the family name already
        sits above the pair — so it only has to distinguish the two sides."""
        for sid, label, short, mask in defs:
            out.append({"id": sid, "family": family, "label": label,
                        "short": short, "mask": mask})

    # --- market trend: the single most important conditioner ------------------
    if "spy" in px:
        spy = px["spy"].reindex(cal).ffill()
        ma = spy.rolling(200).mean()
        pair("Market trend", [
            ("trend_up",   "SPX > 200dma", "above", spy > ma),
            ("trend_down", "SPX < 200dma", "below", spy < ma),
        ])

    # --- volatility: level, not change. 25 and 15 are the conventional cuts ---
    if "vix" in px:
        v = px["vix"].reindex(cal).ffill()
        pair("Volatility", [
            ("vix_calm",   "VIX < 15", "< 15", v < 15),
            ("vix_stress", "VIX > 25", "> 25", v > 25),
        ])

    # --- rates: 10Y yield, in yield points ------------------------------------
    if "tnx" in px:
        d = _diff(px["tnx"], cal)
        pair("10Y yield", [
            ("rates_up",   "Rates rising",  "rising",  d > TNX_BAND),
            ("rates_down", "Rates falling", "falling", d < -TNX_BAND),
        ])

    # --- dollar (UUP starts 2007, so these cells carry a shorter sample) ------
    if "uup" in px:
        d = _chg(px["uup"], cal)
        pair("US dollar", [
            ("usd_up",   "Dollar strong", "strong", d > BAND),
            ("usd_down", "Dollar weak",   "weak",   d < -BAND),
        ])

    # --- oil ------------------------------------------------------------------
    if "wti" in px:
        d = _chg(px["wti"], cal)
        pair("Oil", [
            ("oil_up",   "Oil rising",  "rising",  d > BAND),
            ("oil_down", "Oil falling", "falling", d < -BAND),
        ])

    # --- gold -----------------------------------------------------------------
    if "gold" in px:
        d = _chg(px["gold"], cal)
        pair("Gold", [
            ("gold_up",   "Gold rising",  "rising",  d > BAND),
            ("gold_down", "Gold falling", "falling", d < -BAND),
        ])

    # --- credit: HY vs IG. HYG outperforming LQD is risk appetite -------------
    if "hyg" in px and "lqd" in px:
        ratio = (px["hyg"].reindex(cal).ffill() / px["lqd"].reindex(cal).ffill())
        d = ratio.pct_change(LOOK)
        pair("Credit", [
            ("credit_on",  "Credit risk-on",  "risk-on",  d > BAND / 2),
            ("credit_off", "Credit risk-off", "risk-off", d < -BAND / 2),
        ])

    return out


def build():
    conn = db.connect()
    # The calendar must match themes.js so the page can align by date. themes.js
    # unions every series' sessions; SPY alone would miss days when only foreign
    # names traded. We ship explicit dates and the page maps by date string, so a
    # small drift is harmless — but staying on the same basis keeps `n` honest.
    spy = close_series(conn, "spy")
    if spy is None:
        raise SystemExit("no spy series — cannot build regimes")
    cal = pd.DatetimeIndex(sorted(spy.index))
    cal = cal[cal >= pd.Timestamp(START)]

    regs = build_regimes(conn, cal)
    series = []
    for r in regs:
        m = r["mask"].reindex(cal).fillna(False).astype(bool)
        series.append({
            "id": r["id"], "family": r["family"], "label": r["label"],
            "short": r["short"], "n": int(m.sum()),
            "bits": "".join("1" if b else "0" for b in m.values),
        })

    return {
        "meta": {
            "as_of": cal[-1].strftime("%Y-%m-%d"),
            "start": cal[0].strftime("%Y-%m-%d"),
            "n_dates": len(cal),
            "lookback": LOOK,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "dates": [d.strftime("%Y-%m-%d") for d in cal],
        "regimes": series,
    }


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    (out_dir / "cube").mkdir(parents=True, exist_ok=True)
    p = build()
    js = "window.QUANT_REGIMES = " + json.dumps(p, separators=(",", ":")) + ";\n"
    out = out_dir / "cube" / "regimes.js"
    out.write_text(js)
    print(f"wrote {out}  ({len(js)/1e3:.0f} KB)")
    print(f"  {len(p['regimes'])} regimes over {p['meta']['n_dates']} sessions, "
          f"{p['meta']['start']} -> {p['meta']['as_of']}")
    for r in p["regimes"]:
        print(f"    {r['id']:12} {r['label']:16} {r['n']:>5} days")


if __name__ == "__main__":
    main()
