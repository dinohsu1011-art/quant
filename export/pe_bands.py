"""Ship annual consensus EPS vintages for the Theme Returns P/E-band mode.

The source workbook provides one consensus EPS value for each fiscal year. Per
the source convention, the value labelled FY N is the annual consensus vintage
observed after the FY N-1 report. The page therefore rolls:

    FY+1 after FY N report -> consensus EPS labelled FY N+1
    FY+2 after FY N report -> consensus EPS labelled FY N+2

    python -m export.pe_bands [/some/dir]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "data" / "eps" / "annual_eps.json"
DEFAULT_OUT = Path.home() / "Desktop/Obsidian/trading-brain/reports"
TICKER_ALIASES = {"GOOGL": "GOOG"}

# Month in which each fiscal year begins.  The EPS workbook labels a fiscal
# year by its ending year, so this is what lets the chart roll FY+1/FY+2 when
# the current fiscal year reaches Q3.  A calendar-year company therefore uses
# January; MU, for example, uses September because FY2026 runs Sep-2025 to
# Aug-2026 and its FY+1 estimate should become FY2027 in Mar-2026 (Q3).
FISCAL_START_MONTHS = {
    "4062.T": 4, "5802.T": 4, "5803.T": 4, "6674.T": 4,
    "6857.T": 4, "6981.T": 4, "8035.T": 4,
    "AMAT": 11, "AMD": 1, "AMZN": 1, "ANET": 1, "ARM": 4,
    "ASML": 1, "AVGO": 11, "BE": 1, "CAT": 1, "COHR": 7,
    "CRWD": 2, "CSCO": 8, "EME": 1, "FIX": 1, "FLEX": 4,
    "FSLR": 1, "GLW": 1, "GOOG": 1, "HOOD": 1, "INTC": 1,
    "LITE": 7, "LLY": 1, "META": 1, "MRVL": 3, "MSFT": 7,
    "MU": 9, "MYRG": 1, "NEM": 1, "NET": 1, "NOK": 1,
    "NOW": 1, "NVDA": 2, "NXT": 4, "ORCL": 6, "PANW": 8,
    "RDDT": 1, "STRL": 1, "STX": 7, "TER": 1, "TSM": 1,
    "WDC": 7,
}


def fiscal_q3_start(fy, start_month):
    """Return the first day of Q3 for fiscal year ``fy``."""
    if not isinstance(start_month, int) or not 1 <= start_month <= 12:
        raise ValueError("start_month must be an integer from 1 to 12")
    year = fy if start_month == 1 else fy - 1
    offset = start_month - 1 + 6
    year += offset // 12
    month = offset % 12 + 1
    return f"{year:04d}-{month:02d}-01"


def proxy_schedule(record, basis=1, start_month=None):
    """Return [effective_date, target_fy, eps] annual-vintage rollovers.

    The annual-report step establishes the normal FY+1/FY+2 proxy.  Once that
    fiscal year reaches Q3, the forward proxy rolls to the following fiscal
    year; this matches how a live analyst would stop calling the current-year
    number "forward" late in the year.
    """
    if basis not in (1, 2):
        raise ValueError("basis must be 1 or 2")
    rows = sorted(record.get("rows", []), key=lambda row: (row[0], row[1]))
    by_fy = {row[0]: row for row in rows}
    out = []
    for anchor in rows:
        anchor_fy, report_date, _, record_type = anchor
        if record_type == "f":
            continue
        target = by_fy.get(anchor_fy + basis)
        if not target or not isinstance(target[2], (int, float)) or target[2] <= 0:
            continue
        out.append([report_date, target[0], target[2]])
    if start_month is not None:
        for row in rows:
            fiscal_year = row[0]
            target = by_fy.get(fiscal_year + basis)
            if not target or not isinstance(target[2], (int, float)) or target[2] <= 0:
                continue
            out.append([fiscal_q3_start(fiscal_year, start_month), target[0], target[2]])
    out.sort(key=lambda x: x[0])
    # Keep one effective value per date.  A report and Q3 boundary can
    # coincide for unusual calendars; the later entry is the intended state.
    deduped = {}
    for change in out:
        deduped[change[0]] = change
    return list(deduped.values())


def build():
    payload = json.loads(SOURCE.read_text())
    excluded = payload.get("meta", {}).get("excluded", {})
    series = payload.get("series", {})
    for ticker, record in series.items():
        rows = record.get("rows", [])
        if not rows:
            raise ValueError(f"{ticker}: no EPS rows")
        prior = None
        for row in rows:
            if (
                not isinstance(row, list)
                or len(row) != 4
                or not isinstance(row[0], int)
                or not isinstance(row[1], str)
                or not isinstance(row[2], (int, float))
                or row[3] not in {"h", "e", "f"}
            ):
                raise ValueError(f"{ticker}: malformed EPS row {row!r}")
            if prior is not None and row[0] <= prior:
                raise ValueError(f"{ticker}: fiscal years are not strictly increasing")
            prior = row[0]

    eligible = [
        ticker
        for ticker, record in series.items()
        if ticker not in excluded
        and proxy_schedule(record, 1, FISCAL_START_MONTHS.get(ticker))
        and proxy_schedule(record, 2, FISCAL_START_MONTHS.get(ticker))
    ]
    payload["meta"] = {
        "as_of": payload.get("meta", {}).get("as_of"),
        "method": "annual consensus vintages",
        "convention": (
            "Consensus EPS labelled FY N is treated as the annual vintage "
            "observed after the FY N-1 report."
        ),
        "excluded": excluded,
        "aliases": TICKER_ALIASES,
        "fiscal_start_months": {
            ticker: FISCAL_START_MONTHS[ticker]
            for ticker in series
            if ticker in FISCAL_START_MONTHS
        },
        "eligible": len(eligible),
    }
    return payload


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    (out_dir / "cube").mkdir(parents=True, exist_ok=True)
    payload = build()
    js = "window.QUANT_PE_BANDS = " + json.dumps(
        payload, separators=(",", ":")
    ) + ";\n"
    out = out_dir / "cube" / "pe-bands.js"
    out.write_text(js)
    print(
        f"wrote {out}  ({len(js)/1e3:.1f} KB; "
        f"{payload['meta']['eligible']} eligible tickers)"
    )


if __name__ == "__main__":
    main()
