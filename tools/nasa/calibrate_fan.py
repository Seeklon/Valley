#!/usr/bin/env python3
"""Read NASA's real BASS-II workbook and evaluate instrument calibration.

The only fit here maps fan voltage to an estimated test-section velocity. It is
not a fire model, a calibration of FDS, or a conversion from cabin fan settings.
No workbook formula, external reference or macro is executed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SOURCE_URL = "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25"
AIR_TO_CM_S = 1.0066


def column(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def read_cells(path: Path) -> dict:
    with zipfile.ZipFile(path) as workbook:
        strings = [
            "".join(node.text or "" for node in entry.findall(".//x:t", NS))
            for entry in ET.fromstring(workbook.read("xl/sharedStrings.xml")).findall("x:si", NS)
        ]
        cells = {}
        for cell in ET.fromstring(workbook.read("xl/worksheets/sheet1.xml")).findall(".//x:c", NS):
            raw = cell.find("x:v", NS)
            value = raw.text if raw is not None else ""
            if cell.attrib.get("t") == "s":
                value = strings[int(value)]
            formula = cell.find("x:f", NS)
            cells[cell.attrib["r"]] = {
                "value": value,
                "formula": formula.text if formula is not None else None,
            }
    # Fail loudly if a future workbook uses different units or conversion rules.
    if cells.get("A33", {}).get("value") != "*U =1.0066(AIR)":
        raise ValueError("The workbook's explicit AIR-to-velocity conversion has changed")
    if cells.get("D7", {}).get("formula") != "B7/10":
        raise ValueError("The workbook's explicit fan-display-to-voltage conversion has changed")
    return cells


def extract_points(path: Path) -> tuple[list[dict], dict]:
    cells = read_cells(path)
    sessions, points, exclusions, quality = [], [], [], []

    def cell(key):
        return cells.get(key, {}).get("value", "")

    # A:C, then G:I, K:M, ... DC:DE. D:E contains the documented example formulas.
    starts = [1] + list(range(7, 108, 4))
    for start in starts:
        pot_col, fan_col, air_col = map(column, [start, start + 1, start + 2])
        gmt = cell(f"{fan_col}4")
        match = re.match(r"^(\d{4})-(\d{1,3})", gmt)
        if not match:
            raise ValueError(f"Unrecognized session day at {fan_col}4: {gmt!r}")
        date = datetime(int(match[1]), 1, 1) + timedelta(days=int(match[2]) - 1)
        date_text = date.date().isoformat()
        raw_date = cell(f"{fan_col}3")
        serial = number(raw_date)
        excel_date = (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat() if serial else None
        date_conflict = excel_date is not None and excel_date != date_text
        session = f"BASS-II-{match[1]}-{int(match[2]):03d}-{pot_col}"
        sessions.append(
            {
                "id": session,
                "date": date_text,
                "gmt_note": gmt,
                "date_cell": f"{fan_col}3",
                "gmt_cell": f"{fan_col}4",
                "raw_date": raw_date,
                "excel_date": excel_date,
                "date_conflict": date_conflict,
            }
        )
        if date_conflict:
            quality.append(
                {
                    "session_id": session,
                    "issue": "DATE/GMT disagreement",
                    "date_from_DATE": excel_date,
                    "date_from_GMT": date_text,
                    "action": "retain raw points but exclude from model fitting and evaluation",
                }
            )
        # Each restrictor block has its own Air header. Rows shift between days.
        headers = [r for r in range(6, 36) if cell(f"{air_col}{r}") in {"Air Display", "Air"}]
        if len(headers) != 3:
            raise ValueError(f"Expected three restrictor groups for session {session}")
        for restrictors, header in enumerate(headers):
            end = headers[restrictors + 1] if restrictors < 2 else 36
            for row in range(header + 1, end):
                pot = number(cell(f"{pot_col}{row}"))
                fan = number(cell(f"{fan_col}{row}"))
                air = number(cell(f"{air_col}{row}"))
                if pot is None and fan is None and air is None:
                    continue
                references = {"pot": f"{pot_col}{row}", "fan": f"{fan_col}{row}", "air": f"{air_col}{row}"}
                if fan is None or air is None:
                    exclusions.append(
                        {
                            "session_id": session,
                            "restrictors": restrictors,
                            "source_cells": references,
                            "reason": "missing fan or AIR observation",
                        }
                    )
                    continue
                voltage = fan / 10
                reason = (
                    "unreliable 3.8 V zero anchor explicitly excluded by workbook note"
                    if math.isclose(voltage, 3.8)
                    else None
                )
                if date_conflict:
                    reason = "DATE/GMT disagreement"
                points.append(
                    {
                        "id": f"{session}-r{restrictors}-{row}",
                        "session_id": session,
                        "date": date_text,
                        "session_note": gmt,
                        "restrictors": restrictors,
                        "pot": pot,
                        "fan_display": fan,
                        "fan_voltage_v": voltage,
                        "air_display": air,
                        "estimated_velocity_cm_s": AIR_TO_CM_S * air,
                        "estimated_velocity_m_s": AIR_TO_CM_S * air / 100,
                        "source_cells": references,
                        "eligible": reason is None,
                        "exclusion_reason": reason,
                    }
                )
    return points, {
        "sessions": sessions,
        "quality_issues": quality,
        "missing_pairs": exclusions,
        "source_note": cell("D1"),
        "conversion_note": cell("A33"),
        "measurement_location_note": cell("A34"),
    }


def fit(points: list[dict]) -> dict:
    day_counts = Counter(point["date"] for point in points)
    weights = [1 / day_counts[p["date"]] for p in points]
    weight = sum(weights)
    x_mean = sum(w * p["fan_voltage_v"] for w, p in zip(weights, points)) / weight
    y_mean = sum(w * p["estimated_velocity_cm_s"] for w, p in zip(weights, points)) / weight
    denominator = sum(w * (p["fan_voltage_v"] - x_mean) ** 2 for w, p in zip(weights, points))
    if denominator <= 0:
        raise ValueError("Calibration has no variation in fan voltage")
    slope = (
        sum(
            w * (p["fan_voltage_v"] - x_mean) * (p["estimated_velocity_cm_s"] - y_mean)
            for w, p in zip(weights, points)
        )
        / denominator
    )
    return {
        "method": "date-balanced ordinary least squares; negative outputs clipped to zero",
        "intercept_cm_s": y_mean - slope * x_mean,
        "slope_cm_s_per_v": slope,
        "voltage_domain_v": [
            min(p["fan_voltage_v"] for p in points),
            max(p["fan_voltage_v"] for p in points),
        ],
        "training_point_ids": [p["id"] for p in points],
        "training_days": sorted(day_counts),
        "training_day_balanced_mean_cm_s": y_mean,
    }


def predict(model: dict, voltage: float) -> float | None:
    low, high = model["voltage_domain_v"]
    if not low <= voltage <= high:
        return None
    return max(0.0, model["intercept_cm_s"] + model["slope_cm_s_per_v"] * voltage)


def evaluate(model: dict, points: list[dict]) -> dict:
    rows = []
    for point in points:
        predicted = predict(model, point["fan_voltage_v"])
        rows.append(
            {
                "point_id": point["id"],
                "date": point["date"],
                "source_cells": point["source_cells"],
                "observed_estimate_cm_s": point["estimated_velocity_cm_s"],
                "predicted_cm_s": predicted,
                "absolute_error_cm_s": abs(predicted - point["estimated_velocity_cm_s"])
                if predicted is not None
                else None,
            }
        )
    known = [r for r in rows if r["predicted_cm_s"] is not None]
    errors = [r["absolute_error_cm_s"] for r in known]
    return {
        "test_days": sorted({p["date"] for p in points}),
        "test_count": len(points),
        "in_domain_count": len(known),
        "out_of_domain_count": len(rows) - len(known),
        "mae_cm_s": statistics.fmean(errors) if errors else None,
        "rmse_cm_s": math.sqrt(statistics.fmean(e * e for e in errors)) if errors else None,
        "max_error_cm_s": max(errors, default=None),
        "training_mean_baseline_mae_cm_s": statistics.fmean(
            abs(r["observed_estimate_cm_s"] - model["training_day_balanced_mean_cm_s"]) for r in known
        )
        if known
        else None,
        "predictions": rows,
    }


def local_conversion(points: list[dict], session_id: str, restrictors: int, voltage_v: float) -> dict:
    """Interpolate observed anchors only within a specified unambiguous session."""
    selected = sorted(
        (
            p
            for p in points
            if p["eligible"] and p["session_id"] == session_id and p["restrictors"] == restrictors
        ),
        key=lambda p: p["fan_voltage_v"],
    )
    if len(selected) < 2:
        raise ValueError("This session/restrictor pair lacks two reliable calibration anchors")
    if not selected[0]["fan_voltage_v"] <= voltage_v <= selected[-1]["fan_voltage_v"]:
        raise ValueError("Extrapolation beyond observed calibration voltages is not permitted")
    for left, right in zip(selected, selected[1:]):
        if left["fan_voltage_v"] <= voltage_v <= right["fan_voltage_v"]:
            alpha = (voltage_v - left["fan_voltage_v"]) / (right["fan_voltage_v"] - left["fan_voltage_v"])
            value = left["estimated_velocity_m_s"] * (1 - alpha) + right["estimated_velocity_m_s"] * alpha
            return {
                "velocity_estimate_m_s": value,
                "session_id": session_id,
                "restrictors": restrictors,
                "fan_voltage_v": voltage_v,
                "method": "piecewise-linear interpolation between same-session observed anchors",
                "anchor_ids": [left["id"], right["id"]],
                "anchor_cells": [left["source_cells"], right["source_cells"]],
                "uncertainty": None,
                "scope": "SPICE-based BASS-II test-section centerline estimate only",
            }
    raise ValueError("Unable to bracket fan voltage")


def convert_inventory(path: Path) -> dict:
    converted = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for line, raw in enumerate(csv.DictReader(stream), start=2):
            display = number(raw.get("Air display"))
            usable = display is not None and display > 0
            status = (
                "scalar_display_converted"
                if usable
                else "zero_display_not_resolved_velocity"
                if display == 0
                else "missing"
                if not raw.get("Air display", "").strip()
                else "time_varying_or_annotated_requires_manual_segmentation"
            )
            converted.append(
                {
                    "test_id": raw["Test #"],
                    "csv_line": line,
                    "raw_air_display": raw.get("Air display"),
                    "raw_fan_display": raw.get("Fan display"),
                    "restrictors": raw.get("Flow restrictor"),
                    "gmt": raw.get("GMT"),
                    "status": status,
                    "test_section_velocity_estimate_m_s": display * AIR_TO_CM_S / 100 if usable else None,
                    "method": "workbook AIR-display scaling, not fan-regression prediction"
                    if usable
                    else None,
                    "references": ["PSI-25.csv:Air display", "Fan Calibration data!A33:A34"],
                    "uncertainty": None,
                }
            )
    return {
        "source_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "counts": dict(Counter(r["status"] for r in converted)),
        "observations": converted,
    }


def plot(points: list[dict], models: list[dict], target: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.7), sharey=True)
    colors = {"train": "#1f658a", "test": "#cc5c2b"}
    for restrictors, ax in enumerate(axes):
        for split, label in [("train", "Jours d’ajustement"), ("test", "Jours réservés au test")]:
            subset = [
                p for p in points if p["eligible"] and p["restrictors"] == restrictors and p["split"] == split
            ]
            ax.scatter(
                [p["fan_voltage_v"] for p in subset],
                [p["estimated_velocity_cm_s"] for p in subset],
                s=22,
                alpha=0.7,
                color=colors[split],
                label=label,
            )
        model = models[restrictors]["fit"]
        low, high = model["voltage_domain_v"]
        voltage = [low + (high - low) * i / 80 for i in range(81)]
        ax.plot(
            voltage,
            [predict(model, v) for v in voltage],
            color="#142d3c",
            linewidth=1.8,
            label="Régression sur l’ajustement",
        )
        assessment = models[restrictors]["holdout"]
        ax.set_title(
            f"{restrictors} restrictor(s) · erreur test {assessment['mae_cm_s']:.2f} cm/s", fontsize=11
        )
        ax.set_xlabel("Tension ventilateur (V)")
        ax.grid(alpha=0.15)
    axes[0].set_ylabel("Vitesse estimée dans la section d’essai (cm/s)")
    axes[-1].legend(loc="upper left", fontsize=8)
    fig.suptitle("NASA BASS-II : une même tension ne garantit pas un même écoulement", fontsize=14)
    fig.text(
        0.5,
        0.015,
        "U = 1,0066 × AIR (calibration SPICE indiquée dans le classeur). Test : derniers 20 % des jours, tous restrictors regroupés.\n"
        "Zéros à 3,8 V et session DATE/GMT contradictoire exclus. Calibration instrumentale ; aucune validation de flamme.",
        ha="center",
        fontsize=9,
        color="#334b5a",
    )
    fig.tight_layout(rect=(0, 0.09, 1, 0.93))
    fig.savefig(target, dpi=160)
    plt.close(fig)


def calibrate(workbook: Path) -> dict:
    points, extraction = extract_points(workbook)
    dates = sorted({p["date"] for p in points if p["eligible"]})
    heldout_count = max(1, math.ceil(len(dates) * 0.2))
    train_days, test_days = dates[:-heldout_count], dates[-heldout_count:]
    assert not set(train_days) & set(test_days)
    for point in points:
        point["split"] = (
            "excluded" if not point["eligible"] else "test" if point["date"] in test_days else "train"
        )
    models = []
    for restrictors in range(3):
        train = [p for p in points if p["restrictors"] == restrictors and p["split"] == "train"]
        test = [p for p in points if p["restrictors"] == restrictors and p["split"] == "test"]
        model = fit(train)
        models.append({"restrictors": restrictors, "fit": model, "holdout": evaluate(model, test)})
    report = {
        "schema_version": 1,
        "scope": "instrument calibration only, not flame/FDS calibration",
        "source_url": SOURCE_URL,
        "source_file": workbook.name,
        "source_sha256": hashlib.sha256(workbook.read_bytes()).hexdigest(),
        "source_doi": "10.60555/4qc4-de67",
        "worksheet": "Fan Calibration data",
        "conversions": {
            "fan_voltage_v": "Fan Display / 10",
            "velocity_cm_s": "1.0066 * AIR",
            "reference_cells": ["D7", "A33", "A34"],
            "coefficient_uncertainty": None,
        },
        "partition": {
            "method": "chronological holdout: latest ceil(20% of observed days); all sessions and restrictors on a day stay together",
            "training_days": train_days,
            "test_days": test_days,
            "no_day_overlap": True,
        },
        "counts": {
            "sessions": len(extraction["sessions"]),
            "observed_pairs": len(points),
            "eligible_pairs": sum(p["eligible"] for p in points),
            "training_pairs": sum(p["split"] == "train" for p in points),
            "test_pairs": sum(p["split"] == "test" for p in points),
            "missing_pairs": len(extraction["missing_pairs"]),
        },
        "extraction": extraction,
        "models": models,
        "points": points,
        "limitations": [
            "Published velocities are estimates derived from a display conversion, not independent velocity measurements.",
            "No uncertainty for the factor or the underlying flow instrument is provided in this workbook.",
            "Fan shutdown occurs above 3.8 V; the explicit 3.8 V zero anchors are excluded per source warning.",
            "Soot cleaning and device state alter the calibration. A global cross-day curve is not a universal calibration.",
            "Per-session interpolation must not extrapolate or transfer to another apparatus or cabin inlet.",
            "The first session DATE and GMT disagree and is not used to fit or evaluate the models.",
            "Multiple controls during a burn cannot be collapsed into one mean airflow or treated as independent experiments.",
        ],
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, default=ROOT / "data/sources/BASS-II-fan-calibration.xlsx")
    parser.add_argument("--inventory", type=Path, default=ROOT / "data/sources/PSI-25.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    report = calibrate(args.workbook)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "nasa-fan-calibration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    inventory = convert_inventory(args.inventory)
    inventory["calibration_workbook_sha256"] = report["source_sha256"]
    inventory["scope"] = "Retrospective scalar AIR conversion only; not a complete labeled training dataset"
    (args.output / "nasa-bass2-airflow.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.plot:
        plot(report["points"], report["models"], args.output / "nasa-fan-calibration.png")
    print(
        json.dumps(
            {
                "counts": report["counts"],
                "inventory": inventory["counts"],
                "holdout": [
                    {
                        "restrictors": m["restrictors"],
                        **{k: v for k, v in m["holdout"].items() if k != "predictions"},
                    }
                    for m in report["models"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
