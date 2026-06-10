"""
Event studies on daily returns: define a condition on a trigger day, then
measure the return over the next `horizon` trading session(s).

Canonical example — OddStats' "Mondays after terrible Fridays for the NASDAQ":

    import db
    from analysis.events import event_study, summarize_event, render, FRI
    conn = db.connect()
    # NASDAQ-100; "NASDAQ" in such posts is usually the NDX-100, not the Composite
    tbl = event_study(conn, "ndx", day=FRI, threshold=-0.0475)
    print(render(tbl, "Friday", "Next session"))
    print(summarize_event(tbl))

Notes
-----
* Returns are close-to-close PRICE returns (matches the index-return convention
  and the OddStats table). Pass price="adj_close" for total return on equities.
* "Next session" is the next *trading day*, not the next calendar Monday. Rows
  are trading days only, so a down Friday before a holiday Monday maps to the
  following Tuesday — which is exactly what the OddStats table does (its
  Dec 29 2000 "Monday" is really Tue Jan 2 2001, since Jan 1 was a holiday).
  Pass strict_next_dow=MON to force literal Mondays and drop holiday-shifted rows.
"""
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.stats import summarize

# isodow constants (DuckDB isodow: Monday=1 ... Sunday=7)
MON, TUE, WED, THU, FRI, SAT, SUN = 1, 2, 3, 4, 5, 6, 7
_DOW_NAME = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}

# The 11 SPDR Select Sector ETF view names (for sector cross-sections).
SECTORS = ["xlk", "xlf", "xlv", "xle", "xli", "xly", "xlc", "xlp", "xlu", "xlre", "xlb"]


def _view(symbol: str) -> str:
    """Mirror db.py's view-name derivation so callers can pass '^IXIC' or 'ixic'."""
    return symbol.strip().lstrip("^").lower().replace("-", "_").replace(".", "_")


_OPS = {">": ">", "<": "<", ">=": ">=", "<=": "<=", "==": "=", "!=": "!="}


def _compile_condition(when):
    """Translate a when= regime string into (cte_list, join_sql, where_expr).

    Grammar (point-in-time — every term is known as of the trigger day's close,
    so there is no lookahead):
        <series>_up | <series>_down      sign of that series' daily return
        <term> <op> <term>               e.g. vix>30, spy>spy_200dma, gold_ret>0
    term   = number | <series>[suffix]
    suffix = (none)=close | _prev=prior close | _ret=daily return | _<N>dma=N-session SMA
    op     = > < >= <= == !=
    `series` is a view name (vix, spy, gold, copper, xlk, ndx, ...).

    Note a same-day level on a series defined by the move itself can be circular
    (a -5% day spikes its own VIX); use _prev for the regime you *entered*.
    """
    when = when.strip().lower()
    feats = {}  # series -> set of feature keys: 'val','prev','ret','ma:<N>'

    def term_sql(term):
        term = term.strip()
        try:
            return str(float(term))                      # numeric literal
        except ValueError:
            pass
        m = re.fullmatch(r"([a-z0-9]+?)(_ret_prev|_prev|_ret|_(\d+)dma)?", term)
        if not m:
            raise ValueError(f"unparseable term {term!r} in when=")
        s, suf = m.group(1), m.group(2)
        feats.setdefault(s, set())
        if suf is None:           feats[s].add("val");   col = "val"
        elif suf == "_ret_prev":  feats[s].add("rprev"); col = "rprev"
        elif suf == "_prev":      feats[s].add("prev");  col = "prev"
        elif suf == "_ret":       feats[s].add("ret");   col = "ret"
        else:                     N = int(m.group(3)); feats[s].add(f"ma:{N}"); col = f"ma{N}"
        return f"c_{s}.{s}__{col}"

    mflag = re.fullmatch(r"([a-z0-9]+)_(up|down)", when)
    if mflag:
        s, d = mflag.group(1), mflag.group(2)
        feats.setdefault(s, set()).add("ret")
        where_expr = f'c_{s}.{s}__ret {">" if d == "up" else "<"} 0'
    else:
        m = re.fullmatch(r"(.+?)(>=|<=|==|!=|>|<)(.+)", when)
        if not m:
            raise ValueError(f"unparseable when={when!r}")
        where_expr = f"{term_sql(m.group(1))} {_OPS[m.group(2)]} {term_sql(m.group(3))}"

    ctes, joins = [], []
    for s, fs in feats.items():
        cols = ["date"]
        if "val" in fs:   cols.append(f"close AS {s}__val")
        if "prev" in fs:  cols.append(f"LAG(close) OVER w AS {s}__prev")
        if "ret" in fs:   cols.append(f"close / LAG(close) OVER w - 1 AS {s}__ret")
        if "rprev" in fs: cols.append(f"LAG(close) OVER w / LAG(close, 2) OVER w - 1 AS {s}__rprev")
        for f in sorted(fs):
            if f.startswith("ma:"):
                N = int(f.split(":")[1])
                cols.append(f"AVG(close) OVER (ORDER BY date ROWS BETWEEN {N - 1} "
                            f"PRECEDING AND CURRENT ROW) AS {s}__ma{N}")
        ctes.append(f"c_{s} AS (SELECT {', '.join(cols)} "
                    f"FROM query_table('{_view(s)}') WINDOW w AS (ORDER BY date))")
        joins.append(f"LEFT JOIN c_{s} ON c_{s}.date = r.trigger_date")
    return ctes, "\n        ".join(joins), where_expr, sorted(feats)


