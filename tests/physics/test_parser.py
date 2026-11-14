"""CSV fixtures exercise format semantics, not a claim of CFD validation."""

import csv
import tempfile
import unittest
from pathlib import Path

from ignis.physics import compile_case, parse_result
from ignis.physics.verification import verification_cases


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        scene, config = verification_cases()["cold"]
        config["sample_shape"] = [10, 10, 10]
        self.manifest = compile_case(scene, config, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, final_time=5, omit_column=None, nonfinite=False):
        names = ["Time", "G_TMAX", "G_TMEAN", "G_O2", "G_SOOT", "G_HRR", "G_MASS"]
        values = [0, 22, 21, 0.209, 0.00001, 0.5, 9.6]
        for i, valid in enumerate(self.manifest["sampling"]["valid_mask"]):
            if valid:
                for field, value in zip(
                    ("T", "O2", "S", "U", "V", "W"), (21, 0.209, 0.00001, 0.2, 0.01, -0.01)
                ):
                    names.append(f"P{i:04d}_{field}")
                    values.append("NaN" if nonfinite and field == "T" and i == 0 else value)
        for sensor in self.manifest["sensors"]:
            for field, value in zip(("T", "O2", "S", "U", "V", "W"), (21, 0.209, 0.00001, 0.2, 0.01, -0.01)):
                names.append(f"{sensor['fds_id']}_{field}")
                values.append(value)
        for vent in self.manifest["vents"]:
            names.append(f"FLOW_{vent['fds_id']}")
            values.append(vent["volume_flow_m3_s"])
        if omit_column:
            index = names.index(omit_column)
            names.pop(index)
            values.pop(index)
        with (self.root / "ignis_devc.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["s"] + ["fixture-unit"] * (len(names) - 1))
            writer.writerow(names)
            writer.writerow(values)
            values[0] = final_time
            writer.writerow(values)
        (self.root / "ignis.out").write_text("Version: FDS 6.11.1\nSTOP: FDS completed successfully\n")

    def test_units_order_mask_and_global_metrics(self):
        self.fixture()
        result = parse_result(self.root)
        metric = result["metrics"][-1]
        self.assertEqual(metric["heat_release_w"], 500)
        self.assertAlmostEqual(metric["oxygen_mean_percent"], 20.9)
        self.assertEqual(result["summary"]["released_energy_j"], 2500)
        frame = result["frames"][-1]
        self.assertEqual(len(frame["velocity_m_s"]), 3000)
        for i, valid in enumerate(frame["valid_mask"]):
            self.assertEqual(frame["temperature_c"][i], 21 if valid else None)
            self.assertEqual(
                frame["velocity_m_s"][i * 3 : i * 3 + 3], [0.2, 0.01, -0.01] if valid else [None] * 3
            )
        self.assertEqual(result["provenance"]["engine_version"], "6.11.1")

    def test_incomplete_run_is_not_silently_accepted_for_training(self):
        self.fixture(final_time=2)
        with self.assertRaisesRegex(ValueError, "Incomplete simulation"):
            parse_result(self.root)
        partial = parse_result(self.root, allow_partial=True)
        self.assertFalse(partial["provenance"]["completion"]["reached_requested_time"])

    def test_missing_spatial_column_fails_instead_of_zero_fill(self):
        self.fixture(omit_column="P0000_T")
        with self.assertRaisesRegex(ValueError, "spatial device columns"):
            parse_result(self.root)

    def test_missing_sensor_column_is_not_silently_presented_as_observation(self):
        self.fixture(omit_column="S000_T")
        with self.assertRaisesRegex(ValueError, "instrument columns"):
            parse_result(self.root)

    def test_nonfinite_measurements_remain_null_and_are_flagged(self):
        self.fixture(nonfinite=True)
        result = parse_result(self.root)
        self.assertIsNone(result["frames"][0]["temperature_c"][0])
        self.assertEqual(result["summary"]["nonfinite_spatial_measurements"], 2)

    def test_modified_case_does_not_inherit_false_provenance(self):
        self.fixture()
        with (self.root / "ignis.fds").open("a") as stream:
            stream.write("! Changed input\n")
        with self.assertRaisesRegex(ValueError, "provenance"):
            parse_result(self.root)

    def test_numerical_instability_is_not_hidden_by_valid_csv(self):
        self.fixture()
        (self.root / "ignis.out").write_text("STOP: Numerical Instability\n")
        with self.assertRaisesRegex(ValueError, "instability"):
            parse_result(self.root)

    def test_real_fds_convergence_diagnostics_are_not_terminal_errors(self):
        self.fixture()
        # Excerpt from the actual Windows FDS 6.11.1 coupled verification run.
        (self.root / "ignis.out").write_text(
            "Revision         : FDS-6.11.1-0-gff928db-release\n"
            "Compiler         : Intel(R) Fortran Compiler, Version 2025.2.0\n"
            "       Maximum Velocity Error:  0.83E-04 on Mesh 1 at (6,5,2)\n"
            "       Maximum Pressure Error:  0.81E-03 on Mesh 1 at (7,5,10)\n"
            "STOP: FDS completed successfully (CHID: ignis)\n"
        )
        result = parse_result(self.root)
        self.assertEqual(result["provenance"]["engine_version"], "6.11.1")
        self.assertTrue(result["provenance"]["completion"]["success_message_observed"])

    def test_real_error_record_remains_fatal(self):
        self.fixture()
        (self.root / "ignis.out").write_text("ERROR(101): Invalid input\nSTOP: FDS stopped\n")
        with self.assertRaisesRegex(ValueError, "error"):
            parse_result(self.root)


if __name__ == "__main__":
    unittest.main()
