"""Two spatial class scores for the targeted ISS-inspired demonstration.

Inputs describe geometry, materials, source, boundary conditions and time.
No FDS observation is needed by inference. Scores are uncalibrated class
scores, never temperature, soot concentration or ignition probabilities.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import numpy as np
import torch
from ignis.ml.spatial_network import (
    CHANNELS,
    FEATURE_VERSION,
    SpatialUNet,
    geometry_channels,
    sampling_grid,
)
from ignis.ml.spatial_network import (
    input_tensor as spatial_input_tensor,
)
from ignis.physics import compile_case
from ignis.provenance import canonical_sha
from torch import nn

MODEL_ID = "iss-heat-smoke-poc-20261115"
SCHEMA_VERSION = "iss-poc-1"
HEAT_DELTA_C = 5.0
SMOKE_THRESHOLD_KG_M3 = 1e-6
OUTPUTS = ("heat", "smoke")
SCORE_SEMANTICS = "uncalibrated_spatial_class_scores"


def input_tensor(static, config, manifest, time_s):
    """Encode the genuine zero-power controls without mutating their FDS source.

    FDS intentionally emits no ramp for a disabled source. Its feature value
    is zero at every time; the legacy encoder expects at least one ramp point.
    An empty ramp on an energized source remains an error.
    """
    if manifest["source"]["ramp"]:
        return spatial_input_tensor(static, config, manifest, time_s)
    if config["ignition_power_w"] != 0:
        raise ValueError("An energized ISS source cannot have an empty ramp")
    feature_manifest = {
        **manifest,
        "source": {**manifest["source"], "ramp": [[0.0, 0.0], [float(config["duration_s"]), 0.0]]},
    }
    return spatial_input_tensor(static, config, feature_manifest, time_s)


class ISSClassifier(SpatialUNet):
    """Shared 3D U-Net backbone with separate heat and soot class logits."""

    def __init__(self, width=16):
        super().__init__(width)
        nn.init.constant_(self.field_head.bias, -2.0)
        for parameter in self.global_head.parameters():
            parameter.requires_grad_(False)

    def forward(self, values):
        return super().forward(values)[0]


def architecture(width=16):
    return {
        "version": "iss-heat-smoke-unet3d-1",
        "feature_version": FEATURE_VERSION,
        "input_channels": list(CHANNELS),
        "widths": [width, width * 2, width * 4],
        "output_channels": list(OUTPUTS),
        "output_semantics": "one independent class logit per channel and gas sample",
        "heat_delta_c": HEAT_DELTA_C,
        "smoke_threshold_kg_m3": SMOKE_THRESHOLD_KG_M3,
        "score_semantics": SCORE_SEMANTICS,
        "time_conditioning": "direct; no autoregression and no observed fields as inputs",
        "zero_power_source": "empty compiled ramp gives an identically zero ramp feature; source manifest unchanged",
    }


class ISSPredictor:
    """Hash-checked CPU/GPU inference from a compiled scene, without target arrays."""

    def __init__(self, weights: Path, *, device="cpu", expected_sha256=None):
        weights = Path(weights)
        self.weights_sha256 = hashlib.sha256(weights.read_bytes()).hexdigest()
        if expected_sha256 is not None and self.weights_sha256 != expected_sha256:
            raise ValueError("ISS checkpoint checksum mismatch")
        payload = torch.load(weights, map_location="cpu", weights_only=True)
        if payload.get("id") != MODEL_ID or payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Not an ISS POC checkpoint")
        width = payload["architecture"]["widths"][0]
        if payload["architecture"] != architecture(width):
            raise ValueError("Incompatible ISS classifier architecture")
        self.thresholds = payload["score_thresholds"]
        if set(self.thresholds) != set(OUTPUTS) or any(
            not np.isfinite(v) or not 0 <= v <= 1.000002 for v in self.thresholds.values()
        ):
            raise ValueError("Invalid frozen ISS class thresholds")
        self.sample_shape = tuple(payload["sample_shape"])
        self.network = ISSClassifier(width)
        self.network.load_state_dict(payload["state_dict"], strict=True)
        if any(not torch.isfinite(value).all().item() for value in self.network.state_dict().values()):
            raise ValueError("Nonfinite ISS classifier weights")
        self.device = torch.device(device)
        self.network.to(self.device).eval()
        self.metadata = {key: value for key, value in payload.items() if key != "state_dict"}

    def predict_arrays(self, config: dict, manifest: dict, times, *, batch_size=8):
        """Return [time, point, class] scores and masks in authoritative FDS order."""
        if canonical_sha(config) != canonical_sha(manifest["config"]):
            raise ValueError("Use the effective config associated with the compiled scene")
        shape, bounds, positions, gas, _, _ = sampling_grid(manifest)
        if tuple(shape) != self.sample_shape:
            raise ValueError("ISS POC sampling shape differs from training; no silent interpolation")
        times = np.asarray(times, dtype=np.float64)
        if (
            times.ndim != 1
            or not len(times)
            or not np.isfinite(times).all()
            or np.any(np.diff(times) <= 0)
            or not 1 <= batch_size <= 128
        ):
            raise ValueError("Require ordered finite times and an inference batch of 1..128")
        static = geometry_channels(manifest)
        chunks = []
        with torch.inference_mode():
            for start in range(0, len(times), batch_size):
                values = np.stack(
                    [input_tensor(static, config, manifest, t) for t in times[start : start + batch_size]]
                )
                score = self.network(torch.as_tensor(values, device=self.device)).sigmoid()
                chunks.append(score.flatten(2).transpose(1, 2).cpu().numpy())
        scores = np.concatenate(chunks)
        if not np.isfinite(scores).all():
            raise ValueError("Nonfinite ISS predictions")
        valid = np.broadcast_to(gas[None, :, None], scores.shape).copy()
        predicted = scores >= np.asarray([self.thresholds[name] for name in OUTPUTS])
        scores[~valid] = np.nan
        return {
            "time_s": times,
            "sample_positions_m": positions,
            "bounds_m": bounds,
            "shape": np.asarray(shape),
            "scores": scores,
            "predicted_mask": predicted & valid,
            "valid_mask": valid,
            "output_channels": OUTPUTS,
            "score_thresholds": self.thresholds,
            "score_semantics": SCORE_SEMANTICS,
        }

    def predict_scene(self, scene: dict, config: dict, times, *, batch_size=8):
        """Compile geometry only; this function does not launch the FDS solver."""
        with tempfile.TemporaryDirectory(prefix="ignis-iss-inference-") as directory:
            manifest = compile_case(scene, config, Path(directory))
        return self.predict_arrays(manifest["config"], manifest, times, batch_size=batch_size)