def event_study(conn, symbol, *, day=None, threshold=None, worst_n=None,
                streak=None, streak_dir="down", streak_gap=None,
                horizon=1, strict_next_dow=None, since=None, price="close",
                measure_field="ret", when=None):
    """Conditional next-session returns.

    Returns a DataFrame: trigger_date, trigger_dow, trigger_ret,
                         outcome_date, outcome_dow, outcome_ret.

    day             isodow of the trigger day (FRI=5); None = any day
    threshold       trigger when trigger_ret <= threshold (e.g. -0.0477)
    worst_n         instead of a threshold, take the N most negative trigger days
    streak          consecutive-day trigger: fires on the day the subject completes
                    its Nth consecutive day in `streak_dir` ('down'|'up'), each day
                    optionally also gapping (`streak_gap`: 'up'|'down'|None — open vs
                    prior close). E.g. streak=3, streak_dir='down', streak_gap='up'
                    = 3 red days in a row, each opening above the prior close.
                    Mutually exclusive with threshold/worst_n.
    horizon         sessions ahead to measure (1 = next session)
    strict_next_dow require the outcome day to equal this isodow (e.g. MON)
    since           ISO date string lower bound on the trigger day
    price           'close' (price return) or 'adj_close' (total return)
    when            regime gate on another series, point-in-time as of the trigger
                    close. Examples: "vix>30", "vix_prev>=25", "spy>spy_200dma",
                    "gold_up", "copper<copper_50dma", "gold_ret>0.01".
    measure_field   outcome at the horizon session: 'ret' close-to-close (vs the
                    trigger close) | 'hi'/'lo' that session's intraday high/low vs
                    the trigger close | 'range' (high-low)/trigger close. hi/lo/range
                    use raw (unadjusted) OHLC.
    """
    view = _view(symbol)
    px = "adj_close" if price == "adj_close" else "close"
    h = int(horizon)
    if measure_field == "ret":     outcome_expr = f"LEAD({px}, {h}) OVER w / {px} - 1"
    elif measure_field == "hi":    outcome_expr = f"LEAD(high, {h}) OVER w / close - 1"
    elif measure_field == "lo":    outcome_expr = f"LEAD(low, {h}) OVER w / close - 1"
    elif measure_field == "range": outcome_expr = f"(LEAD(high, {h}) OVER w - LEAD(low, {h}) OVER w) / close"
    else: raise ValueError(f"measure_field {measure_field!r} not in ret/hi/lo/range")
    if measure_field != "ret":
        flat = conn.execute(f"select avg((high = low)::int) from query_table('{view}')").fetchone()[0]
        if flat is not None and flat > 0.95:
            raise ValueError(
                f"measure_field={measure_field!r} is unavailable for '{view}': synthetic basket "
                "series (ingestion/baskets.py) store flat OHLC (high==low), so intraday "
                "hi/lo/range are meaningless — use measure_field='ret'")

    where = ["TRUE"]
    if day is not None:
        where.append(f"r.trigger_dow = {int(day)}")
    if threshold is not None:
        where.append(f"r.trigger_ret <= {float(threshold)}")
    if streak is not None:
        if threshold is not None or worst_n:
            raise ValueError("streak is mutually exclusive with threshold/worst_n")
        where.append(f"r.scount = {int(streak)}")
    if strict_next_dow is not None:
        where.append(f"r.outcome_dow = {int(strict_next_dow)}")
    if since is not None:
        where.append(f"r.trigger_date >= DATE '{pd.Timestamp(since).date()}'")

    cond_ctes, cond_joins = [], ""
    if when:
        cond_ctes, cond_joins, cond_where, cond_series = _compile_condition(when)
        where.append(f"({cond_where})")
        # A conditioner with shorter history than the subject silently truncates
        # the sample (e.g. vix3m starts 2006) — surface that.
        subj_min = conn.execute(f"select min(date) from query_table('{view}')").fetchone()[0]
        for s in cond_series:
            if _view(s) == view:
                continue
            smin = conn.execute(f"select min(date) from query_table('{_view(s)}')").fetchone()[0]
            if smin and subj_min and smin > subj_min:
                warnings.warn(f"when={when!r}: sample limited to {smin}+ by '{s}' "
                              f"(subject '{view}' starts {subj_min})")
    where_sql = " AND ".join(where)

    order, limit = (("r.trigger_ret ASC", f"LIMIT {int(worst_n)}") if worst_n
                    else ("r.trigger_date DESC", ""))

    if streak is not None:
        # Per-day predicate = direction (close vs prior close) AND optional gap
        # qualifier (open vs prior close); consecutive-run counter via the
        # gaps-and-islands trick; the trigger fires where the run count == N.
        dirt = "close < pc" if streak_dir == "down" else "close > pc"
        gapt = {"up": " AND open > pc", "down": " AND open < pc", None: ""}[streak_gap]
        src = f"""(
        WITH raw AS (
            SELECT date, open, high, low, close, adj_close,
                   LAG(close) OVER (ORDER BY date) AS pc
            FROM query_table('{view}')
        ), flag AS (
            SELECT *, CASE WHEN pc IS NOT NULL AND {dirt}{gapt} THEN 1 ELSE 0 END AS hit
            FROM flag_src
        ), grp AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY date)
                      - SUM(hit) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING) AS gid
            FROM flag
        )
        SELECT *, CASE WHEN hit = 1 THEN ROW_NUMBER() OVER (PARTITION BY gid, hit ORDER BY date) END AS scount
        FROM grp)""".replace("FROM flag_src", "FROM raw")
        scount_col = ",\n            scount"
    else:
        src = f"query_table('{view}')"
        scount_col = ""

    cte_block = f"""WITH r AS (
        SELECT
            date                                AS trigger_date,
            isodow(date)                        AS trigger_dow,
            {px} / LAG({px}) OVER w - 1         AS trigger_ret,
            LEAD(date,  {h}) OVER w             AS outcome_date,
            isodow(LEAD(date, {h}) OVER w)      AS outcome_dow,
            {outcome_expr}  AS outcome_ret{scount_col}
        FROM {src}
        WINDOW w AS (ORDER BY date)
    )"""
    if cond_ctes:
        cte_block += ",\n    " + ",\n    ".join(cond_ctes)

    sql = f"""
    {cte_block}
    SELECT r.trigger_date, r.trigger_dow, r.trigger_ret,
           r.outcome_date, r.outcome_dow, r.outcome_ret
    FROM r
        {cond_joins}
    WHERE {where_sql}
    ORDER BY {order}
    {limit}
    """
    return conn.execute(sql).df()


