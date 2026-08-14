"""
One-command refresh pipeline, in strict order:

  1. full re-fetch of every tracked symbol (skip_existing=False — incremental
     append is UNSAFE: closes are auto-adjusted, so any dividend/split rescales
     the entire back-history)
  2. rebuild baskets (levels compound full history, so they MUST follow a fetch)
  3. regenerate the offline cube
  4. regenerate the theme return series (market-lab-themes.html)
  5. regenerate the annual consensus EPS vintages (P/E bands)
  6. regenerate the macro regime masks (market-lab-heatmaps.html)
  7. regenerate the trader-profile data bundle
  8. sync the site copies into web/ and docs/
  9. validate (exits non-zero on any integrity failure)

    ./.venv/bin/python update.py

For an inclusive historical cutoff (yfinance's download end is exclusive):

    QUANT_DATA_THROUGH=2026-07-24 ./.venv/bin/python update.py
"""
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from config import DAILY_DIR, INDEX_SYMBOLS, INDEX_START_DATE, file_stem
from ingestion.fetch import run
from ingestion.tickers import load_tickers
from ingestion.baskets import BASKETS
from ingestion.recos import LEDGER, reco_tickers, build_parquet

MACRO = ["^VIX", "GC=F", "SI=F", "HG=F", "TLT", "IEF", "HYG", "LQD", "^TNX", "^VIX3M", "UUP", "CL=F"]
SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLC", "XLP", "XLU", "XLRE", "XLB"]
THEMATIC_ETFS = ["SMH", "SOXX", "XBI", "IBB", "KRE", "XOP", "OIH", "GDX", "TAN", "ICLN",
                 "XHB", "XRT", "ARKK", "KWEB", "JETS"]
INDUSTRY_ETFS = ["ITA", "IGV", "CIBR", "BOTZ", "IGN", "URA", "XME", "IDRV", "UFO", "GRID",
                 "IBIT", "PAVE", "FIVG"]
# standalone series from the watchlist (not basket members, not in tickers.csv)
EXTRA_SERIES = ["GLD", "SLV", "CPER", "COPX", "URNM", "ETHA", "EEM", "ROBO",
                "TLN", "CRCL", "LCID", "NEO",
                # Tokyo Stock Exchange listings (JPY; TSE calendar). Aliased to
                # SQL-safe stems JP6674/JP7011/JP5802/JP5803 via SYMBOL_ALIASES.
                "6674.T", "7011.T", "5802.T", "5803.T",
                # Korea Exchange listings (KRW; KOSPI calendar).
                "005930.KS", "000660.KS",
                # XETRA listing (EUR); also participates in the gas-power basket.
                "ENR.DE"]


def retry_stale_downloads(symbols, max_lag_days=3):
    """Retry bulk-download laggards one at a time.

    Yahoo occasionally returns a valid but truncated history for a handful of
    symbols inside a large multi-ticker response. Because that is neither empty
    nor an exception, the ordinary fetch reports success and would otherwise
    preserve a stale last bar. Single-symbol requests reliably recover the
    missing tail for active listings; genuinely discontinued feeds simply stay
    stale and remain visible to validate.py.
    """
    import pyarrow.parquet as pq
    import yfinance as yf
    from ingestion.store import store_ticker

    dated = []
    for symbol in symbols:
        path = DAILY_DIR / f"{file_stem(symbol)}.parquet"
        if not path.exists():
            continue
        dates = pq.read_table(path, columns=["date"]).column("date").to_pylist()
        if dates:
            dated.append((symbol, max(dates)))
    if not dated:
        return
    cutoff = max(date for _, date in dated) - timedelta(days=max_lag_days)
    stale = [symbol for symbol, date in dated if date < cutoff]
    if not stale:
        return
    print(f"Retrying {len(stale)} stale bulk results individually: {', '.join(stale)}")
    for symbol in stale:
        # period=max takes Yahoo's single-ticker history path. It avoids the
        # truncated multi-download response while still refreshing the entire
        # adjusted history instead of appending an incompatible raw-price tail.
        for attempt in range(1, 4):
            try:
                frame = yf.download(
                    symbol, period="max", auto_adjust=True, progress=False,
                    group_by="ticker", threads=False,
                )
                if not frame.empty and store_ticker(frame, symbol):
                    break
            except Exception as exc:
                print(f"  [retry {attempt}/3] {symbol}: {exc}")
            if attempt < 3:
                time.sleep(2 ** attempt)
        else:
            print(f"  [stale] {symbol}: single-ticker history unavailable")


def fetch_all():
    run(INDEX_SYMBOLS, start=INDEX_START_DATE, skip_existing=False)
    basket_members = sorted({t for ts in BASKETS.values() for t in ts})
    # reco-book names must stay live even if a call reaches outside every basket
    recos = sorted(reco_tickers())
    tracked = (load_tickers() + MACRO + SECTOR_ETFS + THEMATIC_ETFS + INDUSTRY_ETFS
               + EXTRA_SERIES + basket_members + recos + ["SPY", "QQQ"])
    # Keep legacy single-stock files live even after they leave the current S&P
    # membership or curated baskets. Uppercase orphan stems are Yahoo tickers;
    # lowercase files are synthetic baskets/recommendation indices and must not
    # be sent back to the vendor. Known aliased stems (SPX, JP7011, KR005930,
    # etc.) are already represented by their proper Yahoo symbols above.
    known_stems = {file_stem(symbol) for symbol in list(INDEX_SYMBOLS) + tracked}
    orphan_stocks = [
        path.stem for path in DAILY_DIR.glob("*.parquet")
        if path.stem.isupper() and path.stem not in known_stems
    ]
    rest = sorted(set(tracked + orphan_stocks) - set(INDEX_SYMBOLS))
    run(rest, skip_existing=False)
    retry_stale_downloads(list(INDEX_SYMBOLS) + rest)


