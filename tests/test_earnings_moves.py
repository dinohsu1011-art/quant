import unittest

import pandas as pd

from export.themes import earnings_reactions, move_context
from ingestion.earnings import theme_equities


class EarningsMoveTests(unittest.TestCase):
    def test_theme_equity_calendar_covers_requested_consumer_names(self):
        universe = theme_equities()
        self.assertEqual(universe["SBUX"], "SBUX")
        self.assertEqual(universe["CMG"], "CMG")
        self.assertEqual(universe["COST"], "COST")
        self.assertEqual(universe["kr005930"], "005930.KS")

    def test_after_close_earnings_maps_to_next_trading_session(self):
        prices = pd.Series(
            [100, 101, 105],
            index=pd.to_datetime(["2026-07-28", "2026-07-29", "2026-07-30"]),
        )
        cache = {
            "SBUX": {
                "events": [
                    {
                        "ts": "2026-07-29T16:00:00-04:00",
                        "after_close": True,
                        "reported": True,
                    }
                ]
            }
        }
        self.assertEqual(
            earnings_reactions("SBUX", prices, cache),
            ["2026-07-30"],
        )

    def test_recent_earnings_move_uses_only_prior_earnings_reactions(self):
        dates = pd.bdate_range("2025-01-02", periods=120)
        prices = pd.Series(
            [100 * (1.002 ** i) * (1.05 if i in {20, 40, 60, 80, 100, 119} else 1)
             for i in range(len(dates))],
            index=dates,
        )
        reactions = [dates[i].strftime("%Y-%m-%d") for i in {20, 40, 60, 80, 100, 119}]
        moves = move_context(prices, reactions)
        latest = moves["d"][-1]
        self.assertTrue(latest["e"])
        self.assertEqual(latest["n"], 5)
        self.assertIsNotNone(latest["z"])
        self.assertEqual(len(moves["d"]), 5)
        self.assertEqual(len(moves["w"]), 4)

    def test_theme_returns_has_daily_weekly_move_context_ui(self):
        with open("web/market-lab-themes.html") as f:
            page = f.read()
        self.assertIn('id="movehead"', page)
        self.assertIn('data-move="d"', page)
        self.assertIn('data-move="w"', page)
        self.assertIn("function renderMoveContext(data)", page)
        self.assertIn("prior earnings reactions only", page)

    def test_move_context_follows_consolidated_ticker_card_grid(self):
        with open("web/market-lab-themes.html") as f:
            page = f.read()
        self.assertLess(page.index('id="ddgrid"'), page.index('id="movehead"'))
        self.assertIn('id="tbl" hidden aria-hidden="true"', page)
        self.assertIn("Visible-window performance", page)
        self.assertIn("Full-history drawdown summary", page)
        self.assertIn("Completed ATH episodes · newest first", page)
        self.assertIn('class="ticker-card ', page)
        self.assertIn('class="summary-strip performance"', page)


if __name__ == "__main__":
    unittest.main()
