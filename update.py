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


def fetch_all():
    run(INDEX_SYMBOLS, start=INDEX_START_DATE, skip_existing=False)
    basket_members = sorted({t for ts in BASKETS.values() for t in ts})
    rest = sorted(set(load_tickers() + MACRO + SECTOR_ETFS + THEMATIC_ETFS + INDUSTRY_ETFS
                      + basket_members + ["SPY", "QQQ"]) - set(INDEX_SYMBOLS))
    run(rest, skip_existing=False)


def sub(target):
    args = [sys.executable] + ([target] if target.endswith(".py") else ["-m", target])
    r = subprocess.run(args, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"{target} exited {r.returncode}")


def step(i, name, fn):
    t0 = time.time()
    print(f"\n=== [{i}/5] {name} ===", flush=True)
    try:
        fn()
    except Exception as e:
        print(f"*** PIPELINE STOPPED at [{i}/5] {name}: {e}")
        sys.exit(1)
    print(f"=== [{i}/5] {name} done in {time.time() - t0:.0f}s ===", flush=True)


if __name__ == "__main__":
    step(1, "full re-fetch (all tracked symbols)", fetch_all)
    step(2, "rebuild baskets", lambda: sub("ingestion.baskets"))
    step(3, "regenerate cube", lambda: sub("export.cube"))
    step(4, "regenerate trader-profile bundle", lambda: sub("export.trader_profile"))
    step(5, "validate", lambda: sub("validate.py"))
    print("\nUPDATE COMPLETE — all steps passed.")
