#!/usr/bin/env python3
import argparse
import math
import struct
from pathlib import Path

EMPTY = 0
LEAF_BURNING = 2
STEM_BURNING = 3
BURNED = 4

LEAF_FUEL_MASS_PER_CELL = 1114.2
BASE_IGNITION_KJ_PER_KG = 581.0
WATER_EXTRA_KJ_PER_KG = 2596.0
STEM_IGNITION_THRESHOLD = 23_737_883.0
LEAF_HEAT_PER_TICK = 635_882.0
LEAF_RELEASE_PER_TICK = 77_813.0
LEAF_BURNING_MAX_TICKS = 32
DIAGONAL_WEIGHT = 1.0 / math.sqrt(2.0)
DIRECTION_WEIGHT_SUM = 4.0 + 4.0 * DIAGONAL_WEIGHT
WIND_MAIN_EXP_COEFFICIENT = 0.1783

DX = [0, 1, 1, 1, 0, -1, -1, -1]
DY = [-1, -1, 0, 1, 1, 1, 0, -1]
DIR_WEIGHT = [1.0, DIAGONAL_WEIGHT, 1.0, DIAGONAL_WEIGHT, 1.0, DIAGONAL_WEIGHT, 1.0, DIAGONAL_WEIGHT]
DIR_INDEX = {"N": 0, "NE": 1, "E": 2, "SE": 3, "S": 4, "SW": 5, "W": 6, "NW": 7}
LEAF_MOISTURE_BY_HUMIDITY = [
    0.000, 0.037, 0.051, 0.063, 0.072,
    0.081, 0.089, 0.096, 0.103, 0.109,
    0.116, 0.122, 0.129, 0.137, 0.146,
    0.158, 0.174, 0.196, 0.229, 0.240,
    0.250,
]

PRESETS = {
    "flat": ("../../maps/flat_square/directional_slope_factor.npy", 145, 145),
    "bulam": ("../../maps/bulam/directional_slope_factor.npy", 74, 67),
    "california": ("../../maps/california/directional_slope_factor.npy", 218, 145),
}


def load_npy_float32_3d(path):
    data = Path(path).read_bytes()
    if data[:6] != b"\x93NUMPY":
        raise ValueError(f"not an npy file: {path}")
    major = data[6]
    if major == 1:
        header_len = struct.unpack_from("<H", data, 8)[0]
        offset = 10
    else:
        header_len = struct.unpack_from("<I", data, 8)[0]
        offset = 12
    header = data[offset:offset + header_len].decode("ascii")
    shape_text = header.split("shape': (", 1)[1].split(")", 1)[0]
    shape = tuple(int(part.strip()) for part in shape_text.split(",") if part.strip())
    if len(shape) != 3 or "'<f4'" not in header:
        raise ValueError(f"unsupported npy header: {header}")
    values = struct.unpack_from("<" + "f" * math.prod(shape), data, offset + header_len)
    h, w, dirs = shape
    return values, w, h, dirs


def leaf_threshold(humidity_percent):
    index = max(0, min(20, round(humidity_percent / 5)))
    moisture = LEAF_MOISTURE_BY_HUMIDITY[index]
    return LEAF_FUEL_MASS_PER_CELL * (BASE_IGNITION_KJ_PER_KG + WATER_EXTRA_KJ_PER_KG * moisture)


def slope_at(slope, w, x, y, direction):
    return slope[((y * w + x) * 8) + direction]


def wind_factor(direction, wind_speed, wind_dir):
    if wind_speed <= 0:
        return 1.0
    main = math.exp(WIND_MAIN_EXP_COEFFICIENT * wind_speed)
    adjacent = max(1.0, main / math.sqrt(2.0))
    main_index = DIR_INDEX[wind_dir]
    if direction == main_index:
        return main
    if direction in ((main_index - 1) % 8, (main_index + 1) % 8):
        return adjacent
    return 1.0


def run_case(name, ticks, humidity, wind_speed, wind_dir):
    rel_path, expected_w, expected_h = PRESETS[name]
    slope, w, h, dirs = load_npy_float32_3d(Path(__file__).resolve().parent / rel_path)
    if (w, h, dirs) != (expected_w, expected_h, 8):
        raise ValueError(f"unexpected shape for {name}: {(w, h, dirs)}")

    state = [[EMPTY for _ in range(h)] for _ in range(w)]
    age = [[0 for _ in range(h)] for _ in range(w)]
    heat = [[0.0 for _ in range(h)] for _ in range(w)]
    ever = [[False for _ in range(h)] for _ in range(w)]

    cx, cy = w // 2, h // 2
    threshold = leaf_threshold(humidity)
    state[cx][cy] = LEAF_BURNING
    heat[cx][cy] = threshold
    ever[cx][cy] = True

    rows = []
    for tick in range(1, ticks + 1):
        delta = [[0.0 for _ in range(h)] for _ in range(w)]
        burnout = []
        for x in range(w):
            for y in range(h):
                if state[x][y] != LEAF_BURNING:
                    continue
                age[x][y] += 1
                heat[x][y] += LEAF_HEAT_PER_TICK
                if heat[x][y] >= STEM_IGNITION_THRESHOLD:
                    state[x][y] = STEM_BURNING
                    age[x][y] = 0
                    continue
                for direction in range(8):
                    nx = x + DX[direction]
                    ny = y + DY[direction]
                    if nx < 0 or nx >= w or ny < 0 or ny >= h or state[nx][ny] == STEM_BURNING:
                        continue
                    base = LEAF_RELEASE_PER_TICK * DIR_WEIGHT[direction] / DIRECTION_WEIGHT_SUM
                    delta[nx][ny] += base * wind_factor(direction, wind_speed, wind_dir) * slope_at(slope, w, x, y, direction)
                if age[x][y] >= LEAF_BURNING_MAX_TICKS:
                    burnout.append((x, y))

        for x in range(w):
            for y in range(h):
                if state[x][y] == STEM_BURNING or delta[x][y] <= 0.0:
                    continue
                heat[x][y] += delta[x][y]
                if state[x][y] == EMPTY and heat[x][y] >= threshold:
                    state[x][y] = LEAF_BURNING
                    age[x][y] = 0
                    ever[x][y] = True
                if state[x][y] in (LEAF_BURNING, BURNED) and heat[x][y] >= STEM_IGNITION_THRESHOLD:
                    state[x][y] = STEM_BURNING
                    age[x][y] = 0

        for x, y in burnout:
            if state[x][y] == LEAF_BURNING:
                state[x][y] = BURNED

        leaf = sum(state[x][y] == LEAF_BURNING for x in range(w) for y in range(h))
        stem = sum(state[x][y] == STEM_BURNING for x in range(w) for y in range(h))
        burned = sum(ever[x][y] for x in range(w) for y in range(h))
        rows.append((tick, leaf, stem, burned))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", choices=sorted(PRESETS), default="bulam")
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument("--humidity", type=int, default=0)
    parser.add_argument("--wind-speed", type=int, default=0)
    parser.add_argument("--wind-dir", choices=sorted(DIR_INDEX), default="N")
    args = parser.parse_args()

    print("tick,leaf_burning,stem_burning,total_burned")
    for row in run_case(args.map, args.ticks, args.humidity, args.wind_speed, args.wind_dir):
        print(",".join(str(value) for value in row))


if __name__ == "__main__":
    main()
