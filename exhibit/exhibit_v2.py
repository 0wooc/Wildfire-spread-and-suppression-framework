# -*- coding: utf-8 -*-
"""California Caldor Fire Spread v10."""

import ast
import csv
import math
import struct
import sys
from functools import lru_cache
from pathlib import Path

import pygame


# ---------------------------------------------------------------------------
# 전시 설치 설정
# ---------------------------------------------------------------------------
# PyInstaller one-file 실행본에서는 압축 해제된 자산 경로를 사용한다.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
MAP_FILE = BASE_DIR / "maps" / "california" / "preview_map.png"
SLOPE_FACTOR_FILE = BASE_DIR / "maps" / "california" / "directional_slope_factor.npy"
COMPARISON_MAP_FILE = BASE_DIR / "maps" / "bulam" / "preview_map.png"
COMPARISON_SLOPE_FACTOR_FILE = BASE_DIR / "maps" / "bulam" / "directional_slope_factor.npy"
WEATHER_FILE = BASE_DIR / "maps" / "california" / "California Caldor weather&area 24h.csv"
FOREST_BACKGROUND_FILE = BASE_DIR / "assets" / "forest_background_v2.png"
TOOL_ICON_DIR = BASE_DIR / "assets" / "tool_icons"
UI_FONT_FILE = BASE_DIR / "assets" / "NanumGothic-Bold.ttf"

DISPLAY_WIDTH = 1080
DISPLAY_HEIGHT = 1920
FULLSCREEN = bool(getattr(sys, "frozen", False))
WINDOW_SCALE = 0.45                # 노트북 미리보기 창: 486 x 864
# 이전 전시 속도(슬라이더 약 2/3 지점)의 두 배로 고정한다.
COMPARISON_SPEED_MULTIPLIER = 13.6
HUMIDITY_COMPARISON_SPEED_MULTIPLIER = COMPARISON_SPEED_MULTIPLIER * 1.5
GAME_SPEED_MULTIPLIER = 1.5
GAME_OVER_ACTIVE_FIRE_CELLS = 18_966  # California 218 x 145 격자의 3/5
# 최고 강불 임계 열량을 3회에 나누어 낮추는 진압량.
WATER_COOLING_KJ = 7_912_628.0
INITIAL_FIRE_RADIUS = 2
WET_DURATION_TICKS = 18
WET_SPREAD_FACTOR = 0.35
WET_RECEIVE_FACTOR = 0.30
FIRE_AREA_LIMIT_M2 = 1_000_000
RESULT_SPLIT_MS = 1_050
RESULT_MESSAGE_HOLD_MS = 4_000
SCREEN_FADE_MS = 420
GAME_INTRO_MESSAGE_MS = 3_000
WEAK_WIND_SPEED_KMH = 7.2
STRONG_WIND_SPEED_KMH = 14.4

MAP_LEFT = 48
MAP_TOP = 160
MAP_WIDTH = 984
MAP_HEIGHT = 891
PANEL_TOP = 1095

# 물리 모델: v9.3의 낙엽·줄기 점화 및 풍향·경사 확산식을 유지한다.
CELL_REAL_SIZE_M = 30.0
CELL_AREA_M2 = CELL_REAL_SIZE_M ** 2
SIMULATION_SECONDS_PER_TICK = 5 * 60
BASE_TICK_INTERVAL_MS = 500

LEAF_FUEL_MASS_PER_CELL = 1114.2
BASE_IGNITION_KJ_PER_KG = 581.0
WATER_EXTRA_KJ_PER_KG = 2596.0
LEAF_MOISTURE_BY_HUMIDITY = {
    0: 0.000, 5: 0.037, 10: 0.051, 15: 0.063, 20: 0.072,
    25: 0.081, 30: 0.089, 35: 0.096, 40: 0.103, 45: 0.109,
    50: 0.116, 55: 0.122, 60: 0.129, 65: 0.137, 70: 0.146,
    75: 0.158, 80: 0.174, 85: 0.196, 90: 0.229, 95: 0.240,
    100: 0.250,
}
STEM_IGNITION_THRESHOLD = 23_737_883.0
LEAF_HEAT_PER_TICK = 635_882.0
LEAF_RELEASE_PER_TICK = 77_813.0
LEAF_BURNING_MAX_TICKS = 32
WIND_MAIN_EXP_COEFFICIENT = 0.1783
DIAGONAL_WEIGHT = 1.0 / math.sqrt(2.0)
DIRECTION_WEIGHT_SUM = 4.0 + 4.0 * DIAGONAL_WEIGHT

DIR_NAMES = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
DIR_INDEX = {name: index for index, name in enumerate(DIR_NAMES)}
DIR_KOREAN_NAMES = {
    "N": "북", "NE": "북동", "E": "동", "SE": "남동",
    "S": "남", "SW": "남서", "W": "서", "NW": "북서",
}
# 전시용 풍향 패턴: 남동쪽 → 남서쪽 → 북쪽 순으로 반복한다.
WIND_DIRECTION_PATTERN = ("SE", "SW", "N")
WIND_DIRECTION_CHANGE_TICKS = 18
NEIGHBORS = [
    (0, -1, 0, 1.0), (1, -1, 1, DIAGONAL_WEIGHT),
    (1, 0, 2, 1.0), (1, 1, 3, DIAGONAL_WEIGHT),
    (0, 1, 4, 1.0), (-1, 1, 5, DIAGONAL_WEIGHT),
    (-1, 0, 6, 1.0), (-1, -1, 7, DIAGONAL_WEIGHT),
]

BG = (235, 248, 228)
PANEL_BG = (215, 240, 204)
PANEL_LINE = (159, 196, 139)
WHITE = (255, 255, 250)
MUTED = (59, 89, 61)
ACCENT = (66, 137, 66)
SELECTED = (58, 139, 72)
BUTTON = (250, 255, 246)
BUTTON_TEXT = (32, 85, 42)
TITLE_GREEN = (22, 102, 44)
LEAF_PALETTE = [(255, 214, 150), (255, 184, 96), (255, 146, 55), (245, 105, 28), (222, 72, 12)]
STEM_FIRE = (205, 36, 26)
BURNED = (78, 58, 37)
HEATING = (255, 225, 130)


class Cell:
    def __init__(self, directional_slope_factors):
        self.directional_slope_factors = directional_slope_factors
        self.state = "unburned"
        self.heat = 0.0
        self.leaf_ticks = 0
        self.ever_burned = False
        self.blocked = False
        self.wet_ticks = 0


