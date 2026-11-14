#!/usr/bin/env python3
"""Archive public NASA PSI experiment tables with hashes and explicit data quality."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data/sources"
BASE = "https://psi.nasa.gov/geode-py/ws"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=45) as response:
        return response.read()


def download_file(accession: str, entry: dict) -> bytes:
    identifier = entry["_id"]["$oid"]
    raw = fetch(f"{BASE}/studies/{accession}/download?file={identifier}&version={entry['version']}&redirect=false")
    value = raw.decode().strip()
    if value.startswith("https://"):
        url = value
    else:
        data = json.loads(value)
        url = data if isinstance(data, str) else data.get("url", data.get("downloadUrl"))
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("NASA did not return an HTTPS download location")
    # The short-lived signed URL never enters manifests, output or logs.
    return fetch(url)


def number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def normalize(accession: str, rows: list[dict]) -> tuple[list[dict], dict]:
    output = []
    for line, raw in enumerate(rows, start=2):
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if accession == "PSI-25":
            item = {"test_id": row["Test #"], "material": row["Fuel Sample Material"],
                    "oxygen_initial_percent": number(row.get("Calibrated  initial O2 % by vol")),
                    "oxygen_final_percent": number(row.get("Calibrated final O2 % by vol")),
                    "fan_display": number(row.get("Fan display")), "air_display": number(row.get("Air display")),
                    "airflow_m_s": None, "kind": "combustion_test_inventory"}
        elif accession == "PSI-26":
            item = {"test_id": row.get("As Run Test #"), "material": row["Fuel Sample Material"],
                    "kind": "combustion_test_inventory" if row.get("As Run Test #") else "table_note",
                    "airflow_m_s": None, "oxygen_initial_percent": None}
        else:
            combustion = row.get("Sample Number") in {"S1", "S2"}
            flow = number(row.get("Air Flow (cm/s)"))
            item = {"test_id": row["Sample Number"], "material": row["Material"],
                    "kind": "combustion_test" if combustion else "flow_visualization",
                    "airflow_m_s": flow / 100 if flow is not None else None,
                    "oxygen_description": row.get("Percent O2"),
                    "ignition_power_w": number(row.get("Ignition Power (W)")),
                    "ignition_time_s": number(row.get("Ignition Time (s)")),
                    "burn_time_s": number(row.get("Burn Time (s)")),
                    "flow_direction": row.get("Flow Direction"),
                    "sample_size_m": [number(row.get(f"Sample {axis} (cm)")) / 100
                                      for axis in ["Length", "Width", "Thickness"]] if combustion else None}
        item.update({"source_id": accession, "csv_line": line, "gravity_regime": "microgravity",
                     "raw": row, "measurement_origin": "NASA PSI experimental inventory"})
        output.append(item)
    tests = [r["test_id"] for r in output if r.get("test_id") and r["kind"].startswith("combustion")]
    counts = Counter(tests)
    quality = {"table_rows": len(rows), "combustion_inventory_rows": len(tests),
               "unique_test_identifiers": len(counts),
               "repeated_identifiers": {key: count for key, count in counts.items() if count > 1},
               "direct_airflow_values": sum(r.get("airflow_m_s") is not None for r in output),
               "direct_burn_time_values": sum(r.get("burn_time_s") is not None for r in output),
               "not_a_ready_supervised_dataset": True}
    return output, quality


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    sources, all_rows = [], []
    limits = {
        "PSI-25": "Les réglages de ventilateur ne sont pas des m/s. La conversion exige la courbe de calibration et le montage. Les lignes ne fournissent pas un champ thermique 3D.",
        "PSI-26": "Tableau d’inventaire : des identifiants se répètent et une ligne est une note. Aucun champ 3D ni débit étalonné dans ce tableau.",
        "PSI-98": "Deux essais combustibles S1/S2 et deux références d’écoulement. SIBAL est un composite spécifique ; il ne peut pas être remplacé par notre cellulose générique pour revendiquer une validation.",
    }
    for accession in ["PSI-25", "PSI-26", "PSI-98"]:
        meta_raw = fetch(f"{BASE}/repo/investigations/{accession}")
        metadata = json.loads(meta_raw)
        table = metadata["experimentalTable"][0]
        raw = download_file(accession, table)
        (DEST / f"{accession}.csv").write_bytes(raw)
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        normalized, quality = normalize(accession, rows)
        all_rows.extend(normalized)
        source = {"id": accession, "name": metadata["investigationAcronym"], "title": metadata["title"],
                  "url": f"https://psi.nasa.gov/physci/repo/data/investigations/{accession}",
                  "doi": metadata["doi"], "license": metadata.get("licenseIdentifier"),
                  "metadata_version": metadata["version"], "table_version": table["version"],
                  "table_id": table["_id"]["$oid"], "table_file": f"{accession}.csv",
                  "sha256": hashlib.sha256(raw).hexdigest(),
                  "metadata_sha256": hashlib.sha256(meta_raw).hexdigest(),
                  "retrieved_at": datetime.now(timezone.utc).isoformat(),
                  "status": "experimental_inventory", "description": limits[accession],
                  "quality": quality, "observations": normalized,
                  "objective": metadata.get("objective"), "hypothesis": metadata.get("hypothesis"),
                  "approach": metadata.get("approach"), "hardware": metadata.get("experimentHardware"),
                  "limits": [limits[accession]],
                  "used_for": ["source exploration", "experimental design", "domain comparison"],
                  "used_as_training_labels": False}
        (DEST / f"{accession}.metadata.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
        sources.append(source)
        print(accession, quality, flush=True)
    catalog = {"schema_version": 1, "sources": sources,
               "references": [{"id": "saffire-v-fds", "url": "https://ntrs.nasa.gov/citations/20240008602",
                               "description": "Transport FDS à partir de sources mesurées ; l’étude ne modélise pas les propriétés de la flamme."}],
               "challenge_url": "https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/?tab=details"}
    (DEST / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEST / "observations.json").write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
