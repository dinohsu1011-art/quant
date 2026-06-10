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

sys.path.insert(0, str(Path(__file__).parent))
from ingestion.baskets import BASKETS

DATA = Path(__file__).parent / "data" / "daily"
REPORTS = Path.home() / "Desktop/Obsidian/trading-brain/reports"
DELISTED: set = set()  # stems exempt from the staleness check


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

    def check(name, bad, detail=""):
        ok = len(bad) == 0
        extra = "" if ok else f" — {len(bad)}: {', '.join(map(str, bad[:8]))}{detail}"
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{extra}")
        if not ok:
            fails.append(name)

    ref = q.hi.max()
    thresh = ref - timedelta(days=3)
    print(f"files: {len(q)} · freshest date: {ref} · staleness threshold: {thresh}")
    check("staleness", q[(q.hi < thresh) & (~q.tkr.isin(DELISTED))].tkr.tolist())
    check("duplicate dates", q[q.dup_dates > 0].tkr.tolist())
    check("non-positive prices", q[q.bad_px > 0].tkr.tolist())
    check("inverted high/low", q[q.hl_inv > 0].tkr.tolist())
    check("calendar gap > 10 days", q[q.max_gap > 10].tkr.tolist())

    stems = [p.stem for p in DATA.glob("*.parquet")]
    views = [s.lower().replace("-", "_").replace("^", "") for s in stems]
    check("view-name uniqueness", sorted({v for v in views if views.count(v) > 1}))

    frac = (q.set_index("tkr").flat_rows / q.set_index("tkr").n)
    non_flat_baskets = [b for b in BASKETS if b in frac.index and frac[b] < 1.0]
    unexpected_flat = [t for t, v in frac.items() if t not in BASKETS and v > 0.99]
    check("basket flat-OHLC whitelist", non_flat_baskets + unexpected_flat)

    spy_max = str(con.execute(f"select max(date) from read_parquet('{DATA}/SPY.parquet')").fetchone()[0])

    def as_of(fname, pat):
        p = REPORTS / fname
        m = re.search(pat, p.read_text()) if p.exists() else None
        return m.group(1) if m else None

    cube = as_of("trader-profile-cube.js", r'"as_of":"([^"]+)"')
    djs = as_of("trader-profile-data.js", r'"as_of": ?"([^"]+)"')
    check("artifact as_of consistency",
          [] if cube == djs == spy_max else [f"spy={spy_max}", f"cube={cube}", f"data.js={djs}"])

    print("ALL CHECKS PASSED" if not fails else f"FAILED: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
