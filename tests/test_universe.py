import unittest

import pandas as pd

from analysis.universe import us_calendar


class UniverseCalendarTests(unittest.TestCase):
    def test_later_asian_session_does_not_advance_us_calendar(self):
        px = {
            "AAPL": pd.DataFrame(index=pd.to_datetime(["2026-07-27", "2026-07-28"])),
            "MSFT": pd.DataFrame(index=pd.to_datetime(["2026-07-27", "2026-07-28"])),
            "JP7011": pd.DataFrame(index=pd.to_datetime(["2026-07-28", "2026-07-29"])),
        }

        calendar, members = us_calendar(px)

        self.assertEqual(calendar[-1], pd.Timestamp("2026-07-28"))
        self.assertEqual(set(members), {"AAPL", "MSFT"})


if __name__ == "__main__":
    unittest.main()
