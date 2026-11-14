"""Read observed FDS CSV output into the versioned IGNIS result contract."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path


def _value(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        result = float(value.strip().replace("D", "E").replace("d", "e"))
    except (ValueError, AttributeError):
        return None
    return result if math.isfinite(result) else None


def _scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _read_devices(path: Path) -> tuple[list[dict], dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = csv.reader(stream)
        try:
            units = [s.strip().strip('"') for s in next(rows)]
            names = [s.strip().strip('"') for s in next(rows)]
        except StopIteration as exc:
            raise ValueError("Incomplete FDS device CSV header") from exc
        if not names or names[0].lower() != "time":
            raise ValueError("Expected FDS CSV unit row followed by Time/device-name row")
        names[0] = "Time"
        if len(names) != len(set(names)):
            raise ValueError("Duplicate columns in FDS device CSV")
        result = []
        last_time = -math.inf
        for line_number, row in enumerate(rows, start=3):
            if not row or not any(s.strip() for s in row):
                continue
            if len(row) != len(names):
                raise ValueError(f"Truncated FDS device CSV row {line_number}")
            parsed = {name: _value(value) for name, value in zip(names, row)}
            time_s = parsed["Time"]
            if time_s is None or time_s < 0 or time_s < last_time:
                raise ValueError(f"Invalid or decreasing device time on row {line_number}")
            if time_s == last_time:
                result[-1] = parsed  # FDS restart may repeat its last recorded instant.
            else:
                result.append(parsed)
            last_time = time_s
    if not result:
        raise ValueError("FDS emitted no device measurements")
    return result, dict(zip(names, units))


def parse_result(output_dir: Path, *, allow_partial: bool = False) -> dict:
    """Parse one real calculation. Missing values remain null, never ambient fill.

    The scheduler must additionally verify the FDS process exit status. Unless
    allow_partial is explicitly requested, a run ending before T_END is rejected.
    """
    output_dir = Path(output_dir)
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    deck = (output_dir / manifest["input_file"]).read_bytes()
    if hashlib.sha256(deck).hexdigest() != manifest["deck_sha256"]:
        raise ValueError("FDS input changed after compilation; provenance no longer matches")
    rows, units = _read_devices(output_dir / f"{manifest['chid']}_devc.csv")
    required = {"G_TMAX", "G_TMEAN", "G_O2", "G_SOOT", "G_HRR"}
    missing = required - rows[0].keys()
    if missing:
        raise ValueError(f"FDS output lacks required global measurements: {sorted(missing)}")
    expected_duration = manifest["config"]["duration_s"]
    end_time = rows[-1]["Time"]
    complete_time = end_time >= expected_duration - max(1e-3, manifest["sampling"]["interval_s"] * 0.05)
    if not complete_time and not allow_partial:
        raise ValueError(
            f"Incomplete simulation: last measurement {end_time}s, expected {expected_duration}s"
        )
    logs = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")[-200_000:]
        for p in (
            output_dir / "ignis.out",
            output_dir / "engine.log",
            output_dir / "stdout.log",
            output_dir / "stderr.log",
        )
        if p.exists()
    )
    # FDS prints normal convergence diagnostics such as "Maximum Velocity
    # Error:" at every step. Only error/STOP records are terminal failures.
    failure = re.compile(
        r"^\s*(?:ERROR(?:\s*\(\d+\))?\s*:|STOP\s*:.*(?:ERROR|NUMERICAL INSTABILITY)|NUMERICAL INSTABILITY\b)",
        re.IGNORECASE | re.MULTILINE,
    )
    if failure.search(logs):
        raise ValueError("FDS output reports an error or numerical instability; inspect raw logs")
    # Do not accidentally report the Intel compiler or MPI library version.
    version_match = re.search(r"\bFDS(?:[- ]|\s+Version\s*:?\s*)(\d+\.\d+\.\d+)", logs, re.IGNORECASE)
    observed_version = version_match.group(1) if version_match else None
    warnings = list(manifest["warnings"])
    solver_warnings = sorted(
        set(line.strip() for line in logs.splitlines() if re.match(r"^\s*WARNING\s*:", line, re.IGNORECASE))
    )
    warnings.extend(f"FDS: {line}" for line in solver_warnings)
    if observed_version and observed_version != manifest["engine_version"]:
        warnings.append(f"Executed FDS {observed_version}; compiled target was {manifest['engine_version']}.")
    if not complete_time:
        warnings.append("Partial result: simulation has not reached requested duration.")
    if not observed_version:
        warnings.append(
            "FDS executable version is not present in supplied logs; target version is recorded separately."
        )
    sample = manifest["sampling"]
    mask = sample["valid_mask"]
    field_names = ("T", "O2", "S", "U", "V", "W")
    absent_columns = [
        f"P{i:04d}_{field}"
        for i, valid in enumerate(mask)
        if valid
        for field in field_names
        if f"P{i:04d}_{field}" not in rows[0]
    ]
    if absent_columns:
        raise ValueError(
            f"FDS output lacks {len(absent_columns)} spatial device columns; refusing an incomplete training sample"
        )
    expected_instruments = [
        f"{sensor['fds_id']}_{field}"
        for sensor in manifest["sensors"]
        if sensor["valid"]
        for field in field_names
    ] + [
        f"{surface['fds_id']}_{field}"
        for surface in manifest.get("surface_devices", [])
        for field in ("T", "M", "D", "Q")
    ]
    absent_instruments = [name for name in expected_instruments if name not in rows[0]]
    if absent_instruments:
        raise ValueError(f"FDS output lacks instrument columns: {absent_instruments[:8]}")
    invalid_measurements = 0
    frames, metrics = [], []
    for row in rows:
        time_s = row["Time"]
        frame = {
            "time_s": time_s,
            "shape": sample["shape"],
            "bounds_m": sample["bounds_m"],
            "valid_mask": mask,
            "sample_positions_m": sample["positions_m"],
            "temperature_c": [],
            "oxygen_percent": [],
            "smoke_kg_m3": [],
            "velocity_m_s": [],
        }
        for index, valid in enumerate(mask):
            values = {field: row.get(f"P{index:04d}_{field}") if valid else None for field in field_names}
            if valid:
                invalid_measurements += sum(v is None for v in values.values())
            frame["temperature_c"].append(values["T"])
            frame["oxygen_percent"].append(_scaled(values["O2"], 100))
            frame["smoke_kg_m3"].append(values["S"])
            frame["velocity_m_s"].extend([values["U"], values["V"], values["W"]])
        frames.append(frame)
        sensors = {}
        for sensor in manifest["sensors"]:
            prefix = sensor["fds_id"]
            sensors[sensor["id"]] = {
                "temperature_c": row.get(f"{prefix}_T"),
                "oxygen_percent": _scaled(row.get(f"{prefix}_O2"), 100),
                "smoke_kg_m3": row.get(f"{prefix}_S"),
                "velocity_m_s": [row.get(f"{prefix}_{field}") for field in ("U", "V", "W")],
                "valid": sensor["valid"],
            }
        metric = {
            "time_s": time_s,
            "temperature_max_c": row["G_TMAX"],
            "temperature_mean_c": row["G_TMEAN"],
            "oxygen_mean_percent": _scaled(row["G_O2"], 100),
            "smoke_mean_kg_m3": row["G_SOOT"],
            "heat_release_w": _scaled(row["G_HRR"], 1000),
            "gas_mass_kg": row.get("G_MASS"),
            "sensors": sensors,
            "vent_volume_flows_m3_s": {
                vent["id"]: row.get(f"FLOW_{vent['fds_id']}") for vent in manifest["vents"]
            },
            "fuel_surfaces": {
                surface["object_id"]: {
                    "temperature_c": row.get(f"{surface['fds_id']}_T"),
                    "fuel_mass_flux_kg_m2_s": row.get(f"{surface['fds_id']}_M"),
                    "thickness_m": row.get(f"{surface['fds_id']}_D"),
                    "net_heat_flux_w_m2": _scaled(row.get(f"{surface['fds_id']}_Q"), 1000),
                    "measurement_basis": surface["measurement_basis"],
                }
                for surface in manifest.get("surface_devices", [])
            },
        }
        if any(
            metric[key] is None
            for key in (
                "temperature_max_c",
                "temperature_mean_c",
                "oxygen_mean_percent",
                "smoke_mean_kg_m3",
                "heat_release_w",
            )
        ):
            raise ValueError(f"Non-finite global measurement at t={time_s}; run cannot form a valid dataset")
        metrics.append(metric)
    if invalid_measurements:
        warnings.append(
            f"{invalid_measurements} non-finite spatial values retained as null; unsuitable for training until reviewed."
        )
    integrated_energy = sum(
        (b["time_s"] - a["time_s"]) * (a["heat_release_w"] + b["heat_release_w"]) / 2
        for a, b in zip(metrics, metrics[1:])
    )
    return {
        "provenance": {
            "engine": "FDS",
            "engine_version": observed_version,
            "target_engine_version": manifest["engine_version"],
            "model_id": None,
            "scientific_status": manifest["scientific_status"],
            "source_model": manifest["config"]["source_model"],
            "warnings": warnings,
            "compiler_version": manifest["compiler_version"],
            "material_model_version": manifest["material_model_version"],
            "input_sha256": manifest["deck_sha256"],
            "scene_sha256": manifest["scene_sha256"],
            "config_sha256": manifest["config_sha256"],
            "sampling": sample,
            "material": manifest["material"],
            "solver_mesh": manifest["mesh"],
            "metrics_basis": "FDS whole-domain gas-volume statistics; independent of the sparse display grid",
            "raw_csv_units": units,
            "solver_warnings": solver_warnings,
            "completion": {
                "reached_requested_time": complete_time,
                "success_message_observed": bool(re.search(r"completed successfully", logs, re.IGNORECASE)),
                "process_exit_status": "must be verified by scheduler",
            },
        },
        "metrics": metrics,
        "frames": frames,
        "summary": {
            "duration_s": end_time,
            "sample_count": len(frames),
            "temperature_peak_c": max(m["temperature_max_c"] for m in metrics),
            "heat_release_peak_w": max(m["heat_release_w"] for m in metrics),
            "oxygen_min_mean_percent": min(m["oxygen_mean_percent"] for m in metrics),
            "smoke_peak_mean_kg_m3": max(m["smoke_mean_kg_m3"] for m in metrics),
            "released_energy_j": integrated_energy,
            "released_energy_method": "trapezoidal integral of sampled instantaneous gas-phase HRR",
            "valid_spatial_points": sum(mask),
            "solid_or_unmeasured_points": len(mask) - sum(mask),
            "nonfinite_spatial_measurements": invalid_measurements,
        },
    }
