import unittest

from export.pe_bands import build, fiscal_q3_start, proxy_schedule


class PeBandExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build()

    def test_payload_and_exclusions(self):
        self.assertEqual(len(self.payload["series"]), 63)
        self.assertEqual(
            set(self.payload["meta"]["excluded"]),
            {"ASML", "TSM", "NOK"},
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
        self.assertEqual(fiscal_q3_start(2027, 4), "2026-10-01")
        self.assertIn(
            ["2026-10-01", 2028, 383.823],
            proxy_schedule(record, 1, 4),
        )

    def test_non_positive_eps_creates_gap(self):
        record = self.payload["series"]["MU"]
        fy1 = proxy_schedule(record, 1)
        self.assertNotIn(["2022-09-29", 2023, -4.544], fy1)

    def test_mu_rolls_forward_at_q3_of_its_fiscal_year(self):
        record = self.payload["series"]["MU"]
        self.assertEqual(fiscal_q3_start(2026, 9), "2026-03-01")
        self.assertIn(["2026-03-01", 2027, 152.737], proxy_schedule(record, 1, 9))
        self.assertIn(["2026-03-01", 2028, 165.542], proxy_schedule(record, 2, 9))

    def test_new_tab_series_are_loaded_and_sandisk_is_standalone(self):
        self.assertEqual(
            self.payload["series"]["GEV"]["rows"][-2:],
            [[2028, "2029-01-28", 34.298, "f"], [2029, "2030-01-28", 43.146, "f"]],
        )
        self.assertEqual(
            self.payload["series"]["SNDK"]["rows"][0],
            [2025, "2025-08-14", 2.699, "h"],
        )
        self.assertNotIn("SNDK", self.payload["meta"]["excluded"])


if __name__ == "__main__":
    unittest.main()
