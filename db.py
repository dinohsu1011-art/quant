"""
DuckDB connection factory.
Queries Parquet files directly — no data loading needed.

Usage:
    import db
    conn = db.connect()
    conn.execute("SELECT * FROM spy LIMIT 5").df()
"""
import duckdb
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DAILY_DIR, PRICE_SCALE


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    Returns a DuckDB connection with:
    - All available tickers registered as views (e.g. SELECT * FROM spy)
    - price() macro to convert int64 storage back to float
    - Prices in views already divided by PRICE_SCALE for convenience
    """
    conn = duckdb.connect(database=":memory:", read_only=False)

    # Register each parquet file as a view with prices converted back to float
    parquet_files = sorted(DAILY_DIR.glob("*.parquet"))
    # Refuse to start on a view-name collision — CREATE OR REPLACE would otherwise
    # silently serve one file under the other's name (e.g. a future S&P ticker
    # 'GOLD' colliding with the GC=F alias).
    seen = {}
    for f in parquet_files:
        v = f.stem.lower().replace("-", "_").replace("^", "")
        if v in seen:
            raise RuntimeError(f"view-name collision: '{v}' from {f.name} and {seen[v]}")
        seen[v] = f.name
    for f in parquet_files:
        # View name: lower-cased, dashes/carets normalized. Quoted on creation
        # so reserved-word tickers (ALL, ON, SO, IT, ...) don't break CREATE VIEW.
        view = f.stem.lower().replace("-", "_").replace("^", "")
        conn.execute(f'''
            CREATE OR REPLACE VIEW "{view}" AS
            SELECT
                date,
                open       / {PRICE_SCALE}.0 AS open,
                high       / {PRICE_SCALE}.0 AS high,
                low        / {PRICE_SCALE}.0 AS low,
                close      / {PRICE_SCALE}.0 AS close,
                adj_close  / {PRICE_SCALE}.0 AS adj_close,
                volume
            FROM read_parquet('{f}')
            ORDER BY date
        ''')

    # Convenience macro: read raw int64 prices from parquet directly
    conn.execute(f"CREATE MACRO to_price(x) AS x / {PRICE_SCALE}.0")

    # Daily returns primitive. "next" = next *trading day* (holiday-robust):
    # rows are trading days only, so LEAD steps to the next session, not the
    # next calendar day. dow/next_dow are isodow (Mon=1 ... Fri=5 ... Sun=7).
    #   SELECT * FROM returns('ixic') WHERE dow = 5 AND ret <= -0.0477;
    conn.execute("""
        CREATE MACRO returns(tkr) AS TABLE
        SELECT
            date,
            isodow(date)                    AS dow,
            close / LAG(close)  OVER w - 1  AS ret,
            LEAD(date)  OVER w              AS next_date,
            LEAD(close) OVER w / close - 1  AS next_ret,
            isodow(LEAD(date)   OVER w)     AS next_dow
        FROM query_table(tkr)
        WINDOW w AS (ORDER BY date)
    """)

    print(f"Connected. {len(parquet_files)} tickers available.")
    return conn


def query(sql: str, conn: duckdb.DuckDBPyConnection = None):
    """Run a SQL query and return a pandas DataFrame."""
    if conn is None:
        conn = connect()
    return conn.execute(sql).df()


if __name__ == "__main__":
    conn = connect()
    # Quick sanity check
    result = conn.execute("""
        SELECT date, open, high, low, close, volume
        FROM spy
        ORDER BY date DESC
        LIMIT 5
    """).df()
    print(result)
