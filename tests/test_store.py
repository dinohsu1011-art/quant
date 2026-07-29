import unittest
from datetime import date, datetime, timezone

import pandas as pd

from ingestion.store import normalize


class StoreNormalizationTests(unittest.TestCase):
    @staticmethod
    def daily_frame():
        return pd.DataFrame(
            {
                "Open": [100.0],
                "High": [102.0],
                "Low": [99.0],
                "Close": [101.0],
                "Volume": [1000],
            },
            index=pd.DatetimeIndex(["2026-07-29"]),
        )

    def test_completed_tokyo_session_is_kept_while_new_york_is_open(self):
        now_utc = datetime(2026, 7, 29, 8, 57, tzinfo=timezone.utc)

        normalized = normalize(self.daily_frame(), "7011.T", now_utc=now_utc)

        self.assertEqual(normalized["date"].tolist(), [date(2026, 7, 29)])

    def test_completed_seoul_session_is_kept_while_new_york_is_open(self):
        now_utc = datetime(2026, 7, 29, 8, 57, tzinfo=timezone.utc)

        normalized = normalize(self.daily_frame(), "005930.KS", now_utc=now_utc)

        self.assertEqual(normalized["date"].tolist(), [date(2026, 7, 29)])

    def test_live_us_session_bar_is_still_excluded(self):
        now_utc = datetime(2026, 7, 29, 8, 57, tzinfo=timezone.utc)

        normalized = normalize(self.daily_frame(), "SPY", now_utc=now_utc)

        self.assertTrue(normalized.empty)


if __name__ == "__main__":
    unittest.main()
