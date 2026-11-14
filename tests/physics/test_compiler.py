"""Contract checks; these do not replace execution or physical validation of FDS."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from ignis.physics import compile_case
from ignis.physics.verification import verification_cases, verification_scene


class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scene = verification_scene()
        self.config = verification_cases()["transport"][1]

    def tearDown(self):
        self.temp.cleanup()

    def compile(self, **updates):
        return compile_case(self.scene, {**self.config, **updates}, self.root / "case")

    def deck(self):
        return (self.root / "case" / "ignis.fds").read_text()

    def test_si_inputs_translate_to_one_source_without_double_counting(self):
        manifest = self.compile()
        self.assertEqual(self.deck().count("HRRPUA="), 1)
        self.assertNotIn("EXTERNAL_FLUX", self.deck())
        self.assertAlmostEqual(manifest["source"]["flux_kw_m2"] * manifest["source"]["area_m2"] * 1000, 1000)
        self.assertAlmostEqual(manifest["source"]["imposed_pulse_energy_j"], 2995.0)
        self.assertIn("GVEC=0.0,0.0,-0", self.deck())

    def test_coupled_combustion_has_one_heater_and_no_imposed_fire(self):
        self.compile(source_model="coupled_combustion", material_id="pmma")
        self.assertNotIn("HRRPUA", self.deck())
        self.assertEqual(self.deck().count("EXTERNAL_FLUX="), 1)
        self.assertIn("A=8.5e+12", self.deck())
        self.assertIn("HEAT_OF_REACTION=870", self.deck())

    def test_cellulose_retains_char_and_reports_generic_provenance(self):
        result = self.compile(source_model="coupled_combustion")
        self.assertIn("NU_SPEC=0.6", self.deck())
        self.assertIn("NU_MATL=0.4", self.deck())
        self.assertIn("IGNIS_CHAR", self.deck())
        self.assertEqual(result["material"]["scientific_status"], "generic_unvalidated")

    def test_heavy_fuel_specific_heat_is_explicit_and_surface_pyrolysis_is_measured(self):
        result = self.compile(source_model="coupled_combustion", material_id="pmma")
        self.assertIn("&SPEC ID='IGNIS_FUEL', C=5, H=8, O=2, SPECIFIC_HEAT=1.8", self.deck())
        self.assertIn("QUANTITY='MASS FLUX', SPEC_ID='IGNIS_FUEL'", self.deck())
        self.assertIn("QUANTITY='WALL TEMPERATURE'", self.deck())
        self.assertEqual(len(result["surface_devices"]), 1)

    def test_ventilation_balances_discretized_volume_not_original_rectangles(self):
        self.scene["vents"][1]["size_m"] = [0, 0.8, 0.4]
        result = self.compile()
        flows = [v["volume_flow_m3_s"] for v in result["vents"]]
        self.assertAlmostEqual(sum(flows), 0.0)
        self.assertAlmostEqual(abs(flows[0]), 0.2 * result["vents"][0]["area_m2"])
        self.assertIn("not equal mass flux", result["ventilation"]["balance"])

    def test_oxygen_is_mole_fraction_input_and_mass_fraction_in_fds(self):
        result = self.compile(oxygen_percent=21)
        y = result["air"]["oxygen_mass_fraction"]
        self.assertNotAlmostEqual(y, 0.21)
        recovered = (y / 31.9988) / (y / 31.9988 + (1 - y) / 28.0134)
        self.assertAlmostEqual(recovered, 0.21)
        self.assertIn("HUMIDITY=0.0", self.deck())

    def test_geometry_mask_prevents_sensors_in_solids(self):
        self.config["sample_shape"] = [10, 10, 10]
        result = self.compile()
        sample = result["sampling"]
        self.assertEqual(len(sample["positions_m"]), 1000)
        self.assertEqual(sum(not v for v in sample["valid_mask"]), 8)
        for i, valid in enumerate(sample["valid_mask"]):
            self.assertEqual(f"ID='P{i:04d}_T'" in self.deck(), valid)
        self.assertLess(sample["positions_m"][0][2], sample["positions_m"][1][2])
        self.assertEqual(sample["positions_m"][0][:2], sample["positions_m"][1][:2])

    def test_room_walls_do_not_block_ventilation(self):
        self.scene["objects"].append(
            {"id": "boundary-wall", "role": "wall", "center_m": [0, 1, 1], "size_m": [0.08, 2, 2]}
        )
        self.compile()
        self.assertEqual(self.deck().count("&OBST"), 1)
        self.assertEqual(self.deck().count("&VENT"), 2)

    def test_overlapping_proxies_rejected_after_snapping(self):
        duplicate = copy.deepcopy(self.scene["objects"][0])
        duplicate["id"] = "overlap"
        self.scene["objects"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.compile()
        self.assertFalse((self.root / "case").exists())

    def test_blocked_vent_rejected(self):
        self.scene["objects"].append(
            {
                "id": "blocking-box",
                "role": "obstacle",
                "material_id": "steel",
                "center_m": [0.1, 1, 1],
                "size_m": [0.2, 0.8, 0.8],
            }
        )
        with self.assertRaisesRegex(ValueError, "blocked"):
            self.compile()

    def test_sensor_in_solid_is_explicitly_missing(self):
        self.scene["sensors"].append({"id": "inside-sample", "position_m": [1, 1, 0.2]})
        result = self.compile()
        sensor = result["sensors"][-1]
        self.assertFalse(sensor["valid"])
        self.assertNotIn(f"ID='{sensor['fds_id']}_T'", self.deck())

    def test_invalid_numeric_inputs_and_excessive_mesh_are_rejected(self):
        for key, value in [
            ("gravity_g", math.nan),
            ("oxygen_percent", math.inf),
            ("airflow_m_s", -1),
            ("ignition_power_w", True),
            ("sample_shape", [8.5, 2, 2]),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.compile(**{key: value})
        self.scene["bounds_m"] = [30, 30, 30]
        with self.assertRaisesRegex(ValueError, "resource ceiling"):
            self.compile(mesh_cell_m=0.025)

    def test_prescribed_power_is_not_misrepresented_as_electrical_power(self):
        with self.assertRaisesRegex(ValueError, "coupled_combustion only"):
            self.compile(ignition_kind="resistive", current_a=10, resistance_ohm=2)

    def test_resistive_heat_and_cutoff_are_resolved_before_emission(self):
        result = self.compile(
            source_model="coupled_combustion",
            ignition_kind="resistive",
            current_a=10,
            resistance_ohm=2,
            cutoff_s=1,
        )
        self.assertEqual(result["config"]["ignition_power_w"], 200)
        self.assertEqual(result["source"]["ramp"][-1], (1, 0))
        self.assertNotIn("HRRPUA", self.deck())

    def test_compilation_is_deterministic_and_does_not_overwrite(self):
        first = self.compile()
        other = compile_case(self.scene, self.config, self.root / "other")
        self.assertEqual(first["deck_sha256"], other["deck_sha256"])
        self.assertEqual(first["config_sha256"], other["config_sha256"])
        self.assertNotIn(b"\r\n", (self.root / "case" / "ignis.fds").read_bytes())
        self.assertEqual(
            json.loads((self.root / "case" / "manifest.json").read_text())["deck_sha256"],
            first["deck_sha256"],
        )
        with self.assertRaises(FileExistsError):
            self.compile()


if __name__ == "__main__":
    unittest.main()
