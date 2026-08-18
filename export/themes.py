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
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from config import file_stem
from ingestion.baskets import BASKETS
from ingestion.factors import FACTORS as FACTOR_DEFS
from ingestion.recos import LEDGER, walk, held_windows

DEFAULT_OUT = Path.home() / "Desktop/Obsidian/trading-brain/reports"
START = "2000-01-01"  # calendar floor; individual series start when they start
PE_INPUT = Path(__file__).parent.parent / "data" / "eps" / "annual_eps.json"
EARNINGS_INPUT = Path(__file__).parent.parent / "data" / "earnings_dates.json"

# The full S&P 500 Consumer Staples cohort, plus the six restaurant names the
# index classifies as Consumer Discretionary. These are visible rail equities,
# not synthetic baskets: every line is the company's own full price history.
# Large, commonly compared names lead each list; the rest complete the sector.
CONSUMER_STAPLES = [
    ("COST", "Costco · COST"), ("WMT", "Walmart · WMT"),
    ("PG", "Procter & Gamble · PG"), ("KO", "Coca-Cola · KO"),
    ("PEP", "PepsiCo · PEP"), ("PM", "Philip Morris · PM"),
    ("MO", "Altria · MO"), ("MDLZ", "Mondelez · MDLZ"),
    ("MNST", "Monster Beverage · MNST"), ("CL", "Colgate-Palmolive · CL"),
    ("KDP", "Keurig Dr Pepper · KDP"), ("TGT", "Target · TGT"),
    ("KR", "Kroger · KR"), ("SYY", "Sysco · SYY"),
    ("ADM", "Archer-Daniels-Midland · ADM"), ("BF-B", "Brown-Forman · BF-B"),
    ("BG", "Bunge Global · BG"), ("CASY", "Casey's General Stores · CASY"),
    ("CHD", "Church & Dwight · CHD"), ("CLX", "Clorox · CLX"),
    ("DG", "Dollar General · DG"), ("DLTR", "Dollar Tree · DLTR"),
    ("EL", "Estée Lauder · EL"), ("GIS", "General Mills · GIS"),
    ("HRL", "Hormel Foods · HRL"), ("HSY", "Hershey · HSY"),
    ("KHC", "Kraft Heinz · KHC"), ("KMB", "Kimberly-Clark · KMB"),
    ("KVUE", "Kenvue · KVUE"), ("MKC", "McCormick · MKC"),
    ("SJM", "J.M. Smucker · SJM"), ("STZ", "Constellation Brands · STZ"),
    ("TAP", "Molson Coors · TAP"), ("TSN", "Tyson Foods · TSN"),
]
RESTAURANTS = [
    ("SBUX", "Starbucks · SBUX"), ("CMG", "Chipotle · CMG"),
    ("MCD", "McDonald's · MCD"), ("YUM", "Yum! Brands · YUM"),
    ("DRI", "Darden Restaurants · DRI"), ("DPZ", "Domino's · DPZ"),
]

