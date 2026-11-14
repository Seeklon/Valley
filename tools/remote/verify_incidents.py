"""Run small, real Windows FDS cases for every prescribed incident family."""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from ignis.config import Settings
from ignis.engine import FDSRunner, write_json
from ignis.incidents import INCIDENTS, incident_scene
from ignis.schema import RunConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    args = parser.parse_args()
    settings = Settings(args.home/"app", args.home/"runtime",
        Path("E:/IGNIS-Valley/tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe"))
    scene = incident_scene(next(s for s in json.loads(settings.catalog_path.read_text(encoding="utf-8"))["scenes"]
                                if s["id"] == "soyuz"))
    folder = settings.runtime/("incident-check-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    folder.mkdir(parents=True)
    runner = FDSRunner(settings)
    checks = []
    for family in INCIDENTS:
        config = RunConfig(scene_id="soyuz", source_model="coupled_combustion", incident_type=family["id"],
            component_id=scene["components"][0]["id"], duration_s=6,
            ignition_power_w=1000, ignition_duration_s=1 if family["id"] == "arc" else 3).physical_config()
        directory = folder/family["id"]
        result = runner.run(scene, config, directory)
        manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
        assert result["summary"]["duration_s"] >= 5.9
        assert result["summary"]["nonfinite_spatial_measurements"] == 0
        if family["id"] in {"flaming", "smoldering", "battery"}:
            assert result["summary"]["smoke_peak_mean_kg_m3"] > 0
        if family["id"] == "flaming":
            # HRRPUA specifies injected chemical power, not instantaneous burning.
            # Verify the source flow without forcing oxygen/mixing-limited HRR.
            assert result["summary"]["heat_release_peak_w"] > 0
            with (directory/"ignis_hrr.csv").open(encoding="utf-8") as handle:
                next(handle)
                rows = list(csv.DictReader(handle))
            mass_flow = max(float(row["MLR_IGNIS_FUEL_pmma"]) for row in rows)
            assert math.isclose(mass_flow * 25_200_000, config["ignition_power_w"], rel_tol=.01)
        checks.append({"family": family["id"], "passed": True, "summary": result["summary"],
                       "incident": manifest["incident"], "wall_time_s": result["provenance"]["wall_time_s"]})
        print("VERIFIED", family["id"], result["summary"]["temperature_peak_c"], flush=True)
    write_json(folder/"verification.json", {"checked_at": datetime.now(timezone.utc).isoformat(),
        "engine": "FDS 6.11.1", "checks": checks, "passed": True})
    print("INCIDENT_VERIFICATION", str(folder/"verification.json"), flush=True)


if __name__ == "__main__":
    main()
