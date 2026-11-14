"""Render exported FDS/model audit data locally with matplotlib (no inference)."""

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
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402


def walls(ax, objects):
    for obj in objects:
        x0, x1, y0, y1, z0, z1 = obj["bounds_m"]
        vertices = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
        faces = [
            vertices[list(indices)]
            for indices in (
                (0, 1, 3, 2),
                (4, 5, 7, 6),
                (0, 1, 5, 4),
                (2, 3, 7, 6),
                (0, 2, 6, 4),
                (1, 3, 7, 5),
            )
        ]
        ax.add_collection3d(
            Poly3DCollection(faces, facecolor="#adb5bd", edgecolor="#6c757d", linewidth=0.25, alpha=0.10)
        )


def render(directory):
    packed = directory / "plot-data.json.gz"
    cases = (
        json.loads(gzip.decompress(packed.read_bytes()))
        if packed.exists()
        else json.loads((directory / "plot-data.json").read_text())
    )
    report = json.loads((directory / "report.json").read_text())
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
        }
    )
    colors = {"similar": "#175c8e", "novel_geometry": "#b74b22"}
    labels = {"similar": "Environnements similaires", "novel_geometry": "Nouvelles géométries"}
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), layout="constrained")
    for channel, ax in enumerate(axes):
        scale = 1 if channel == 0 else 1e6
        all_values = []
        for group in colors:
            selected = [case for case in cases if case["group"] == group]
            x = [np.max(np.asarray(case["fds_max"])[:, channel]) * scale for case in selected]
            y = [np.max(np.asarray(case["model_max"])[:, channel]) * scale for case in selected]
            all_values.extend(x + y)
            ax.scatter(
                x, y, c=colors[group], label=labels[group], s=38, alpha=0.7, edgecolor="white", linewidth=0.4
            )
        if channel == 0:
            hi = max(all_values) * 1.05
            lo = 19
            ax.set_title("Pic de température échantillonné")
            ax.set_xlabel("Simulation FDS (°C)")
            ax.set_ylabel("Modèle (°C)")
        else:
            hi = max(all_values) * 1.5
            lo = 0
            ax.set_title("Pic de concentration de suie")
            ax.set_xlabel("Simulation FDS (mg/m³)")
            ax.set_ylabel("Modèle (mg/m³)")
            ax.set_xscale("symlog", linthresh=0.1)
            ax.set_yscale("symlog", linthresh=0.1)
        ax.plot([lo, hi], [lo, hi], "--", color="#777777", linewidth=1, label="Prédiction exacte")
        ax.set(xlim=(lo, hi), ylim=(lo, hi))
        ax.grid(alpha=0.15)
    axes[0].legend(fontsize=9, loc="upper left")
    fig.suptitle(
        f"IGNIS · {report['completed_runs']} nouveaux cas · modèle figé", fontsize=16, fontweight="bold"
    )
    fig.savefig(directory / "peaks-comparison.png", dpi=170)
    plt.close(fig)

    # Examples fixed by ID, not selected for favorable model performance.
    ids = ("similar-soyuz-flaming-microg", "novel_geometry-perimeter-flaming-microg")
    chosen = [next(case for case in cases if case["run_id"] == identifier) for identifier in ids]
    fig = plt.figure(figsize=(11, 10), layout="constrained")
    for row, case in enumerate(chosen):
        frame = case["peak_frames"]["smoke"]
        norm = LogNorm(vmin=0.1, vmax=max(1.0, max(frame["fds"] + frame["model"]) * 1e6))
        for column, key in enumerate(("fds", "model")):
            ax = fig.add_subplot(2, 2, row * 2 + column + 1, projection="3d")
            walls(ax, case["objects"])
            values = np.asarray(frame[key]) * 1e6
            active = values >= 0.1
            points = np.asarray(frame["positions_m"])[active]
            scatter = ax.scatter(
                *points.T, c=values[active], cmap="inferno", norm=norm, s=32, alpha=0.9, depthshade=False
            )
            ax.scatter(*case["source"]["position_m"], marker="*", s=100, color="#d62728", edgecolor="black")
            bounds = case["bounds_m"]
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
            name = "Soyouz — similaire" if row == 0 else "Compartiment inédit"
            ax.set_title(
                f"{name} · {'FDS' if key == 'fds' else 'Modèle'}\nt = {frame['time_s']:g} s", fontsize=11
            )
            ax.tick_params(labelsize=8)
        bar = fig.colorbar(scatter, ax=fig.axes[-2:], shrink=0.6, pad=0.02)
        bar.set_label("Suie (mg/m³) · même échelle sur la ligne", fontsize=9)
    fig.suptitle("Fumée prédite et simulée aux mêmes positions 3D", fontsize=16, fontweight="bold")
    fig.supxlabel(
        "\n\nPoints ≥ 0,1 mg/m³ · étoile : source imposée · instant du pic FDS · grille 8×10×4\n"
        "Simulation synthétique ; seuil exploratoire, pas un seuil de danger",
        fontsize=10,
    )
    fig.savefig(directory / "smoke-3d-comparison.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    render(parser.parse_args().directory)