def build_recos():
    """Rebuild each reco book's synthetic index, so open positions mark to the
    latest close. Must run after the fetch and before the theme export reads it."""
    import db
    conn = db.connect()
    for name, book in LEDGER.items():
        out, lvl = build_parquet(conn, name, book)
        print(f"  built {out.name}: {len(lvl)} rows -> {lvl.iloc[-1]:.2f}")


def sub(target):
    args = [sys.executable] + ([target] if target.endswith(".py") else ["-m", target])
    r = subprocess.run(args, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"{target} exited {r.returncode}")


REPORTS = Path.home() / "Desktop/Obsidian/trading-brain/reports"
SITE_PAGES = ["market-lab.html", "market-lab.js", "market-lab-baskets.html",
              "market-lab-drawdowns.html", "market-lab-themes.html",
              "market-lab-heatmaps.html", "market-lab-weekend.html",
              "market-lab-leaders.html"]
# Theme Returns and Leaders are maintained as tracked application source. The other legacy
# Market Lab pages still originate in the Obsidian reports folder.
TRACKED_PAGE_SOURCES = {"market-lab-themes.html", "market-lab-leaders.html"}


def sync_site():
    """Copy the market-lab pages + cube data into web/ (source backup) and docs/
    (GitHub Pages payload), stamping ?v=<as_of> on script/data references so
    browsers and the Pages CDN never serve stale JS or menus after an update.
    trader-profile.html is personal and is NOT copied."""
    import hashlib
    import re
    m = re.search(r'"as_of":"([^"]+)"', (REPORTS / "cube" / "index.js").read_text())
    # as_of alone doesn't change when the cube is rebuilt without new market data
    # (e.g. adding a basket), so append a short content hash of the cube payload —
    # otherwise browsers keep serving the stale ?v=<as_of> copy after such a deploy.
    h = hashlib.md5()
    for cf in sorted((REPORTS / "cube").glob("*.js")):
        h.update(cf.read_bytes())
    stamp = (m.group(1) if m else "0").replace("-", "") + "-" + h.hexdigest()[:8]
    pat = re.compile(r'src="(market-lab\.js|cube/(?:index|baskets|drawdowns|themes|pe-bands|regimes|weekend|leaders)\.js)(?:\?v=[^"]*)?"')
    web, docs = ROOT / "web", ROOT / "docs"
    for d in (web, docs):
        d.mkdir(exist_ok=True)
    for p in SITE_PAGES:
        if not p.endswith(".html"):
            shutil.copy2(REPORTS / p, web / p)
            shutil.copy2(REPORTS / p, docs / p)
            continue
        f = (web / p) if p in TRACKED_PAGE_SOURCES else (REPORTS / p)
        # web/ keeps the canonical unstamped page, so the tracked backup only
        # changes when the page itself changes — not on every daily refresh
        raw = pat.sub(r'src="\1"', f.read_text())
        stamped = pat.sub(rf'src="\1?v={stamp}"', raw)
        (web / p).write_text(raw)
        (docs / p).write_text(stamped)
        (REPORTS / p).write_text(stamped)
    cube_dst = ROOT / "docs" / "cube"
    cube_dst.mkdir(exist_ok=True)
    for f in (REPORTS / "cube").glob("*.js"):
        shutil.copy2(f, cube_dst / f.name)
    print(f"synced {len(SITE_PAGES)} pages + cube data → web/ and docs/ "
          "(push to GitHub to refresh the Pages site)")


TOTAL_STEPS = 14


def step(i, name, fn):
    t0 = time.time()
    print(f"\n=== [{i}/{TOTAL_STEPS}] {name} ===", flush=True)
    try:
        fn()
    except Exception as e:
        print(f"*** PIPELINE STOPPED at [{i}/{TOTAL_STEPS}] {name}: {e}")
        sys.exit(1)
    print(f"=== [{i}/{TOTAL_STEPS}] {name} done in {time.time() - t0:.0f}s ===", flush=True)


if __name__ == "__main__":
    step(1, "full re-fetch (all tracked symbols)", fetch_all)
    step(2, "refresh cached earnings dates", lambda: sub("ingestion.earnings"))
    step(3, "rebuild baskets", lambda: sub("ingestion.baskets"))
    step(4, "rebuild reco books (mark open calls to latest close)", build_recos)
    step(5, "regenerate cube", lambda: sub("export.cube"))
    step(6, "regenerate theme return series", lambda: sub("export.themes"))
    step(7, "regenerate annual consensus EPS vintages", lambda: sub("export.pe_bands"))
    step(8, "regenerate weekend review (breadth, scans, gauges)", lambda: sub("export.weekend"))
    step(9, "top up company/sector labels for new names", lambda: sub("ingestion.meta"))
    step(10, "regenerate single-stock leaders screen", lambda: sub("export.leaders"))
    step(11, "regenerate macro regime masks", lambda: sub("export.regimes"))
    step(12, "regenerate trader-profile bundle", lambda: sub("export.trader_profile"))
    step(13, "sync site copies (web/ + docs/ for GitHub Pages)", sync_site)
    step(14, "validate", lambda: sub("validate.py"))
    print("\nUPDATE COMPLETE — all steps passed.")
