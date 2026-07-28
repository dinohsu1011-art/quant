import unittest

from export.pe_bands import build, proxy_schedule


class PeBandExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build()

    def test_payload_and_exclusions(self):
        self.assertEqual(len(self.payload["series"]), 51)
        self.assertEqual(
            set(self.payload["meta"]["excluded"]),
            {"ASML", "TSM", "NOK", "SNDK"},
        )
        self.assertEqual(self.payload["meta"]["method"], "annual consensus vintages")
        self.assertEqual(self.payload["meta"]["aliases"], {"GOOGL": "GOOG"})

    def test_us_fy1_and_fy2_roll_at_prior_report(self):
        record = self.payload["series"]["AMAT"]
        fy1 = proxy_schedule(record, 1)
        fy2 = proxy_schedule(record, 2)
        self.assertIn(["2024-11-14", 2025, 9.349], fy1)
        self.assertIn(["2024-11-14", 2026, 12.434], fy2)
        self.assertIn(["2025-11-13", 2026, 12.434], fy1)
        self.assertIn(["2025-11-13", 2027, 17.104], fy2)

    def test_japanese_fiscal_year_rollover(self):
        record = self.payload["series"]["4062.T"]
        self.assertIn(["2026-05-11", 2027, 255.826], proxy_schedule(record, 1))
        self.assertIn(["2026-05-11", 2028, 383.823], proxy_schedule(record, 2))

    def test_non_positive_eps_creates_gap(self):
        record = self.payload["series"]["MU"]
        fy1 = proxy_schedule(record, 1)
        self.assertNotIn(["2022-09-29", 2023, -4.544], fy1)


if __name__ == "__main__":
    unittest.main()
