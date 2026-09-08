# -*- coding: utf-8 -*-
"""Using a single DEM tif, automatically generate terrain files for wildfire simulation.

Get tif: https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3

Terminal command example:
    python map_builder.py bulamsan_dem.tif bulamsan

Results:
    maps/bulamsan/dem_final.tif
    maps/bulamsan/preview_map.png
    maps/bulamsan/preview_map_smooth.png
    maps/bulamsan/directional_slope_factor.npy
    maps/bulamsan/slope_preview.png
    maps/bulamsan/map_config.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import BoundaryNorm, LightSource, LinearSegmentedColormap, ListedColormap
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy.ndimage import distance_transform_edt, gaussian_filter, zoom

TARGET_CRS = "EPSG:5179"
CELL_SIZE_M = 30.0
NODATA = -9999.0
MIN_VALID_ELEVATION_M = -500.0
MAX_VALID_ELEVATION_M = 9000.0
SMOOTH_SCALE = 8
PREVIEW_PIXELS_PER_CELL = 16
MAX_PREVIEW_PIXELS = 18_000_000
MAX_SMOOTH_DISPLAY_CELLS = 10_000_000
PREVIEW_GAUSSIAN_SIGMA = 0.8
TERRAIN_COLORS = ["#83B66C", "#68A456", "#4D9148", "#33743A", "#14532D"]
MINOR_CONTOUR_COLOR = "#73816B"
MAJOR_CONTOUR_COLOR = "#56634F"
SLOPE_COLORS = ["#83B66C", "#E5D46A", "#E89243", "#C84435"]
BASE_DIR = Path(__file__).resolve().parents[1]

DIRECTIONS = [
    (0, -1, "N"), (1, -1, "NE"), (1, 0, "E"), (1, 1, "SE"),
    (0, 1, "S"), (-1, 1, "SW"), (-1, 0, "W"), (-1, -1, "NW"),
]


def fill_invalid_with_nearest(data: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, int]:
    """무효 셀을 가장 가까운 유효 고도값으로 채워 렌더링 줄무늬를 막는다."""
    filled_cells = int((~valid).sum())
    if not filled_cells:
        return data, 0

    filled = data.copy()
    nearest = distance_transform_edt(~valid, return_distances=False, return_indices=True)
    filled[~valid] = filled[tuple(nearest[:, ~valid])]
    return filled, filled_cells


def largest_valid_rectangle(mask: np.ndarray) -> tuple[int, int, int, int]:
    """유효 영역 안에 완전히 들어가는 가장 큰 직사각형을 찾는다."""
    best_area = 0
    best = None
    heights = np.zeros(mask.shape[1], dtype=np.int32)

    for row_index, row in enumerate(mask):
        heights = np.where(row, heights + 1, 0)
        stack: list[int] = []

        for col_index in range(mask.shape[1] + 1):
            current_height = heights[col_index] if col_index < mask.shape[1] else 0

            while stack and current_height < heights[stack[-1]]:
                top = stack.pop()
                height = int(heights[top])
                left = stack[-1] + 1 if stack else 0
                width = col_index - left
                area = height * width

                if area > best_area:
                    best_area = area
                    best = (
                        row_index - height + 1,
                        row_index,
                        left,
                        col_index - 1,
                    )

            stack.append(col_index)

    if best is None:
        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]
        return int(rows[0]), int(rows[-1]), int(cols[0]), int(cols[-1])

    return best


def convert_dem(input_file: Path, output_file: Path) -> tuple[np.ndarray, dict]:
    """원본 DEM을 30 m 정사각 셀로 바꾸고 시뮬레이션용 GeoTIFF로 저장한다."""
    with rasterio.open(input_file) as src:
        if src.crs is None:
            raise ValueError("입력 tif에 좌표계(CRS) 정보가 없습니다.")
        transform, width, height = calculate_default_transform(
            src.crs, TARGET_CRS, src.width, src.height, *src.bounds,
            resolution=CELL_SIZE_M,
        )

        source = src.read(1, masked=True).astype(np.float32)
        source_data = source.filled(NODATA)
        source_valid = (
            np.isfinite(source_data)
            & (source_data != NODATA)
            & (source_data >= MIN_VALID_ELEVATION_M)
            & (source_data <= MAX_VALID_ELEVATION_M)
        )
        if src.nodata is not None:
            source_valid &= source_data != src.nodata

        if not source_valid.any():
            raise ValueError("입력 tif에 유효한 고도값이 없습니다.")

        source_data, source_filled_cells = fill_invalid_with_nearest(source_data, source_valid)

        projected = np.full((height, width), NODATA, dtype=np.float32)
        reproject(
            source=source_data, destination=projected,
            src_transform=src.transform, src_crs=src.crs, src_nodata=NODATA,
            dst_transform=transform, dst_crs=TARGET_CRS, dst_nodata=NODATA,
            resampling=Resampling.bilinear,
        )

        projected_mask = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=source_valid.astype(np.uint8), destination=projected_mask,
            src_transform=src.transform, src_crs=src.crs, src_nodata=0,
            dst_transform=transform, dst_crs=TARGET_CRS, dst_nodata=0,
            resampling=Resampling.nearest,
        )

        valid = (projected_mask > 0) & np.isfinite(projected) & (projected != NODATA)
        if not valid.any():
            raise ValueError("변환 결과에 유효한 고도값이 없습니다.")
        r0, r1, c0, c1 = largest_valid_rectangle(valid)
        elevation = projected[r0:r1 + 1, c0:c1 + 1].copy()
        elevation_mask = projected_mask[r0:r1 + 1, c0:c1 + 1] > 0
        elevation_valid = elevation_mask & np.isfinite(elevation) & (elevation != NODATA)
        elevation, projected_filled_cells = fill_invalid_with_nearest(elevation, elevation_valid)
        crop_transform = window_transform(Window(c0, r0, elevation.shape[1], elevation.shape[0]), transform)
        meta = src.meta.copy()
        meta.update(
            driver="GTiff", dtype="float32", count=1, crs=TARGET_CRS,
            transform=crop_transform, width=elevation.shape[1], height=elevation.shape[0],
            nodata=None, compress="deflate",
        )
    with rasterio.open(output_file, "w", **meta) as dst:
        dst.write(elevation.astype(np.float32), 1)
    return elevation.astype(float), {
        "grid_width": int(elevation.shape[1]), "grid_height": int(elevation.shape[0]),
        "cell_size_m": CELL_SIZE_M, "crs": TARGET_CRS,
        "elevation_min_m": float(elevation.min()), "elevation_max_m": float(elevation.max()),
        "filled_edge_cells": projected_filled_cells,
        "filled_source_cells": source_filled_cells,
        "filled_projected_cells": projected_filled_cells,
    }


def save_preview(elevation: np.ndarray, output_file: Path, smooth: bool) -> None:
    """계산용 고도는 바꾸지 않고, 표시용 등고선 배경 이미지를 만든다."""
    height, width = elevation.shape
    low, high = float(elevation.min()), float(elevation.max())
    if smooth:
        smooth_scale = min(SMOOTH_SCALE, max(1, int(math.sqrt(MAX_SMOOTH_DISPLAY_CELLS / elevation.size))))
        display = zoom(elevation, smooth_scale, order=3)
        display = np.clip(display, low, high)
        resolution = CELL_SIZE_M / smooth_scale
    else:
        display = elevation
        resolution = CELL_SIZE_M

    shade_display = gaussian_filter(display, sigma=PREVIEW_GAUSSIAN_SIGMA, mode="nearest")

    pixels_per_cell = min(
        PREVIEW_PIXELS_PER_CELL,
        max(1, int(math.sqrt(MAX_PREVIEW_PIXELS / elevation.size))),
    )
    cmap = LinearSegmentedColormap.from_list("green_terrain", TERRAIN_COLORS)
    shaded = LightSource(azdeg=315, altdeg=45).shade(
        shade_display, cmap=cmap, vert_exag=1.2, dx=resolution, dy=resolution, blend_mode="soft"
    )
    dpi = 180
    fig = plt.figure(figsize=(width * pixels_per_cell / dpi,
                              height * pixels_per_cell / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(shaded, origin="upper", aspect="auto")
    minor = np.arange(math.ceil(low / 20) * 20, high + 20, 20)
    major = np.arange(math.ceil(low / 100) * 100, high + 100, 100)
    ax.contour(display, levels=minor, colors=MINOR_CONTOUR_COLOR, linewidths=0.35, alpha=0.65)
    major_cs = ax.contour(display, levels=major, colors=MAJOR_CONTOUR_COLOR, linewidths=0.85, alpha=0.9)
    ax.clabel(major_cs, inline=True, fontsize=7, fmt="%d m")
    ax.set_axis_off()
    fig.savefig(output_file, dpi=dpi)
    plt.close(fig)


def slope_factor(angle: float) -> tuple[float, int]:
    if angle < 5:
        return 1.0, 0
    if angle < 15:
        return 1.2, 10
    if angle < 25:
        return 1.6, 20
    return 2.8, 30


def save_directional_slope(elevation: np.ndarray, factor_file: Path, preview_file: Path) -> dict:
    """각 셀에서 8방향으로 확산할 때 쓸 오르막 경사 가중치를 저장한다."""
    height, width = elevation.shape
    factors = np.ones((height, width, 8), dtype=np.float32)
    max_class = np.zeros((height, width), dtype=np.int16)
    counts = {0: 0, 10: 0, 20: 0, 30: 0}
    total = 0
    for y in range(height):
        for x in range(width):
            cell_max = 0
            for i, (dx, dy, _) in enumerate(DIRECTIONS):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                total += 1
                rise = elevation[ny, nx] - elevation[y, x]
                if rise <= 0:
                    factor, cls = 1.0, 0
                else:
                    run = CELL_SIZE_M if dx == 0 or dy == 0 else CELL_SIZE_M * math.sqrt(2)
                    factor, cls = slope_factor(math.degrees(math.atan(rise / run)))
                factors[y, x, i] = factor
                counts[cls] += 1
                cell_max = max(cell_max, cls)
            max_class[y, x] = cell_max
    np.save(factor_file, factors)
    cmap = ListedColormap(SLOPE_COLORS)
    norm = BoundaryNorm([-1, 5, 15, 25, 31], cmap.N)
    fig, ax = plt.subplots(figsize=(8, 7), dpi=180)
    img = ax.imshow(max_class, cmap=cmap, norm=norm, origin="upper")
    bar = plt.colorbar(img, ax=ax, fraction=0.04, pad=0.03, ticks=[0, 10, 20, 30])
    bar.ax.set_yticklabels(["0°", "10°", "20°", "30°"])
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(preview_file, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    return {"directional_link_count": total, "slope_class_counts": counts}


def build_map(input_file: Path, map_name: str, output_root: Path) -> None:
    # 실행 위치와 무관하게 프로젝트 폴더(map_builder.py가 있는 폴더)를 기준으로 동작한다.
    if not input_file.is_absolute():
        input_file = BASE_DIR / input_file
    if not output_root.is_absolute():
        output_root = BASE_DIR / output_root

    if not input_file.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_file}")

    folder = output_root / map_name
    folder.mkdir(parents=True, exist_ok=True)
    files = {
        "dem": folder / "dem_final.tif",
        "preview_map": folder / "preview_map.png",
        "preview_map_smooth": folder / "preview_map_smooth.png",
        "directional_slope_factor": folder / "directional_slope_factor.npy",
        "slope_preview": folder / "slope_preview.png",
        "config": folder / "map_config.json",
    }
    elevation, dem_info = convert_dem(input_file, files["dem"])
    save_preview(elevation, files["preview_map"], smooth=False)
    save_preview(elevation, files["preview_map_smooth"], smooth=True)
    slope_info = save_directional_slope(elevation, files["directional_slope_factor"], files["slope_preview"])
    config = {
        "map_name": map_name, "source_file": str(input_file),
        "files": {key: str(value) for key, value in files.items() if key != "config"},
        **dem_info, **slope_info,
    }
    files["config"].write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    # 마지막으로 생성한 맵을 firespread가 자동으로 사용하도록 기록한다.
    def relative_to_project(path: Path) -> str:
        return path.relative_to(BASE_DIR).as_posix()

    active_map = {
        "map_name": map_name,
        "files": {
            "dem": relative_to_project(files["dem"]),
            "preview_map": relative_to_project(files["preview_map"]),
            "preview_map_smooth": relative_to_project(files["preview_map_smooth"]),
            "directional_slope_factor": relative_to_project(files["directional_slope_factor"]),
            "slope_preview": relative_to_project(files["slope_preview"]),
            "config": relative_to_project(files["config"]),
        },
        "grid_width": dem_info["grid_width"],
        "grid_height": dem_info["grid_height"],
        "cell_size_m": dem_info["cell_size_m"],
    }
    active_map_file = BASE_DIR / "active_map.json"
    active_map_file.write_text(
        json.dumps(active_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Map build complete")
    print("Map name:", map_name)
    print("Grid size:", dem_info["grid_width"], "x", dem_info["grid_height"])
    print("Resolution:", dem_info["cell_size_m"], "m x", dem_info["cell_size_m"], "m")
    print("Elevation range:", round(dem_info["elevation_min_m"], 2), "~", round(dem_info["elevation_max_m"], 2), "m")
    print("Created files:")
    for path in files.values():
        print(" -", path)
    print(" -", active_map_file)
    print("Active map for firespread:", map_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="원본 tif DEM에서 산불 시뮬레이션용 지형 맵을 생성합니다.")
    parser.add_argument("input_file", nargs="?", default="bulamsan_dem.tif")
    parser.add_argument("map_name", nargs="?", default=None)
    parser.add_argument("--output-root", default="maps")
    args = parser.parse_args()
    input_file = Path(args.input_file)
    map_name = args.map_name or input_file.stem.replace("_dem", "")
    build_map(input_file, map_name, Path(args.output_root))


if __name__ == "__main__":
    main()
