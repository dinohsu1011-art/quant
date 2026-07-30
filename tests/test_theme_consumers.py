import unittest

import pandas as pd

from export.themes import CONSUMER_STAPLES, RESTAURANTS, SINGLE_NAMES


class ThemeConsumerUniverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.members = pd.read_csv("data/tickers.csv")

    def test_all_current_sp500_consumer_staples_are_in_theme_returns(self):
        expected = set(
            self.members.loc[
                self.members["sector"].eq("Consumer Staples"), "ticker"
            ]
        )
        actual = {ticker for ticker, _ in CONSUMER_STAPLES}
        self.assertEqual(actual, expected)

    def test_all_current_sp500_restaurants_are_in_theme_returns(self):
        expected = set(
            self.members.loc[self.members["industry"].eq("Restaurants"), "ticker"]
        )
        actual = {ticker for ticker, _ in RESTAURANTS}
        self.assertEqual(actual, expected)

    def test_requested_names_are_visible_single_name_equities(self):
        self.assertTrue({"SBUX", "CMG", "COST"}.issubset(SINGLE_NAMES))
        self.assertTrue(
            {ticker for ticker, _ in CONSUMER_STAPLES + RESTAURANTS}.issubset(
                SINGLE_NAMES
            )
        )


if __name__ == "__main__":
    unittest.main()
