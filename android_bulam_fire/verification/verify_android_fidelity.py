#!/usr/bin/env python3
"""Verify Android fire-engine fidelity against the validated Python model."""

from __future__ import annotations

import hashlib
import math
import re
import sys
from pathlib import Path

from heat_engine_reference import PRESETS, load_npy_float32_3d, run_case


ROOT = Path(__file__).resolve().parents[2]
FIRE_VIEW = ROOT / "android_bulam_fire/app/src/main/java/com/genius/firespread/FireView.java"
ASSET_MAPS = ROOT / "android_bulam_fire/app/src/main/assets/maps"

EXPECTED_CONSTANTS = {
    "CELL_AREA_M2": 900.0,
    "LEAF_FUEL_MASS_PER_CELL": 1114.2,
    "BASE_IGNITION_KJ_PER_KG": 581.0,
    "WATER_EXTRA_KJ_PER_KG": 2596.0,
    "STEM_IGNITION_THRESHOLD": 23_737_883.0,
    "LEAF_HEAT_PER_TICK": 635_882.0,
    "LEAF_RELEASE_PER_TICK": 77_813.0,
    "LEAF_BURNING_MAX_TICKS": 32.0,
    "WIND_MAIN_EXP_COEFFICIENT": 0.1783,
}

REQUIRED_SOURCE_MARKERS = [
    "heatDelta[nx][ny] += finalTransfer",
    "slopeFactor[y][x][d]",
    "Math.exp(WIND_MAIN_EXP_COEFFICIENT * windSpeedKmh)",
    "maxSlopeFactorAt(x, y) < 2.8f",
    "clearSuppressionAtCell(x, y)",
]

EXPECTED_FINALS = {
    ("flat", 0, 0, "N"): (60, 0, 0, 1),
    ("flat", 0, 10, "E"): (60, 56, 9, 66),
    ("flat", 50, 10, "E"): (60, 19, 2, 24),
    ("flat", 0, 20, "SW"): (60, 395, 426, 821),
    ("flat", 100, 10, "NW"): (60, 7, 1, 9),
    ("bulam", 0, 0, "N"): (60, 0, 0, 1),
    ("bulam", 0, 10, "E"): (60, 91, 22, 113),
    ("bulam", 50, 10, "E"): (60, 26, 7, 36),
    ("bulam", 0, 20, "SW"): (60, 484, 548, 1032),
    ("bulam", 100, 10, "NW"): (60, 7, 2, 9),
    ("california", 0, 0, "N"): (60, 0, 0, 1),
    ("california", 0, 10, "E"): (60, 104, 49, 153),
    ("california", 50, 10, "E"): (60, 48, 21, 72),
    ("california", 0, 20, "SW"): (60, 550, 707, 1257),
    ("california", 100, 10, "NW"): (60, 19, 4, 25),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def java_number(source: str, name: str) -> float:
    pattern = rf"\b{name}\s*=\s*([0-9][0-9_]*(?:\.[0-9]+)?)"
    match = re.search(pattern, source)
    if not match:
        raise AssertionError(f"Missing Java constant: {name}")
    return float(match.group(1).replace("_", ""))


def check_java_source() -> None:
    source = FIRE_VIEW.read_text(encoding="utf-8")
    for name, expected in EXPECTED_CONSTANTS.items():
        actual = java_number(source, name)
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9):
            raise AssertionError(f"{name}: expected {expected}, got {actual}")

    for marker in REQUIRED_SOURCE_MARKERS:
        if marker not in source:
            raise AssertionError(f"Missing Android source marker: {marker}")


def check_assets() -> None:
    name_to_folder = {
        "flat": "flat_square",
        "bulam": "bulam",
        "california": "california",
    }
    for preset_name, (relative_slope, expected_w, expected_h) in PRESETS.items():
        folder = name_to_folder[preset_name]
        source_dir = (Path(__file__).resolve().parent / relative_slope).resolve().parent
        asset_dir = ASSET_MAPS / folder

        for filename in ("directional_slope_factor.npy", "preview_map.png"):
            source_file = source_dir / filename
            asset_file = asset_dir / filename
            if sha256(source_file) != sha256(asset_file):
                raise AssertionError(f"Asset hash mismatch: {folder}/{filename}")

        values, width, height, dirs = load_npy_float32_3d(asset_dir / "directional_slope_factor.npy")
        if (width, height, dirs) != (expected_w, expected_h, 8):
            raise AssertionError(f"Unexpected slope shape for {folder}: {(width, height, dirs)}")

        allowed = {1.0, 1.2, 1.6, 2.8}
        for value in values:
            if not any(math.isclose(value, allowed_value, rel_tol=0.0, abs_tol=1e-6) for allowed_value in allowed):
                raise AssertionError(f"Unexpected slope factor in {folder}: {value}")


def check_reference_regression() -> None:
    for (name, humidity, wind_speed, wind_dir), expected in EXPECTED_FINALS.items():
        rows = run_case(name, 60, humidity, wind_speed, wind_dir)
        actual = rows[-1]
        if actual != expected:
            raise AssertionError(
                f"Reference regression failed for {(name, humidity, wind_speed, wind_dir)}: "
                f"expected {expected}, got {actual}"
            )


def main() -> int:
    checks = [
        ("android source constants and formulas", check_java_source),
        ("android map assets", check_assets),
        ("validated reference scenarios", check_reference_regression),
    ]
    for label, check in checks:
        check()
        print(f"PASS {label}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