def summarize_event(df, label="event"):
    """Significance stats on the outcome returns (pending/NULL outcomes dropped)."""
    r = df["outcome_ret"].dropna().to_numpy(dtype="float64")
    return summarize(r, label=label)


def compare_regimes(conn, symbol, regimes, **kw):
    """Run the same event_study under several `when=` gates and stack the stats.

    regimes: dict {label: when_string_or_None}. Pass None for the unconditional
    baseline. Returns a DataFrame, one row per regime (n, win_rate=next-day up
    rate, mean_pct, t_stat, ci, ...) — the regime-comparison table.

        compare_regimes(conn, "spy", {
            "all": None, "uptrend": "spy>spy_200dma", "downtrend": "spy<spy_200dma",
        }, threshold=-0.03)
    """
    rows = [summarize_event(event_study(conn, symbol, when=w, **kw), label)
            for label, w in regimes.items()]
    return pd.DataFrame(rows)


_TOK = re.compile(r"[a-z][a-z0-9]*(?:_ret_prev|_ret|_prev|_\d+dma)?")


def _parse_tok(t):
    m = re.fullmatch(r"([a-z][a-z0-9]*?)(_ret_prev|_ret|_prev|_(\d+)dma)?", t)
    return m.group(1), m.group(2), (int(m.group(3)) if m.group(3) else None)


