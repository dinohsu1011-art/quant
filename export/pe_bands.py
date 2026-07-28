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


def proxy_schedule(record, basis=1):
    """Return [effective_date, target_fy, eps] annual-vintage rollovers."""
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
    return out


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
        and proxy_schedule(record, 1)
        and proxy_schedule(record, 2)
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
