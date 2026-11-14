#!/usr/bin/env python3
"""Archive bounded public NASA documents and validate the curated evidence catalogue.

Default operation is offline. Source documents are data: no document code,
macros, instructions or external links are executed. Existing raw files are
never replaced. Curated conclusions are source-reviewed annotations, not runtime predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "data/prevention/evidence"
MAX_PDF_BYTES = 15_000_000
EPISTEMIC_STATUSES = {"observation", "author_interpretation", "protocol", "data_gap"}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fetch(url: str, limit: int) -> bytes:
    if not url.startswith("https://ntrs.nasa.gov/"):
        raise ValueError("Only public NASA NTRS HTTPS endpoints are accepted")
    request = urllib.request.Request(url, headers={"User-Agent": "IGNIS-public-evidence/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if not response.url.startswith("https://ntrs.nasa.gov/"):
            raise ValueError("Unexpected download redirect")
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"Source exceeds the {limit}-byte archive limit")
    return content


def preserve(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Refusing to replace archived evidence: {path.name}")
        return
    path.write_bytes(content)


def archive_ntrs(identifier: str, base: Path = EVIDENCE) -> dict:
    if not re.fullmatch(r"\d{11}", identifier):
        raise ValueError("Expected an eleven-digit NTRS identifier")
    folder = base / "raw" / f"NTRS-{identifier}"
    provenance_path = folder / "provenance.json"
    if provenance_path.exists():
        return json.loads(provenance_path.read_text(encoding="utf-8"))
    metadata_url = f"https://ntrs.nasa.gov/api/citations/{identifier}"
    metadata_raw = fetch(metadata_url, 2_000_000)
    metadata = json.loads(metadata_raw)
    if metadata.get("distribution") != "PUBLIC":
        raise ValueError("Source is not explicitly public")
    candidates = [item for item in metadata.get("downloads", [])
                  if item.get("mimetype") == "application/pdf" and not item.get("draft")]
    if not candidates:
        raise ValueError("No public final PDF found")
    selected = candidates[0]
    download_url = "https://ntrs.nasa.gov" + selected["links"]["pdf"]
    pdf = fetch(download_url, MAX_PDF_BYTES)
    if not pdf.startswith(b"%PDF"):
        raise ValueError("Downloaded artifact is not a PDF")
    folder.mkdir(parents=True, exist_ok=True)
    preserve(folder / "metadata.json", metadata_raw)
    preserve(folder / "source.pdf", pdf)
    # stdout avoids a temporary file or overwriting an existing extraction.
    extracted = subprocess.run(["pdftotext", "-layout", str(folder / "source.pdf"), "-"],
                               capture_output=True, check=True).stdout
    preserve(folder / "source.txt", extracted)
    provenance = {
        "source_id": f"NTRS-{identifier}", "title": metadata["title"],
        "landing_url": f"https://ntrs.nasa.gov/citations/{identifier}",
        "metadata_url": metadata_url, "download_url": download_url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "distribution": metadata["distribution"], "sti_type": metadata.get("stiType"),
        "original_filename": selected["name"],
        "files": [{"name": name, "bytes": (folder / name).stat().st_size,
                   "sha256": sha256((folder / name).read_bytes())}
                  for name in ["metadata.json", "source.pdf", "source.txt"]],
        "text_extraction": "pdftotext -layout; form feed separates physical PDF pages; verify the PDF for OCR ambiguity",
    }
    preserve(provenance_path, (json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode())
    return provenance


def _local_member(folder: Path, name: str) -> Path:
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError("Artifact path escapes its source directory")
    return path


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(base: Path = EVIDENCE) -> dict:
    curated = json.loads((base / "curated.json").read_text(encoding="utf-8"))
    sources = []
    pages_by_source = {}
    metadata_by_source = {}
    for path in sorted((base / "raw").glob("*/provenance.json")):
        provenance = json.loads(path.read_text(encoding="utf-8"))
        identifier = provenance["source_id"]
        if identifier != path.parent.name or provenance["distribution"] != "PUBLIC":
            raise ValueError("Invalid source provenance")
        artifacts = []
        for artifact in provenance["files"]:
            member = _local_member(path.parent, artifact["name"])
            content = member.read_bytes()
            if len(content) != artifact["bytes"] or sha256(content) != artifact["sha256"]:
                raise ValueError(f"Archived source changed: {identifier}/{artifact['name']}")
            artifacts.append({**artifact, "path": f"raw/{identifier}/{artifact['name']}"})
        annotation = curated["sources"][identifier]
        sources.append({**provenance, **annotation, "artifacts": artifacts})
        text_path = path.parent / "source.txt"
        if text_path.exists():
            pages_by_source[identifier] = text_path.read_text(encoding="utf-8").split("\f")
        metadata_by_source[identifier] = json.loads((path.parent / "metadata.json").read_text(encoding="utf-8"))
    source_ids = {source["source_id"] for source in sources}
    if source_ids != set(curated["sources"]):
        raise ValueError("Curated and archived source lists differ")

    def validate_anchors(item: dict) -> None:
        if item["source_id"] not in source_ids or not item.get("anchors"):
            raise ValueError("A conclusion or record has no traceable source")
        for anchor in item["anchors"]:
            if "pdf_page" in anchor:
                pages = pages_by_source.get(item["source_id"], [])
                page = anchor["pdf_page"]
                if not isinstance(page, int) or page < 1 or page > len(pages) or not pages[page - 1].strip():
                    raise ValueError("Invalid physical PDF page")
                if anchor.get("quote"):
                    if _normalized_text(anchor["quote"]) not in _normalized_text(pages[page - 1]):
                        raise ValueError(f"Quote is absent from the cited page: {item['id']}")
            elif "text_lines" in anchor:
                lines = "\f".join(pages_by_source.get(item["source_id"], [])).splitlines()
                start, end = anchor["text_lines"]
                if start < 1 or end < start or end > len(lines):
                    raise ValueError("Invalid source text line range")
                if anchor.get("quote") and _normalized_text(anchor["quote"]) not in _normalized_text(
                    "\n".join(lines[start - 1:end])
                ):
                    raise ValueError(f"Quote is absent from the cited lines: {item['id']}")
            elif "json_pointer" in anchor:
                pointer = anchor["json_pointer"]
                if not isinstance(pointer, str) or not pointer.startswith("/"):
                    raise ValueError("Invalid source metadata JSON pointer")
                value = metadata_by_source[item["source_id"]]
                try:
                    for part in pointer[1:].split("/"):
                        part = part.replace("~1", "/").replace("~0", "~")
                        if isinstance(value, list):
                            if not part.isdecimal():
                                raise ValueError("Invalid list index")
                            value = value[int(part)]
                        else:
                            value = value[part]
                except (KeyError, IndexError, TypeError, ValueError) as error:
                    raise ValueError("Source metadata JSON pointer does not resolve") from error
            else:
                raise ValueError("Unsupported source anchor")

    identifiers = set()
    for conclusion in curated["conclusions"]:
        if conclusion["id"] in identifiers or conclusion["epistemic_status"] not in EPISTEMIC_STATUSES:
            raise ValueError("Duplicate conclusion or invalid epistemic status")
        identifiers.add(conclusion["id"])
        validate_anchors(conclusion)
        for field in ["conditions", "uncertainties", "compatibility", "evidence_quality", "mechanisms", "materials"]:
            if field not in conclusion:
                raise ValueError(f"Missing conclusion field: {field}")
    for record in curated["experimental_records"]:
        validate_anchors(record)
        if record["id"] in identifiers:
            raise ValueError("Duplicate experimental record")
        identifiers.add(record["id"])
        if any(record[field] for field in (
            "used_for_training", "eligible_for_ignition_model_validation", "eligible_for_thermal_model_validation"
        )):
            raise ValueError("This archive does not establish training or model-validation eligibility")
        observation_end = record["observation_end_s"]
        if not _finite_number(observation_end) or observation_end < 0:
            raise ValueError("Observation end must be finite and nonnegative")
        last_time = -1.0
        for sample in record["samples"]:
            time_s = sample["time_s"]
            if not _finite_number(time_s) or time_s < 0 or time_s < last_time:
                raise ValueError("Sample times must be finite, nonnegative and monotonic")
            source_minutes = sample["source_time_min"]
            if not _finite_number(source_minutes) or not math.isclose(
                time_s, source_minutes * 60, rel_tol=0, abs_tol=1e-9
            ):
                raise ValueError("Source minutes and normalized seconds disagree")
            last_time = time_s
            temperature = sample.get("temperature_c")
            if temperature is not None and (
                not _finite_number(temperature) or sample.get("temperature_qualifier") not in {"eq", "gt", "ge", "lt", "le"}
            ):
                raise ValueError("Temperature value or inequality is invalid")
            current = sample["current_a"]
            current_status = sample["current_status"]
            if current_status == "recorded":
                if not _finite_number(current) or current < 0:
                    raise ValueError("Recorded current requires a finite nonnegative value")
            elif current_status not in {"not_recorded", "power_off"} or current is not None:
                raise ValueError("Blank and power-off current cells must remain null")
        if record["event"]["observed"] is False and record["event"].get("time_s") is not None:
            raise ValueError("No-event records cannot invent an ignition time")
        if last_time > observation_end:
            raise ValueError("Samples extend beyond the observation window")
        event_time = record["event"].get("time_s")
        if event_time is not None and not (
            _finite_number(event_time) and 0 <= event_time <= observation_end
        ):
            raise ValueError("Event falls outside the observation window")

    return {"schema_version": 1, "review_date": curated["review_date"],
            "scope": curated["scope"], "ranking_contract": curated["ranking_contract"],
            "sources": sources, "conclusions": curated["conclusions"],
            "experimental_records": curated["experimental_records"],
            "contradictions": curated["contradictions"], "data_gaps": curated["data_gaps"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-ntrs", nargs="+", metavar="ID", help="Explicitly download bounded public PDFs")
    parser.add_argument("--check", action="store_true", help="Verify sources, anchors and existing catalogue without writing")
    args = parser.parse_args()
    if args.archive_ntrs:
        for identifier in args.archive_ntrs:
            item = archive_ntrs(identifier)
            print(item["source_id"], item["title"])
        return
    catalog = validate()
    serialized = json.dumps(catalog, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path = EVIDENCE / "catalog.json"
    if args.check:
        if path.read_text(encoding="utf-8") != serialized:
            raise ValueError("Catalogue differs from the verified annotations")
    else:
        path.write_text(serialized, encoding="utf-8")
    print(json.dumps({"sources": len(catalog["sources"]), "conclusions": len(catalog["conclusions"]),
                      "experimental_records": len(catalog["experimental_records"]), "verified": True}))


if __name__ == "__main__":
    main()