def sequence(conn, legs, subject, *, anchor_day=None, measure_offset=1,
             measure_field="ret", since=None):
    """Multi-session sequence event study — chain conditions across CONSECUTIVE
    trading sessions, then measure `subject` a few sessions later.

    legs : list; each element is a condition string (or list of strings = AND)
           that must hold on successive sessions starting at the anchor. Same
           grammar as event_study's when= : "spy_ret<=-0.025", "spy_ret<0",
           "spy>spy_200dma", "vix>30", "gold_up".
    subject        : series whose move is the outcome.
    anchor_day     : isodow constraint on the FIRST leg's session (e.g. FRI).
    measure_offset : sessions AFTER the last leg to measure (1 = next session,
                     0 = the last leg's own session).
    measure_field  : 'ret'  close-to-close return |
                     'hi'    intraday HIGH vs prior close (max favorable) |
                     'lo'    intraday LOW  vs prior close (max adverse) |
                     'range' (high-low)/prior close (intraday range).
    since          : ISO date lower bound on the anchor session.

    Returns one row per match: anchor_date, anchor_dow, measure_date,
    measure_dow, outcome_ret (fraction). Pipe to summarize_event() for stats.

        # Tuesday after [Fri SPY <= -2.5%] -> [red Monday], measured on XLE:
        sequence(conn, ["spy_ret<=-0.025", "spy_ret<0"], "xle",
                 anchor_day=FRI, measure_offset=1)
    """
    legs = [leg if isinstance(leg, list) else [leg] for leg in legs]
    subj = _view(subject)

    def translate(c):
        c = re.sub(r"([a-z0-9]+)_up\b", r"(\1_ret>0)", c.strip().lower())
        return re.sub(r"([a-z0-9]+)_down\b", r"(\1_ret<0)", c)

    leg_conds = [[translate(c) for c in leg] for leg in legs]
    tokens = set()
    for leg in leg_conds:
        for c in leg:
            tokens.update(_TOK.findall(c))
    bases = {_parse_tok(t)[0] for t in tokens} | {subj}

    need_ohlc = measure_field in ("hi", "lo", "range")
    if need_ohlc:
        flat = conn.execute(f"select avg((high = low)::int) from {subj}").fetchone()[0]
        if flat is not None and flat > 0.95:
            raise ValueError(
                f"measure_field={measure_field!r} is unavailable for '{subj}': synthetic basket "
                "series (ingestion/baskets.py) store flat OHLC (high==low) — use measure_field='ret'")
    frames, mins = [], {}
    for b in bases:
        if b == subj and need_ohlc:
            d = conn.execute(f"select date, close, high, low from {b} order by date").df()
            d = d.rename(columns={"close": b + "__c", "high": b + "__h", "low": b + "__l"})
        else:
            d = conn.execute(f"select date, close from {b} order by date").df().rename(columns={"close": b + "__c"})
        frames.append(d.set_index("date"))
        mins[b] = frames[-1].index.min()
    J = pd.concat(frames, axis=1, join="inner").sort_index()
    lim = max(mins, key=lambda k: mins[k])
    if mins[lim] > mins[subj]:
        warnings.warn(f"sequence(): sample limited to {mins[lim]}+ by '{lim}' "
                      f"(subject '{subj}' starts {mins[subj]})")
    J.index = pd.to_datetime(J.index)
    if since:
        J = J[J.index >= pd.Timestamp(since)]

    for t in tokens:
        base, feat, n = _parse_tok(t)
        c = J[base + "__c"]
        J[t] = c if feat is None else (c.pct_change() if feat == "_ret"
                                       else c.pct_change().shift(1) if feat == "_ret_prev"
                                       else c.shift(1) if feat == "_prev" else c.rolling(n).mean())

    dow = (J.index.dayofweek + 1).to_numpy()      # isodow Mon=1..Sun=7
    N = len(J)
    combined = np.ones(N, dtype=bool)
    for k, leg in enumerate(leg_conds):
        mk = np.ones(N, dtype=bool)
        for c in leg:
            mk &= J.eval(c).to_numpy()
        combined &= np.concatenate([mk[k:], np.zeros(k, dtype=bool)]) if k else mk
    if anchor_day is not None:
        combined &= (dow == int(anchor_day))

    pc = J[subj + "__c"].to_numpy()
    prev = np.concatenate([[np.nan], pc[:-1]])
    if measure_field == "ret":
        meas = pc / prev - 1
    elif measure_field == "hi":
        meas = J[subj + "__h"].to_numpy() / prev - 1
    elif measure_field == "lo":
        meas = J[subj + "__l"].to_numpy() / prev - 1
    elif measure_field == "range":
        meas = (J[subj + "__h"].to_numpy() - J[subj + "__l"].to_numpy()) / prev
    else:
        raise ValueError(f"measure_field {measure_field!r} not in ret/hi/lo/range")

    L = len(legs)
    idx = np.where(combined)[0]
    mpos = idx + (L - 1) + int(measure_offset)
    ok = mpos < N
    idx, mpos = idx[ok], mpos[ok]
    return pd.DataFrame({
        "anchor_date": [J.index[i].date() for i in idx],
        "anchor_dow": dow[idx],
        "measure_date": [J.index[p].date() for p in mpos],
        "measure_dow": dow[mpos],
        "outcome_ret": meas[mpos],
    })


