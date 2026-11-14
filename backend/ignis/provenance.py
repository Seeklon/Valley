"""Canonical physical scene identity excludes presentation-only asset metadata."""

from __future__ import annotations

import hashlib
import json

PHYSICAL_SCENE_HASH_VERSION = 2
PHYSICAL_SCENE_KEYS = (
    "id",
    "bounds_m",
    "coordinate_system",
    "units",
    "objects",
    "vents",
    "sensors",
    "source_position_m",
    "defaults",
)


def canonical_sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _normalize_integer_floats(value):
    """JSON 4 and 4.0 describe the same geometry; retain all noninteger values."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalize_integer_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_integer_floats(item) for key, item in value.items()}
    return value


def physical_scene_sha(scene):
    physical = {key: scene.get(key) for key in PHYSICAL_SCENE_KEYS}
    return canonical_sha(_normalize_integer_floats(physical))