def load_world(slope_factor_file=SLOPE_FACTOR_FILE):
    if not slope_factor_file.exists():
        raise FileNotFoundError("maps/bulam의 preview_map.png 또는 directional_slope_factor.npy를 찾을 수 없습니다.")

    # map_builder.py가 만든 float32 NPY 파일을 표준 라이브러리로 읽는다.
    # 전시 PC에는 rasterio/numpy 설치가 필요 없다.
    with slope_factor_file.open("rb") as source:
        if source.read(6) != b"\x93NUMPY":
            raise ValueError("지원하지 않는 경사 가중치 파일입니다.")
        major, _minor = struct.unpack("BB", source.read(2))
        header_size = struct.unpack("<H" if major == 1 else "<I", source.read(2 if major == 1 else 4))[0]
        header = source.read(header_size).decode("latin1")
        if "'descr': '<f4'" not in header:
            raise ValueError("불암산 전시용 경사 가중치 파일 형식이 아닙니다.")
        shape_start = header.index("'shape':") + len("'shape':")
        shape_end = header.index("}", shape_start)
        shape = ast.literal_eval(header[shape_start:shape_end].strip().rstrip(","))
        if len(shape) != 3 or shape[2] != 8:
            raise ValueError("방향별 경사 가중치 형식이 아닙니다.")
        height, width, _directions = shape
        values = struct.unpack(f"<{width * height * 8}f", source.read(width * height * 8 * 4))

    grid = []
    for x in range(width):
        column = []
        for y in range(height):
            offset = (y * width + x) * 8
            column.append(Cell(values[offset:offset + 8]))
        grid.append(column)
    return grid, width, height


def leaf_threshold(humidity):
    moisture = LEAF_MOISTURE_BY_HUMIDITY[humidity]
    return LEAF_FUEL_MASS_PER_CELL * (BASE_IGNITION_KJ_PER_KG + WATER_EXTRA_KJ_PER_KG * moisture)


def wind_factor(direction_index, wind_speed, wind_direction):
    main_factor = math.exp(WIND_MAIN_EXP_COEFFICIENT * wind_speed)
    main_index = DIR_INDEX[wind_direction]
    if direction_index == main_index:
        return main_factor
    if direction_index in ((main_index - 1) % 8, (main_index + 1) % 8):
        return max(1.0, main_factor / math.sqrt(2.0))
    return 1.0


def wind_direction_for_tick(tick):
    pattern_index = (tick // WIND_DIRECTION_CHANGE_TICKS) % len(WIND_DIRECTION_PATTERN)
    return WIND_DIRECTION_PATTERN[pattern_index]


def ignite(grid, x, y, threshold):
    cell = grid[x][y]
    if cell.blocked or cell.state in ("stem", "burned"):
        return
    cell.state = "leaf"
    cell.heat = max(cell.heat, threshold)
    cell.leaf_ticks = 0
    cell.ever_burned = True


def update_fire(grid, grid_width, grid_height, threshold, wind_speed, wind_direction):
    for column in grid:
        for cell in column:
            if cell.wet_ticks > 0:
                cell.wet_ticks -= 1
    heat_delta = [[0.0 for _ in range(grid_height)] for _ in range(grid_width)]
    burnout = []
    for x in range(grid_width):
        for y in range(grid_height):
            cell = grid[x][y]
            if cell.state != "leaf":
                continue
            cell.leaf_ticks += 1
            cell.heat += LEAF_HEAT_PER_TICK
            if cell.heat >= STEM_IGNITION_THRESHOLD:
                cell.state = "stem"
                continue
            for dx, dy, direction_index, direction_weight in NEIGHBORS:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < grid_width and 0 <= ny < grid_height):
                    continue
                neighbor = grid[nx][ny]
                if neighbor.blocked or neighbor.state == "stem":
                    continue
                base = LEAF_RELEASE_PER_TICK * direction_weight / DIRECTION_WEIGHT_SUM
                slope = cell.directional_slope_factors[direction_index]
                source_factor = WET_SPREAD_FACTOR if cell.wet_ticks > 0 else 1.0
                receive_factor = WET_RECEIVE_FACTOR if neighbor.wet_ticks > 0 else 1.0
                heat_delta[nx][ny] += base * wind_factor(direction_index, wind_speed, wind_direction) * slope * source_factor * receive_factor
            if cell.leaf_ticks >= LEAF_BURNING_MAX_TICKS:
                burnout.append((x, y))
    for x in range(grid_width):
        for y in range(grid_height):
            cell = grid[x][y]
            if cell.state == "stem" or heat_delta[x][y] <= 0:
                continue
            cell.heat += heat_delta[x][y]
            if cell.state == "unburned" and cell.heat >= threshold:
                ignite(grid, x, y, threshold)
            elif cell.state in ("leaf", "burned") and cell.heat >= STEM_IGNITION_THRESHOLD:
                cell.state = "stem"
    for x, y in burnout:
        if grid[x][y].state == "leaf":
            grid[x][y].state = "burned"


@lru_cache(maxsize=128)
def make_font(size, bold=False):
    # 실제 Bold 글꼴을 공통 사용한다. 합성 굵기나 운영체제별 대체 글꼴은 사용하지 않는다.
    return pygame.font.Font(str(UI_FONT_FILE), size)


def make_fitted_font(text, maximum_size, maximum_width, bold=False):
    for size in range(maximum_size, 0, -1):
        font = make_font(size, bold)
        if font.size(text)[0] <= maximum_width:
            return font
    return make_font(1, bold)


def draw_text(surface, font, text, rect, color=WHITE, align="left"):
    image = font.render(text, True, color)
    text_rect = image.get_rect()
    if align == "center":
        text_rect.center = rect.center
    elif align == "right":
        text_rect.midright = rect.midright
    else:
        text_rect.midleft = rect.midleft
    surface.blit(image, text_rect)


def button(surface, font, rect, label, selected=False):
    pygame.draw.rect(surface, SELECTED if selected else BUTTON, rect, border_radius=14)
    pygame.draw.rect(surface, ACCENT if selected else PANEL_LINE, rect, 3, border_radius=14)
    draw_text(surface, font, label, rect, WHITE if selected else BUTTON_TEXT, "center")


def count_burned(grid):
    return sum(cell.ever_burned for column in grid for cell in column)


def exceeds_fire_area_limit(grid):
    return count_burned(grid) * CELL_AREA_M2 >= FIRE_AREA_LIMIT_M2


