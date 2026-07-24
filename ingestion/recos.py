"""
Recommendation track-record engine for the coverage lists.

A coverage list (mycoverage / fredcoverage) has an overlaid *recommendation book*:
up to 5 slots, each holding one name at a time, entered on its recommendation
date and exited when swapped out. Unlike a basket (a static bag of tickers), the
book is a time-stamped ledger of calls, and its headline metric banks realized
returns permanently.

Headline metric (user's definition):

    M(t) = ( sum of the return of EVERY recommendation, past and present ) / 5

where each recommendation's return runs from its entry close to its exit close
(frozen there) for a closed call, or to the latest close for an open one. It is
an ARITHMETIC sum of simple returns (not compounding) normalised by the fixed
slot count 5, so a swapped-out winner's realized return stays in the sum forever
and stacks additively on top of its replacement. Shipped as an index level
100*(1+M) so it charts next to everything else (100 = flat book).

The ledger is a flat list of dated swaps; slots never need pairing, because the
metric sums over held windows regardless of which slot held them. A name's held
windows (bold on the chart) and idle windows (ghost — priced as if still held,
display only, NOT in the sum) both fall out of the same walk.

    python -m ingestion.recos            # verify + print the book
    python -m ingestion.recos --build    # also write the synthetic parquet(s)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from config import DAILY_DIR, PRICE_SCALE, file_stem
from ingestion.store import SCHEMA

# ---------------------------------------------------------------------------
# The ledger. Each book: an initiation (date, 5 names) + a dated list of swaps,
# every swap a list of (out, in) pairs. Tickers use their yfinance symbol so
# '.T' names resolve through file_stem to their JP-stem views. All dates 2026.
# ---------------------------------------------------------------------------
LEDGER = {
    "mycoverage": {
        "init": ("2026-04-30", ["GEV", "PWR", "HUBB", "ETN", "STLD"]),
        "swaps": [
            ("2026-05-15", [("HUBB", "FCX"), ("GEV", "FSLR")]),
            ("2026-05-22", [("ETN", "5802.T")]),
            ("2026-06-05", [("5802.T", "HUBB")]),
            ("2026-06-18", [("STLD", "ETN"), ("PWR", "NEM")]),
            ("2026-06-26", [("FCX", "CNP"), ("FSLR", "PWR")]),
            ("2026-07-24", [("NEM", "7011.T")]),
        ],
    },
}
SLOTS = 5


def reco_tickers(book=None):
    """Every ticker ever named in a book (init + both sides of every swap), so the
    fetch step can keep them all live even when a call reaches outside a basket."""
    books = [book] if book is not None else list(LEDGER.values())
    out = set()
    for b in books:
        out.update(b["init"][1])
        for _, pairs in b["swaps"]:
            for o, i in pairs:
                out.add(o); out.add(i)
    return out


def _view(t):
    return file_stem(t).lower().replace("-", "_").replace(".", "_")


def walk(book):
    """Return (instances, events, current).

    instances: list of dicts {ticker, entry, exit(None=open)} — one per held
               window (a name re-recommended later gets a second instance).
    events:    {date -> list of human strings} for the swap markers.
    current:   list of the currently-held tickers (open instances).
    """
    init_date, init_names = book["init"]
    active = {n: init_date for n in init_names}     # ticker -> entry date
    instances = []
    events = {init_date: ["Initiated: " + ", ".join(init_names)]}
    for date, pairs in book["swaps"]:
        lines = []
        for out, inn in pairs:
            if out in active:
                instances.append({"ticker": out, "entry": active.pop(out), "exit": date})
            active[inn] = date
            lines.append(f"{out} → {inn}")
        events.setdefault(date, []).extend(lines)
    for n, entry in active.items():
        instances.append({"ticker": n, "entry": entry, "exit": None})
    return instances, events, list(active.keys())


def held_windows(instances):
    """ticker -> sorted list of (entry, exit|None) held windows (bold segments)."""
    out = {}
    for it in instances:
        out.setdefault(it["ticker"], []).append((it["entry"], it["exit"]))
    for k in out:
        out[k].sort()
    return out


def _closes(conn, ticker):
    df = conn.execute(
        f'SELECT date, close FROM "{_view(ticker)}" WHERE close>0 ORDER BY date'
    ).fetchdf()
    s = pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))
    return s


def price_on(s, date):
    """Close on `date`, else the last close on/before it (handles a swap dated on
    today's not-yet-settled session by falling back to the prior close)."""
    d = pd.Timestamp(date)
    s2 = s[s.index <= d]
    return float(s2.iloc[-1]) if len(s2) else np.nan


def strategy_level(conn, book):
    """Return a pd.Series: the 100*(1+M) index over the book's trading calendar."""
    instances, _, _ = walk(book)
    px = {it["ticker"]: _closes(conn, it["ticker"]) for it in instances}
    start = pd.Timestamp(book["init"][0])
    # trading calendar = union of every ledger ticker's sessions from start on
    cal = sorted(set().union(*[set(s[s.index >= start].index) for s in px.values()]))
    cal = pd.DatetimeIndex(cal)
    lv = []
    for t in cal:
        tot = 0.0
        for it in instances:
            entry = pd.Timestamp(it["entry"])
            if entry > t:
                continue
            end = t if it["exit"] is None else min(t, pd.Timestamp(it["exit"]))
            p0, p1 = price_on(px[it["ticker"]], entry), price_on(px[it["ticker"]], end)
            tot += (p1 / p0 - 1.0)
        lv.append(100.0 * (1.0 + tot / SLOTS))
    return pd.Series(lv, index=cal)


def realized_table(conn, book):
    """Per-instance return table for verification."""
    instances, _, _ = walk(book)
    rows = []
    for it in instances:
        s = _closes(conn, it["ticker"])
        entry = it["entry"]
        end = it["exit"] or str(s.index[-1].date())
        p0, p1 = price_on(s, entry), price_on(s, end)
        rows.append({
            "ticker": it["ticker"], "entry": entry, "exit": it["exit"] or "OPEN",
            "p0": round(p0, 2), "p1": round(p1, 2),
            "ret_%": round((p1 / p0 - 1) * 100, 1),
        })
    return pd.DataFrame(rows)


def build_parquet(conn, name, book):
    lvl = strategy_level(conn, book)
    arr = (lvl * PRICE_SCALE).round().astype("int64").to_numpy()
    df = pd.DataFrame({
        "date": [d.date() for d in lvl.index],
        "open": arr, "high": arr, "low": arr, "close": arr, "adj_close": arr,
        "volume": np.zeros(len(lvl), dtype="int64"),
    })
    out = DAILY_DIR / f"{name}_reco.parquet"
    pq.write_table(pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False),
                   out, compression="snappy")
    return out, lvl


def main():
    conn = db.connect()
    do_build = "--build" in sys.argv
    for name, book in LEDGER.items():
        instances, events, current = walk(book)
        print(f"\n=== {name} — recommendation book ===")
        print("current 5:", ", ".join(current))
        print(f"{len(instances)} instances (held windows); swaps:",
              ", ".join(d for d, _ in book["swaps"]))
        tbl = realized_table(conn, book)
        print(tbl.to_string(index=False))
        summ = tbl["ret_%"].sum()
        print(f"\nsum of all returns = {summ:.1f}%   /{SLOTS} = {summ/SLOTS:.2f}%  "
              f"-> index today = {100*(1+summ/100/SLOTS):.2f}")
        if do_build:
            out, lvl = build_parquet(conn, name, book)
            print(f"wrote {out}  ({len(lvl)} rows, {lvl.index[0].date()}->{lvl.index[-1].date()}, "
                  f"last {lvl.iloc[-1]:.2f})")


if __name__ == "__main__":
    main()
