"""Render measured hotspot diagnostics; no inference, interpolation or new labels."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from render_spatial_audit import walls  # noqa: E402


def render(directory):
    report = json.loads((directory / "diagnostic/report.json").read_text())
    exports = {}
    for name in ("uniform", "hot"):
        plots = json.loads(gzip.decompress((directory / f"diagnostic/{name}-plots.json.gz").read_bytes()))
        exports[name] = {row["run_id"]: row for row in plots}
    rows = report["results"]["hot"]["metrics"]["peak_alignment"]
    chosen = max((r for r in rows if r["gravity_g"] < 0.01), key=lambda r: r["sampled_peak_c"])
    identifier = chosen["run_id"]
    case = exports["hot"][identifier]
    frame = case["peak_frames"]["temperature"]
    other = exports["uniform"][identifier]["peak_frames"]["temperature"]
    if other["time_s"] != frame["time_s"] or other["positions_m"] != frame["positions_m"]:
        raise ValueError("Comparisons require exactly the same measured points and time")
    if other["fds"] != frame["fds"]:
        raise ValueError("Reference temperatures changed")
    positions = np.asarray(frame["positions_m"])
    values = [np.asarray(frame["fds"]), np.asarray(other["model"]), np.asarray(frame["model"])]
    visible = np.logical_or.reduce([v >= 25 for v in values])
    normalization = Normalize(vmin=20, vmax=max(float(v.max()) for v in values))
    labels = ["Simulation FDS", "Tirage uniforme", "Instants chauds plus fréquents"]
    fig = plt.figure(figsize=(14, 5.6), layout="constrained")
    axes = []
    for number, (label, value) in enumerate(zip(labels, values)):
        ax = fig.add_subplot(1, 3, number + 1, projection="3d")
        axes.append(ax)
        walls(ax, case["objects"])
        dots = ax.scatter(*positions[visible].T, c=value[visible], norm=normalization, cmap="inferno", s=48)
        source = np.asarray(case["source"]["position_m"])
        ax.scatter(*source, marker="x", color="#178aab", s=75, label="Source imposée")
        bounds = case["bounds_m"]
        ax.set(xlim=(0, bounds[0]), ylim=(0, bounds[1]), zlim=(0, bounds[2]))
        ax.set(xlabel="x (m)", ylabel="y (m)", zlabel="z (m)")
        ax.set_box_aspect(bounds)
        ax.view_init(elev=24, azim=-52)
        at = int(np.argmax(values[0]))
        ax.set_title(f"{label}\nÀ la sonde du pic : {value[at]:.1f} °C", fontsize=11)
    fig.colorbar(dots, ax=axes, shrink=0.65, label="Température du gaz (°C)")
    axes[0].legend(loc="lower left", fontsize=8)
    fig.suptitle(f"Diagnostic TRAIN · même foyer microgravité · t = {frame['time_s']:.2f} s", fontsize=16)
    fig.text(
        0.02,
        0.01,
        "Points mesurés uniquement ; union des sondes ≥25 °C. Aucun volume interpolé. Un cas appris, pas un test de généralisation.",
        fontsize=9,
    )
    fig.savefig(directory / "diagnostic-hotspot-3d.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 6), layout="constrained")
    for name, label, color in (("uniform", "Uniforme", "#7b8190"), ("hot", "Instants chauds", "#007f88")):
        peaks = report["results"][name]["metrics"]["peak_alignment"]
        for micro, marker in ((True, "o"), (False, "^")):
            selected = [p for p in peaks if (p["gravity_g"] < 0.01) == micro and p["peak_is_hot"]]
            ax.scatter(
                [p["sampled_peak_c"] for p in selected],
                [p["prediction_at_true_peak_c"] for p in selected],
                marker=marker,
                s=65,
                color=color,
                label=label + (" · microg" if micro else " · Terre"),
            )
    ax.plot([20, 400], [20, 400], "--", color="#777777", linewidth=1)
    ax.set(
        xlim=(15, 400),
        ylim=(15, 400),
        xlabel="Température FDS échantillonnée au pic (°C)",
        ylabel="Prédiction à la même position et au même instant (°C)",
    )
    ax.set_title(
        "Six foyers connus · diagnostic d'apprentissage\nDeux contrôles froids : aucune fausse alerte chaleur"
    )
    ax.grid(alpha=0.2)
    ax.legend(fontsize=9)
    fig.savefig(directory / "diagnostic-peak-amplitude.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    render(parser.parse_args().directory)
