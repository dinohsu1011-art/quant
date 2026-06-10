"""
One-command refresh pipeline, in strict order:

  1. full re-fetch of every tracked symbol (skip_existing=False — incremental
     append is UNSAFE: closes are auto-adjusted, so any dividend/split rescales
     the entire back-history)
  2. rebuild baskets (levels compound full history, so they MUST follow a fetch)
  3. regenerate the offline cube
  4. regenerate the trader-profile data bundle
  5. validate (exits non-zero on any integrity failure)

    ./.venv/bin/python update.py
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from config import INDEX_SYMBOLS, INDEX_START_DATE
from ingestion.fetch import run
from ingestion.tickers import load_tickers
from ingestion.baskets import BASKETS

MACRO = ["^VIX", "GC=F", "SI=F", "HG=F", "TLT", "IEF", "HYG", "LQD", "^TNX", "^VIX3M", "UUP", "CL=F"]
SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLC", "XLP", "XLU", "XLRE", "XLB"]
THEMATIC_ETFS = ["SMH", "SOXX", "XBI", "IBB", "KRE", "XOP", "OIH", "GDX", "TAN", "ICLN",
                 "XHB", "XRT", "ARKK", "KWEB", "JETS"]
INDUSTRY_ETFS = ["ITA", "IGV", "CIBR", "BOTZ", "IGN", "URA", "XME", "IDRV", "UFO", "GRID",
                 "IBIT", "PAVE", "FIVG"]
# standalone series from the watchlist (not basket members, not in tickers.csv)
EXTRA_SERIES = ["GLD", "SLV", "CPER", "COPX", "URNM", "ETHA", "EEM", "ROBO",
                "TLN", "CRCL", "LCID", "NEO"]


def fetch_all():
    run(INDEX_SYMBOLS, start=INDEX_START_DATE, skip_existing=False)
    basket_members = sorted({t for ts in BASKETS.values() for t in ts})
    rest = sorted(set(load_tickers() + MACRO + SECTOR_ETFS + THEMATIC_ETFS + INDUSTRY_ETFS
                      + EXTRA_SERIES + basket_members + ["SPY", "QQQ"]) - set(INDEX_SYMBOLS))
    run(rest, skip_existing=False)


def sub(target):
    args = [sys.executable] + ([target] if target.endswith(".py") else ["-m", target])
    r = subprocess.run(args, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"{target} exited {r.returncode}")


REPORTS = Path.home() / "Desktop/Obsidian/trading-brain/reports"
SITE_PAGES = ["market-lab.html", "market-lab.js", "market-lab-baskets.html", "market-lab-drawdowns.html"]


def sync_site():
    """Copy the market-lab pages + cube data into web/ (source backup) and docs/
    (GitHub Pages payload), stamping ?v=<as_of> on script/data references so
    browsers and the Pages CDN never serve stale JS or menus after an update.
    trader-profile.html is personal and is NOT copied."""
    import re
    m = re.search(r'"as_of":"([^"]+)"', (REPORTS / "cube" / "index.js").read_text())
    stamp = (m.group(1) if m else "0").replace("-", "")
    pat = re.compile(r'src="(market-lab\.js|cube/(?:index|baskets|drawdowns)\.js)(?:\?v=[^"]*)?"')
    for p in SITE_PAGES:
        if p.endswith(".html"):
            f = REPORTS / p
            f.write_text(pat.sub(rf'src="\1?v={stamp}"', f.read_text()))
    for dest in (ROOT / "web", ROOT / "docs"):
        dest.mkdir(exist_ok=True)
        for p in SITE_PAGES:
            shutil.copy2(REPORTS / p, dest / p)
    cube_dst = ROOT / "docs" / "cube"
    cube_dst.mkdir(exist_ok=True)
    for f in (REPORTS / "cube").glob("*.js"):
        shutil.copy2(f, cube_dst / f.name)
    print(f"synced {len(SITE_PAGES)} pages + cube data → web/ and docs/ "
          "(push to GitHub to refresh the Pages site)")


def step(i, name, fn):
    t0 = time.time()
    print(f"\n=== [{i}/6] {name} ===", flush=True)
    try:
        fn()
    except Exception as e:
        print(f"*** PIPELINE STOPPED at [{i}/6] {name}: {e}")
        sys.exit(1)
    print(f"=== [{i}/6] {name} done in {time.time() - t0:.0f}s ===", flush=True)


if __name__ == "__main__":
    step(1, "full re-fetch (all tracked symbols)", fetch_all)
    step(2, "rebuild baskets", lambda: sub("ingestion.baskets"))
    step(3, "regenerate cube", lambda: sub("export.cube"))
    step(4, "regenerate trader-profile bundle", lambda: sub("export.trader_profile"))
    step(5, "sync site copies (web/ + docs/ for GitHub Pages)", sync_site)
    step(6, "validate", lambda: sub("validate.py"))
    print("\nUPDATE COMPLETE — all steps passed.")