def run():
    pygame.init()
    flags = pygame.FULLSCREEN if FULLSCREEN else 0
    window_size = (DISPLAY_WIDTH, DISPLAY_HEIGHT) if FULLSCREEN else (
        round(DISPLAY_WIDTH * WINDOW_SCALE), round(DISPLAY_HEIGHT * WINDOW_SCALE)
    )
    window = pygame.display.set_mode(window_size, flags)
    screen = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT))
    pygame.display.set_caption(" ")
    clock = pygame.time.Clock()
    start_title_font = make_fitted_font("산불을 체험해보자!", 120, 840, True)
    start_button_font = make_font(155, True)
    panel_label_font = make_font(46, True)
    area_font = make_font(30, True)
    explanation_font = make_font(42, True)
    transition_explanation_font = make_fitted_font("습도가 낮을수록 나무와 낙엽이 말라", 52, 850, True)

    game_grid, grid_width, grid_height = load_world()
    panel_map_width, panel_map_height = 940, 440
    panel_map_image = pygame.transform.smoothscale(
        pygame.image.load(MAP_FILE).convert(),
        (panel_map_width, panel_map_height),
    )
    comparison_map_image = pygame.transform.smoothscale(
        pygame.image.load(COMPARISON_MAP_FILE).convert(),
        (panel_map_width, panel_map_height),
    )
    if not FOREST_BACKGROUND_FILE.exists():
        raise FileNotFoundError(f"숲 배경 이미지를 찾을 수 없습니다: {FOREST_BACKGROUND_FILE}")
    forest_source = pygame.image.load(FOREST_BACKGROUND_FILE).convert()
    forest_width = max(
        DISPLAY_WIDTH + 1,
        round(forest_source.get_width() * DISPLAY_HEIGHT / forest_source.get_height()),
    )
    forest_scaled = pygame.transform.smoothscale(forest_source, (forest_width, DISPLAY_HEIGHT))
    forest_blurred = pygame.transform.smoothscale(
        pygame.transform.smoothscale(forest_scaled, (forest_width // 10, DISPLAY_HEIGHT // 10)),
        (forest_width, DISPLAY_HEIGHT),
    )
    comparison_mode = None
    scene = "start"
    weak_grid = strong_grid = None
    comparison_grid_width = 74
    comparison_grid_height = 67
    elapsed_ticks = 0
    last_tick = pygame.time.get_ticks()
    transition_started_at = None
    frozen = False
    result_reveal_started_at = None
    fade_target = None
    game_intro_stage = 0
    game_intro_started_at = None

    def load_california_weather():
        if not WEATHER_FILE.exists():
            raise FileNotFoundError(f"California weather CSV를 찾을 수 없습니다: {WEATHER_FILE}")
        with WEATHER_FILE.open("r", encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        return [
            {
                "tick": int(float(row["simulation_tick_5min"])),
                "humidity": int(float(row["humidity_input_for_current_code_percent_rounded_to_5"])),
                "wind_speed": float(row["wind_speed_10m_kmh"]),
                "wind_direction": row["wind_direction_input_for_current_code"].strip().upper(),
            }
            for row in rows
        ]

    weather_timeline = load_california_weather()
    game_elapsed_ticks = 0
    game_last_tick = pygame.time.get_ticks()
    game_weather = weather_timeline[0]
    game_paused = False
    developer_mode = False
    selected_tool = None
    game_result = None
    game_result_started_at = None
    on_fire_cells = 13
    water_effects = []
    firebreak_drag_start = None
    game_center_x, game_center_y = grid_width // 2, grid_height // 2
    def ignite_initial_fire():
        threshold = leaf_threshold(game_weather["humidity"])
        for ignition_x in range(game_center_x - INITIAL_FIRE_RADIUS, game_center_x + INITIAL_FIRE_RADIUS + 1):
            for ignition_y in range(game_center_y - INITIAL_FIRE_RADIUS, game_center_y + INITIAL_FIRE_RADIUS + 1):
                distance = abs(ignition_x - game_center_x) + abs(ignition_y - game_center_y)
                if distance > INITIAL_FIRE_RADIUS:
                    continue
                ignite(game_grid, ignition_x, ignition_y, threshold)
                # 중심 5칸은 강불, 바깥 8칸은 약불로 시작한다.
                game_grid[ignition_x][ignition_y].heat = STEM_IGNITION_THRESHOLD * 0.75 if distance <= 1 else threshold

    game_map_rect = pygame.Rect(40, 325, 1000, 960)
    game_map_source = pygame.image.load(MAP_FILE).convert()
    source_crop = game_map_source.get_rect().inflate(
        -round(game_map_source.get_width() * 0.46),
        -round(game_map_source.get_height() * 0.50),
    )
    game_map_image = pygame.transform.smoothscale(game_map_source.subsurface(source_crop), game_map_rect.size)
    visible_x0 = round(grid_width * source_crop.left / game_map_source.get_width())
    visible_x1 = round(grid_width * source_crop.right / game_map_source.get_width())
    visible_y0 = round(grid_height * source_crop.top / game_map_source.get_height())
    visible_y1 = round(grid_height * source_crop.bottom / game_map_source.get_height())
    game_label_font = make_font(32, True)
    game_direction_font = make_font(24, True)
    tool_label_font = make_font(31, True)

    tool_buttons = [
        {"name": "방화선", "icon": "firebreak.png", "cooldown_ms": 4_000, "ready_at": pygame.time.get_ticks(), "rect": pygame.Rect(60, 1305, 460, 112), "flash_until": 0},
        {"name": "비행기", "icon": "plane.png", "cooldown_ms": 7_000, "ready_at": pygame.time.get_ticks() + 7_000, "rect": pygame.Rect(560, 1305, 460, 112), "flash_until": 0},
        {"name": "헬기", "icon": "helicopter.png", "cooldown_ms": 5_000, "ready_at": pygame.time.get_ticks() + 5_000, "rect": pygame.Rect(60, 1450, 460, 112), "flash_until": 0},
        {"name": "소방차", "icon": "firetruck.png", "cooldown_ms": 2_000, "ready_at": pygame.time.get_ticks(), "rect": pygame.Rect(560, 1450, 460, 112), "flash_until": 0},
    ]
    restart_rect = pygame.Rect(60, 1600, 960, 82)
    developer_rect = pygame.Rect(60, 1710, 960, 82)
    return_rect = pygame.Rect(330, 1035, 420, 110)
    game_back_rect = pygame.Rect(50, 20, 150, 62)

    tool_icons = {}
    for tool in tool_buttons:
        icon_path = TOOL_ICON_DIR / tool["icon"]
        if not icon_path.exists():
            raise FileNotFoundError(f"진압수단 아이콘을 찾을 수 없습니다: {icon_path}")
        icon = pygame.image.load(icon_path).convert_alpha()
        scale = min(116 / icon.get_width(), 78 / icon.get_height())
        tool_icons[tool["icon"]] = pygame.transform.smoothscale(
            icon,
            (round(icon.get_width() * scale), round(icon.get_height() * scale)),
        )

    ignite_initial_fire()

    def reset_game():
        nonlocal game_grid, game_elapsed_ticks, game_last_tick, game_weather, game_paused, selected_tool, game_result, game_result_started_at, on_fire_cells, water_effects, firebreak_drag_start
        game_grid, _, _ = load_world()
        game_elapsed_ticks = 0
        game_weather = weather_timeline[0]
        game_last_tick = pygame.time.get_ticks()
        game_paused = False
        selected_tool = None
        game_result = None
        game_result_started_at = None
        on_fire_cells = 13
        water_effects = []
        firebreak_drag_start = None
        ignite_initial_fire()
        for tool in tool_buttons:
            tool["ready_at"] = pygame.time.get_ticks() if tool["name"] in ("방화선", "소방차") else pygame.time.get_ticks() + tool["cooldown_ms"]

    def return_to_start_screen():
        nonlocal scene, comparison_mode, frozen, game_result, game_paused
        scene = "start"
        comparison_mode = None
        frozen = False
        game_result = None
        game_paused = False

    def start_game_intro(started_at):
        nonlocal scene, game_intro_stage, game_intro_started_at
        reset_game()
        scene = "game_intro"
        game_intro_stage = 0
        game_intro_started_at = started_at

    def apply_firebreak(start, end):
        steps = min(8, max(abs(end[0] - start[0]), abs(end[1] - start[1])) + 1)
        for index in range(steps):
            ratio = 0 if steps == 1 else index / (steps - 1)
            x = round(start[0] + (end[0] - start[0]) * ratio)
            y = round(start[1] + (end[1] - start[1]) * ratio)
            if 0 <= x < grid_width and 0 <= y < grid_height:
                cell = game_grid[x][y]
                cell.blocked = True
                cell.heat = 0.0
                cell.state = "burned"

    def apply_tool(tool, gx, gy):
        if tool["name"] == "방화선":
            return
        else:
            radius_x, radius_y = {"비행기": (5, 3), "헬기": (3, 2), "소방차": (2, 2)}[tool["name"]]
            targets = [(x, y) for x in range(gx - radius_x, gx + radius_x + 1) for y in range(gy - radius_y, gy + radius_y + 1)]
        for x, y in targets:
            if not (0 <= x < grid_width and 0 <= y < grid_height):
                continue
            cell = game_grid[x][y]
            water_effects.append({"x": x, "y": y, "apply_at": pygame.time.get_ticks() + (abs(x - gx) + abs(y - gy)) * 45, "applied": False})

    def process_water_effects(now_ms):
        active = []
        for effect in water_effects:
            if not effect["applied"] and now_ms >= effect["apply_at"]:
                cell = game_grid[effect["x"]][effect["y"]]
                cell.heat = max(0.0, cell.heat - WATER_COOLING_KJ)
                cell.wet_ticks = max(cell.wet_ticks, WET_DURATION_TICKS)
                if cell.state in ("leaf", "stem") and cell.heat < leaf_threshold(game_weather["humidity"]):
                    cell.state = "unburned"
                    cell.leaf_ticks = 0
                effect["applied"] = True
                effect["fade_until"] = now_ms + 420
            if not effect["applied"] or now_ms < effect["fade_until"]:
                active.append(effect)
        water_effects[:] = active

    def count_on_fire_cells():
        return sum(cell.state in ("leaf", "stem") for column in game_grid for cell in column)

    def clear_isolated_embers():
        active = {(x, y) for x in range(grid_width) for y in range(grid_height) if game_grid[x][y].state in ("leaf", "stem")}
        if not active:
            return True
        visited = set()
        components = []
        for start in active:
            if start in visited:
                continue
            stack = [start]
            component = []
            visited.add(start)
            while stack:
                x, y = stack.pop()
                component.append((x, y))
                for dx, dy, _direction, _weight in NEIGHBORS:
                    neighbor = (x + dx, y + dy)
                    if neighbor in active and neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
            components.append(component)
        if any(len(component) > 2 for component in components):
            return False
        return True

    start_title_rect = pygame.Rect(80, 810, 920, 300)
    game_shortcut_rect = pygame.Rect(280, 1150, 520, 130)
    back_rect = pygame.Rect(38, 36, 112, 72)
    weak_panel = pygame.Rect(40, 150, 1000, 610)
    strong_panel = pygame.Rect(40, 800, 1000, 610)
    result_weak_panel = pygame.Rect(40, 105, 1000, 610)
    result_strong_panel = pygame.Rect(40, 995, 1000, 610)

    def start_comparison(mode):
        nonlocal weak_grid, strong_grid, elapsed_ticks, comparison_mode, last_tick, frozen, result_reveal_started_at, comparison_grid_width, comparison_grid_height
        weak_grid, comparison_grid_width, comparison_grid_height = load_world(COMPARISON_SLOPE_FACTOR_FILE)
        strong_grid, _, _ = load_world(COMPARISON_SLOPE_FACTOR_FILE)
        humidities = (25, 25) if mode == "wind" else (70, 0)
        center_x, center_y = comparison_grid_width // 2, comparison_grid_height // 2
        for grid, humidity in zip((weak_grid, strong_grid), humidities):
            for ignition_x, ignition_y in (
                (center_x - 1, center_y - 1),
                (center_x, center_y - 1),
                (center_x - 1, center_y),
                (center_x, center_y),
            ):
                ignite(grid, ignition_x, ignition_y, leaf_threshold(humidity))
        elapsed_ticks = 0
        comparison_mode = mode
        frozen = False
        result_reveal_started_at = None
        last_tick = pygame.time.get_ticks()

    def ease_out_cubic(value):
        return 1 - (1 - max(0.0, min(1.0, value))) ** 3

    def lerp(start, end, value):
        return round(start + (end - start) * value)

    def draw_fire_panel(panel_rect, label, grid, humidity, wind_speed):
        pygame.draw.rect(screen, WHITE, panel_rect, border_radius=32)
        pygame.draw.rect(screen, PANEL_LINE, panel_rect, 3, border_radius=32)
        draw_text(
            screen,
            panel_label_font,
            label,
            pygame.Rect(panel_rect.x, panel_rect.y + 20, panel_rect.width, 58),
            TITLE_GREEN,
            "center",
        )
        map_rect = pygame.Rect(panel_rect.x + 30, panel_rect.y + 90, panel_map_width, panel_map_height)
        screen.blit(comparison_map_image, map_rect.topleft)
        threshold = leaf_threshold(humidity)
        cell_w = panel_map_width / comparison_grid_width
        cell_h = panel_map_height / comparison_grid_height
        overlay = pygame.Surface((panel_map_width, panel_map_height), pygame.SRCALPHA)
        for x in range(comparison_grid_width):
            for y in range(comparison_grid_height):
                cell = grid[x][y]
                rect = pygame.Rect(round(x * cell_w), round(y * cell_h), math.ceil(cell_w) + 1, math.ceil(cell_h) + 1)
                if cell.state == "unburned" and cell.heat > 0:
                    ratio = min(1.0, cell.heat / threshold)
                    overlay.fill((*HEATING, int(35 + 150 * ratio)), rect)
                elif cell.state == "leaf":
                    ratio = max(0.0, min(1.0, (cell.heat - threshold) / (STEM_IGNITION_THRESHOLD - threshold)))
                    overlay.fill((*LEAF_PALETTE[min(4, int(ratio * 5))], 235), rect)
                elif cell.state == "stem":
                    overlay.fill((*STEM_FIRE, 245), rect)
                elif cell.state == "burned":
                    overlay.fill((*BURNED, 200), rect)
                if cell.wet_ticks > 0:
                    overlay.fill((80, 190, 255, 45), rect)
        screen.blit(overlay, map_rect.topleft)
        burned_area_m2 = count_burned(grid) * CELL_AREA_M2
        draw_text(screen, area_font, f"피해 면적: {burned_area_m2:,.0f} m²", pygame.Rect(panel_rect.x, panel_rect.bottom - 62, panel_rect.width, 40), TITLE_GREEN, "center")

    def weather_for_tick(tick):
        current = weather_timeline[0]
        for record in weather_timeline:
            if record["tick"] > tick:
                break
            current = record
        return current

    def draw_environment_slider(label, value_text, y, ratio, track_left, track_right):
        draw_text(screen, game_label_font, f"{label}: {value_text}", pygame.Rect(62, y, track_left - 76, 52), WHITE, "left")
        track_y = y + 27
        pygame.draw.line(screen, (119, 126, 123), (track_left, track_y), (track_right, track_y), 5)
        for tick in range(5):
            tick_x = track_left + round((track_right - track_left) * tick / 4)
            pygame.draw.line(screen, (176, 183, 179), (tick_x, track_y - 13), (tick_x, track_y + 13), 3)
        knob_x = track_left + round((track_right - track_left) * max(0.0, min(1.0, ratio)))
        pygame.draw.circle(screen, (235, 244, 239), (knob_x, track_y), 15)
        pygame.draw.circle(screen, (34, 141, 82), (knob_x, track_y), 10)

    def draw_game_screen():
        screen.fill((23, 27, 25))
        pygame.draw.rect(screen, (9, 12, 11), game_map_rect.inflate(12, 12), border_radius=10)
        screen.blit(game_map_image, game_map_rect.topleft)

        humidity = game_weather["humidity"]
        threshold = leaf_threshold(humidity)
        cell_w = game_map_rect.width / (visible_x1 - visible_x0)
        cell_h = game_map_rect.height / (visible_y1 - visible_y0)
        overlay = pygame.Surface(game_map_rect.size, pygame.SRCALPHA)
        for x in range(visible_x0, visible_x1):
            for y in range(visible_y0, visible_y1):
                cell = game_grid[x][y]
                rect = pygame.Rect(round((x - visible_x0) * cell_w), round((y - visible_y0) * cell_h), math.ceil(cell_w) + 1, math.ceil(cell_h) + 1)
                if cell.state == "unburned" and cell.heat > 0:
                    ratio = min(1.0, cell.heat / threshold)
                    overlay.fill((*HEATING, int(35 + 150 * ratio)), rect)
                elif cell.state == "leaf":
                    ratio = max(0.0, min(1.0, (cell.heat - threshold) / (STEM_IGNITION_THRESHOLD - threshold)))
                    overlay.fill((*LEAF_PALETTE[min(4, int(ratio * 5))], 235), rect)
                elif cell.state == "stem":
                    overlay.fill((*STEM_FIRE, 245), rect)
                elif cell.state == "burned":
                    overlay.fill((*BURNED, 200), rect)
                if cell.wet_ticks > 0:
                    overlay.fill((80, 190, 255, 45), rect)
        screen.blit(overlay, game_map_rect.topleft)
        for effect in water_effects:
            if not effect["applied"]:
                continue
            if not (visible_x0 <= effect["x"] < visible_x1 and visible_y0 <= effect["y"] < visible_y1):
                continue
            age = max(0, effect["fade_until"] - now) / 420
            cx = game_map_rect.x + round((effect["x"] - visible_x0 + 0.5) * cell_w)
            cy = game_map_rect.y + round((effect["y"] - visible_y0 + 0.5) * cell_h)
            pygame.draw.circle(screen, (72, 186, 255), (cx, cy), max(7, round(20 * age)))

        top_panel = pygame.Rect(0, 0, DISPLAY_WIDTH, 285)
        bottom_panel = pygame.Rect(0, 1295, DISPLAY_WIDTH, DISPLAY_HEIGHT - 1295)
        pygame.draw.rect(screen, (48, 52, 50), top_panel)
        pygame.draw.rect(screen, (48, 52, 50), bottom_panel)
        pygame.draw.line(screen, (102, 112, 107), (48, 285), (1032, 285), 2)
        pygame.draw.line(screen, (102, 112, 107), (48, 1295), (1032, 1295), 2)
        pygame.draw.rect(screen, (39, 72, 53), game_back_rect, border_radius=18)
        pygame.draw.lines(screen, WHITE, False, [(145, 34), (118, 51), (145, 68)], 6)
        draw_environment_slider("습도", f"{humidity}%", 105, humidity / 100, 300, 1000)
        draw_text(screen, game_label_font, f"풍속: {game_weather['wind_speed']:.1f} km/h", pygame.Rect(62, 211, 265, 52), WHITE, "left")

        button_y = 198
        gap = 6
        button_width = (1032 - 342 - gap * 7) // 8
        for index, direction in enumerate(DIR_NAMES):
            x = 342 + index * (button_width + gap)
            rect = pygame.Rect(x, button_y, button_width, 78)
            selected = direction == game_weather["wind_direction"]
            pygame.draw.rect(screen, (83, 116, 97) if selected else (40, 44, 42), rect, border_radius=7)
            pygame.draw.rect(screen, (202, 215, 207) if selected else (126, 135, 130), rect, 2, border_radius=7)
            draw_text(screen, game_direction_font, DIR_KOREAN_NAMES[direction], rect, WHITE, "center")

        for tool in tool_buttons:
            remaining_ms = max(0, tool["ready_at"] - now)
            ready = remaining_ms == 0
            clicked = now < tool["flash_until"]
            rect = tool["rect"]
            progress = 1.0 - remaining_ms / tool["cooldown_ms"]
            fill = (61, 141, 89) if clicked else (53, 57, 55)
            border = (226, 246, 231) if clicked else ((144, 203, 159) if ready else (100, 109, 104))
            pygame.draw.rect(screen, fill, rect, border_radius=10)
            pygame.draw.rect(screen, border, rect, 3, border_radius=10)
            icon = tool_icons[tool["icon"]]
            icon_rect = icon.get_rect(midleft=(rect.x + 26, rect.centery - 6))
            screen.blit(icon, icon_rect)
            draw_text(screen, tool_label_font, tool["name"], pygame.Rect(rect.x + 145, rect.y + 22, rect.width - 170, 45), WHITE, "left")
            track = pygame.Rect(rect.x + 16, rect.bottom - 26, rect.width - 32, 12)
            pygame.draw.rect(screen, (33, 37, 35), track, border_radius=6)
            if progress > 0:
                progress_bar = pygame.Rect(track.x, track.y, max(8, round(track.width * progress)), track.height)
                pygame.draw.rect(screen, (73, 181, 98), progress_bar, border_radius=6)

        for rect, label, active in ((restart_rect, "다시하기", False), (developer_rect, "개발자 모드", developer_mode)):
            pygame.draw.rect(screen, (54, 85, 65) if active else (53, 57, 55), rect, border_radius=10)
            pygame.draw.rect(screen, (144, 203, 159) if active else (100, 109, 104), rect, 3, border_radius=10)
            draw_text(screen, tool_label_font, label, rect, WHITE, "center")

        if game_result is not None:
            if game_result == "성공":
                blurred = pygame.transform.smoothscale(
                    pygame.transform.smoothscale(screen, (108, 192)),
                    (DISPLAY_WIDTH, DISPLAY_HEIGHT),
                )
                screen.blit(blurred, (0, 0))
                screen.fill((4, 25, 12, 82), special_flags=pygame.BLEND_RGBA_ADD)
                progress = min(1.0, (now - game_result_started_at) / 520)
                scale = 0.72 + 0.28 * (1 - (1 - progress) ** 3)
                result_box = pygame.Rect(0, 0, round(820 * scale), round(330 * scale))
                result_box.center = (DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2)
                pygame.draw.rect(screen, (20, 112, 58), result_box, border_radius=42)
                pygame.draw.rect(screen, (213, 246, 221), result_box, 5, border_radius=42)
                draw_text(screen, make_font(round(126 * scale), True), "성공!", result_box, WHITE, "center")
                if now - game_result_started_at >= 1_000:
                    pygame.draw.rect(screen, (244, 255, 247), return_rect, border_radius=26)
                    pygame.draw.rect(screen, (45, 142, 76), return_rect, 4, border_radius=26)
                    draw_text(screen, make_font(45, True), "돌아가기", return_rect, TITLE_GREEN, "center")
            else:
                result_box = pygame.Rect(190, 700, 700, 260)
                pygame.draw.rect(screen, (151, 48, 37), result_box, border_radius=32)
                draw_text(screen, make_font(90, True), "실패", result_box, WHITE, "center")

    while True:
        now = pygame.time.get_ticks()
        if scene == "game" and game_result == "성공" and now - game_result_started_at >= 10_000:
            return_to_start_screen()
        if scene == "game":
            process_water_effects(now)
        if scene == "game" and game_result is None and not game_paused and now - game_last_tick >= BASE_TICK_INTERVAL_MS / GAME_SPEED_MULTIPLIER:
            game_weather = weather_for_tick(game_elapsed_ticks)
            update_fire(
                game_grid,
                grid_width,
                grid_height,
                leaf_threshold(game_weather["humidity"]),
                game_weather["wind_speed"],
                game_weather["wind_direction"],
            )
            game_elapsed_ticks += 1
            game_weather = weather_for_tick(game_elapsed_ticks)
            on_fire_cells = count_on_fire_cells()
            # 잔불(1~2칸) 자동 성공 판정은 현재 비활성화한다.
            # if clear_isolated_embers():
            #     game_result = "성공"
            #     game_result_started_at = now
            if on_fire_cells == 0:
                game_result = "성공"
                game_result_started_at = now
            elif on_fire_cells >= GAME_OVER_ACTIVE_FIRE_CELLS:
                game_result = "실패"
                game_result_started_at = now
            game_last_tick = now
        elif scene == "transition" and now - transition_started_at >= SCREEN_FADE_MS:
            scene = "comparison"
            last_tick = now
        elif scene == "fade_between" and now - transition_started_at >= SCREEN_FADE_MS:
            if fade_target == "humidity":
                start_comparison("humidity")
                scene = "comparison"
            else:
                start_game_intro(now)
        elif scene == "game_intro" and now - game_intro_started_at >= GAME_INTRO_MESSAGE_MS:
            if game_intro_stage == 0:
                game_intro_stage = 1
                game_intro_started_at = now
            else:
                scene = "game_intro_fade"
                transition_started_at = now
        elif scene == "game_intro_fade" and now - transition_started_at >= SCREEN_FADE_MS:
            scene = "game"
            game_last_tick = now
        elif scene == "comparison" and not frozen and now - last_tick >= BASE_TICK_INTERVAL_MS / (
            HUMIDITY_COMPARISON_SPEED_MULTIPLIER if comparison_mode == "humidity" else COMPARISON_SPEED_MULTIPLIER
        ):
            current_wind_direction = wind_direction_for_tick(elapsed_ticks)
            if comparison_mode == "wind":
                update_fire(weak_grid, comparison_grid_width, comparison_grid_height, leaf_threshold(25), WEAK_WIND_SPEED_KMH, current_wind_direction)
                update_fire(strong_grid, comparison_grid_width, comparison_grid_height, leaf_threshold(25), STRONG_WIND_SPEED_KMH, current_wind_direction)
            else:
                update_fire(weak_grid, comparison_grid_width, comparison_grid_height, leaf_threshold(70), WEAK_WIND_SPEED_KMH, current_wind_direction)
                update_fire(strong_grid, comparison_grid_width, comparison_grid_height, leaf_threshold(0), WEAK_WIND_SPEED_KMH, current_wind_direction)
            elapsed_ticks += 1
            last_tick = now
            if exceeds_fire_area_limit(weak_grid) or exceeds_fire_area_limit(strong_grid):
                frozen = True
                result_reveal_started_at = now
        elif scene == "comparison" and frozen and result_reveal_started_at is not None:
            result_complete_at = result_reveal_started_at + RESULT_SPLIT_MS + RESULT_MESSAGE_HOLD_MS
            if now >= result_complete_at:
                fade_target = "humidity" if comparison_mode == "wind" else "game_intro"
                scene = "fade_between"
                transition_started_at = now

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    return
                if event.key == pygame.K_r:
                    scene = "start"
                    comparison_mode = None
                    frozen = False
                if event.key == pygame.K_SPACE and scene == "game" and developer_mode:
                    game_paused = not game_paused
            if event.type == pygame.MOUSEBUTTONDOWN:
                mx = int(event.pos[0] * DISPLAY_WIDTH / window_size[0])
                my = int(event.pos[1] * DISPLAY_HEIGHT / window_size[1])
                logical_pos = (mx, my)
                if event.button == 1:
                    if scene == "start" and start_title_rect.collidepoint(logical_pos):
                        start_comparison("wind")
                        scene = "transition"
                        transition_started_at = now
                    elif scene == "start" and game_shortcut_rect.collidepoint(logical_pos):
                        start_game_intro(now)
                    elif scene == "comparison" and back_rect.collidepoint(logical_pos):
                        scene = "start"
                        comparison_mode = None
                        frozen = False
                    elif scene == "game":
                        if game_back_rect.collidepoint(logical_pos):
                            return_to_start_screen()
                        elif game_result == "성공" and now - game_result_started_at >= 1_000 and return_rect.collidepoint(logical_pos):
                            return_to_start_screen()
                        if restart_rect.collidepoint(logical_pos):
                            reset_game()
                        elif developer_rect.collidepoint(logical_pos):
                            developer_mode = not developer_mode
                            if developer_mode:
                                for tool in tool_buttons:
                                    tool["ready_at"] = now
                        else:
                            for tool in tool_buttons:
                                if tool["rect"].collidepoint(logical_pos) and (developer_mode or now >= tool["ready_at"]):
                                    tool["flash_until"] = now + 180
                                    selected_tool = tool
                                    break
                            else:
                                if selected_tool is not None and game_map_rect.collidepoint(logical_pos):
                                    gx = visible_x0 + int((logical_pos[0] - game_map_rect.x) * (visible_x1 - visible_x0) / game_map_rect.width)
                                    gy = visible_y0 + int((logical_pos[1] - game_map_rect.y) * (visible_y1 - visible_y0) / game_map_rect.height)
                                    if selected_tool["name"] == "방화선":
                                        firebreak_drag_start = (gx, gy)
                                    else:
                                        apply_tool(selected_tool, gx, gy)
                                        selected_tool["ready_at"] = now if developer_mode else now + selected_tool["cooldown_ms"]
                                        selected_tool = None
            if event.type == pygame.MOUSEBUTTONUP and scene == "game" and firebreak_drag_start is not None and selected_tool is not None:
                mx = int(event.pos[0] * DISPLAY_WIDTH / window_size[0])
                my = int(event.pos[1] * DISPLAY_HEIGHT / window_size[1])
                if game_map_rect.collidepoint((mx, my)):
                    gx = visible_x0 + int((mx - game_map_rect.x) * (visible_x1 - visible_x0) / game_map_rect.width)
                    gy = visible_y0 + int((my - game_map_rect.y) * (visible_y1 - visible_y0) / game_map_rect.height)
                    apply_firebreak(firebreak_drag_start, (gx, gy))
                    selected_tool["ready_at"] = now if developer_mode else now + selected_tool["cooldown_ms"]
                    selected_tool = None
                firebreak_drag_start = None

        screen.fill(BG)
        if scene == "start":
            offset = int((pygame.time.get_ticks() / 1000 * 18) % forest_width)
            screen.blit(forest_blurred, (-offset, 0))
            screen.blit(forest_blurred, (forest_width - offset, 0))
            forest_tint = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.SRCALPHA)
            forest_tint.fill((14, 57, 29, 72))
            screen.blit(forest_tint, (0, 0))
            shadow_rect = start_title_rect.move(0, 16)
            pygame.draw.rect(screen, (3, 23, 12), shadow_rect, border_radius=42)
            title_card = pygame.Surface(start_title_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(title_card, (9, 67, 35, 220), title_card.get_rect(), border_radius=42)
            pygame.draw.rect(title_card, (190, 236, 177, 185), title_card.get_rect(), 4, border_radius=42)
            screen.blit(title_card, start_title_rect.topleft)
            inner_rect = start_title_rect.inflate(-24, -24)
            pygame.draw.rect(screen, (255, 255, 250), inner_rect, 1, border_radius=32)
            draw_text(screen, start_title_font, "산불을 체험해보자!", start_title_rect, WHITE, "center")
            pygame.draw.rect(screen, (9, 67, 35), game_shortcut_rect, border_radius=30)
            pygame.draw.rect(screen, (190, 236, 177), game_shortcut_rect, 3, border_radius=30)
            draw_text(screen, make_font(48, True), "게임으로 바로가기", game_shortcut_rect, WHITE, "center")
            window.blit(pygame.transform.smoothscale(screen, window_size), (0, 0))
            pygame.display.flip()
            clock.tick(60)
            continue

        if scene == "transition":
            # 시작 화면의 마지막 모습을 남겨 두었다가 짧게 어둡게 전환한다.
            offset = int((pygame.time.get_ticks() / 1000 * 18) % forest_width)
            screen.blit(forest_blurred, (-offset, 0))
            screen.blit(forest_blurred, (forest_width - offset, 0))
            transition_t = (now - transition_started_at) / SCREEN_FADE_MS
            fade = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.SRCALPHA)
            fade.fill((2, 19, 9, min(230, int(40 + transition_t * 190))))
            screen.blit(fade, (0, 0))
            window.blit(pygame.transform.smoothscale(screen, window_size), (0, 0))
            pygame.display.flip()
            clock.tick(60)
            continue

        if scene == "game":
            draw_game_screen()
            window.blit(pygame.transform.smoothscale(screen, window_size), (0, 0))
            pygame.display.flip()
            clock.tick(60)
            continue

        if scene == "game_intro":
            offset = int((pygame.time.get_ticks() / 1000 * 18) % forest_width)
            screen.blit(forest_blurred, (-offset, 0))
            screen.blit(forest_blurred, (forest_width - offset, 0))
            intro_tint = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.SRCALPHA)
            intro_tint.fill((3, 30, 15, 126))
            screen.blit(intro_tint, (0, 0))
            intro_card = pygame.Rect(60, 710, 960, 500)
            intro_shadow = intro_card.move(0, 18)
            pygame.draw.rect(screen, (2, 17, 8), intro_shadow, border_radius=42)
            intro_surface = pygame.Surface(intro_card.size, pygame.SRCALPHA)
            pygame.draw.rect(intro_surface, (247, 255, 244, 235), intro_surface.get_rect(), border_radius=42)
            pygame.draw.rect(intro_surface, (187, 230, 177, 220), intro_surface.get_rect(), 4, border_radius=42)
            screen.blit(intro_surface, intro_card.topleft)
            intro_lines = (
                ("이제 직접 진압해 보며", "산불을 막는 일이 왜", "어려운지 체험해 보세요!")
                if game_intro_stage == 0
                else ("진압 수단을 선택한 뒤", "지도에 눌러 배치하세요.", "방화선은 손가락으로 밀어", "설치합니다.")
            )
            intro_font = make_font(56, True)
            line_height = 92
            lines_height = len(intro_lines) * line_height
            first_line_y = intro_card.centery - lines_height // 2
            for index, line in enumerate(intro_lines):
                line_rect = pygame.Rect(intro_card.x + 40, first_line_y + index * line_height, intro_card.width - 80, line_height)
                draw_text(screen, intro_font, line, line_rect, TITLE_GREEN, "center")
            window.blit(pygame.transform.smoothscale(screen, window_size), (0, 0))
            pygame.display.flip()
            clock.tick(60)
            continue

        if scene == "game_intro_fade":
            draw_game_screen()
            fade_t = min(1.0, (now - transition_started_at) / SCREEN_FADE_MS)
            fade = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.SRCALPHA)
            fade.fill((3, 20, 10, round(255 * (1 - fade_t))))
            screen.blit(fade, (0, 0))
            window.blit(pygame.transform.smoothscale(screen, window_size), (0, 0))
            pygame.display.flip()
            clock.tick(60)
            continue

        pygame.draw.rect(screen, TITLE_GREEN, back_rect, border_radius=20)
        pygame.draw.lines(screen, WHITE, False, [(102, 54), (78, 72), (102, 90)], 8)
        if comparison_mode == "wind":
            result_t = 0.0
            if frozen and result_reveal_started_at is not None:
                result_t = ease_out_cubic((now - result_reveal_started_at) / RESULT_SPLIT_MS)
            animated_weak_panel = pygame.Rect(40, lerp(weak_panel.y, result_weak_panel.y, result_t), 1000, 610)
            animated_strong_panel = pygame.Rect(40, lerp(strong_panel.y, result_strong_panel.y, result_t), 1000, 610)
            draw_fire_panel(animated_weak_panel, "약한 바람", weak_grid, 25, WEAK_WIND_SPEED_KMH)
            draw_fire_panel(animated_strong_panel, "강한 바람", strong_grid, 25, STRONG_WIND_SPEED_KMH)
            message_y = lerp(1470, 785, result_t)
            message_card = pygame.Surface((1000, 140), pygame.SRCALPHA)
            pygame.draw.rect(message_card, (255, 255, 250, 242), message_card.get_rect(), border_radius=28)
            pygame.draw.rect(message_card, PANEL_LINE, message_card.get_rect(), 3, border_radius=28)
            screen.blit(message_card, (40, message_y))
            if result_t >= 0.42:
                draw_text(screen, transition_explanation_font, "바람이 강할수록 불씨와 열이", pygame.Rect(70, message_y + 18, 940, 48), TITLE_GREEN, "center")
                draw_text(screen, transition_explanation_font, "멀리 날아가 불이 빠르게 번집니다!", pygame.Rect(70, message_y + 76, 940, 48), TITLE_GREEN, "center")
            else:
                draw_text(screen, explanation_font, "바람이 강할수록 불씨와 열이 멀리 날아가", pygame.Rect(70, message_y + 20, 940, 42), TITLE_GREEN, "center")
                draw_text(screen, explanation_font, "불이 빠르게 번집니다!", pygame.Rect(70, message_y + 76, 940, 42), TITLE_GREEN, "center")
        else:
            result_t = 0.0
            if frozen and result_reveal_started_at is not None:
                result_t = ease_out_cubic((now - result_reveal_started_at) / RESULT_SPLIT_MS)
            animated_weak_panel = pygame.Rect(40, lerp(weak_panel.y, result_weak_panel.y, result_t), 1000, 610)
            animated_strong_panel = pygame.Rect(40, lerp(strong_panel.y, result_strong_panel.y, result_t), 1000, 610)
            draw_fire_panel(animated_weak_panel, "높은 습도", weak_grid, 70, WEAK_WIND_SPEED_KMH)
            draw_fire_panel(animated_strong_panel, "낮은 습도", strong_grid, 0, WEAK_WIND_SPEED_KMH)
            message_y = lerp(1470, 785, result_t)
            message_card = pygame.Surface((1000, 140), pygame.SRCALPHA)
            pygame.draw.rect(message_card, (255, 255, 250, 242), message_card.get_rect(), border_radius=28)
            pygame.draw.rect(message_card, PANEL_LINE, message_card.get_rect(), 3, border_radius=28)
            screen.blit(message_card, (40, message_y))
            if result_t >= 0.42:
                draw_text(screen, transition_explanation_font, "습도가 낮을수록 나무와 낙엽이 말라", pygame.Rect(70, message_y + 18, 940, 48), TITLE_GREEN, "center")
                draw_text(screen, transition_explanation_font, "불이 쉽게 붙습니다!", pygame.Rect(70, message_y + 76, 940, 48), TITLE_GREEN, "center")
            else:
                draw_text(screen, explanation_font, "습도가 낮을수록 나무와 낙엽이 말라", pygame.Rect(70, message_y + 20, 940, 42), TITLE_GREEN, "center")
                draw_text(screen, explanation_font, "불이 쉽게 붙습니다!", pygame.Rect(70, message_y + 76, 940, 42), TITLE_GREEN, "center")
        if scene == "fade_between":
            fade_t = min(1.0, (now - transition_started_at) / SCREEN_FADE_MS)
            fade = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.SRCALPHA)
            fade.fill((2, 19, 9, int(35 + fade_t * 205)))
            screen.blit(fade, (0, 0))
        window.blit(pygame.transform.smoothscale(screen, window_size), (0, 0))
        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    run()
