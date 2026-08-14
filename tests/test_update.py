import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import update


class UpdateRetryTests(unittest.TestCase):
    def test_stale_bulk_result_gets_full_single_ticker_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for ticker, last in (("FRESH", date(2026, 8, 13)), ("STALE", date(2026, 7, 1))):
                pq.write_table(pa.table({"date": pa.array([last], type=pa.date32())}),
                               root / f"{ticker}.parquet")
            frame = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-08-13"]))
            with patch.object(update, "DAILY_DIR", root), \
                 patch("yfinance.download", return_value=frame) as download, \
                 patch("ingestion.store.store_ticker", return_value=root / "STALE.parquet") as store:
                update.retry_stale_downloads(["FRESH", "STALE"])

            download.assert_called_once_with(
                "STALE", period="max", auto_adjust=True, progress=False,
                group_by="ticker", threads=False,
            )
            store.assert_called_once_with(frame, "STALE")


if __name__ == "__main__":
    unittest.main()
