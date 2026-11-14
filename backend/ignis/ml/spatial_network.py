"""Small geometry-conditioned 3D emulator of sampled FDS temperature and soot.

The convolution grid follows actual FDS sampling coordinates, not a rendered
volume. Boundary airflow is an input; no velocity field is invented. Training
is CUDA-only in tools/remote/train_spatial.py; inference defaults to the CPU.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ignis.ml.incidents import COMPILER_VERSION, GLOBAL_KEYS, INCIDENT_TYPES, file_sha
from ignis.physics.materials import INERT_MATERIALS, MATERIALS, MODEL_VERSION

FEATURE_VERSION = "incident-voxel-features-1"
ARCHITECTURE_VERSION = "incident-unet3d-1"
MODEL_IDS = ("spatial-pilot-v1", "spatial-corpus-v1", "spatial-compact-v1")
MATERIAL_IDS = tuple(sorted((*MATERIALS, *INERT_MATERIALS)))
STATIC_CHANNELS = (
    "x_over_width",
    "y_over_depth",
    "z_over_height",
    "gas_sample",
    "solid_volume_fraction",
    *["substrate_" + name for name in MATERIAL_IDS],
    *["coating_" + name for name in sorted(MATERIALS)],
    "density_scaled",
    "specific_heat_scaled",
    "conductivity_scaled",
    "emissivity",
    "heat_of_combustion_scaled",
    "soot_yield_scaled",
    "coating_thickness_scaled",
    "source_patch_fraction",
    "source_dx",
    "source_dy",
    "source_dz",
    "source_distance",
    "inlet_area_fraction",
    "outlet_area_fraction",
    "boundary_u_scaled",
    "boundary_v_scaled",
    "boundary_w_scaled",
)
CONDITION_CHANNELS = (
    "time_scaled",
    "source_elapsed_scaled",
    "post_source_time_scaled",
    "source_ramp_fraction",
    "power_scaled",
    "duration_scaled",
    "gravity_g",
    "log_gravity_scaled",
    "oxygen_scaled",
    "ambient_scaled",
    "pressure_scaled",
    "airflow_scaled",
    "width_scaled",
    "depth_scaled",
    "height_scaled",
    "source_x_scaled",
    "source_y_scaled",
    "source_z_scaled",
    "source_area_scaled",
    *["incident_" + name for name in INCIDENT_TYPES],
)
CHANNELS = STATIC_CHANNELS + CONDITION_CHANNELS
FIELD_SCALES = np.array([20.0, 1e-6], dtype=np.float32)
GLOBAL_SCALES = np.array([30.0, 20.0, 1e-7, 1000.0], dtype=np.float32)


def sampling_grid(manifest: dict):
    sample = manifest["sampling"]
    shape = tuple(sample["shape"])
    if (
        len(shape) != 3
        or any(isinstance(n, bool) or not isinstance(n, int) or n < 4 for n in shape)
        or np.prod(shape) > 4096
    ):
        raise ValueError("Spatial model requires three grid dimensions >=4 and at most 4096 samples")
    bounds = np.asarray(sample["bounds_m"], dtype=float)
    positions = np.asarray(sample["positions_m"], dtype=float)
    mask = np.asarray(sample["valid_mask"], dtype=bool)
    if (
        bounds.shape != (3,)
        or positions.shape != (int(np.prod(shape)), 3)
        or mask.shape != (len(positions),)
        or not mask.any()
        or not np.isfinite(bounds).all()
        or not np.isfinite(positions).all()
        or np.any(bounds <= 0)
        or np.any(positions <= 0)
        or np.any(positions >= bounds)
    ):
        raise ValueError("Invalid spatial sampling coordinates or gas mask")
    axes = [np.unique(positions[:, a]) for a in range(3)]
    expected = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    if tuple(map(len, axes)) != shape or not np.array_equal(expected, positions):
        raise ValueError("Sampling must use verified x,y,z Cartesian order, z fastest; no regridding")
    edges = [np.r_[0, (axis[:-1] + axis[1:]) / 2, bounds[a]] for a, axis in enumerate(axes)]
    return shape, bounds, positions, mask, axes, edges


def _properties(identifier: str) -> np.ndarray:
    if identifier in MATERIALS:
        m = MATERIALS[identifier]
        values = [
            m["density_kg_m3"],
            m["specific_heat_kj_kg_k"],
            m["conductivity_w_m_k"],
            m["emissivity"],
            m["heat_of_combustion_kj_kg"],
            m["soot_yield"],
        ]
    elif identifier in INERT_MATERIALS:
        rho, k, cp, emissivity = INERT_MATERIALS[identifier]
        values = [rho, cp, k, emissivity, 0, 0]
    else:
        raise ValueError("Unknown physical material: " + str(identifier))
    return np.asarray(values) / [8000, 3, 205, 1, 30000, 0.05]


def _fraction(box: np.ndarray, edges: list[np.ndarray]) -> np.ndarray:
    spans = [
        np.maximum(0, np.minimum(edge[1:], box[a, 1]) - np.maximum(edge[:-1], box[a, 0])) / np.diff(edge)
        for a, edge in enumerate(edges)
    ]
    return spans[0][:, None, None] * spans[1][None, :, None] * spans[2][None, None, :]


def _surface_fraction(box, edges, axes, normal_axis):
    """Area overlap on a nearest sampling layer; preserves even small source patches."""
    spans = []
    for a, edge in enumerate(edges):
        if a == normal_axis:
            span = np.zeros(len(axes[a]))
            span[int(np.argmin(abs(axes[a] - box[a].mean())))] = 1
        else:
            span = np.maximum(0, np.minimum(edge[1:], box[a, 1]) - np.maximum(edge[:-1], box[a, 0]))
            span /= np.diff(edge)
        spans.append(span)
    return spans[0][:, None, None] * spans[1][None, :, None] * spans[2][None, None, :]


def geometry_channels(manifest: dict) -> np.ndarray:
    """Fractional geometry channels retain thin objects between sampling points.

    Material properties are volume-fraction weighted encodings, not a physical
    mixture law. Source/vent projections are boundary features, never labels.
    """
    if (
        manifest.get("compiler_version") != COMPILER_VERSION
        or manifest.get("material_model_version") != MODEL_VERSION
    ):
        raise ValueError("Incompatible compiler or material model for spatial features")
    shape, bounds, positions, gas, axes, edges = sampling_grid(manifest)
    features = np.zeros((len(STATIC_CHANNELS), *shape), dtype=np.float32)
    index = {name: i for i, name in enumerate(STATIC_CHANNELS)}
    features[:3] = (positions / bounds).T.reshape(3, *shape)
    features[index["gas_sample"]] = gas.reshape(shape)
    for obj in manifest["objects"]:
        fraction = _fraction(np.asarray(obj["bounds_m"]).reshape(3, 2), edges)
        material, coating = obj["material_id"], obj.get("combustible_material_id")
        properties = _properties(material)
        features[index["solid_volume_fraction"]] += fraction
        features[index["substrate_" + material]] += fraction
        if coating is not None:
            if coating not in MATERIALS:
                raise ValueError("Unknown combustible material")
            features[index["coating_" + coating]] += fraction
        for name, value in zip(
            STATIC_CHANNELS[index["density_scaled"] : index["coating_thickness_scaled"]], properties
        ):
            features[index[name]] += fraction * value
        features[index["coating_thickness_scaled"]] += fraction * obj["thermal_thickness_m"] / 0.1
    source = manifest["incident"]["source"]
    if source.get("face") != 3:
        raise ValueError("Spatial source must use the compiled upper-face patch")
    source_pos = np.asarray(source["position_m"], dtype=float)
    source_box = np.asarray(source["bounds_m"], dtype=float).reshape(3, 2)
    features[index["source_patch_fraction"]] = _surface_fraction(source_box, edges, axes, 2)
    delta = (positions - source_pos) / bounds
    features[index["source_dx"] : index["source_distance"]] = delta.T.reshape(3, *shape)
    features[index["source_distance"]] = np.linalg.norm(delta, axis=1).reshape(shape)
    for vent in manifest["vents"]:
        box = np.asarray(vent["bounds_m"]).reshape(3, 2)
        planar = np.flatnonzero(abs(box[:, 1] - box[:, 0]) < 1e-8)
        if len(planar) != 1:
            raise ValueError("Vent must lie on one compartment boundary")
        normal_axis = int(planar[0])
        wall = box[normal_axis, 0]
        if abs(wall) < 1e-8:
            outward = -1.0
        elif abs(wall - bounds[normal_axis]) < 1e-8:
            outward = 1.0
        else:
            raise ValueError("Vent plane is not a compartment boundary")
        area = _surface_fraction(box, edges, axes, normal_axis)
        features[index[vent["role"] + "_area_fraction"]] += area
        # FDS uses negative VOLUME_FLOW for inflow; the boundary plane defines
        # outward direction. Annotation normals do not set SURF flow direction.
        velocity = np.zeros(3)
        velocity[normal_axis] = outward * vent["volume_flow_m3_s"] / vent["area_m2"]
        for a in range(3):
            features[index["boundary_u_scaled"] + a] += area * velocity[a] / 0.4
    if not np.isfinite(features).all():
        raise ValueError("Nonfinite spatial geometry features")
    return features


def condition_values(config: dict, manifest: dict, time_s: float) -> np.ndarray:
    shape, bounds, _, _, _, _ = sampling_grid(manifest)
    del shape
    source = manifest["incident"]["source"]
    gravity = float(config["gravity_g"])
    duration = float(config["ignition_duration_s"])
    t = float(time_s)
    if (
        config.get("incident_type") not in INCIDENT_TYPES
        or not 0 < gravity <= 1
        or not 0 <= t <= float(config["duration_s"]) + 1e-6
    ):
        raise ValueError("Invalid spatial conditioning or prediction horizon")
    ramp = manifest["source"]["ramp"]
    factor = float(np.interp(t, [point[0] for point in ramp], [point[1] for point in ramp]))
    values = [
        t / 30,
        min(t, duration) / 10,
        max(0, t - duration) / 30,
        factor,
        config["ignition_power_w"] / 3000,
        duration / 10,
        gravity,
        np.log10(gravity) / 4,
        config["oxygen_percent"] / 21,
        config["ambient_temperature_c"] / 20,
        config["pressure_pa"] / 101325,
        config["airflow_m_s"] / 0.4,
        *(bounds / 8),
        *(np.asarray(source["position_m"]) / bounds),
        source["area_m2"] / 4,
        *[float(config["incident_type"] == kind) for kind in INCIDENT_TYPES],
    ]
    result = np.asarray(values, dtype=np.float32)
    if result.shape != (len(CONDITION_CHANNELS),) or not np.isfinite(result).all():
        raise ValueError("Invalid condition channel schema")
    return result


def input_tensor(static: np.ndarray, config: dict, manifest: dict, time_s: float) -> np.ndarray:
    conditions = condition_values(config, manifest, time_s)
    broadcast = np.broadcast_to(conditions[:, None, None, None], (len(conditions), *static.shape[1:]))
    return np.ascontiguousarray(np.concatenate([static, broadcast]), dtype=np.float32)


def encode_fields(values, ambient_c=20.0):
    return np.arcsinh((np.asarray(values) - [ambient_c, 0]) / FIELD_SCALES).astype(np.float32)


def decode_fields(values, ambient_c=20.0):
    result = np.sinh(np.clip(np.asarray(values, dtype=np.float64), -12, 12)) * FIELD_SCALES
    result[..., 0] += ambient_c
    result[..., 0] = np.clip(result[..., 0], -20, 2500)
    result[..., 1] = np.maximum(result[..., 1], 0)
    return result


def encode_globals(values, ambient_c=20.0):
    return np.arcsinh((np.asarray(values) - [ambient_c, ambient_c, 0, 0]) / GLOBAL_SCALES).astype(np.float32)


def decode_globals(values, ambient_c=20.0):
    result = np.sinh(np.clip(np.asarray(values, dtype=np.float64), -12, 12)) * GLOBAL_SCALES
    result[..., :2] += ambient_c
    result[..., :2] = np.clip(result[..., :2], -20, 2500)
    result[..., 2:] = np.maximum(result[..., 2:], 0)
    return result


class ConvBlock(nn.Sequential):
    def __init__(self, input_channels, output_channels):
        super().__init__(
            nn.Conv3d(input_channels, output_channels, 3, padding=1),
            nn.GroupNorm(4, output_channels),
            nn.SiLU(),
            nn.Conv3d(output_channels, output_channels, 3, padding=1),
            nn.GroupNorm(4, output_channels),
            nn.SiLU(),
        )


class SpatialUNet(nn.Module):
    """Direct time-conditioned fields; no iterative rollout or predicted airflow."""

    def __init__(self, base_channels=24):
        super().__init__()
        if base_channels not in (16, 24, 32):
            raise ValueError("Unsupported spatial network width")
        self.base_channels = base_channels
        c = base_channels
        self.encoder0 = ConvBlock(len(CHANNELS), c)
        self.encoder1 = ConvBlock(c, c * 2)
        self.bottleneck = ConvBlock(c * 2, c * 4)
        self.decoder1 = ConvBlock(c * 6, c * 2)
        self.decoder0 = ConvBlock(c * 3, c)
        self.field_head = nn.Conv3d(c, 2, 1)
        self.global_head = nn.Sequential(nn.Linear(c * 4, c * 2), nn.SiLU(), nn.Linear(c * 2, 4))
        # Begin at the analytical ambient baseline, rather than arbitrary hot fields.
        nn.init.zeros_(self.field_head.weight)
        nn.init.zeros_(self.field_head.bias)
        nn.init.zeros_(self.global_head[-1].weight)
        nn.init.zeros_(self.global_head[-1].bias)

    def forward(self, values):
        if values.ndim != 5 or values.shape[1] != len(CHANNELS) or min(values.shape[2:]) < 4:
            raise ValueError("Expected [batch, channels, x, y, z] spatial input")
        shape = values.shape[2:]
        pads = tuple(v for n in reversed(shape) for v in (0, (-n) % 4))
        values = F.pad(values, pads, mode="replicate")
        e0 = self.encoder0(values)
        e1 = self.encoder1(F.avg_pool3d(e0, 2))
        middle = self.bottleneck(F.avg_pool3d(e1, 2))
        d1 = self.decoder1(
            torch.cat(
                [F.interpolate(middle, size=e1.shape[2:], mode="trilinear", align_corners=False), e1], dim=1
            )
        )
        d0 = self.decoder0(
            torch.cat(
                [F.interpolate(d1, size=e0.shape[2:], mode="trilinear", align_corners=False), e0], dim=1
            )
        )
        fields = self.field_head(d0)[:, :, : shape[0], : shape[1], : shape[2]]
        globals_ = self.global_head(middle.mean(dim=(2, 3, 4)))
        return fields, globals_


def masked_loss(prediction, target, mask, weights=None):
    """Equal observed channels per frame; missing targets never become zero labels."""
    mask = mask.bool()
    safe_target = torch.where(mask, target, torch.zeros_like(target))
    errors = F.smooth_l1_loss(prediction, safe_target, reduction="none")
    dimensions = tuple(range(1, errors.ndim))
    weight = mask.to(errors.dtype) if weights is None else torch.where(mask, weights, 0.0)
    count = weight.sum(dim=dimensions)
    if torch.any(count == 0).item():
        raise ValueError("Every training frame requires observed targets")
    return (torch.where(mask, errors, torch.zeros_like(errors)) * weight).sum(dim=dimensions) / count


def architecture(base_channels=24):
    return {
        "version": ARCHITECTURE_VERSION,
        "channels": list(CHANNELS),
        "widths": [base_channels, base_channels * 2, base_channels * 4],
        "normalization": "fixed physical scales; GroupNorm",
        "fields": ["temperature_c", "smoke_kg_m3"],
        "global_keys": list(GLOBAL_KEYS),
        "time_conditioning": "direct; no autoregressive rollout",
        "padding": "replicate to multiple of four; crop predictions to exact sample shape",
    }


def checkpoint(network: SpatialUNet, model_id: str):
    if model_id not in MODEL_IDS:
        raise ValueError("Unknown spatial model ID")
    return {
        "model_id": model_id,
        "feature_version": FEATURE_VERSION,
        "architecture": architecture(network.base_channels),
        "state_dict": {key: value.detach().cpu().clone() for key, value in network.state_dict().items()},
    }


class SpatialSurrogate:
    """Safe CPU-first loader; returns sampled arrays for explicit later UI integration."""

    def __init__(self, directory: Path, *, device="cpu"):
        directory = Path(directory)
        self.metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        if (
            self.metadata.get("id") not in MODEL_IDS
            or self.metadata.get("kind") != "incident_3d_unet"
            or self.metadata.get("feature_version") != FEATURE_VERSION
            or self.metadata.get("compiler_version") != COMPILER_VERSION
            or self.metadata.get("material_model_version") != MODEL_VERSION
        ):
            raise ValueError("Incompatible spatial model metadata")
        width = self.metadata["architecture"]["widths"][0]
        expected = architecture(width)
        if self.metadata["architecture"] != expected:
            raise ValueError("Incompatible spatial model architecture")
        weights = directory / "weights.pt"
        if file_sha(weights) != self.metadata.get("weights_sha256"):
            raise ValueError("Spatial weights checksum mismatch")
        payload = torch.load(weights, map_location="cpu", weights_only=True)
        if (
            payload.get("model_id") != self.metadata["id"]
            or payload.get("architecture") != expected
            or payload.get("feature_version") != FEATURE_VERSION
        ):
            raise ValueError("Incompatible spatial model checkpoint")
        self.network = SpatialUNet(width)
        self.network.load_state_dict(payload["state_dict"], strict=True)
        if any(not torch.isfinite(v).all().item() for v in self.network.state_dict().values()):
            raise ValueError("Nonfinite spatial model weights")
        self.device = torch.device(device)
        self.network.to(self.device).eval()

    def predict_arrays(self, config: dict, manifest: dict, times, *, batch_size=4):
        shape, _, _, mask, _, _ = sampling_grid(manifest)
        if list(shape) != self.metadata["sample_shape"]:
            raise ValueError("Sampling shape differs from training; no silent interpolation")
        if not 1 <= batch_size <= 8:
            raise ValueError("Spatial inference batch must be between 1 and 8")
        times = np.asarray(times, dtype=float)
        if times.ndim != 1 or not len(times) or not np.isfinite(times).all():
            raise ValueError("Prediction times must be a finite nonempty vector")
        static = geometry_channels(manifest)
        fields = np.full((len(times), len(mask), 2), np.nan)
        globals_ = np.zeros((len(times), 4), dtype=float)
        ambient = config["ambient_temperature_c"]
        with torch.inference_mode():
            for start in range(0, len(times), batch_size):
                batch = np.stack(
                    [input_tensor(static, config, manifest, t) for t in times[start : start + batch_size]]
                )
                f, g = self.network(torch.from_numpy(batch).to(self.device))
                values = f.cpu().numpy().reshape(len(batch), 2, -1).transpose(0, 2, 1)
                fields[start : start + len(batch)] = decode_fields(values, ambient)
                globals_[start : start + len(batch)] = decode_globals(g.cpu().numpy(), ambient)
        fields[:, ~mask] = np.nan
        initial = times == 0
        fields[initial] = np.where(mask[:, None], [ambient, 0.0], [np.nan, np.nan])
        globals_[initial] = [ambient, ambient, 0.0, 0.0]
        if not np.isfinite(fields[:, mask]).all() or not np.isfinite(globals_).all():
            raise ValueError("Nonfinite spatial prediction")
        return fields, globals_
