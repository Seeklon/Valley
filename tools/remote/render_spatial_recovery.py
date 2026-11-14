"""Render local recovery evidence; no simulation, inference or data fabrication.

python tools/remote/render_spatial_recovery.py --directory evidence/incidents/spatial-recovery

Requires the 60-case historical and replay exports plus a 20- or 40-case reserved
test export, all in verify_spatial.plot_case format. Inputs are checked before
either output is written. The historical audit remains untouched.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LogNorm  # noqa: E402

if __package__:
    from .render_spatial_audit import walls
else:
    from render_spatial_audit import walls

EXAMPLE_IDS = (
    "similar-soyuz-flaming-microg",
    "novel_geometry-perimeter-flaming-microg",
)
EXAMPLE_LABELS = ("Soyouz", "Disposition périphérique")
SMOKE_THRESHOLD_MG_M3 = 0.1
HISTORICAL_EXPORT = (
    Path(__file__).resolve().parents[2] / "evidence/incidents/spatial-pilot/expanded-audit/plot-data.json.gz"
)


def numeric(value, shape, label):
    result = np.asarray(value, dtype=float)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(f"Invalid or missing numeric data: {label}; expected {shape}")
    return result


def validate_cases(cases, *, expected_count=None, grouped=False):
    """Validate exported observations, never fill missing values or interpolate."""
    if not isinstance(cases, list) or not cases:
        raise ValueError("A nonempty list of plot_case exports is required")
    if expected_count is not None and len(cases) != expected_count:
        raise ValueError(f"Expected {expected_count} complete cases, received {len(cases)}")
    indexed = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("run_id"), str) or not case["run_id"]:
            raise ValueError("Every export requires a run_id")
        identifier = case["run_id"]
        if identifier in indexed:
            raise ValueError("Duplicate case: " + identifier)
        if grouped and case.get("group") not in ("similar", "novel_geometry"):
            raise ValueError("Missing or unknown diagnostic group: " + identifier)
        if not isinstance(case.get("incident_type"), str):
            raise ValueError("Missing incident type: " + identifier)
        times = np.asarray(case.get("time_s"), dtype=float)
        if (
            times.ndim != 1
            or not len(times)
            or not np.isfinite(times).all()
            or np.any(times < 0)
            or np.any(np.diff(times) <= 0)
        ):
            raise ValueError("Invalid observation times: " + identifier)
        maxima = {}
        for key in ("fds_max", "model_max"):
            maxima[key] = numeric(case.get(key), (len(times), 2), identifier + ":" + key)
            if np.any(maxima[key][:, 1] < 0):
                raise ValueError("Negative soot concentration: " + identifier)
        bounds = numeric(case.get("bounds_m"), (3,), identifier + ":bounds_m")
        if np.any(bounds <= 0):
            raise ValueError("Invalid compartment bounds: " + identifier)
        source = case.get("source")
        if not isinstance(source, dict):
            raise ValueError("Missing imposed source: " + identifier)
        position = numeric(source.get("position_m"), (3,), identifier + ":source")
        if np.any(position < 0) or np.any(position > bounds):
            raise ValueError("Source outside compartment: " + identifier)
        objects = case.get("objects")
        if not isinstance(objects, list):
            raise ValueError("Missing geometry: " + identifier)
        for obj in objects:
            box = numeric(obj.get("bounds_m"), (6,), identifier + ":object").reshape(3, 2)
            if np.any(box[:, 0] < 0) or np.any(box[:, 1] > bounds) or np.any(box[:, 0] >= box[:, 1]):
                raise ValueError("Invalid object bounds: " + identifier)
        frames = case.get("peak_frames")
        if not isinstance(frames, dict):
            raise ValueError("Missing measured peak frames: " + identifier)
        for channel, name in enumerate(("temperature", "smoke")):
            frame = frames.get(name)
            if not isinstance(frame, dict):
                raise ValueError("Missing peak frame: " + identifier + ":" + name)
            points = np.asarray(frame.get("positions_m"), dtype=float)
            if (
                points.ndim != 2
                or points.shape[1] != 3
                or not len(points)
                or not np.isfinite(points).all()
                or np.any(points < 0)
                or np.any(points > bounds)
            ):
                raise ValueError("Invalid observed sample positions: " + identifier)
            observed = numeric(frame.get("fds"), (len(points),), identifier + ":fds:" + name)
            predicted = numeric(frame.get("model"), (len(points),), identifier + ":model:" + name)
            if channel == 1 and (np.any(observed < 0) or np.any(predicted < 0)):
                raise ValueError("Negative soot in peak frame: " + identifier)
            peak_index = int(np.argmax(maxima["fds_max"][:, channel]))
            if frame.get("time_s") != times[peak_index] or not np.isclose(
                observed.max(), maxima["fds_max"][peak_index, channel], rtol=1e-10, atol=0
            ):
                raise ValueError("Frame is not the exported FDS peak: " + identifier + ":" + name)
        indexed[identifier] = case
    return indexed


def compare_replay(historical, replay):
    """Require the same cases and FDS evidence before claiming an improvement."""
    if historical.keys() != replay.keys():
        raise ValueError("Historical/replay case membership differs")
    for identifier, old in historical.items():
        new = replay[identifier]
        for key in ("group", "incident_type", "objects", "source"):
            if old[key] != new[key]:
                raise ValueError(f"Historical/replay {key} differs: {identifier}")
        for key in ("time_s", "bounds_m", "fds_max"):
            if not np.array_equal(old[key], new[key]):
                raise ValueError(f"Historical/replay {key} differs: {identifier}")
        for name in ("temperature", "smoke"):
            before, after = old["peak_frames"][name], new["peak_frames"][name]
            for key in ("time_s", "positions_m", "fds"):
                if not np.array_equal(before[key], after[key]):
                    raise ValueError(f"Historical/replay peak {name}:{key} differs: {identifier}")
    if any(identifier not in replay for identifier in EXAMPLE_IDS):
        raise ValueError("A predefined comparison example is missing")


def gravity_group(identifier):
    tokens = identifier.split("-")
    labels = [label for label in ("microg", "earth") if label in tokens]
    if len(labels) != 1:
        raise ValueError("Cannot identify one gravity in case ID: " + identifier)
    return labels[0]


def smoke_figure(historical, replay):
    fig = plt.figure(figsize=(15, 10), layout="constrained")
    fig.get_layout_engine().set(rect=(0, 0.09, 1, 0.91))
    for row, identifier in enumerate(EXAMPLE_IDS):
        old, new = historical[identifier], replay[identifier]
        frame = old["peak_frames"]["smoke"]
        points = np.asarray(frame["positions_m"])
        columns = (
            ("FDS", np.asarray(frame["fds"]) * 1e6),
            ("Ancien modèle", np.asarray(frame["model"]) * 1e6),
            ("Nouveau modèle", np.asarray(new["peak_frames"]["smoke"]["model"]) * 1e6),
        )
        norm = LogNorm(vmin=SMOKE_THRESHOLD_MG_M3, vmax=max(1.0, *(v.max() for _, v in columns)))
        row_axes = []
        for column, (label, values) in enumerate(columns):
            ax = fig.add_subplot(2, 3, row * 3 + column + 1, projection="3d")
            row_axes.append(ax)
            walls(ax, old["objects"])
            active = values >= SMOKE_THRESHOLD_MG_M3
            scatter = ax.scatter(
                *points[active].T,
                c=values[active],
                cmap="inferno",
                norm=norm,
                s=27,
                alpha=0.9,
                depthshade=False,
            )
            if not active.any():
                ax.text2D(0.03, 0.04, "Aucun point au-dessus du seuil", transform=ax.transAxes, fontsize=9)
            ax.scatter(*old["source"]["position_m"], marker="*", s=115, color="#d62728", edgecolor="black")
            bounds = old["bounds_m"]
            ax.set(
                xlim=(0, bounds[0]),
                ylim=(0, bounds[1]),
                zlim=(0, bounds[2]),
                xlabel="x (m)",
                ylabel="y (m)",
                zlabel="z (m)",
            )
            ax.set_box_aspect(bounds)
            ax.view_init(elev=23, azim=-60)
            ax.set_title(f"{EXAMPLE_LABELS[row]} · {label}\nt = {frame['time_s']:g} s", fontsize=11)
            ax.tick_params(labelsize=8)
        bar = fig.colorbar(scatter, ax=row_axes, shrink=0.58, pad=0.02)
        bar.set_label("Suie (mg/m³) · échelle commune sur la ligne", fontsize=9)
    fig.suptitle(
        "Diagnostic déjà connu · fumée FDS et prédictions avant/après", fontsize=17, fontweight="bold"
    )
    fig.text(
        0.5,
        0.012,
        "Scénarios déjà utilisés pour diagnostiquer le pilote · aucune validation indépendante ici\n"
        "Points ≥ 0,1 mg/m³ · étoile : source imposée · mêmes positions et instant du pic FDS\n"
        "Simulation synthétique ; seuil exploratoire, pas un seuil de danger",
        fontsize=10,
        ha="center",
        va="bottom",
    )
    return fig


def peaks_figure(cases):
    groups = {"microg": [], "earth": []}
    for case in cases:
        groups[gravity_group(case["run_id"])].append(case)
    colors = {"microg": "#175c8e", "earth": "#b74b22"}
    labels = {"microg": "Microgravité", "earth": "Gravité terrestre"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), layout="constrained")
    for channel, ax in enumerate(axes):
        scale = 1 if channel == 0 else 1e6
        extrema = []
        for group, selected in groups.items():
            if not selected:
                continue
            x = [np.max(np.asarray(case["fds_max"])[:, channel]) * scale for case in selected]
            y = [np.max(np.asarray(case["model_max"])[:, channel]) * scale for case in selected]
            extrema.extend(x + y)
            ax.scatter(
                x,
                y,
                c=colors[group],
                label=f"{labels[group]} (n = {len(selected)})",
                s=43,
                alpha=0.75,
                edgecolor="white",
                linewidth=0.4,
            )
        if channel == 0:
            span = max(1.0, max(extrema) - min(extrema))
            low, high = min(extrema) - 0.05 * span, max(extrema) + 0.05 * span
            ax.set_title("Pic de température échantillonné")
            ax.set_xlabel("Simulation FDS (°C)")
            ax.set_ylabel("Nouveau modèle (°C)")
        else:
            low, high = 0.0, max(1.0, max(extrema) * 1.2)
            ax.set_title("Pic de concentration de suie")
            ax.set_xlabel("Simulation FDS (mg/m³)")
            ax.set_ylabel("Nouveau modèle (mg/m³)")
            ax.set_xscale("symlog", linthresh=SMOKE_THRESHOLD_MG_M3)
            ax.set_yscale("symlog", linthresh=SMOKE_THRESHOLD_MG_M3)
        ax.plot([low, high], [low, high], "--", color="#777777", linewidth=1, label="Prédiction exacte")
        ax.set(xlim=(low, high), ylim=(low, high))
        ax.grid(alpha=0.15)
    axes[0].legend(fontsize=9, loc="upper left")
    fig.suptitle(f"Géométries réservées · {len(cases)} cas de test", fontsize=17, fontweight="bold")
    fig.supxlabel(
        "Chaque point représente un cas ; maxima des champs échantillonnés sur la trajectoire\n"
        "Référence synthétique FDS · ces valeurs ne constituent pas une validation expérimentale NASA",
        fontsize=10,
    )
    return fig


def load_export(path):
    if not path.is_file():
        raise FileNotFoundError("Required evidence export is missing: " + str(path))
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def render(directory):
    historical = validate_cases(load_export(HISTORICAL_EXPORT), expected_count=60, grouped=True)
    replay = validate_cases(load_export(directory / "replay-plots.json.gz"), expected_count=60, grouped=True)
    heldout = validate_cases(load_export(directory / "test-plots.json.gz"))
    if len(heldout) not in (20, 40):
        raise ValueError(f"Expected 20 or 40 reserved test cases, received {len(heldout)}")
    compare_replay(historical, replay)
    if replay.keys() & heldout.keys():
        raise ValueError("Reserved test case IDs overlap the known diagnostic")
    # Check all gravity labels before creating any files. Dataset split integrity
    # is the evaluator's responsibility; this renderer does not infer it from IDs.
    for identifier in heldout:
        gravity_group(identifier)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
        }
    )
    figures = (
        ("smoke-before-after.png", smoke_figure(historical, replay)),
        ("heldout-peaks.png", peaks_figure(list(heldout.values()))),
    )
    try:
        for name, figure in figures:
            figure.savefig(directory / name, dpi=170)
    finally:
        for _, figure in figures:
            plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    render(parser.parse_args().directory.resolve())
