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

# Index / ETF symbols tracked alongside the S&P 500 constituents. yfinance
# prefixes indices with '^'. They need deeper history than equities to capture
# old events (e.g. the 1987 crash), so they ingest from INDEX_START_DATE.
INDEX_SYMBOLS = ["^IXIC", "^GSPC", "^NDX", "QQQ"]
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
