"""Ship daily index levels for every theme, sector, ETF and macro series as a
static JS file, so `market-lab-themes.html` can chart and compare returns over
any window with no backend.

The cube ships *event-study statistics*; this ships the underlying *time series*.
Each series is rebased to 100 at its own first observation and stored with an
offset (`i0`) into a shared trading-day calendar, so nothing but real history is
transmitted. The page rebases again to whatever window the user picks.

Baskets broaden as their members list (see ingestion/baskets.py), so each basket
also carries the date its membership first went complete — the page flags any
window that starts before that.

    python -m export.themes [/some/dir]
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from config import file_stem
from ingestion.baskets import BASKETS
from ingestion.recos import LEDGER, walk, held_windows

DEFAULT_OUT = Path.home() / "Desktop/Obsidian/trading-brain/reports"
START = "2000-01-01"  # calendar floor; individual series start when they start

# id -> (label, group). Order within a group drives the rail order, and the
# order of the groups here drives the rail top-to-bottom: broad market context
# first (Indices -> Macro -> Sectors -> Thematic ETFs), then the pure-play baskets.
GROUPS = [
    ("My Coverage", [
        ("mycoverage_reco", "Recommended"),
        ("mycoverage", "Active Coverage"),
        ("coverage1", "Original Coverage"),
    ]),
    ("Fred Coverage", [
        ("fredcoverage", "Fred Coverage"),
    ]),
    ("Indices", [
        ("spy", "S&P 500 · SPY"), ("qqq", "Nasdaq-100 · QQQ"),
        ("ixic", "Nasdaq Composite"),
        ("n225", "Nikkei 225 · Japan"), ("ks11", "KOSPI · Korea"),
        ("twii", "TAIEX · Taiwan"), ("ssec", "Shanghai Composite"),
        ("hsi", "Hang Seng · China"), ("ftse", "FTSE 100 · London"),
    ]),
    ("Korea — single names", [
        ("kr005930", "Samsung Electronics · Korea"),
        ("kr000660", "SK hynix · Korea"),
    ]),
    ("Macro & cross-asset", [
        ("gold", "Gold"), ("silver", "Silver"), ("copper", "Copper"), ("wti", "WTI Crude"),
        ("tlt", "20Y Treasuries · TLT"), ("ief", "7-10Y Treasuries · IEF"),
        ("hyg", "High Yield · HYG"), ("lqd", "IG Credit · LQD"),
        ("uup", "US Dollar · UUP"), ("tnx", "10Y Yield · TNX"),
        ("vix", "VIX"), ("vix3m", "VIX 3-Month"),
    ]),
    ("Sectors", [
        ("xlk", "Technology · XLK"), ("xlc", "Comm. Svcs · XLC"), ("xly", "Cons. Disc. · XLY"),
        ("xli", "Industrials · XLI"), ("xlf", "Financials · XLF"), ("xlv", "Health Care · XLV"),
        ("xle", "Energy · XLE"), ("xlb", "Materials · XLB"), ("xlu", "Utilities · XLU"),
        ("xlp", "Cons. Staples · XLP"), ("xlre", "Real Estate · XLRE"),
    ]),
    ("Thematic ETFs", [
        ("smh", "Semis · SMH"), ("igv", "Software · IGV"), ("cibr", "Cybersecurity · CIBR"),
        ("botz", "Robotics · BOTZ"), ("ign", "Networking · IGN"), ("ura", "Uranium · URA"),
        ("grid", "Electrification · GRID"), ("pave", "Infrastructure · PAVE"),
        ("fivg", "5G · FIVG"), ("ita", "Defense & Aero · ITA"), ("ufo", "Space · UFO"),
        ("idrv", "EV / Auto · IDRV"), ("tan", "Solar · TAN"), ("icln", "Clean Energy · ICLN"),
        ("arkk", "Innovation · ARKK"), ("ibit", "Bitcoin · IBIT"), ("kweb", "China Internet · KWEB"),
        ("xbi", "Biotech · XBI"), ("kre", "Regional Banks · KRE"), ("gdx", "Gold Miners · GDX"),
        ("xme", "Metals & Mining · XME"), ("xop", "Oil E&P · XOP"), ("oih", "Oil Services · OIH"),
        ("xhb", "Homebuilders · XHB"), ("xrt", "Retail · XRT"), ("jets", "Airlines · JETS"),
    ]),
    ("AI & semis — baskets", [
        ("gpu", "GPU"), ("cpuasic", "CPU + ASIC"),
        ("memory", "Memory"), ("semicap", "Semicap"), ("powersemi", "Power Semis"),
        ("photonics", "Photonics"), ("connectivity", "Connectivity"),
        ("networking", "Networking"), ("aiserver", "AI Servers"),
        ("hyperscale", "Hyperscalers"), ("neocloud", "Neocloud"),
        ("cdnedge", "CDN / Edge"),
    ]),
    ("Software — baskets", [
        ("software", "Software"), ("cyber", "Cybersecurity"),
    ]),
    ("Power & industrial — baskets", [
        ("utilities", "Utilities & IPPs"), ("elecind", "Electric Industrial"),
        ("gas", "Gas Power"), ("epc", "EPC"), ("nuclear", "Nuclear"),
        ("solutil", "Industrial Solar"), ("solresi", "Residential Solar"),
        ("materials", "Materials"), ("miners", "Metals — Miners"),
    ]),
    ("Defense & frontier — baskets", [
        ("defense", "Defense & Aero"), ("space", "Space"), ("robotics", "Robotics"),
    ]),
    ("Japan — baskets", [
        ("japan", "Japan · elec & grid"),
    ]),
]

# series whose *level* is not a total-return-like price (charting % change on
# these is still meaningful, but they are not investable — flag for the page).
NOT_INVESTABLE = {"vix", "vix3m", "tnx"}
SINGLE_NAMES = {"kr005930", "kr000660"}

# Coverage-book handoff. The prior book ("Coverage 1") is measured from `anchor`
# and drawn bold up to `switch`, then ghosts forward (the "if I'd kept it"
# counterfactual); the live book ("Active Coverage") is level-matched to the
# prior book at `switch` and drawn bold from there — one continuous coverage
# track. The page reads these dates off each series' shipped `handoff` block.
# `switch` is a forward placeholder until the swap is official; while it is still
# in the future (beyond the data), Coverage 1 simply runs bold to the present and
# the active book renders as a normal basket. Update this one date on switch day.
COVERAGE_HANDOFF = {
    "prev": "coverage1",
    "next": "mycoverage",
    "anchor": "2026-04-30",
    "switch": "2026-07-31",
}


def _view(t):
    # file_stem first, so aliased symbols ('6674.T' -> 'JP6674') hit their real view.
    return file_stem(t).lower().replace("-", "_").replace(".", "_")


def close_series(conn, view):
    df = conn.execute(
        f'SELECT date, close FROM "{view}" WHERE date >= \'{START}\' ORDER BY date'
    ).fetchdf()
    if df.empty:
        return None
    s = pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))
    return s[s > 0].dropna()


def member_full_date(conn, tickers):
    """Date on which the last member of a basket started trading."""
    firsts = []
    for t in tickers:
        try:
            r = conn.execute(f'SELECT min(date) FROM "{_view(t)}"').fetchone()
        except Exception:
            continue
        if r and r[0]:
            firsts.append(pd.Timestamp(r[0]))
    return max(firsts) if firsts else None


def rebase(s, cal, pos):
    """Reindex onto the shared calendar, forward-fill, trim to first real bar,
    and rebase to 100 there. Returns (i0, lv-list)."""
    s = s.reindex(cal).ffill()
    s = s[s.first_valid_index():]
    lv = (s / s.iloc[0] * 100).round(3)
    return pos[s.index[0]], [None if pd.isna(v) else float(v) for v in lv.values]


def reco_meta():
    """Per-book recommendation metadata for the page: each name's held windows
    (bold vs ghost), the dated swap events (hover markers), and the current 5."""
    out = {}
    for lst, book in LEDGER.items():
        instances, events, current = walk(book)
        hw = held_windows(instances)
        out[lst] = {
            "names": [{"t": t, "windows": [[e, x] for (e, x) in ws]}
                      for t, ws in hw.items()],
            "events": [{"d": d, "lines": ls} for d, ls in sorted(events.items())],
            "current": current,
        }
    return out


def build():
    conn = db.connect()
    RECO = reco_meta()
    # tickers named anywhere in a reco book must ship a price line even if they
    # sit in no basket (a call can reach outside current coverage).
    reco_tickers = {n["t"] for r in RECO.values() for n in r["names"]}

    raw, missing = {}, []
    for _, items in GROUPS:
        for sid, _ in items:
            s = close_series(conn, sid)
            # reco strategy lines are short by construction — exempt from the floor
            floor = 0 if sid.endswith("_reco") else 30
            if s is None or len(s) < floor:
                missing.append(sid)
                continue
            raw[sid] = s

    # every basket constituent as its own series, so the page can drill a basket
    # down into the individual stocks that make it up. Keyed by uppercase ticker
    # (all series ids above are lowercase, so no collision). Thin/too-new names
    # that fail the length floor simply don't get a line.
    # constituent lines use a lower floor than the 30-session rail floor so a
    # fresh IPO (e.g. SPCX, listed weeks ago) draws its drill-down line as soon
    # as it has ~3 weeks of history instead of waiting out a full 30 sessions.
    members = sorted({t for ts in BASKETS.values() for t in ts} | reco_tickers)
    stock_raw = {}
    for t in members:
        s = close_series(conn, _view(t))
        if s is not None and len(s) >= 15:
            stock_raw[t] = s

    # shared calendar: every trading day anything traded on (SPY-anchored)
    cal = sorted(set().union(*[set(s.index) for s in
                               list(raw.values()) + list(stock_raw.values())]))
    cal = pd.DatetimeIndex(cal)
    pos = {d: i for i, d in enumerate(cal)}

    series = []
    for group, items in GROUPS:
        for sid, label in items:
            if sid not in raw:
                continue
            i0, lv = rebase(raw[sid], cal, pos)
            rec = {"id": sid, "label": label, "group": group, "i0": i0, "lv": lv}
            if sid.endswith("_reco") and sid[:-5] in RECO:
                rec["kind"] = "reco"
                r = RECO[sid[:-5]]
                rec["reco"] = r
                # the names with a drawable price line, so the page can chart them
                rec["memberIds"] = [n["t"] for n in r["names"] if n["t"] in stock_raw]
            elif sid in BASKETS:
                rec["kind"] = "basket"
                rec["members"] = list(BASKETS[sid])
                # only the members that actually have a drawable series
                rec["memberIds"] = [t for t in BASKETS[sid] if t in stock_raw]
                full = member_full_date(conn, BASKETS[sid])
                if full is not None:
                    rec["full"] = full.strftime("%Y-%m-%d")
            elif sid in NOT_INVESTABLE:
                rec["kind"] = "level"
            elif sid in SINGLE_NAMES:
                # Visible rail equities use a distinct kind because ordinary
                # `stock` series are hidden constituent drill-downs on the page.
                rec["kind"] = "equity"
            else:
                rec["kind"] = "etf"
            # coverage-book handoff metadata (leaves the basket kind + drill-down
            # intact; only tells the page how to rebase/split this aggregate line)
            if sid == COVERAGE_HANDOFF["prev"]:
                rec["handoff"] = {"role": "prev", "anchor": COVERAGE_HANDOFF["anchor"],
                                  "switch": COVERAGE_HANDOFF["switch"]}
            elif sid == COVERAGE_HANDOFF["next"]:
                rec["handoff"] = {"role": "next", "anchor": COVERAGE_HANDOFF["anchor"],
                                  "switch": COVERAGE_HANDOFF["switch"],
                                  "prevId": COVERAGE_HANDOFF["prev"]}
            series.append(rec)

    n_rail = len(series)
    # constituent stock lines — hidden from the rail, revealed per basket on demand
    for t in members:
        if t not in stock_raw:
            continue
        i0, lv = rebase(stock_raw[t], cal, pos)
        series.append({"id": t, "label": t, "group": "", "kind": "stock",
                       "i0": i0, "lv": lv})

    payload = {
        "meta": {
            "as_of": cal[-1].strftime("%Y-%m-%d"),
            "start": cal[0].strftime("%Y-%m-%d"),
            "n_dates": len(cal),
            "n_series": n_rail,
            "n_members": len(series) - n_rail,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "missing": missing,
        },
        "dates": [d.strftime("%Y-%m-%d") for d in cal],
        "series": series,
    }
    return payload


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    (out_dir / "cube").mkdir(parents=True, exist_ok=True)
    p = build()
    js = "window.QUANT_THEMES = " + json.dumps(p, separators=(",", ":")) + ";\n"
    out = out_dir / "cube" / "themes.js"
    out.write_text(js)
    m = p["meta"]
    print(f"wrote {out}  ({len(js)/1e6:.2f} MB)")
    print(f"  {m['n_series']} rail series + {m['n_members']} constituents, "
          f"{m['n_dates']} sessions, {m['start']} -> {m['as_of']}")
    if m["missing"]:
        print(f"  missing views: {', '.join(m['missing'])}")


if __name__ == "__main__":
    main()
