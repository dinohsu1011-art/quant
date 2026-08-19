import unittest

from export.themes import GROUPS


class ThemeGroupOrderTests(unittest.TestCase):
    def test_coverage_stays_pinned_and_economic_groups_follow(self):
        names = [name for name, _ in GROUPS]
        self.assertEqual(names[:2], ["My Coverage", "Fred Coverage"])
        expected = [
            "Market benchmarks — US",
            "Market benchmarks — international",
            "Macro & commodities",
            "Sector ETFs",
            "Technology & AI — ETFs",
            "Technology & AI — baskets",
            "Software — baskets",
            "Power, infrastructure & resources — ETFs",
            "Power, infrastructure & resources — baskets",
            "Healthcare & biotech",
            "Consumer — ETFs",
            "Consumer — baskets",
            "Consumer discretionary — single names",
            "Consumer staples — single names",
            "Defense, aerospace & frontier — ETFs",
            "Defense & frontier — baskets",
            "Regional companies",
            "Regional baskets",
            "Other thematic ETFs",
            "Factor 20s",
        ]
        self.assertEqual(names[2:], expected)

    def test_every_series_appears_once_in_the_navigation(self):
        ids = [series_id for _, items in GROUPS for series_id, _ in items]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
