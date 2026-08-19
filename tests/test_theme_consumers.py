import unittest

import pandas as pd

from export.themes import (
    ALL_CONSUMER_STAPLES,
    CONSUMER_DISCRETIONARY,
    CONSUMER_STAPLES,
    RESTAURANTS,
    SINGLE_NAMES,
)
from ingestion.baskets import BASKETS


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
        self.assertTrue({"SBUX", "CMG", "COST", "BKNG", "MTN"}.issubset(SINGLE_NAMES))
        self.assertTrue(
            {ticker for ticker, _ in CONSUMER_DISCRETIONARY + ALL_CONSUMER_STAPLES}.issubset(
                SINGLE_NAMES
            )
        )

    def test_complete_sp500_discretionary_cohort_plus_completion_names(self):
        expected = set(
            self.members.loc[
                self.members["sector"].eq("Consumer Discretionary"), "ticker"
            ]
        )
        actual = {ticker for ticker, _ in CONSUMER_DISCRETIONARY}
        self.assertTrue(expected.issubset(actual))
        self.assertTrue({"MTN", "CAVA", "TXRH", "ONON", "DKS"}.issubset(actual))

    def test_consumer_baskets_and_completion_staples(self):
        staples = {ticker for ticker, _ in ALL_CONSUMER_STAPLES}
        self.assertTrue({"CELH", "ELF", "BJ", "SFM", "POST"}.issubset(staples))
        self.assertEqual(set(BASKETS["consumerdisc"]),
                         {ticker for ticker, _ in CONSUMER_DISCRETIONARY})
        self.assertEqual(set(BASKETS["consumerstaples"]), staples)


if __name__ == "__main__":
    unittest.main()
