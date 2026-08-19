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
from ingestion.recos import LEDGER, walk
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
    # MRVL sits here as well as in cpuasic: its custom silicon is the ASIC story,
    # its optical DSP and interconnect is the connectivity one. A name is allowed
    # in two baskets, and leaving it out of this one made a two-name theme.
    "connectivity": ["CRDO", "ALAB", "MRVL"],
    "networking":   ["CSCO", "ANET"],
    # compute, cloud & software
    "aiserver":     ["SMCI", "DELL", "HPE", "VRT", "AAPL", "IBM"],
    "hyperscale":   ["MSFT", "GOOGL", "AMZN", "META", "ORCL"],
    "neocloud":     ["CRWV", "NBIS", "APLD", "IREN", "DOCN", "CIFR"],
    "cdnedge":      ["NET", "AKAM", "FSLY"],
    "software":     ["CRM", "NOW", "ADBE", "INTU", "WDAY", "SNOW", "DDOG", "MDB",
                     "TEAM", "SHOP", "HUBS", "TWLO", "GTLB", "PATH", "RDDT", "PLTR"],
    "cyber":        ["PANW", "CRWD", "S", "OKTA", "ZS"],
    # Pure-play biotechnology rather than broad pharmaceuticals or life-science
    # tools. The first half is the commercial large/mid-cap leadership cohort;
    # the second captures newer RNA, gene-editing, oncology and platform names.
    # Equal weighting keeps AMGN/GILD from turning this into another cap-weighted
    # IBB while still giving the clinical-stage companies a diversified basket.
    "biotech":      ["AMGN", "GILD", "VRTX", "REGN", "BIIB", "ALNY", "UTHR", "ARGX",
                     "INSM", "BMRN", "NBIX", "INCY", "MRNA", "CRSP", "BEAM", "NTLA",
                     "RXRX", "RVMD", "VKTX", "TWST"],
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
    # Copper, gold and silver producers plus the three major precious-metals
    # royalty/streaming companies. Keep this to liquid US listings so every
    # constituent shares the basket's trading calendar. Barrick trades as B
    # (not GOLD) on the NYSE since May 2025; GOLD remains the repo's GC=F stem.
    "miners":       [
        # copper / diversified copper-gold
        "FCX", "SCCO", "TECK", "HBM", "ERO", "B",
        # gold producers
        "NEM", "AEM", "KGC", "AU", "GFI", "BTG", "IAG",
        # silver producers
        "PAAS", "AG", "HL", "CDE", "EXK",
        # royalties and streaming
        "RGLD", "FNV", "WPM",
    ],
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
    # Personal coverage watchlist (user-curated). Mixes US and TSE (7011/5802/
    # 5803/6501) names, so the level is built from their mutual sessions and only
    # loosely aligns across calendars — it's a tracker, not an investable index.
    # Overlaps every other basket by design.
    # The book takes over from `coverage1` at the 2026-08-22 close (HANDOFFS in
    # export/themes.py): the electricals/utilities cut narrowed and the six
    # mega-cap platforms came in, so the list is no longer a power-only book.
    "mycoverage":   ["GEV", "7011.T", "TSLA", "PWR", "CAT", "BE", "ETN", "5802.T",
                     "VRT", "GLW", "5803.T", "6501.T", "FLEX", "GOOGL", "MSFT",
                     "META", "AMZN", "ORCL", "SPCX", "AAPL"],
    # The prior personal coverage book (20 names), kept as a fixed reference vs
    # the live `mycoverage` ("Active Coverage"). The themes page anchors it to
    # 2026-04-30 and hands off to the active book on the switch date — see
    # HANDOFFS in export/themes.py. Equal-weight, same tracker semantics.
    "coverage1":    ["AME", "EMR", "ETN", "FSLR", "GEV", "HUBB", "HWM", "PWR",
                     "TSLA", "5802.T", "7011.T", "ED", "CEG", "CNP", "DUK",
                     "NRG", "VST", "FCX", "NEM", "STLD"],
    # A second personal watchlist (semis / memory / semicap value chain), same
    # cross-calendar tracker semantics as `mycoverage`. The four .T names
    # (6857 Advantest, 6981 Murata, 8035 Tokyo Electron, 4062 Ibiden) trade on
    # the TSE and align only loosely with the US names when charted.
    "fredcoverage": ["MU", "WDC", "SNDK", "STX", "ANET", "CSCO", "MRVL", "NVDA",
                     "AMD", "AVGO", "INTC", "AMAT", "ASML", "TER", "LITE", "COHR",
                     "6857.T", "6981.T", "8035.T", "4062.T"],
    # Fred's prior book — the same 20 slots before six mega-cap/software names
    # (META, AAPL, MSFT, GOOGL, ORCL, AMZN) were swapped out for six semis
    # (COHR, LITE, STX, SNDK, MRVL, INTC). Still the live book; `fredcoverage`
    # is labelled "Active" but hasn't taken over yet — see HANDOFFS.
    "fredcoverage1": ["MU", "WDC", "ANET", "CSCO", "NVDA", "AMD", "AVGO", "AMAT",
                      "ASML", "TER", "6857.T", "6981.T", "8035.T", "4062.T",
                      "META", "AAPL", "MSFT", "GOOGL", "ORCL", "AMZN"],
}

# The five names each book is holding *right now*, as an ordinary equal-weight
# basket. `{book}_reco` already ships the book's realized track record — every
# call ever made, banked; this is the different question of how the current five
# behave together, and it can be charted back before any of them were picked.
#
# Derived from the ledger rather than typed out, so a swap can never leave a
# stale hand-written list behind: edit LEDGER, rebuild, and this follows.
for _book, _spec in LEDGER.items():
    BASKETS[f"{_book}_reco5"] = list(walk(_spec)[2])


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
        # Build the basket on both bases, from the same constituents on the same
        # days, so a basket carries the price/total distinction its members do.
        # Compounding an equal-weight mean of daily returns twice is the only
        # honest way to do it: the ratio of two finished levels is not the mean
        # of the members' dividend factors once weights drift intraperiod.
        cols, adj_cols, avail = {}, {}, []
        for t in tickers:
            if _view(t) not in have:
                print(f"  [miss] {name}: {t} unavailable"); continue
            d = conn.execute(
                f'select date, close, adj_close from "{_view(t)}" order by date'
            ).df()
            d["date"] = pd.to_datetime(d["date"])
            d = d.set_index("date")
            cols[t], adj_cols[t] = d["close"], d["adj_close"]
            avail.append(t)
        if not cols:
            print(f"  [skip] {name}: no constituents available"); continue

        def _level(frames):
            px = pd.concat(frames, axis=1, sort=False).sort_index()
            eq = px.pct_change().mean(axis=1, skipna=True).fillna(0.0)
            return 100.0 * (1.0 + eq).cumprod()

        level = _level(cols)              # price return  -> close
        adj_level = _level(adj_cols)      # total return  -> adj_close
        lvl = (level * PRICE_SCALE).round().astype("int64").to_numpy()
        adj = (adj_level.reindex(level.index) * PRICE_SCALE).round().astype("int64").to_numpy()
        df = pd.DataFrame({
            "date": [d.date() for d in level.index],
            "open": lvl, "high": lvl, "low": lvl, "close": lvl, "adj_close": adj,
            "volume": np.zeros(len(level), dtype="int64"),
        })
        pq.write_table(pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False),
                       DAILY_DIR / f"{name}.parquet", compression="snappy")
        print(f"  {name:11} {','.join(avail):40} {str(level.index.min().date())}→  {len(level)} rows")


if __name__ == "__main__":
    main()
