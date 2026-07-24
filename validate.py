"""
Data + artifact integrity scan. Run after every update; exits 1 on any FAIL.

Checks: (a) staleness vs the freshest series, (b) duplicate dates, (c) non-positive
prices, (d) inverted high/low bars, (e) calendar gaps >10 days, (f) view-name
uniqueness, (g) basket parquets flat-OHLC exactly as expected (and nothing else),
(h) cube/data.js as_of == max(spy date).

    ./.venv/bin/python validate.py
"""
import re
import sys
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from ingestion.baskets import BASKETS
from ingestion.recos import LEDGER

DATA = Path(__file__).parent / "data" / "daily"
REPORTS = Path.home() / "Desktop/Obsidian/trading-brain/reports"
DELISTED: set = set()  # stems exempt from the staleness check

# Staleness is graded, because Yahoo routinely stalls the history endpoint for a
# handful of thin symbols while still quoting them live (seen 2026-07: VIX3M,
# SATS, FIVG, IGN froze at 07-17 with working quotes). Halting an unattended
# daily job over 4 files in 703 would mean the site stops updating for weeks over
# nothing. So a few stale series warn; the spine going stale, or staleness
# spreading, still fails hard.
CORE = {"SPY", "QQQ", "GSPC", "NDX", "IXIC", "VIX",
        "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLC", "XLP", "XLU", "XLRE", "XLB"}
STALE_TOLERANCE = 0.02  # fraction of all series allowed stale before it's a failure


def main():
    con = duckdb.connect()
    q = con.execute(f"""
        select regexp_extract(filename,'([^/]+)\\.parquet$',1) tkr,
               count(*) n, min(date) lo, max(date) hi,
               count(*)-count(distinct date) dup_dates,
               sum((open<=0 or high<=0 or low<=0 or close<=0)::int) bad_px,
               sum((high<low)::int) hl_inv,
               sum((high=low)::int) flat_rows,
               max(date_diff('day', lag_d, date)) max_gap
        from (select *, lag(date) over (partition by filename order by date) lag_d, filename
              from read_parquet('{DATA}/*.parquet', filename=true))
        group by 1
    """).df()
    fails = []
    warns = []

    def check(name, bad, detail="", fatal=True):
        ok = len(bad) == 0
        tag = "PASS" if ok else ("FAIL" if fatal else "WARN")
        extra = "" if ok else f" — {len(bad)}: {', '.join(map(str, bad[:8]))}{detail}"
        print(f"  [{tag}] {name}{extra}")
        if not ok:
            (fails if fatal else warns).append(name)

    ref = q.hi.max()
    thresh = ref - timedelta(days=3)
    print(f"files: {len(q)} · freshest date: {ref} · staleness threshold: {thresh}")
    stale = q[(q.hi < thresh) & (~q.tkr.isin(DELISTED))].tkr.tolist()
    core_stale = sorted(set(stale) & CORE)
    if core_stale:
        check("staleness (core series)", core_stale)
    else:
        widespread = len(stale) > STALE_TOLERANCE * len(q)
        check("staleness", stale,
              detail=f" (limit {int(STALE_TOLERANCE * len(q))})" if widespread else "",
              fatal=widespread)
    check("duplicate dates", q[q.dup_dates > 0].tkr.tolist())
    check("non-positive prices", q[q.bad_px > 0].tkr.tolist())
    check("inverted high/low", q[q.hl_inv > 0].tkr.tolist())
    # TSE names (JP* stems) and the japan basket legitimately close for Japan's
    # Golden Week — up to ~10 consecutive sessions (~11 calendar days, e.g. the
    # 2019 imperial-transition closure), so they get a wider gap tolerance.
    # International headline indices close for long local holidays (Shanghai's
    # ~3-week 1999 Spring Festival, Taiwan/Korea Lunar New Year + Chuseok), so
    # they get a generous 22-day allowance — verified genuine market closures.
    FOREIGN_IDX = {"N225", "KS11", "TWII", "SSEC", "HSI", "FTSE"}
    def gap_limit(t):
        if str(t) in FOREIGN_IDX: return 22
        if str(t).startswith("JP") or t == "japan": return 12
        return 10
    gap_bad = [t for t, g in zip(q.tkr, q.max_gap) if pd.notna(g) and g > gap_limit(t)]
    check("calendar gap > 10 days", gap_bad)

    stems = [p.stem for p in DATA.glob("*.parquet")]
    views = [s.lower().replace("-", "_").replace("^", "") for s in stems]
    check("view-name uniqueness", sorted({v for v in views if views.count(v) > 1}))

    # synthetic index parquets that are flat-OHLC by construction: the equal-weight
    # baskets, plus each reco book's index level ('{book}_reco').
    flat_ok = set(BASKETS) | {f"{b}_reco" for b in LEDGER}
    frac = (q.set_index("tkr").flat_rows / q.set_index("tkr").n)
    non_flat_baskets = [b for b in BASKETS if b in frac.index and frac[b] < 1.0]
    unexpected_flat = [t for t, v in frac.items() if t not in flat_ok and v > 0.99]
    check("basket flat-OHLC whitelist", non_flat_baskets + unexpected_flat)

    spy_max = str(con.execute(f"select max(date) from read_parquet('{DATA}/SPY.parquet')").fetchone()[0])

    def as_of(fname, pat):
        p = REPORTS / fname
        m = re.search(pat, p.read_text()) if p.exists() else None
        return m.group(1) if m else None

    cube = as_of("cube/index.js", r'"as_of":"([^"]+)"')
    djs = as_of("trader-profile-data.js", r'"as_of": ?"([^"]+)"')
    check("artifact as_of consistency",
          [] if cube == djs == spy_max else [f"spy={spy_max}", f"cube={cube}", f"data.js={djs}"])

    if warns:
        print(f"WARNINGS: {warns}")
    print("ALL CHECKS PASSED" if not fails else f"FAILED: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
