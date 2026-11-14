"""Regression checks against a real NASA workbook, not synthetic flame labels."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("nasa_calibration", ROOT / "tools/nasa/calibrate_fan.py")
calibration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calibration)


class NasaCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = calibration.calibrate(ROOT / "data/sources/BASS-II-fan-calibration.xlsx")
        cls.points = cls.report["points"]

    def test_real_cells_preserve_unit_conversion_and_shifted_restrictor_rows(self):
        by_cell = {p["source_cells"]["air"]: p for p in self.points}
        self.assertEqual(by_cell["M7"]["restrictors"], 0)
        self.assertEqual(by_cell["M7"]["air_display"], 59)
        self.assertAlmostEqual(by_cell["M7"]["fan_voltage_v"], 12.2)
        self.assertAlmostEqual(by_cell["M7"]["estimated_velocity_m_s"], 0.593894)
        self.assertEqual(by_cell["DE17"]["restrictors"], 1)
        self.assertAlmostEqual(by_cell["DE17"]["estimated_velocity_m_s"], 0.276815)

    def test_source_warning_and_conflicting_date_excluded_without_deleting_data(self):
        conflict = [p for p in self.points if p["session_id"] == "BASS-II-2014-043-A"]
        self.assertEqual(len(conflict), 18)
        self.assertTrue(all(not p["eligible"] for p in conflict))
        anchors = [p for p in self.points if p["fan_voltage_v"] == 3.8]
        self.assertTrue(anchors)
        self.assertTrue(all(p["split"] == "excluded" for p in anchors))
        actual_zero = [p for p in self.points if p["eligible"] and p["air_display"] == 0]
        self.assertTrue(actual_zero)
        self.assertTrue(all(p["fan_voltage_v"] > 3.8 for p in actual_zero))

    def test_day_holdout_cannot_leak_other_sessions_or_restrictors(self):
        partition = self.report["partition"]
        self.assertFalse(set(partition["training_days"]) & set(partition["test_days"]))
        self.assertLess(max(partition["training_days"]), min(partition["test_days"]))
        sessions = set()
        for point in self.points:
            if point["date"] == "2014-07-31" and point["eligible"]:
                sessions.add(point["session_id"])
                self.assertEqual(point["split"], "test")
        self.assertEqual(len(sessions), 2)
        by_id = {p["id"]: p for p in self.points}
        for model in self.report["models"]:
            self.assertTrue(all(by_id[p]["split"] == "train" for p in model["fit"]["training_point_ids"]))
        one_restrictor = self.report["models"][1]
        self.assertEqual(one_restrictor["holdout"]["out_of_domain_count"], 5)
        self.assertIsNone(calibration.predict(one_restrictor["fit"], 4.2))

    def test_local_interpolation_requires_observed_unambiguous_session_domain(self):
        estimate = calibration.local_conversion(self.points, "BASS-II-2014-049-K", 0, 12.2)
        self.assertAlmostEqual(estimate["velocity_estimate_m_s"], 0.593894)
        with self.assertRaisesRegex(ValueError, "Extrapolation"):
            calibration.local_conversion(self.points, "BASS-II-2014-049-K", 0, 13)
        with self.assertRaisesRegex(ValueError, "reliable calibration anchors"):
            calibration.local_conversion(self.points, "BASS-II-2014-043-A", 0, 12.2)

    def test_inventory_sequences_remain_sequences_and_zero_is_not_exact_air_speed(self):
        result = calibration.convert_inventory(ROOT / "data/sources/PSI-25.csv")
        by_id = {p["test_id"]: p for p in result["observations"]}
        self.assertAlmostEqual(by_id["B1"]["test_section_velocity_estimate_m_s"], 0.05033)
        self.assertIn("approaching", by_id["B6"]["raw_air_display"])
        self.assertIsNone(by_id["B6"]["test_section_velocity_estimate_m_s"])
        zeros = [p for p in result["observations"] if p["status"] == "zero_display_not_resolved_velocity"]
        self.assertEqual(len(zeros), 1)
        self.assertIsNone(zeros[0]["test_section_velocity_estimate_m_s"])


if __name__ == "__main__":
    unittest.main()
