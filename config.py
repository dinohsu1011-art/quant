import os
from datetime import date, timedelta
from pathlib import Path

# Project root
ROOT = Path(__file__).parent

# Data paths
DATA_DIR = ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
TICKERS_FILE = DATA_DIR / "tickers.csv"

# Ensure directories exist
DAILY_DIR.mkdir(parents=True, exist_ok=True)

# Precision: store prices as int64 = price * PRICE_SCALE
# 5 decimal places covers all equity prices without loss
PRICE_SCALE = 100_000

# Historical range
START_DATE = "1990-01-01"

# Optional inclusive data cutoff for reproducible historical refreshes.
# yfinance's `end` is exclusive, so FETCH_END_DATE advances this by one day;
# ingestion/store.py also enforces the inclusive date after normalization.
DATA_THROUGH = os.environ.get("QUANT_DATA_THROUGH")
try:
    DATA_THROUGH_DATE = date.fromisoformat(DATA_THROUGH) if DATA_THROUGH else None
except ValueError as exc:
    raise RuntimeError("QUANT_DATA_THROUGH must be YYYY-MM-DD") from exc
FETCH_END_DATE = ((DATA_THROUGH_DATE + timedelta(days=1)).isoformat()
                  if DATA_THROUGH_DATE else None)

# Index / ETF symbols tracked alongside the S&P 500 constituents. yfinance
# prefixes indices with '^'. They need deeper history than equities to capture
# old events (e.g. the 1987 crash), so they ingest from INDEX_START_DATE.
INDEX_SYMBOLS = ["^IXIC", "^GSPC", "^NDX", "QQQ",
                 # Small/mid caps and equal weight. The weekend review reads the
                 # market through three indexes (S&P, Nasdaq, Russell 2000), and
                 # the ratios IWM/SPY and RSP/SPY say whether a move is broad or
                 # just the mega caps. ^RUT carries history back to 1987; IWM
                 # (1999), MDY (1995) and RSP (2003) start when they listed.
                 "^RUT", "IWM", "MDY", "RSP",
                 # international headline indices (own local calendars; standalone
                 # rebased lines, not US-aligned baskets — like the '.T' names)
                 "^N225", "^KS11", "^TWII", "000001.SS", "^HSI", "^FTSE"]
INDEX_START_DATE = "1971-01-01"

# Ingestion batch size (yfinance rate limiting)
BATCH_SIZE = 50
BATCH_DELAY_SECONDS = 2
MAX_RETRIES = 3


# Friendly stems for symbols whose raw yfinance ticker is unfriendly as a
# filename / SQL view. Keys are yfinance symbols; values become the parquet
# stem and (lower-cased) the DuckDB view name. Metals use COMEX continuous
# futures (GC=F/SI=F/HG=F) as the spot proxy — true spot FX isn't on Yahoo.
SYMBOL_ALIASES = {
    "^VIX": "VIX",
    "GC=F": "GOLD",
    "SI=F": "SILVER",
    "HG=F": "COPPER",
    "CL=F": "WTI",   # WTI crude futures
    "000001.SS": "SSEC",   # Shanghai Composite (dot + leading digit -> SQL-safe stem)
    # Tokyo Stock Exchange listings. yfinance uses a '.T' suffix; alias to a
    # SQL-safe stem (a bare '6674.T' view name has a dot and a leading digit).
    # These trade on the TSE calendar, so they align only loosely with the
    # US-session series — fine as standalone series, not for US-aligned baskets.
    "6674.T": "JP6674",  # GS Yuasa
    "7011.T": "JP7011",  # Mitsubishi Heavy Industries
    "5802.T": "JP5802",  # Sumitomo Electric
    "5803.T": "JP5803",  # Fujikura
    "6857.T": "JP6857",  # Advantest
    "6981.T": "JP6981",  # Murata Manufacturing
    "8035.T": "JP8035",  # Tokyo Electron
    "4062.T": "JP4062",  # Ibiden
    # Korea Exchange listings (KRW; KOSPI calendar).
    "005930.KS": "KR005930",  # Samsung Electronics
    "000660.KS": "KR000660",  # SK hynix
    # European turbine / power-equipment OEMs (XETRA / Helsinki calendars).
    "ENR.DE": "SIEMENS_ENERGY",   # Siemens Energy AG
    "WRT1V.HE": "WARTSILA",       # Wärtsilä
}


def file_stem(symbol: str) -> str:
    """Filesystem stem for a symbol's parquet file.

    Applies SYMBOL_ALIASES first ('GC=F' -> 'GOLD'); otherwise strips yfinance's
    '^' index prefix ('^IXIC' -> 'IXIC') so filenames stay shell- and SQL-friendly.
    Preserves case and dashes to match the existing convention ('BRK-B.parquet');
    db.py derives the lower-cased view name.
    """
    if symbol in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[symbol]
    return symbol.lstrip("^")