# id -> (label, group). Order within a group drives the rail order, and the
# order of the groups here drives the rail top-to-bottom: broad market context
# first (Indices -> Macro -> Sectors -> Thematic ETFs), then the pure-play baskets.
GROUPS = [
    ("My Coverage", [
        ("mycoverage_reco", "Recommended"),
        ("mycoverage_reco5", "Recommended — current 5"),
        ("mycoverage", "Active Coverage"),
        ("coverage1", "Original Coverage"),
    ]),
    ("Fred Coverage", [
        ("fredcoverage_reco", "Fred Recommended"),
        ("fredcoverage_reco5", "Fred Recommended — current 5"),
        ("fredcoverage", "Fred Active Coverage"),
        ("fredcoverage1", "Fred Original Coverage"),
    ]),
    ("Indices", [
        ("spy", "S&P 500 · SPY"), ("qqq", "Nasdaq-100 · QQQ"),
        ("ixic", "Nasdaq Composite"),
        ("rut", "Russell 2000"), ("iwm", "Russell 2000 · IWM"),
        ("mdy", "S&P Midcap 400 · MDY"), ("rsp", "S&P 500 Equal Weight · RSP"),
        ("n225", "Nikkei 225 · Japan"), ("ks11", "KOSPI · Korea"),
        ("twii", "TAIEX · Taiwan"), ("ssec", "Shanghai Composite"),
        ("hsi", "Hang Seng · China"), ("ftse", "FTSE 100 · London"),
    ]),
    ("Korea — single names", [
        ("kr005930", "Samsung Electronics · Korea"),
        ("kr000660", "SK hynix · Korea"),
    ]),
    ("Europe — single names", [
        ("siemens_energy", "Siemens Energy · Germany"),
    ]),
    ("Consumer staples — single names", CONSUMER_STAPLES),
    ("Restaurants — single names", RESTAURANTS),
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

# Cross-sectional factor buckets (see ingestion/factors.py). The whole universe is
# re-scored and re-sorted every month end, so unlike a theme basket the membership
# is a live screen rather than a curated list. Twenty names a side, fixed, so each
# line is a book you could actually hold. Top and bottom get their own rail group;
# the dollar-neutral spread between them gets another, because a line that can sit
# at 11 while its neighbours sit at 400 would wreck a shared axis if it were filed
# next to them.
GROUPS += [
    ("Factor 20s", [(f"fac_{k}_{sd}", f"{lab} · {word}")
                    for k, lab, _, _, _ in FACTOR_DEFS
                    for sd, word in (("hi", "top 20"), ("lo", "bottom 20"))]),
    ("Factor spreads", [(f"fac_{k}_ls", f"{lab} · top − bottom")
                        for k, lab, _, _, _ in FACTOR_DEFS]),
]

# series whose *level* is not a total-return-like price (charting % change on
# these is still meaningful, but they are not investable — flag for the page).
NOT_INVESTABLE = {"vix", "vix3m", "tnx"}
SINGLE_NAMES = (
    {"kr005930", "kr000660", "siemens_energy"}
    | {ticker for ticker, _ in CONSUMER_STAPLES + RESTAURANTS}
)

# Coverage-book handoffs, one per person. The prior book is measured from
# `anchor` and drawn bold up to `switch`, then ghosts forward (the "if I'd kept
# it" counterfactual); the newer book is level-matched to the prior book at
# `switch` and drawn bold from there — one continuous coverage track. The page
# reads these dates off each series' shipped `handoff` block.
# `switch` is a forward placeholder until the swap is official; while it is still
# in the future (beyond the data), the original book simply runs bold to the
# present and the newer book renders as a normal basket. Neither switch has
# happened yet — update the one date on switch day.
HANDOFFS = [
    {"prev": "coverage1",     "next": "mycoverage",   "anchor": "2026-04-30",
     "switch": "2026-08-22"},
    {"prev": "fredcoverage1", "next": "fredcoverage", "anchor": "2026-01-09",
     "switch": "2026-07-31"},
]

# Coverage books are read as "I bought these names and held them", so their
# headline is the plain average of the members' returns from the left edge of the
# window — each name counts once, no rebalancing. The thematic baskets keep the
# standard daily-rebalanced index shipped in `lv`, which is start-invariant and
# stops one 10-bagger from becoming the whole theme. The page rebuilds the
# average whenever the window moves; this flag only tells it which to do.
AVG_BASKETS = {"mycoverage", "coverage1", "fredcoverage", "fredcoverage1",
               "mycoverage_reco5", "fredcoverage_reco5"}


def _view(t):
    # file_stem first, so aliased symbols ('6674.T' -> 'JP6674') hit their real view.
    return file_stem(t).lower().replace("-", "_").replace(".", "_")


def close_series(conn, view, col="close"):
    """`close` is split-adjusted only (price return); `adj_close` reinvests
    dividends (total return). The page charts the former and multiplies by the
    shipped dividend factor when the reader asks for the latter."""
    df = conn.execute(
        f'SELECT date, {col} FROM "{view}" WHERE date >= \'{START}\' ORDER BY date'
    ).fetchdf()
    if df.empty:
        return None
    s = pd.Series(df[col].values, index=pd.to_datetime(df["date"]))
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
    and rebase to 100 there. Returns (i0, lv-list, raw-first-price)."""
    s = s.reindex(cal).ffill()
    s = s[s.first_valid_index():]
    p0 = float(s.iloc[0])
    lv = (s / s.iloc[0] * 100).round(3)
    return (
        pos[s.index[0]],
        [None if pd.isna(v) else float(v) for v in lv.values],
        p0,
    )


def div_steps(price_s, total_s, cal):
    """Sparse cumulative dividend-reinvestment factor for one series.

    The total-return level is the price-return level times this factor, so the
    page can offer both bases without a second copy of every daily array. The
    factor is flat between ex-dividend dates, which is what makes it cheap:
    a 25-year dividend payer emits ~100 steps against ~6,000 levels, and a name
    that has never paid emits nothing at all (key omitted -> the page uses 1).

    Returned as [[local_index, factor], ...] against the same trimmed, rebased
    index `rebase` produces, always opening with [0, 1.0].
    """
    if total_s is None:
        return None
    p = price_s.reindex(cal).ffill()
    p = p[p.first_valid_index():]
    t = total_s.reindex(cal).ffill().reindex(p.index)
    # A gap in the total-return column would silently distort the toggled view;
    # drop the factor and let the series read as price-only in both modes.
    if t.isna().any() or float(t.iloc[0]) <= 0:
        return None
    f = (t / float(t.iloc[0])) / (p / float(p.iloc[0]))

    # Both columns are stored as 4-decimal fixed point, so their ratio jitters at
    # the 1e-6 level on every bar. Treating that as a step ships one entry per
    # trading day — the exact opposite of the point. A step counts only when it
    # moves the factor by more than TOL relatively, which lands the count near
    # the number of dividends actually paid. Each emitted step carries the true
    # factor at that bar, so the error never accumulates: it stays under TOL,
    # which is 0.002pp on a return quoted to two decimals.
    TOL = 2e-5
    steps, last = [], None
    for k, v in enumerate(f.to_numpy(dtype=float)):
        if last is None or abs(v / last - 1.0) > TOL:
            v = float(f"{v:.7g}")
            steps.append([k, v])
            last = v
    # Constant 1.0 throughout = never paid a dividend. Ship nothing.
    if len(steps) == 1 and steps[0][1] == 1.0:
        return None
    return steps


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


def pe_tickers():
    """Ticker -> display label for usable EPS names, including names that sit in
    no basket. Orphans are shipped as visible rail equities so their P/E chart
    is reachable from Theme Returns."""
    if not PE_INPUT.exists():
        return {}
    payload = json.loads(PE_INPUT.read_text())
    excluded = payload.get("meta", {}).get("excluded", {})
    return {
        ticker: record.get("label") or ticker
        for ticker, record in payload.get("series", {}).items()
        if ticker not in excluded
    }


def earnings_cache():
    if not EARNINGS_INPUT.exists():
        return {}
    return json.loads(EARNINGS_INPUT.read_text()).get("series", {})


def earnings_reactions(series_id, prices, cache):
    """Actual session whose close captures an earnings release reaction."""
    record = cache.get(series_id, {})
    if not record or prices.empty:
        return []
    sessions = pd.DatetimeIndex(prices.index).tz_localize(None).normalize()
    out = []
    for event in record.get("events", []):
        stamp = pd.Timestamp(event["ts"])
        if stamp.tzinfo is not None:
            stamp = stamp.tz_localize(None)
        target = stamp.normalize()
        if event.get("after_close"):
            target += pd.Timedelta(days=1)
        pos = sessions.searchsorted(target)
        if pos < len(sessions):
            out.append(sessions[pos].strftime("%Y-%m-%d"))
    return sorted(set(out))


def _move_stat(value, sample):
    sample = pd.Series(sample).dropna()
    n = len(sample)
    if n < 4:
        return None, None, n
    sigma = float(sample.std(ddof=1))
    z = None if not sigma else abs(float(value)) / sigma
    percentile = (float((sample.abs() <= abs(value)).sum()) + 1) / (n + 1) * 100
    return (
        None if z is None else round(z, 2),
        round(percentile, 1),
        n,
    )


def seasonality(prices):
    """Average calendar-month return, Jan..Dec, over the series' whole history.

    Deliberately not windowed. The heat strip beside it answers "what happened
    in each of the last 24 months"; this answers "what does this thing usually
    do in March", and a two-year window has two Marches in it. The sample count
    ships with every month so a thin one is visible rather than implied.

    Month-end to month-end, so the first partial month is dropped rather than
    counted as a short month's return.

    Each month's sample is winsorized at the 10th/90th percentile before the mean
    is taken. Not for smoothing — for survival. Yahoo's split-adjusted history has
    genuine breaks in it (NVR shows +2600% in October 1993, a reorganisation the
    adjustment never applied), and one bar like that sets the whole average.
    Clipping the tails to their own 10/90 keeps every observation in the sample
    while denying any single one the power to decide the answer.
    """
    p = prices[prices > 0].dropna().sort_index()
    m = p.resample("ME").last().dropna()
    r = m.pct_change(fill_method=None).dropna()
    if len(r) < 12:
        return None
    out = []
    for mo in range(1, 13):
        s = r[r.index.month == mo].to_numpy(dtype=float)
        if not len(s):
            out.append(None)
            continue
        lo, hi = np.percentile(s, [10, 90])
        out.append([round(float(np.clip(s, lo, hi).mean()) * 100, 2), int(len(s))])
    return out


def move_context(prices, reactions):
    """Latest five sessions and four weeks versus like-for-like history.

    Ordinary moves use every prior session in the file. Earnings reactions use
    only prior earnings reactions, so a +7% print is not described as a routine
    4-sigma day when it is ordinary for that company's reporting days.

    This used to be capped at the prior three years, on the argument that a
    stock's normal range drifts and 2015 is a poor yardstick for today. True, but
    the cost was worse: 756 samples cannot resolve anything rarer than 1 in 756,
    so every genuinely large move came back as "0 in 756" with no reading at all.
    A long sample muddies the yardstick; a short one has nothing to say about the
    tails, and the tails are the only reason to look.
    """
    prices = prices[prices > 0].dropna().sort_index()
    if len(prices) < 10:
        return {}
    reactions = set(reactions)
    daily = prices.pct_change(fill_method=None).dropna()
    daily_rows = []
    for stamp, value in daily.tail(5).items():
        day = pd.Timestamp(stamp).strftime("%Y-%m-%d")
        prior = daily[daily.index < stamp]
        is_earnings = day in reactions
        sample = (
            prior[[pd.Timestamp(x).strftime("%Y-%m-%d") in reactions for x in prior.index]]
            if is_earnings else prior
        )
        z, percentile, n = _move_stat(value, sample)
        daily_rows.append({
            "date": day, "r": round(float(value), 5), "z": z,
            "p": percentile, "e": is_earnings, "n": n,
        })

    frame = prices.rename("close").to_frame()
    frame["period"] = frame.index.to_period("W-FRI")
    grouped = frame.groupby("period").agg(close=("close", "last"))
    grouped["date"] = frame.groupby("period").apply(
        lambda x: pd.Timestamp(x.index[-1]).strftime("%Y-%m-%d"),
        include_groups=False,
    )
    grouped["r"] = grouped["close"].pct_change(fill_method=None)
    reaction_periods = {pd.Timestamp(x).to_period("W-FRI") for x in reactions}
    weekly_rows = []
    valid = grouped.dropna(subset=["r"])
    for period, row in valid.tail(4).iterrows():
        prior = valid[valid.index < period]["r"]
        is_earnings = period in reaction_periods
        sample = (
            prior[[x in reaction_periods for x in prior.index]]
            if is_earnings else prior
        )
        z, percentile, n = _move_stat(row["r"], sample)
        weekly_rows.append({
            "date": row["date"], "r": round(float(row["r"]), 5), "z": z,
            "p": percentile, "e": is_earnings, "n": n,
        })
    return {"d": daily_rows, "w": weekly_rows}


def add_move_context(record, series_id, prices, cache):
    reactions = earnings_reactions(series_id, prices, cache)
    moves = move_context(prices, reactions)
    if moves:
        record["moves"] = moves


def factor_meta():
    """Current membership + sigma for each factor decile, from the last rebalance.

    A factor bucket's "members" is a screen, not a definition: it is who happened
    to rank there at the most recent month end, and it will differ next month.
    """
    f = Path(__file__).parent.parent / "data" / "factor_buckets.json"
    if not f.exists():
        return {}
    d = json.loads(f.read_text())
    out = {}
    for key, blob in d.get("factors", {}).items():
        for side in ("hi", "lo"):
            out[f"fac_{key}_{side}"] = {
                "members": [t for t, _ in blob[side]],
                "sigma": {t: z for t, z in blob[side]},
                "rebalanced": blob["rebalanced"], "scored": blob["scored"],
                "n": d.get("n"), "win": blob.get("win"),
                "caveats": d.get("caveats", []),
            }
        out[f"fac_{key}_ls"] = {
            "members": [], "sigma": {}, "rebalanced": blob["rebalanced"],
            "scored": blob["scored"], "n": d.get("n"), "win": blob.get("win"),
            "caveats": d.get("caveats", []),
        }
    return out


def build():
    conn = db.connect()
    RECO = reco_meta()
    FACTOR_META = factor_meta()
    PE_TICKERS = pe_tickers()
    EARNINGS = earnings_cache()
    # tickers named anywhere in a reco book must ship a price line even if they
    # sit in no basket (a call can reach outside current coverage).
    reco_tickers = {n["t"] for r in RECO.values() for n in r["names"]}

    raw, raw_adj, missing = {}, {}, []
    for _, items in GROUPS:
        for sid, _ in items:
            s = close_series(conn, _view(sid))
            # reco strategy lines are short by construction — exempt from the floor
            floor = 0 if sid.endswith("_reco") else 30
            if s is None or len(s) < floor:
                missing.append(sid)
                continue
            raw[sid] = s
            raw_adj[sid] = close_series(conn, _view(sid), "adj_close")

    # every basket constituent as its own series, so the page can drill a basket
    # down into the individual stocks that make it up. Keyed by uppercase ticker
    # (all series ids above are lowercase, so no collision). Thin/too-new names
    # that fail the length floor simply don't get a line.
    # constituent lines use a lower floor than the 30-session rail floor so a
    # fresh IPO (e.g. SPCX, listed weeks ago) draws its drill-down line as soon
    # as it has ~3 weeks of history instead of waiting out a full 30 sessions.
    listed_members = {t for ts in BASKETS.values() for t in ts} | reco_tickers
    members = sorted(listed_members | set(PE_TICKERS))
    stock_raw, stock_adj = {}, {}
    for t in members:
        # Visible single names already have a rail record above. Keep them in
        # stock_raw so basket/recommendation drill-downs can reference them,
        # but do not append a second series with the same id.
        s = close_series(conn, _view(t))
        if s is not None and len(s) >= 15:
            stock_raw[t] = s
            stock_adj[t] = close_series(conn, _view(t), "adj_close")

    # shared calendar: every trading day anything traded on (SPY-anchored)
    cal = sorted(set().union(*[set(s.index) for s in
                               list(raw.values()) + list(stock_raw.values())]))
    cal = pd.DatetimeIndex(cal)

    # The page runs to the most common last bar, not the newest one. Tokyo closes
    # a calendar day ahead of New York, so on a Monday evening in Asia the union
    # calendar already carries a date the US session has not reached. Left in, the
    # right edge of every chart would be a day on which ~97% of the universe was
    # simply forward-filled, and any mixed basket would post a return built from
    # four Tokyo names moving against sixteen frozen ones. Tokyo's extra bar waits
    # a day rather than being blended into a session that has not happened. Same
    # rule as export/leaders.py.
    as_of = Counter(s.index[-1] for s in
                    list(raw.values()) + list(stock_raw.values())).most_common(1)[0][0]
    cal = cal[cal <= as_of]
    pos = {d: i for i, d in enumerate(cal)}

    series = []
    for group, items in GROUPS:
        for sid, label in items:
            if sid not in raw:
                continue
            i0, lv, p0 = rebase(raw[sid], cal, pos)
            rec = {
                "id": sid, "label": label, "group": group,
                "i0": i0, "lv": lv, "p0": p0,
            }
            dv = div_steps(raw[sid], raw_adj.get(sid), cal)
            if dv:
                rec["dv"] = dv
            if sid.endswith("_reco") and sid[:-5] in RECO:
                rec["kind"] = "reco"
                r = RECO[sid[:-5]]
                rec["reco"] = r
                # the names with a drawable price line, so the page can chart them
                rec["memberIds"] = [n["t"] for n in r["names"] if n["t"] in stock_raw]
            elif sid in FACTOR_META:
                # Filed as a basket so the rail's existing drill-down works, but
                # `fac` marks it as a screen: the constituent list is who ranked
                # there at the last month end, not a standing membership.
                # Deliberately NOT added to `listed_members`: a decile is ~61
                # names out of the whole universe, and shipping a full price
                # history for every name in all sixteen deciles would add ~10 MB
                # to a page that already carries 16. The screen is listed in full
                # as text; only the names that already have a line for another
                # reason are drillable.
                f = FACTOR_META[sid]
                rec["kind"] = "basket"
                rec["members"] = list(f["members"])
                rec["memberIds"] = [t for t in f["members"] if t in stock_raw]
                rec["fac"] = {k: f[k] for k in
                              ("sigma", "rebalanced", "scored", "n", "win", "caveats")}
            elif sid in BASKETS:
                rec["kind"] = "basket"
                if sid in AVG_BASKETS:
                    rec["avg"] = True
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
            add_move_context(rec, sid, raw[sid], EARNINGS)
            seas = seasonality(raw[sid])
            if seas:
                rec["seas"] = seas
            # coverage-book handoff metadata (leaves the basket kind + drill-down
            # intact; only tells the page how to rebase/split this aggregate line)
            for h in HANDOFFS:
                if sid == h["prev"]:
                    rec["handoff"] = {"role": "prev", "anchor": h["anchor"],
                                      "switch": h["switch"]}
                elif sid == h["next"]:
                    rec["handoff"] = {"role": "next", "anchor": h["anchor"],
                                      "switch": h["switch"], "prevId": h["prev"]}
            series.append(rec)

    # constituent stock lines — hidden from the rail, revealed per basket on demand
    for t in members:
        if t not in stock_raw:
            continue
        if t in SINGLE_NAMES:
            continue
        i0, lv, p0 = rebase(stock_raw[t], cal, pos)
        orphan = t not in listed_members
        rec = {"id": t, "label": PE_TICKERS.get(t, t),
               "group": "P/E bands" if orphan else "",
               "kind": "equity" if orphan else "stock",
               "i0": i0, "lv": lv, "p0": p0,
               "moves": move_context(
                   stock_raw[t], earnings_reactions(t, stock_raw[t], EARNINGS)
               )}
        dv = div_steps(stock_raw[t], stock_adj.get(t), cal)
        if dv:
            rec["dv"] = dv
        seas = seasonality(stock_raw[t])
        if seas:
            rec["seas"] = seas
        series.append(rec)
    n_rail = sum(s["kind"] != "stock" for s in series)

    payload = {
        "meta": {
            "as_of": as_of.strftime("%Y-%m-%d"),
            "start": cal[0].strftime("%Y-%m-%d"),
            "n_dates": len(cal),
            "n_series": n_rail,
            "n_members": sum(s["kind"] == "stock" for s in series),
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
