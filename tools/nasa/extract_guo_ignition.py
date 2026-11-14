"""Extract ONLY experimental vector markers in Guo et al. (2023), Figure 5.

Requires PyMuPDF for this archival extraction only, not for the application.
The unmodified manuscript is CC-BY-NC-ND 4.0. Derived numerical readings retain
the graphical uncertainty and are not original raw experimental records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

SOURCE_URL = "https://eprints.lib.hokudai.ac.jp/dspace/bitstream/2115/95853/1/F.Guo_FSJ_141%282023%29103925.pdf"
SOURCE_SHA256 = "cb5837c2c8570338da4020ad0648e8630555bf43b0dec92ecb9bcfbb2b6ec853"
ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "data/prevention/ignition"
FACILITIES = {
    "DAS": {"color": [0.21569, 0.67843, 0.41961], "gravity_g": 0.03, "exposure_s": 20},
    "MGLAB": {"color": [0.10196, 0.43529, 0.87451], "gravity_g": 0.00001, "exposure_s": 4.5},
    "COSMOTORRE": {"color": [0.94510, 0.25098, 0.25098], "gravity_g": 0.001, "exposure_s": 3},
}
# Partition fixed before fitting; all facility observations at one current stay together.
PARTITION = {
    "train": [3.5, 4, 5, 6, 6.5, 8, 10, 18],
    "validation": [5.5, 9, 13],
    "test": [4.5, 7, 7.5, 11, 15],
}


def extract(path: Path):
    import fitz

    doc = fitz.open(path)
    page = doc[7]
    drawings = page.get_drawings()
    # Axis paths are verified against labelled major ticks on PDF p.8.
    x0, x25 = 185.1000061, 424.5
    y_half, y32 = 474.9599915, 367.6199646
    assert any(abs(d["rect"].x0-x0) < .01 and abs(d["rect"].x1-x25) < .01
               and abs(d["rect"].y0-488.100006) < .01 for d in drawings)
    points = []
    for d in drawings:
        color = d.get("color")
        if color is None:
            continue
        facility = next((name for name, item in FACILITIES.items()
                         if max(abs(a-b) for a, b in zip(color, item["color"])) < .0001), None)
        if facility is None:
            continue  # Includes every simulated black marker and dashed curve.
        rect = d["rect"]
        # Exclude legend symbols (DAS y=366.8, MGLAB=379.5, COSMO=391.5).
        if rect.y0 < 400 and 260 < rect.x0 < 275:
            continue
        if not (210 < rect.x0 < 365 and 380 < rect.y0 < 465):
            raise ValueError("Unexpected coloured drawing in the source figure")
        cx, cy = (rect.x0+rect.x1)/2, (rect.y0+rect.y1)/2
        if facility == "COSMOTORRE":
            # Equilateral triangle: the anchor is the centroid, not its box centre.
            vertices = {(float(p.x), float(p.y)) for item in d["items"] for p in item[1:]}
            if len(vertices) != 3:
                raise ValueError("Unexpected triangle geometry")
            cx = sum(v[0] for v in vertices)/3
            cy = sum(v[1] for v in vertices)/3
        raw_current = (cx-x0)/(x25-x0)*25
        current = round(raw_current*2)/2
        if abs(raw_current-current) > .02:
            raise ValueError("Marker does not match its nominal half-ampere current")
        delay = .5 * 2**((y_half-cy)/(y_half-y32)*6)
        split = next(key for key, values in PARTITION.items() if current in values)
        points.append({
            "id": f"guo2023-{facility.lower()}-{current:g}a", "source_id": "GUO-2023",
            "facility": facility, "current_a": current, "read_current_a": raw_current,
            "ignition_delay_s": delay, "event_observed": True,
            "family_id": f"current-{current:g}a", "split": split,
            "gravity_g": FACILITIES[facility]["gravity_g"],
            "facility_max_exposure_s": FACILITIES[facility]["exposure_s"],
            "origin": "published_experimental_figure_digitization",
            "source_page_pdf": 8, "source_figure": "5",
            "pdf_marker_anchor": [cx, cy], "pdf_drawing_seqno": d["seqno"],
            "reading_envelope": {"current_a": .05, "relative_delay": .05,
                                 "meaning": "Conservative graphical reading allowance; NOT experimental uncertainty or a confidence interval"},
            "experimental_uncertainty": None, "replicate_count": None,
        })
    points.sort(key=lambda row: (row["current_a"], row["facility"]))
    counts = {name: sum(p["facility"] == name for p in points) for name in FACILITIES}
    if counts != {"DAS": 15, "MGLAB": 6, "COSMOTORRE": 5}:
        raise ValueError(f"Figure extraction counts changed: {counts}")
    # Independent textual anchor checks, not extra training samples.
    for current, delay in [(5, 7.736), (18, .876)]:
        p = next(row for row in points if row["current_a"] == current and row["facility"] == "DAS")
        if abs(p["ignition_delay_s"] / delay - 1) > .05:
            raise ValueError("The vector reading does not agree with the textual reference")
    return points


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.pdf.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("The input differs from the verified unmodified accepted manuscript")
    points = extract(args.pdf)
    FOLDER.mkdir(parents=True, exist_ok=True)
    original = FOLDER / "guo2023.pdf"
    if original.exists() and hashlib.sha256(original.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Existing archive differs; preserve and inspect it before replacing any source")
    if args.pdf.resolve() != original.resolve():
        shutil.copyfile(args.pdf, original)
    source_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    data = {
        "dataset_id": "guo2023-figure5-v1", "source_id": "GUO-2023",
        "title": "Identifying two ignition modes of polymer insulated wires with continuous excess current in microgravity",
        "doi": "10.1016/j.firesaf.2023.103925", "url": "https://hdl.handle.net/2115/95853",
        "download_url": SOURCE_URL, "source_sha256": source_hash,
        "source_bytes": original.stat().st_size, "source_file": "guo2023.pdf",
        "license": "CC-BY-NC-ND 4.0 (accepted manuscript, unchanged)",
        "authors": "Feng Guo, Seiya Kawaguchi, Nozomu Hashimoto, Osamu Fujita",
        "is_nasa_dataset": False,
        "method": "Coloured vector symbol centres, linear current axis, log2 time axis; black simulated points excluded",
        "axis_anchors": {"x_current_0_25_pdf_pt": [185.1000061, 424.5],
                         "y_time_half_32_pdf_pt": [474.9599915, 367.6199646]},
        "partition": PARTITION,
        "protocol": {"material_preset": "nichrome_ldpe_guo2023", "wire_length_m": .07,
                     "core_radius_m": .00025, "insulation_thickness_m": .00015,
                     "resistance_per_m_ohm": 5.5, "resistance_tolerance_fraction": .07,
                     "forcing": "constant excess current, initially quiescent gas",
                     "associated_numerical_context": {"temperature_c": 20, "oxygen_percent": 21, "pressure_pa": 101325},
                     "experimental_environment_uncertainty": "Numerical nominal atmosphere is stated in Figure 2; per-test atmosphere logs are unavailable"},
        "limitations": [
            "Only published igniting cases: no non-ignitions, failure frequencies or full censoring records",
            "26 plotted observations are not 26 verified independent raw trials; replicate counts are unavailable",
            "Current groups are held out together; no independent study or flight-vehicle validation",
            "Microgravity facilities have different residual acceleration and exposure time; a causal gravity effect is not identifiable",
            "A predicted conditional delay is not an ignition probability, mission risk or remaining useful life of actual spacecraft wiring",
            "Graphical readings retain rounding/marker-anchor uncertainty; time series and experimental uncertainty are unavailable",
        ], "points": points,
    }
    (FOLDER / "dataset.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"points": len(points), "source_sha256": source_hash,
                      "counts": {s: sum(p["split"] == s for p in points) for s in PARTITION}}))


if __name__ == "__main__":
    main()
