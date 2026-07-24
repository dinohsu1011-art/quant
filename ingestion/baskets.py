"""
Build equal-weight, daily-rebalanced BASKET index series for AI/chip value-chain
themes that have no clean ETF. Each basket becomes a synthetic parquet (an index
level stored in the price columns) so it plugs straight into db.py views,
event_study, and the cube — queryable by its name (e.g. 'gpu', 'semicap').

Constituents not already in the dataset are pulled from yfinance first. The basket
return each day is the equal-weight mean of its available constituents' daily
returns (so the basket broadens as names IPO), compounded into a level from 100.

    python -m ingestion.baskets
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
from ingestion.fetch import run
from ingestion.store import SCHEMA

# Theme baskets (user's categorization; reorganized 2026-07-23). US listings only
# — foreign exchanges (KRX 000660/005930, ASX BHP, SWX ABBN, OTC SMERY/SBGSY) are
# excluded for trading-calendar alignment; HG excluded (Hamilton Insurance,
# mis-tagged). The AI/semis taxonomy stays STRICT — each chip/software name lives
# in exactly ONE basket, so its single home is its highest-signal theme (AMD→gpu,
# AVGO/MRVL→cpuasic, ANET→networking, VRT→aiserver, PLTR→software). The broad
# sector/theme cuts (utilities, japan, gas, mycoverage) are allowed to OVERLAP
# that taxonomy and each other — a name can appear in its home basket AND in a
# cross-cutting theme (e.g. GEV/CAT/CMI in elecind AND gas, 7011 in japan AND gas).
# `mycoverage` is the user's personal watchlist and overlaps nearly everything by
# design. Overlap is only a curation choice; the build handles repeats fine.
BASKETS = {
    # chips & AI value chain
    "gpu":          ["NVDA", "AMD", "TSM"],
    "cpuasic":      ["INTC", "AVGO", "MRVL", "QCOM", "ARM"],
    "memory":       ["MU", "WDC", "STX", "SNDK", "PENG", "MRAM"],
    "semicap":      ["AMAT", "LRCX", "KLAC", "ASML", "KLIC"],
    "powersemi":    ["ON", "MPWR", "STM", "POWI", "ALGM", "WOLF", "NXPI", "DIOD", "AOSL", "VSH"],
    "photonics":    ["COHR", "LITE", "FN", "AXTI", "AAOI", "GLW", "VIAV"],
    "connectivity": ["CRDO", "ALAB"],
    "networking":   ["CSCO", "ANET"],
    # compute, cloud & software
    "aiserver":     ["SMCI", "DELL", "HPE", "VRT", "AAPL", "IBM"],
    "hyperscale":   ["MSFT", "GOOGL", "AMZN", "META", "ORCL"],
    "neocloud":     ["CRWV", "NBIS", "APLD", "IREN", "DOCN", "CIFR"],
    "cdnedge":      ["NET", "AKAM", "FSLY"],
    "software":     ["CRM", "NOW", "ADBE", "INTU", "WDAY", "SNOW", "DDOG", "MDB",
                     "TEAM", "SHOP", "HUBS", "TWLO", "GTLB", "PATH", "RDDT", "PLTR"],
    "cyber":        ["PANW", "CRWD", "S", "OKTA", "ZS"],
    # physical economy / electrification
    "elecind":      ["ETN", "GEV", "CAT", "CMI", "AME", "HUBB", "GNRC", "MOD", "ENS", "POWL"],
    "epc":          ["PWR", "EME", "MTZ", "FIX", "STRL", "PRIM", "IESC", "MYRG", "FLR", "J", "ECG"],
    "nuclear":      ["CCJ", "CEG", "BWXT", "OKLO", "NXE", "LEU", "SMR", "UUUU", "XE"],
    "solutil":      ["FSLR", "NXT", "ARRY", "SHLS", "FLNC", "EOSE", "CWEN", "BE", "PLUG", "FCEL", "BEP"],
    "solresi":      ["ENPH", "SEDG", "RUN"],
    # regulated utilities + merchant power / IPPs (CEG lives in `nuclear`, its
    # highest-signal home, so it's intentionally not repeated here).
    "utilities":    ["NEE", "SO", "DUK", "D", "AEP", "VST", "EXC", "PEG", "XEL", "ED",
                     "SRE", "PCG", "EIX", "WEC", "ETR", "DTE", "PPL", "AEE", "FE", "ES",
                     "CMS", "LNT", "AES", "NI", "EVRG", "ATO", "PNW", "CNP", "NRG"],
    # aero, defense & frontier
    "defense":      ["LMT", "RTX", "NOC", "GD", "LHX", "HII", "BA", "TXT", "LDOS", "TDG", "HEI",
                     "CW", "OSK", "KTOS", "MRCY", "AVAV", "RCAT", "UMAC", "HWM"],
    "space":        ["IRDM", "RKLB", "ASTS", "LUNR", "RDW", "PL", "FLY", "SPCX"],
    "robotics":     ["ROK", "EMR", "PH", "APH", "ZBRA", "CGNX", "NOVT", "LSCC", "AMBA", "MBLY",
                     "SYM", "AUR", "OUST", "AEVA", "INDI", "TSLA", "XPEV", "SERV", "RR",
                     "ARBE", "KITT", "ALNT", "VPG", "AMBQ"],
    # resources
    "miners":       ["FCX", "SCCO", "NEM", "TECK", "HBM"],
    "materials":    ["MP", "ALB", "NUE", "STLD", "CLF", "USAR", "SOLS"],
    # Japan — the one deliberate exception to the US-listings rule. These trade on
    # the Tokyo calendar; the basket level is built from the members' mutual TSE
    # returns (they share a calendar), and only aligns loosely with US series when
    # charted together. Members carry '.T' (yfinance) and alias to jpNNNN views.
    "japan":        ["6674.T", "7011.T", "5802.T", "5803.T"],
    # Gas-power equipment: heavy-duty turbine / genset / fuel-cell OEMs that sell
    # the kit gas-fired generation is built from. A cross-cutting theme, so it
    # overlaps by design — GEV/CAT/CMI/GNRC keep their elecind home, BE its
    # solutil home, 7011 its japan home. Two European OEMs (Siemens Energy ENR.DE,
    # Wärtsilä WRT1V.HE) trade on XETRA/Helsinki calendars, aliased to SQL-safe
    # stems; they align only loosely with the US-session names when charted.
    # INIO (Innio, Jenbacher/Waukesha gas engines) and FPS (Forgent Power) are
    # 2026 IPOs, so their lines only start mid-2026.
    "gas":          ["GEV", "CAT", "CMI", "BE", "GNRC", "7011.T", "ENR.DE", "WRT1V.HE",
                     "INIO", "FPS"],
    # Personal coverage watchlist (user-curated, from the image list + SPCX). Mixes
    # US and TSE (6674/5802/5803) names, so the level is built from their mutual
    # sessions and only loosely aligns across calendars — it's a tracker, not an
    # investable index. Overlaps every other basket by design.
    "mycoverage":   ["DELL", "HWM", "CEG", "TSLA", "VST", "CNP", "ETN", "VRT", "CMI",
                     "GEV", "PWR", "HUBB", "FIX", "EME", "CAT", "6674.T", "5802.T",
                     "5803.T", "BE", "GLW", "SPCX"],
}


def _view(t):
    # file_stem first, so aliased symbols ('6674.T' -> 'JP6674') resolve to their
    # real view name instead of an unmatched '6674.t'.
    return file_stem(t).lower().replace("-", "_")


def _views(conn):
    return {r[0] for r in conn.execute("select table_name from information_schema.tables").fetchall()}


def main():
    conn = db.connect()
    have = _views(conn)
    allc = sorted({t for ts in BASKETS.values() for t in ts})
    missing = [t for t in allc if _view(t) not in have]
    if missing:
        print("Pulling missing constituents:", missing)
        run(missing, skip_existing=False)
        conn = db.connect()
        have = _views(conn)

    print("\nBuilding baskets:")
    for name, tickers in BASKETS.items():
        cols, avail = {}, []
        for t in tickers:
            if _view(t) not in have:
                print(f"  [miss] {name}: {t} unavailable"); continue
            d = conn.execute(f'select date, close from "{_view(t)}" order by date').df()
            d["date"] = pd.to_datetime(d["date"])
            cols[t] = d.set_index("date")["close"]
            avail.append(t)
        if not cols:
            print(f"  [skip] {name}: no constituents available"); continue
        px = pd.concat(cols, axis=1, sort=False).sort_index()
        eq = px.pct_change().mean(axis=1, skipna=True).fillna(0.0)
        level = 100.0 * (1.0 + eq).cumprod()
        lvl = (level * PRICE_SCALE).round().astype("int64").to_numpy()
        df = pd.DataFrame({
            "date": [d.date() for d in level.index],
            "open": lvl, "high": lvl, "low": lvl, "close": lvl, "adj_close": lvl,
            "volume": np.zeros(len(level), dtype="int64"),
        })
        pq.write_table(pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False),
                       DAILY_DIR / f"{name}.parquet", compression="snappy")
        print(f"  {name:11} {','.join(avail):40} {str(level.index.min().date())}→  {len(level)} rows")


if __name__ == "__main__":
    main()