def render(df, trigger_label="Trigger", outcome_label="Outcome"):
    """Pretty fixed-width table mirroring the OddStats layout."""
    head = f"{trigger_label:<17}{'Ret':>9}    {outcome_label:<17}{'Ret':>9}"
    lines = [head, "-" * len(head)]
    for row in df.itertuples():
        td = f"{_DOW_NAME[row.trigger_dow]} {str(row.trigger_date)[:10]}"
        tr = f"{row.trigger_ret * 100:+.2f}%"
        if pd.isna(row.outcome_ret) or pd.isna(row.outcome_date):
            od, orr = "(pending)", "?"
        else:
            od = f"{_DOW_NAME[row.outcome_dow]} {str(row.outcome_date)[:10]}"
            orr = f"{row.outcome_ret * 100:+.2f}%"
        lines.append(f"{td:<17}{tr:>9}    {od:<17}{orr:>9}")
    return "\n".join(lines)


if __name__ == "__main__":
    import db

    conn = db.connect()
    # NASDAQ-100 (^NDX) reproduces the OddStats table exactly; "NASDAQ" in such
    # posts is usually the NDX-100, not the Composite (^IXIC).
    tbl = event_study(conn, "ndx", day=FRI, threshold=-0.0475)
    print("\nMondays after terrible Fridays for the NASDAQ-100 (^NDX), Friday <= -4.75%\n")
    print(render(tbl, "Friday", "Next session"))
    print()
    print(summarize_event(tbl, "NDX next session after Friday <= -4.75%"))
