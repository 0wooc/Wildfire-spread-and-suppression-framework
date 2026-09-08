import csv
import json
import math
import random
from pathlib import Path

import pygame
import rasterio

pygame.init()

BASE_DIR = Path(__file__).resolve().parents[1]
ACTIVE_MAP_FILE = BASE_DIR / "active_map.json"
MAPS_DIR = BASE_DIR / "maps"


def load_json_file(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def relative_to_project(path):
    return path.relative_to(BASE_DIR).as_posix()


def resolve_project_path(path_value, fallback):
    path = Path(path_value) if path_value else fallback
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def find_weather_data_file(config_file, files):
    weather_value = files.get("weather_data")
    if weather_value:
        weather_file = Path(weather_value)
        if not weather_file.is_absolute():
            weather_file = config_file.parent / weather_file

        if weather_file.exists():
            return weather_file

        print(f"Weather CSV listed in map_config.json was not found: {weather_file}")
        return None

    csv_files = sorted(config_file.parent.glob("*.csv"))
    if len(csv_files) == 1:
        return csv_files[0]

    if len(csv_files) > 1:
        print(f"Multiple weather CSV files found in {config_file.parent}.")
        print("Set files.weather_data in map_config.json to choose one file.")

    return None


def find_available_maps():
    if not MAPS_DIR.exists():
        return []

    available_maps = []
    for config_file in sorted(MAPS_DIR.glob("*/map_config.json")):
        try:
            config = load_json_file(config_file)
        except (OSError, json.JSONDecodeError):
            continue

        map_name = config.get("map_name") or config_file.parent.name
        files = config.get("files", {})
        dem_file = resolve_project_path(files.get("dem"), config_file.parent / "dem_final.tif")
        preview_file = resolve_project_path(files.get("preview_map"), config_file.parent / "preview_map.png")
        smooth_preview_file = resolve_project_path(files.get("preview_map_smooth"), preview_file)
        slope_file = resolve_project_path(files.get("directional_slope_factor"), config_file.parent / "directional_slope_factor.npy")
        slope_preview_file = resolve_project_path(files.get("slope_preview"), config_file.parent / "slope_preview.png")
        weather_file = find_weather_data_file(config_file, files)

        if not dem_file.exists() or not preview_file.exists():
            continue

        available_maps.append({
            "map_name": map_name,
            "config": config_file,
            "dem": dem_file,
            "preview_map": preview_file,
            "preview_map_smooth": smooth_preview_file,
            "directional_slope_factor": slope_file,
            "slope_preview": slope_preview_file,
            "weather_data": weather_file,
            "grid_width": config.get("grid_width"),
            "grid_height": config.get("grid_height"),
            "cell_size_m": config.get("cell_size_m", 30.0),
        })

    return available_maps


def select_active_map():
    available_maps = find_available_maps()
    if not available_maps:
        if not ACTIVE_MAP_FILE.exists():
            raise FileNotFoundError(
                "active_map.json이 없고 maps 폴더에서 사용할 수 있는 맵도 찾지 못했습니다. 먼저 map_builder.py로 맵을 생성하세요."
            )
        return load_json_file(ACTIVE_MAP_FILE)

    current_name = None
    if ACTIVE_MAP_FILE.exists():
        try:
            current_name = load_json_file(ACTIVE_MAP_FILE).get("map_name")
        except (OSError, json.JSONDecodeError):
            current_name = None

    print("\nAvailable maps:")
    for index, map_info in enumerate(available_maps, start=1):
        size_text = ""
        if map_info["grid_width"] and map_info["grid_height"]:
            size_text = f" ({map_info['grid_width']} x {map_info['grid_height']})"
        current_mark = " [current]" if map_info["map_name"] == current_name else ""
        print(f"{index}. {map_info['map_name']}{size_text}{current_mark}")

    while True:
        choice = input("Select map number, or press Enter to keep current: ").strip()
        if choice == "" and current_name:
            selected = next((m for m in available_maps if m["map_name"] == current_name), available_maps[0])
            break

        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(available_maps):
                selected = available_maps[index - 1]
                break

        print("올바른 번호를 입력하세요.")

    active_map_data = {
        "map_name": selected["map_name"],
        "files": {
            "dem": relative_to_project(selected["dem"]),
            "preview_map": relative_to_project(selected["preview_map"]),
            "preview_map_smooth": relative_to_project(selected["preview_map_smooth"]),
            "directional_slope_factor": relative_to_project(selected["directional_slope_factor"]),
            "slope_preview": relative_to_project(selected["slope_preview"]),
            "weather_data": (
                relative_to_project(selected["weather_data"])
                if selected["weather_data"] is not None
                else None
            ),
            "config": relative_to_project(selected["config"]),
        },
        "grid_width": selected["grid_width"],
        "grid_height": selected["grid_height"],
        "cell_size_m": selected["cell_size_m"],
    }
    ACTIVE_MAP_FILE.write_text(json.dumps(active_map_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Active map:", selected["map_name"])
    if selected["weather_data"] is not None:
        print("Weather CSV:", relative_to_project(selected["weather_data"]))
    else:
        print("Weather CSV: None (manual weather mode)")
    return active_map_data


active_map = select_active_map()

MAP_NAME = active_map["map_name"]
FIRE_AREA_LOG_FILE = BASE_DIR / f"{MAP_NAME}_fire_area_log.csv"
DEM_FILE = BASE_DIR / active_map["files"]["dem"]
MAP_BACKGROUND_FILE = BASE_DIR / active_map["files"]["preview_map"]

if not DEM_FILE.exists():
    raise FileNotFoundError(f"현재 맵의 DEM 파일을 찾을 수 없습니다: {DEM_FILE}")
if not MAP_BACKGROUND_FILE.exists():
    raise FileNotFoundError(f"현재 맵의 배경 이미지를 찾을 수 없습니다: {MAP_BACKGROUND_FILE}")

with rasterio.open(DEM_FILE) as src:
    elevation_map = src.read(1).astype(float)

# elevation_map은 [y, x] 순서로 저장되어 있다.
GRID_HEIGHT, GRID_WIDTH = elevation_map.shape

# 맵이 큰 경우 창 크기를 제한하고, 셀 표시 크기를 줄여 전체 맵을 화면 안에 맞춘다.
DEFAULT_CELL_SIZE = 12
MIN_CELL_SIZE = 1
SIDEBAR_WIDTH = 300
MAX_WINDOW_WIDTH = 2560
MAX_WINDOW_HEIGHT = 1800

display_info = pygame.display.Info()
window_width_limit = min(MAX_WINDOW_WIDTH, max(640, display_info.current_w - 80))
window_height_limit = min(MAX_WINDOW_HEIGHT, max(480, display_info.current_h - 120))

max_map_width = window_width_limit - SIDEBAR_WIDTH
max_map_height = window_height_limit
CELL_SIZE = min(DEFAULT_CELL_SIZE, max_map_width // GRID_WIDTH, max_map_height // GRID_HEIGHT)
CELL_SIZE = max(MIN_CELL_SIZE, CELL_SIZE)

SCREEN_WIDTH = GRID_WIDTH * CELL_SIZE + SIDEBAR_WIDTH
SCREEN_HEIGHT = GRID_HEIGHT * CELL_SIZE

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption(f"Fire Spread Simulation Framework - {MAP_NAME}")

# 실제 고도로 생성한 지도 이미지를 격자 영역의 배경으로 사용한다.
# 경사 계산은 DEM 값으로 수행하며, 이 이미지는 화면 표현에만 사용한다.
map_background_original = pygame.image.load(MAP_BACKGROUND_FILE).convert()
map_background = pygame.transform.smoothscale(
    map_background_original,
    (GRID_WIDTH * CELL_SIZE, GRID_HEIGHT * CELL_SIZE),
)

print("Loaded map:", MAP_NAME)
print("Loaded DEM:", DEM_FILE)
print("Loaded background:", MAP_BACKGROUND_FILE)
print("Grid size:", GRID_WIDTH, "x", GRID_HEIGHT)
print("Elevation range:", elevation_map.min(), "~", elevation_map.max())

clock = pygame.time.Clock()

# Windows 환경이면 맑은 고딕을 우선 사용한다.
# 없으면 pygame 기본 폰트로 자동 대체된다.
font = pygame.font.SysFont("malgungothic", 15)
small_font = pygame.font.SysFont("malgungothic", 12)


# ============================================================
# 2. 색상 설정
# ============================================================

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
TARGET_CELL_BORDER = WHITE

PINE_GREEN = (33, 130, 58)
PINE_DARK = (22, 90, 42)
WATER_BLUE = (40, 90, 210)
ROCK_GRAY = (100, 100, 100)
AERIAL_PREVIEW_SKY_BLUE = (80, 220, 255)
SUPPRESSION_PENDING_BLUE = (90, 200, 255)
FIREFIGHTER_PENDING_PURPLE = (180, 150, 255)
FIREFIGHTER_ACTIVE_PURPLE = (125, 85, 215)
TRUCK_ACTIVE_GREEN = (0, 210, 0)
FIREBREAK_ACTIVE_BLACK = (0, 0, 0)
FIREBREAK_PENDING_TINT = (20, 20, 20)

PRE_LEAF_IGNITION_YELLOW = (255, 252, 220)  # 낙엽 발화 전 열 축적: 연노랑
LEAF_FIRE_ORANGE_PALETTE = [
    (255, 214, 150),
    (255, 184, 96),
    (255, 146, 55),
    (245, 105, 28),
    (222, 72, 12),
]  # 낙엽 발화: 연주황 -> 진주황
LEAF_FIRE_ORANGE = LEAF_FIRE_ORANGE_PALETTE[2]
STEM_FIRE_RED = (195, 25, 25)       # 줄기 셀 발화: 빨간색
LEAF_BURNED_BROWN = (95, 70, 42)

SIDEBAR_GRAY = (55, 55, 55)
BUTTON_COLOR = (45, 45, 45)
BUTTON_HOVER_COLOR = (75, 75, 75)
BUTTON_SELECTED_COLOR = (110, 110, 110)

TEXT_MUTED = (200, 200, 200)

SIDEBAR_PADDING = 14
SECTION_GAP = 8
BUTTON_HEIGHT = 25
WIND_BUTTON_HEIGHT = 23
TOOL_BUTTON_GAP = 4

# 경사 테두리는 화면 가독성을 위한 표시 전용 색상이다.
# 10 -> 20 -> 30도로 갈수록 조금씩 진해지지만, 전체 톤은 옅은 물 탄 갈색으로 유지한다.
SLOPE_BORDER_COLOR = {
    10: (232, 218, 200),
    20: (218, 194, 164),
    30: (202, 170, 132),
}


# ============================================================
# 3. 시뮬레이션 상수
# ============================================================

# 셀의 실제 크기.
# 설계도에 따라 모든 셀은 30 m x 30 m 로 고정한다.
CELL_REAL_SIZE_M = 30.0
CELL_AREA_M2 = 900.0

# 1틱은 실제 시간 5분에 해당한다.
# 화면에서는 배속 상태에 따라 1틱 진행 간격을 바꾼다.
NORMAL_TICK_INTERVAL_MS = 500
FAST_TICK_INTERVAL_MS = 100
SIMULATION_SECONDS_PER_TICK = 5 * 60

# 실제 산불 검증용 시간별 환경 데이터 CSV.
# 선택한 지도 폴더에 연결된 CSV가 존재하면 시작 시 자동 재생 모드가 활성화된다.
weather_path_value = active_map.get("files", {}).get("weather_data")
WEATHER_DATA_FILE = BASE_DIR / weather_path_value if weather_path_value else None

# ------------------------------------------------------------
# 낙엽 점화 임계값 계산에 쓰는 상수
# ------------------------------------------------------------

LEAF_FUEL_MASS_PER_CELL = 1114.2      # kg
BASE_IGNITION_KJ_PER_KG = 581.0       # kJ/kg
WATER_EXTRA_KJ_PER_KG = 2596.0        # kJ/kg

# 대기습도 -> 낙엽 내부 수분량
# 설계도에 주어진 표 값을 그대로 사용한다.
LEAF_MOISTURE_BY_HUMIDITY = {
    0: 0.000,
    5: 0.037,
    10: 0.051,
    15: 0.063,
    20: 0.072,
    25: 0.081,
    30: 0.089,
    35: 0.096,
    40: 0.103,
    45: 0.109,
    50: 0.116,
    55: 0.122,
    60: 0.129,
    65: 0.137,
    70: 0.146,
    75: 0.158,
    80: 0.174,
    85: 0.196,
    90: 0.229,
    95: 0.240,
    100: 0.250,
}

# 줄기 점화 임계값.
# 설계도에서 이미 계산된 최종값을 그대로 사용한다.
STEM_IGNITION_THRESHOLD = 23_737_883.0  # kJ

# ------------------------------------------------------------
# 낙엽 발화 셀의 열량
# ------------------------------------------------------------

# 낙엽 발화 상태에서는 매 틱 이 열량이 셀 내부에 더해진다.
LEAF_HEAT_PER_TICK = 635_882.0  # kJ/tick

# 낙엽에서 발생한 열 중 주변 확산에 기여하는 비율.
# 설계도에서 계산된 0.1224를 그대로 사용한다.
LEAF_RELEASE_RATIO = 0.1224

# 틱당 주변으로 방출되는 총 열량.
# 설계도 최종값인 77,813 kJ/tick을 그대로 사용한다.
LEAF_RELEASE_PER_TICK = 77_813.0  # kJ/tick
LEAF_BURNING_MAX_TICKS = 32

# 8방향 분배 비중.
# 상하좌우는 1, 대각선은 1 / sqrt(2).
DIAGONAL_WEIGHT = 1.0 / math.sqrt(2.0)
DIRECTION_WEIGHT_SUM = 4.0 + 4.0 * DIAGONAL_WEIGHT

# ------------------------------------------------------------
# 경사 가중치
# ------------------------------------------------------------

# 설계도에 주어진 경사별 가중치만 사용한다.
SLOPE_FACTOR = {
    0: 1.0,
    10: 1.2,
    20: 1.6,
    30: 2.8,
}

# ------------------------------------------------------------
# 바람 가중치
# ------------------------------------------------------------

WIND_SPEED_MIN_KMH = 0
WIND_SPEED_STEP_KMH = 1
WIND_MAIN_EXP_COEFFICIENT = 0.1783

DIR_NAMES = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
DIR_INDEX = {name: i for i, name in enumerate(DIR_NAMES)}

# dx, dy, 방향 인덱스, 방향 비중
NEIGHBORS = [
    (0, -1, 0, 1.0),
    (1, -1, 1, DIAGONAL_WEIGHT),
    (1, 0, 2, 1.0),
    (1, 1, 3, DIAGONAL_WEIGHT),
    (0, 1, 4, 1.0),
    (-1, 1, 5, DIAGONAL_WEIGHT),
    (-1, 0, 6, 1.0),
    (-1, -1, 7, DIAGONAL_WEIGHT),
]


# ============================================================
# 4. 지형과 셀 상태
# ============================================================

TERRAIN_PINE = 0
TERRAIN_WATER = 1
TERRAIN_ROCK = 2

STATE_UNBURNED = 0
STATE_LEAF_BURNING = 1
STATE_STEM_BURNING = 2
STATE_LEAF_BURNED = 3

TERRAIN_NAME = {
    TERRAIN_PINE: "Pine",
    TERRAIN_WATER: "Water",
    TERRAIN_ROCK: "Rock",
}

STATE_NAME = {
    STATE_UNBURNED: "Unburned",
    STATE_LEAF_BURNING: "Leaf burning",
    STATE_STEM_BURNING: "Stem burning",
    STATE_LEAF_BURNED: "Leaf burned",
}


class Cell:
    def __init__(self):
        # 기본 지형은 소나무림 셀이다.
        # 소나무림 셀은 낙엽 점화와 줄기 점화가 모두 가능하다.
        self.terrain = TERRAIN_PINE

        # 고도는 경사 계산용으로 사용한다.
        # reset_world()에서 실제 불암산 DEM 고도값이 입력된다.
        self.elevation = 0.0

        # 현재 상태: 미발화, 낙엽 발화, 줄기 발화.
        self.state = STATE_UNBURNED

        # 셀 내부에 누적된 열량.
        self.accumulated_heat = 0.0

        # 낙엽 점화 임계값은 습도에 따라 바뀐다.
        self.leaf_threshold = 0.0

        # 줄기 점화 임계값은 현재 설계에서 고정값이다.
        self.stem_threshold = STEM_IGNITION_THRESHOLD

        # 현재 틱에서 주변으로 전달하는 열량 표시용 값.
        self.outgoing_heat = 0.0
        self.leaf_burning_ticks = 0

        # 누적 연소면적 계산용 상태값.
        # 한 번이라도 발화한 셀은 진압되거나 연소가 종료되어도 True로 유지된다.
        self.ever_burned = False


grid = [[Cell() for _ in range(GRID_HEIGHT)] for _ in range(GRID_WIDTH)]


# ============================================================
# 5. 현재 시뮬레이션 조작 상태
# ============================================================

is_running = False
last_tick_time = pygame.time.get_ticks()
elapsed_ticks = 0
is_fast_mode = False
show_slope_borders = False

humidity_percent = 0
wind_speed_kmh = 0
wind_dir_name = "N"
wind_input_text = "0"
wind_input_active = False
target_x_text = ""
target_y_text = ""
target_input_active = None
target_cell = None
humidity_slider_dragging = False

# CSV 기반 실제 기상 자동 입력 상태
weather_timeline = []
weather_data_mode = False
current_weather_record_index = -1

selected_tool = None
suppression_placement_markers = []

# 진압 수단
# 소방헬기와 소방비행기는 배치 지점을 클릭하는 순간 한 번만 냉각 열량을 적용한다.
# 소방관은 ㄱ자 형태로 배치되며, active 상태가 된 셀은 더 이상 주변으로 열을 방출하지 못한다.
TOOL_FIREFIGHTER = 1
TOOL_TRUCK = 2
TOOL_HELI = 3
TOOL_PLANE = 4
TOOL_FIREBREAK = 5

# 항공 진압 수단의 확정값
# 냉각 열량은 물 1 L당 유효 냉각량 1,848 kJ를 적용한 결과다.
HELI_COOLING_PER_CELL_KJ = 5_544_000.0      # KA-32T, 3,000 L / 2 cells x 2
PLANE_COOLING_PER_CELL_KJ = 5_670_588.0     # DHC-515, 6,137 L / 4 cells x 2

HELI_DROP_WIDTH = 3
HELI_DROP_HEIGHT = 2
PLANE_DROP_WIDTH = 5
PLANE_DROP_HEIGHT = 3

# 방화벽과 소방차는 v0의 배치 구조를 가져오되, 쿨타임은 사용하지 않는다.
FIREBREAK_NONE = 0
FIREBREAK_PENDING = 1
FIREBREAK_ACTIVE = 2
FIREBREAK_DEPLOY_TICKS = 10

TRUCK_NONE = 0
TRUCK_PENDING = 1
TRUCK_ACTIVE = 2
TRUCK_DEPLOY_TICKS = 8
TRUCK_DURATION_TICKS = 6
TRUCK_BLOCK_SIZE = 2
TRUCK_HEAT_COOL_PER_TICK_KJ = 154_000.0

FIREFIGHTER_NONE = 0
FIREFIGHTER_PENDING = 1
FIREFIGHTER_ACTIVE = 2
FIREFIGHTER_DEPLOY_TICKS = 4
# 클릭한 셀을 ㄱ자의 모서리로 보고, 오른쪽 1셀과 아래쪽 1셀을 함께 막는다.
FIREFIGHTER_SHAPE_OFFSETS = [(0, 0), (1, 0), (0, 1)]

tool_definitions = [
    ("Firefighter", TOOL_FIREFIGHTER),
    ("Fire Truck", TOOL_TRUCK),
    ("Helicopter", TOOL_HELI),
    ("Plane", TOOL_PLANE),
    ("Firebreak", TOOL_FIREBREAK),
]


# ============================================================
# 6. 버튼 생성
# ============================================================

sidebar_x = GRID_WIDTH * CELL_SIZE

reset_button = pygame.Rect(0, 0, 0, 0)
speed_button = pygame.Rect(0, 0, 0, 0)
slope_border_button = pygame.Rect(0, 0, 0, 0)
weather_mode_button = pygame.Rect(0, 0, 0, 0)
humidity_slider_rect = pygame.Rect(0, 0, 0, 0)
wind_input_rect = pygame.Rect(0, 0, 0, 0)
target_x_input_rect = pygame.Rect(0, 0, 0, 0)
target_y_input_rect = pygame.Rect(0, 0, 0, 0)
target_cell_button = pygame.Rect(0, 0, 0, 0)

wind_buttons = []

for i, name in enumerate(DIR_NAMES):
    wind_buttons.append({"rect": pygame.Rect(0, 0, 0, 0), "name": name})

tool_buttons = []

for i, (label, tool_id) in enumerate(tool_definitions):
    tool_buttons.append({"rect": pygame.Rect(0, 0, 0, 0), "label": label, "tool_id": tool_id})

# 방화벽 상태
firebreak_state = [[FIREBREAK_NONE for _ in range(GRID_HEIGHT)] for _ in range(GRID_WIDTH)]
firebreak_timer = [[0 for _ in range(GRID_HEIGHT)] for _ in range(GRID_WIDTH)]

# 소방차 상태
truck_state = [[TRUCK_NONE for _ in range(GRID_HEIGHT)] for _ in range(GRID_WIDTH)]
truck_timer = [[0 for _ in range(GRID_HEIGHT)] for _ in range(GRID_WIDTH)]

# 소방관 상태
firefighter_state = [[FIREFIGHTER_NONE for _ in range(GRID_HEIGHT)] for _ in range(GRID_WIDTH)]
firefighter_timer = [[0 for _ in range(GRID_HEIGHT)] for _ in range(GRID_WIDTH)]


# ============================================================
# 7. 유틸리티 함수
# ============================================================

def in_bounds(x, y):
    return 0 <= x < GRID_WIDTH and 0 <= y < GRID_HEIGHT


def draw_text(text, x, y, color=WHITE, use_small=False):
    used_font = small_font if use_small else font
    surface = used_font.render(text, True, color)
    screen.blit(surface, (x, y))


def get_leaf_fire_color(cell):
    heat_range = cell.stem_threshold - cell.leaf_threshold
    if heat_range <= 0:
        return LEAF_FIRE_ORANGE_PALETTE[-1]

    ratio = (cell.accumulated_heat - cell.leaf_threshold) / heat_range
    ratio = max(0.0, min(1.0, ratio))
    index = min(len(LEAF_FIRE_ORANGE_PALETTE) - 1, int(ratio * len(LEAF_FIRE_ORANGE_PALETTE)))
    return LEAF_FIRE_ORANGE_PALETTE[index]


def calculate_leaf_threshold():
    # 설계도:
    # 낙엽 점화 임계값 =
    # 셀당 낙엽 표면 연료량 x (581 + 2596 x 낙엽 내부 수분량)
    moisture = LEAF_MOISTURE_BY_HUMIDITY[humidity_percent]
    return LEAF_FUEL_MASS_PER_CELL * (BASE_IGNITION_KJ_PER_KG + WATER_EXTRA_KJ_PER_KG * moisture)


def refresh_thresholds():
    # 습도가 바뀌면 모든 소나무림 셀의 낙엽 점화 임계값을 다시 설정한다.
    # 물과 바위는 발화하지 않으므로 매우 큰 값으로 둔다.
    leaf_threshold = calculate_leaf_threshold()

    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            cell = grid[x][y]

            if cell.terrain == TERRAIN_PINE:
                cell.leaf_threshold = leaf_threshold
                cell.stem_threshold = STEM_IGNITION_THRESHOLD
                if cell.state == STATE_UNBURNED and cell.accumulated_heat >= cell.leaf_threshold:
                    cell.state = STATE_LEAF_BURNING
                    cell.leaf_burning_ticks = 0
                    cell.ever_burned = True
            else:
                cell.leaf_threshold = float("inf")
                cell.stem_threshold = float("inf")


def get_wind_factor(direction_index):
    # 풍속은 입력값을 그대로 공식에 넣어 계산한다.
    if wind_speed_kmh <= 0:
        return 1.0

    main_factor = math.exp(WIND_MAIN_EXP_COEFFICIENT * wind_speed_kmh)
    adjacent_factor = max(1.0, main_factor / math.sqrt(2.0))

    main_index = DIR_INDEX[wind_dir_name]
    left_index = (main_index - 1) % 8
    right_index = (main_index + 1) % 8

    if direction_index == main_index:
        return main_factor

    if direction_index == left_index or direction_index == right_index:
        return adjacent_factor

    return 1.0


def slope_degree_between(x, y, nx, ny):
    # 현재 셀에서 이웃 셀로 갈 때 고도가 높아지는 경우만 오르막으로 본다.
    # 고도가 낮아지거나 같으면 경사 가중치는 1.0이다.
    current_elevation = grid[x][y].elevation
    neighbor_elevation = grid[nx][ny].elevation

    elevation_diff = neighbor_elevation - current_elevation

    if elevation_diff <= 0:
        return 0

    # 셀 간 거리는 기본 30m.
    # 대각선 방향은 실제 거리가 더 길다.
    dx = nx - x
    dy = ny - y
    distance = CELL_REAL_SIZE_M * math.sqrt(dx * dx + dy * dy)

    angle = math.degrees(math.atan(elevation_diff / distance))

    # 설계도에서 쓰는 10, 20, 30도 단계로 단순화한다.
    if angle < 5:
        return 0
    if angle < 15:
        return 10
    if angle < 25:
        return 20
    return 30


def get_slope_factor(x, y, nx, ny):
    degree = slope_degree_between(x, y, nx, ny)
    return SLOPE_FACTOR[degree]


def get_cell_display_slope(x, y):
    # 화면 표시용 경사값.
    # 이 셀 주변으로 갈 수 있는 가장 큰 오르막 경사를 표시한다.
    max_degree = 0

    for dx, dy, _, _ in NEIGHBORS:
        nx = x + dx
        ny = y + dy

        if in_bounds(nx, ny):
            max_degree = max(max_degree, slope_degree_between(x, y, nx, ny))

    return max_degree


def can_burn(cell):
    # 현재 설계에서 물과 바위는 발화하지 않고 열도 전달하지 않는다.
    return cell.terrain == TERRAIN_PINE


def blend_color(base_color, tint_color, base_weight=3, tint_weight=1):
    r, g, b = base_color
    tr, tg, tb = tint_color
    total = base_weight + tint_weight
    return (
        (r * base_weight + tr * tint_weight) // total,
        (g * base_weight + tg * tint_weight) // total,
        (b * base_weight + tb * tint_weight) // total,
    )


def is_firebreak_active(x, y):
    return firebreak_state[x][y] == FIREBREAK_ACTIVE


def is_truck_active(x, y):
    return truck_state[x][y] == TRUCK_ACTIVE


def is_firefighter_active(x, y):
    return firefighter_state[x][y] == FIREFIGHTER_ACTIVE


def can_place_ground_suppression(x, y):
    if not in_bounds(x, y):
        return False

    cell = grid[x][y]
    if not can_burn(cell):
        return False

    # v0와 같이 급경사지에는 지상 진압 수단을 배치하지 않는다.
    if get_cell_display_slope(x, y) >= 30:
        return False

    return True


def clear_suppression_at_cell(x, y):
    removed = False

    if firebreak_state[x][y] != FIREBREAK_NONE:
        firebreak_state[x][y] = FIREBREAK_NONE
        firebreak_timer[x][y] = 0
        removed = True

    if truck_state[x][y] != TRUCK_NONE:
        truck_state[x][y] = TRUCK_NONE
        truck_timer[x][y] = 0
        removed = True

    if firefighter_state[x][y] != FIREFIGHTER_NONE:
        firefighter_state[x][y] = FIREFIGHTER_NONE
        firefighter_timer[x][y] = 0
        removed = True

    return removed


def load_weather_timeline():
    # CSV의 시간별 습도·풍속·풍향을 읽는다.
    # 풍향 열은 이미 시뮬레이션에서 확산을 강화할 방향으로 변환된 값을 사용한다.
    if WEATHER_DATA_FILE is None:
        print("Weather CSV: None (manual weather mode)")
        return []

    if not WEATHER_DATA_FILE.exists():
        print("Weather CSV not found. Manual weather mode:", WEATHER_DATA_FILE)
        return []

    required_columns = {
        "simulation_tick_5min",
        "hours_after_ignition",
        "humidity_input_for_current_code_percent_rounded_to_5",
        "wind_speed_10m_kmh",
        "wind_direction_input_for_current_code",
    }
    records = []

    try:
        with WEATHER_DATA_FILE.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            missing = required_columns.difference(reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSV 필수 열이 없습니다: {sorted(missing)}")

            for row in reader:
                direction = row["wind_direction_input_for_current_code"].strip().upper()
                if direction not in DIR_INDEX:
                    raise ValueError(f"지원하지 않는 풍향입니다: {direction}")

                observed_area = row.get("observed_cumulative_burn_area_km2", "").strip()
                records.append({
                    "tick": int(float(row["simulation_tick_5min"])),
                    "hour": float(row["hours_after_ignition"]),
                    "humidity": int(float(row["humidity_input_for_current_code_percent_rounded_to_5"])),
                    "wind_speed": float(row["wind_speed_10m_kmh"]),
                    "wind_direction": direction,
                    "observed_area_km2": float(observed_area) if observed_area else None,
                })
    except (OSError, ValueError) as exc:
        print("Weather CSV load failed. Manual weather mode:", exc)
        return []

    records.sort(key=lambda record: record["tick"])
    print("Loaded weather CSV:", WEATHER_DATA_FILE)
    print("Weather records:", len(records))
    return records


def get_weather_record_index_for_tick(tick):
    index_at_tick = -1
    for index, record in enumerate(weather_timeline):
        if record["tick"] <= tick:
            index_at_tick = index
        else:
            break
    return index_at_tick


def apply_weather_for_elapsed_tick(force=False):
    global humidity_percent, wind_speed_kmh, wind_dir_name, wind_input_text
    global current_weather_record_index

    if not weather_data_mode or not weather_timeline:
        return

    record_index = get_weather_record_index_for_tick(elapsed_ticks)
    if record_index < 0:
        record_index = 0

    if not force and record_index == current_weather_record_index:
        return

    record = weather_timeline[record_index]
    humidity_percent = max(0, min(100, record["humidity"]))
    wind_speed_kmh = max(WIND_SPEED_MIN_KMH, record["wind_speed"])
    wind_dir_name = record["wind_direction"]
    wind_input_text = format_wind_speed(wind_speed_kmh)
    current_weather_record_index = record_index
    refresh_thresholds()


def get_current_weather_record():
    if not weather_data_mode or not weather_timeline:
        return None

    record_index = get_weather_record_index_for_tick(elapsed_ticks)
    if record_index < 0:
        record_index = 0
    return weather_timeline[record_index]


weather_timeline = load_weather_timeline()
weather_data_mode = bool(weather_timeline)


# ============================================================
# 8. 맵 생성
# ============================================================

def generate_elevation_map():
    # 불암산 DEM의 실제 고도값을 각 셀에 저장한다.
    # elevation_map은 [y, x] 순서이고, grid는 [x][y] 순서다.
    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            grid[x][y].elevation = float(elevation_map[y, x])


def clear_terrain():
    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            grid[x][y].terrain = TERRAIN_PINE


def stamp_circle_terrain(terrain_type, count, min_radius, max_radius):
    # 물 지형을 원형 패치로 만든다.
    for _ in range(count):
        cx = random.randrange(GRID_WIDTH)
        cy = random.randrange(GRID_HEIGHT)
        radius = random.randint(min_radius, max_radius)
        radius2 = radius * radius

        for x in range(max(0, cx - radius), min(GRID_WIDTH, cx + radius + 1)):
            for y in range(max(0, cy - radius), min(GRID_HEIGHT, cy + radius + 1)):
                dx = x - cx
                dy = y - cy

                if dx * dx + dy * dy <= radius2:
                    grid[x][y].terrain = terrain_type


def stamp_square_terrain(terrain_type, count, min_size, max_size):
    # 바위 지형을 사각형 패치로 만든다.
    for _ in range(count):
        size = random.randint(min_size, max_size)
        x0 = random.randint(0, GRID_WIDTH - size)
        y0 = random.randint(0, GRID_HEIGHT - size)

        for x in range(x0, x0 + size):
            for y in range(y0, y0 + size):
                grid[x][y].terrain = terrain_type


def reset_fire_only():
    global elapsed_ticks, current_weather_record_index
    global suppression_placement_markers

    # 지형과 고도는 유지하고, 화재 상태만 초기화한다.
    elapsed_ticks = 0
    current_weather_record_index = -1
    initialize_fire_area_log()
    suppression_placement_markers = []

    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            cell = grid[x][y]
            cell.state = STATE_UNBURNED
            cell.accumulated_heat = 0.0
            cell.outgoing_heat = 0.0
            cell.leaf_burning_ticks = 0
            cell.ever_burned = False

            firebreak_state[x][y] = FIREBREAK_NONE
            firebreak_timer[x][y] = 0
            truck_state[x][y] = TRUCK_NONE
            truck_timer[x][y] = 0
            firefighter_state[x][y] = FIREFIGHTER_NONE
            firefighter_timer[x][y] = 0

    if weather_data_mode and weather_timeline:
        apply_weather_for_elapsed_tick(force=True)
    else:
        refresh_thresholds()


def reset_world():
    # 실제 불암산 고도 맵을 사용한다.
    # 지형 종류 데이터는 아직 없으므로 전체 셀을 소나무림으로 둔다.
    clear_terrain()
    generate_elevation_map()

    reset_fire_only()


# ============================================================
# 9. 발화 처리
# ============================================================

def ignite_leaf_cell(x, y):
    # 사용자가 클릭한 지점을 낙엽 발화 상태로 만든다.
    # 물과 바위는 발화하지 않는다.
    cell = grid[x][y]

    if not can_burn(cell):
        return

    if cell.state in (STATE_STEM_BURNING, STATE_LEAF_BURNED):
        return

    cell.state = STATE_LEAF_BURNING
    cell.leaf_burning_ticks = 0
    cell.ever_burned = True

    # 낙엽 발화 상태가 되려면 최소한 낙엽 점화 임계값만큼의 열량이 있어야 한다.
    cell.accumulated_heat = max(cell.accumulated_heat, cell.leaf_threshold)


def clear_cell_fire(x, y):
    # 우클릭으로 해당 셀의 화재 상태만 지운다.
    cell = grid[x][y]
    cell.state = STATE_UNBURNED
    cell.accumulated_heat = 0.0
    cell.outgoing_heat = 0.0
    cell.leaf_burning_ticks = 0


def get_aerial_drop_cells(center_x, center_y, width, height):
    # 클릭한 셀 주변의 직사각형 투하 대상 셀 목록을 반환한다.
    # 화면 밖으로 나가는 부분의 물은 소실된 것으로 처리한다.
    left = center_x - width // 2
    top = center_y - height // 2
    target_cells = []

    for x in range(left, left + width):
        for y in range(top, top + height):
            if in_bounds(x, y):
                target_cells.append((x, y))


    return target_cells


def apply_aerial_cooling(x, y, width, height, cooling_per_cell_kj):
    # 헬기와 비행기는 일회성 투하 수단이다.
    # 대상 셀의 현재 누적 열량을 한 번 감소시키고, 열량이 0이 된 발화 셀만 진압한다.
    for tx, ty in get_aerial_drop_cells(x, y, width, height):
        cell = grid[tx][ty]

        if not can_burn(cell):
            continue

        cell.accumulated_heat = max(0.0, cell.accumulated_heat - cooling_per_cell_kj)

        if cell.accumulated_heat <= 0.0:
            if cell.state in (STATE_LEAF_BURNING, STATE_STEM_BURNING):
                cell.state = STATE_UNBURNED

            cell.outgoing_heat = 0.0
            cell.leaf_burning_ticks = 0


def deploy_helicopter(x, y):
    apply_aerial_cooling(x, y, HELI_DROP_WIDTH, HELI_DROP_HEIGHT, HELI_COOLING_PER_CELL_KJ)


def deploy_plane(x, y):
    apply_aerial_cooling(x, y, PLANE_DROP_WIDTH, PLANE_DROP_HEIGHT, PLANE_COOLING_PER_CELL_KJ)


def deploy_firebreak(x, y):
    if not in_bounds(x, y):
        return False

    if clear_suppression_at_cell(x, y):
        return False

    cell = grid[x][y]
    if not can_burn(cell):
        return False

    # v0와 같이 이미 불이 붙은 셀에는 방화벽을 직접 설치하지 않는다.
    if cell.state in (STATE_LEAF_BURNING, STATE_STEM_BURNING):
        return False

    if firebreak_state[x][y] != FIREBREAK_NONE:
        return False

    firebreak_state[x][y] = FIREBREAK_PENDING
    firebreak_timer[x][y] = FIREBREAK_DEPLOY_TICKS
    return True


def deploy_truck_block(top_left_x, top_left_y):
    target_cells = []

    for dx in range(TRUCK_BLOCK_SIZE):
        for dy in range(TRUCK_BLOCK_SIZE):
            x = top_left_x + dx
            y = top_left_y + dy

            if not can_place_ground_suppression(x, y):
                return False

            if firebreak_state[x][y] != FIREBREAK_NONE:
                return False

            if truck_state[x][y] != TRUCK_NONE:
                return False

            if firefighter_state[x][y] != FIREFIGHTER_NONE:
                return False

            target_cells.append((x, y))

    for x, y in target_cells:
        truck_state[x][y] = TRUCK_PENDING
        truck_timer[x][y] = TRUCK_DEPLOY_TICKS

    return True



def get_firefighter_cells(corner_x, corner_y):
    target_cells = []

    for dx, dy in FIREFIGHTER_SHAPE_OFFSETS:
        x = corner_x + dx
        y = corner_y + dy

        if in_bounds(x, y):
            target_cells.append((x, y))

    return target_cells


def deploy_firefighter_l_shape(corner_x, corner_y):
    target_cells = get_firefighter_cells(corner_x, corner_y)

    if len(target_cells) != len(FIREFIGHTER_SHAPE_OFFSETS):
        return False

    for x, y in target_cells:
        if not can_place_ground_suppression(x, y):
            return False

        if firebreak_state[x][y] != FIREBREAK_NONE:
            return False

        if truck_state[x][y] != TRUCK_NONE:
            return False

        if firefighter_state[x][y] != FIREFIGHTER_NONE:
            return False

    for x, y in target_cells:
        firefighter_state[x][y] = FIREFIGHTER_PENDING
        firefighter_timer[x][y] = FIREFIGHTER_DEPLOY_TICKS

    return True

def apply_suppression_one_tick():
    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            cell = grid[x][y]

            if firebreak_state[x][y] == FIREBREAK_PENDING:
                firebreak_timer[x][y] -= 1
                if firebreak_timer[x][y] <= 0:
                    firebreak_state[x][y] = FIREBREAK_ACTIVE
                    firebreak_timer[x][y] = 0
                    cell.state = STATE_UNBURNED
                    cell.accumulated_heat = 0.0
                    cell.outgoing_heat = 0.0
                    cell.leaf_burning_ticks = 0

            elif firebreak_state[x][y] == FIREBREAK_ACTIVE:
                cell.state = STATE_UNBURNED
                cell.accumulated_heat = 0.0
                cell.outgoing_heat = 0.0
                cell.leaf_burning_ticks = 0

            if truck_state[x][y] == TRUCK_PENDING:
                truck_timer[x][y] -= 1
                if truck_timer[x][y] <= 0:
                    truck_state[x][y] = TRUCK_ACTIVE
                    truck_timer[x][y] = TRUCK_DURATION_TICKS

            elif truck_state[x][y] == TRUCK_ACTIVE:
                truck_timer[x][y] -= 1

                if can_burn(cell):
                    cell.accumulated_heat = max(0.0, cell.accumulated_heat - TRUCK_HEAT_COOL_PER_TICK_KJ)

                    if cell.accumulated_heat <= 0.0:
                        if cell.state in (STATE_LEAF_BURNING, STATE_STEM_BURNING):
                            cell.state = STATE_UNBURNED
                        cell.outgoing_heat = 0.0
                        cell.leaf_burning_ticks = 0

                if truck_timer[x][y] <= 0:
                    truck_state[x][y] = TRUCK_NONE
                    truck_timer[x][y] = 0

            if firefighter_state[x][y] == FIREFIGHTER_PENDING:
                firefighter_timer[x][y] -= 1
                if firefighter_timer[x][y] <= 0:
                    firefighter_state[x][y] = FIREFIGHTER_ACTIVE
                    firefighter_timer[x][y] = 0

            elif firefighter_state[x][y] == FIREFIGHTER_ACTIVE:
                # 소방관은 열량을 직접 제거하지 않고, 해당 셀의 열 방출만 차단한다.
                cell.outgoing_heat = 0.0


# ============================================================
# 10. 화재 확산 업데이트
# ============================================================

def update_fire_one_tick():
    apply_suppression_one_tick()

    # 각 셀에 이번 틱 동안 새로 전달될 열량을 따로 저장한다.
    # 바로 grid에 더하면 같은 틱 안에서 연쇄 반응이 과하게 발생할 수 있다.
    heat_delta = [[0.0 for _ in range(GRID_HEIGHT)] for _ in range(GRID_WIDTH)]
    leaf_burnout_candidates = []

    # --------------------------------------------------------
    # 1단계: 낙엽 발화 셀이 자기 열량을 증가시키고 주변으로 열을 방출한다.
    # --------------------------------------------------------
    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            cell = grid[x][y]
            cell.outgoing_heat = 0.0

            if cell.state != STATE_LEAF_BURNING:
                continue

            if is_firebreak_active(x, y):
                continue

            # 낙엽 발화 셀은 매 틱 고정 열량을 내부에 더한다.
            cell.leaf_burning_ticks += 1
            cell.accumulated_heat += LEAF_HEAT_PER_TICK

            # 누적 열량이 줄기 점화 임계값을 넘으면 줄기 발화 상태로 전환한다.
            # 이때 낙엽 발화 상태는 종료된다.
            if cell.accumulated_heat >= cell.stem_threshold:
                cell.state = STATE_STEM_BURNING
                cell.leaf_burning_ticks = 0
                continue

            # 소방관이 배치된 셀은 더 이상 주변으로 열을 방출하지 못한다.
            if is_firefighter_active(x, y):
                cell.outgoing_heat = 0.0
                continue

            # 줄기 발화 전까지는 낙엽 방출 열량을 주변 8방향으로 나누어 전달한다.
            cell.outgoing_heat = LEAF_RELEASE_PER_TICK

            for dx, dy, dir_index, dir_weight in NEIGHBORS:
                nx = x + dx
                ny = y + dy

                if not in_bounds(nx, ny):
                    continue

                neighbor = grid[nx][ny]

                if is_firebreak_active(nx, ny):
                    continue

                # 물과 바위는 열을 받지 않는다.
                if not can_burn(neighbor):
                    continue

                # 줄기 발화 이후에는 외부에서 열량을 전달받지 않는다.
                if neighbor.state == STATE_STEM_BURNING:
                    continue

                base_transfer = LEAF_RELEASE_PER_TICK * dir_weight / DIRECTION_WEIGHT_SUM
                wind_factor = get_wind_factor(dir_index)
                slope_factor = get_slope_factor(x, y, nx, ny)

                final_transfer = base_transfer * wind_factor * slope_factor
                heat_delta[nx][ny] += final_transfer

            if cell.leaf_burning_ticks >= LEAF_BURNING_MAX_TICKS:
                leaf_burnout_candidates.append((x, y))

    # --------------------------------------------------------
    # 2단계: 전달된 열량을 실제 셀에 반영한다.
    # --------------------------------------------------------
    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            cell = grid[x][y]

            if is_firebreak_active(x, y):
                continue

            if not can_burn(cell):
                continue

            if cell.state == STATE_STEM_BURNING:
                continue

            received_heat = heat_delta[x][y]

            if received_heat <= 0:
                continue

            cell.accumulated_heat += received_heat

            # 미발화 셀이 낙엽 점화 임계값에 도달하면 낙엽 발화 상태가 된다.
            if cell.state == STATE_UNBURNED and cell.accumulated_heat >= cell.leaf_threshold:
                cell.state = STATE_LEAF_BURNING
                cell.leaf_burning_ticks = 0
                cell.ever_burned = True

            # 낙엽 발화 또는 낙엽 연소 완료 셀이 줄기 점화 임계값에 도달하면 줄기 발화 상태가 된다.
            if cell.state in (STATE_LEAF_BURNING, STATE_LEAF_BURNED) and cell.accumulated_heat >= cell.stem_threshold:
                cell.state = STATE_STEM_BURNING
                cell.leaf_burning_ticks = 0

    for x, y in leaf_burnout_candidates:
        cell = grid[x][y]
        if cell.state == STATE_LEAF_BURNING:
            cell.state = STATE_LEAF_BURNED
            cell.outgoing_heat = 0.0


# ============================================================
# 11. 그리기
# ============================================================

def draw_grid():
    leaf_count = 0
    stem_count = 0

    # 소나무림 기본 배경은 고도 기반 지도 이미지로 표시한다.
    screen.blit(map_background, (0, 0))

    def draw_slope_border(x, y, rect):
        # 토글이 켜진 경우에만 DEM 기반 화면 표시용 경사를 셀 테두리로 덧그린다.
        # 경사 가중치 계산은 이 표시 여부와 무관하게 기존 로직 그대로 동작한다.
        if not show_slope_borders:
            return

        slope_deg = get_cell_display_slope(x, y)
        if slope_deg != 0:
            pygame.draw.rect(screen, SLOPE_BORDER_COLOR[slope_deg], rect, 1)

    def draw_target_border(x, y, rect):
        if target_cell != (x, y):
            return

        border_width = 2
        pygame.draw.rect(screen, TARGET_CELL_BORDER, rect, border_width)

    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            cell = grid[x][y]
            rect = pygame.Rect(x * CELL_SIZE, y * CELL_SIZE, CELL_SIZE, CELL_SIZE)

            # 물·바위 자료는 이후 추가하며, 지정된 경우 배경 위에 표시한다.
            if cell.terrain == TERRAIN_WATER:
                pygame.draw.rect(screen, WATER_BLUE, rect)
                draw_slope_border(x, y, rect)
                draw_target_border(x, y, rect)
                continue

            if cell.terrain == TERRAIN_ROCK:
                pygame.draw.rect(screen, ROCK_GRAY, rect)
                draw_slope_border(x, y, rect)
                draw_target_border(x, y, rect)
                continue

            # 미발화 셀에 열이 쌓이는 과정은 투명 오버레이로 표시하여
            # 지도 배경을 유지하면서 발화 직전 상태를 확인할 수 있게 한다.
            if cell.state == STATE_UNBURNED and cell.leaf_threshold > 0:
                ratio = min(1.0, cell.accumulated_heat / cell.leaf_threshold)

                if ratio > 0:
                    heating_overlay = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)

                    if ratio >= 0.7:
                        heating_overlay.fill((*PRE_LEAF_IGNITION_YELLOW, 210))
                    else:
                        alpha = int(30 + 150 * ratio)
                        heating_overlay.fill((255, 196, 80, alpha))

                    screen.blit(heating_overlay, rect.topleft)

            # 발화 및 연소 완료 상태는 지도 위에 셀 색상으로 표시한다.
            if cell.state == STATE_LEAF_BURNING:
                pygame.draw.rect(screen, get_leaf_fire_color(cell), rect)
                leaf_count += 1
            elif cell.state == STATE_STEM_BURNING:
                pygame.draw.rect(screen, STEM_FIRE_RED, rect)
                stem_count += 1
            elif cell.state == STATE_LEAF_BURNED:
                pygame.draw.rect(screen, LEAF_BURNED_BROWN, rect)

            if firebreak_state[x][y] == FIREBREAK_PENDING:
                pending_overlay = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
                pending_overlay.fill((*FIREBREAK_PENDING_TINT, 150))
                screen.blit(pending_overlay, rect.topleft)
            elif firebreak_state[x][y] == FIREBREAK_ACTIVE:
                pygame.draw.rect(screen, FIREBREAK_ACTIVE_BLACK, rect)

            if truck_state[x][y] == TRUCK_PENDING:
                pending_overlay = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
                pending_overlay.fill((*SUPPRESSION_PENDING_BLUE, 150))
                screen.blit(pending_overlay, rect.topleft)
            elif truck_state[x][y] == TRUCK_ACTIVE:
                pygame.draw.rect(screen, TRUCK_ACTIVE_GREEN, rect)

            if firefighter_state[x][y] == FIREFIGHTER_PENDING:
                pending_overlay = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
                pending_overlay.fill((*FIREFIGHTER_PENDING_PURPLE, 150))
                screen.blit(pending_overlay, rect.topleft)
            elif firefighter_state[x][y] == FIREFIGHTER_ACTIVE:
                pygame.draw.rect(screen, FIREFIGHTER_ACTIVE_PURPLE, rect)

            draw_slope_border(x, y, rect)
            draw_target_border(x, y, rect)

    return leaf_count, stem_count


def draw_aerial_drop_preview():
    if selected_tool == TOOL_HELI:
        width = HELI_DROP_WIDTH
        height = HELI_DROP_HEIGHT
    elif selected_tool == TOOL_PLANE:
        width = PLANE_DROP_WIDTH
        height = PLANE_DROP_HEIGHT
    else:
        return

    mx, my = pygame.mouse.get_pos()
    if mx < 0 or mx >= GRID_WIDTH * CELL_SIZE or my < 0 or my >= GRID_HEIGHT * CELL_SIZE:
        return

    gx = mx // CELL_SIZE
    gy = my // CELL_SIZE
    preview_overlay = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
    preview_overlay.fill((*AERIAL_PREVIEW_SKY_BLUE, 140))

    for tx, ty in get_aerial_drop_cells(gx, gy, width, height):
        rect = pygame.Rect(tx * CELL_SIZE, ty * CELL_SIZE, CELL_SIZE, CELL_SIZE)
        screen.blit(preview_overlay, rect.topleft)
        pygame.draw.rect(screen, AERIAL_PREVIEW_SKY_BLUE, rect, 1)


def get_suppression_marker_cells(tool_id, gx, gy):
    if tool_id == TOOL_HELI:
        return get_aerial_drop_cells(gx, gy, HELI_DROP_WIDTH, HELI_DROP_HEIGHT)

    if tool_id == TOOL_PLANE:
        return get_aerial_drop_cells(gx, gy, PLANE_DROP_WIDTH, PLANE_DROP_HEIGHT)

    if tool_id == TOOL_TRUCK:
        cells = []
        for dx in range(TRUCK_BLOCK_SIZE):
            for dy in range(TRUCK_BLOCK_SIZE):
                tx = gx + dx
                ty = gy + dy
                if in_bounds(tx, ty):
                    cells.append((tx, ty))
        return cells

    if tool_id == TOOL_FIREBREAK:
        return [(gx, gy)] if in_bounds(gx, gy) else []

    if tool_id == TOOL_FIREFIGHTER:
        return get_firefighter_cells(gx, gy)

    return []


def add_suppression_marker(tool_id, gx, gy):
    cells = get_suppression_marker_cells(tool_id, gx, gy)
    if not cells:
        return

    marker = {"tool_id": tool_id, "cells": cells}
    if marker not in suppression_placement_markers:
        suppression_placement_markers.append(marker)


def get_suppression_marker_style(tool_id):
    if tool_id in (TOOL_HELI, TOOL_PLANE):
        return AERIAL_PREVIEW_SKY_BLUE, 95
    if tool_id == TOOL_TRUCK:
        return TRUCK_ACTIVE_GREEN, 95
    if tool_id == TOOL_FIREBREAK:
        return WHITE, 95
    if tool_id == TOOL_FIREFIGHTER:
        return FIREFIGHTER_ACTIVE_PURPLE, 95
    return WHITE, 95


def draw_suppression_markers():
    for marker in suppression_placement_markers:
        color, alpha = get_suppression_marker_style(marker["tool_id"])
        marker_overlay = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
        marker_overlay.fill((*color, alpha))

        for tx, ty in marker["cells"]:
            rect = pygame.Rect(tx * CELL_SIZE, ty * CELL_SIZE, CELL_SIZE, CELL_SIZE)
            screen.blit(marker_overlay, rect.topleft)
            pygame.draw.rect(screen, color, rect, 1)




def draw_ground_suppression_preview():
    if selected_tool not in (TOOL_FIREBREAK, TOOL_TRUCK, TOOL_FIREFIGHTER):
        return

    mx, my = pygame.mouse.get_pos()
    if mx < 0 or mx >= GRID_WIDTH * CELL_SIZE or my < 0 or my >= GRID_HEIGHT * CELL_SIZE:
        return

    gx = mx // CELL_SIZE
    gy = my // CELL_SIZE

    preview_overlay = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)

    if selected_tool == TOOL_FIREBREAK:
        preview_overlay.fill((*WHITE, 95))
        target_cells = [(gx, gy)]
        border_color = WHITE
    elif selected_tool == TOOL_TRUCK:
        preview_overlay.fill((*TRUCK_ACTIVE_GREEN, 95))
        target_cells = []
        for dx in range(TRUCK_BLOCK_SIZE):
            for dy in range(TRUCK_BLOCK_SIZE):
                tx = gx + dx
                ty = gy + dy
                if in_bounds(tx, ty):
                    target_cells.append((tx, ty))
        border_color = TRUCK_ACTIVE_GREEN
    else:
        preview_overlay.fill((*FIREFIGHTER_ACTIVE_PURPLE, 95))
        target_cells = get_firefighter_cells(gx, gy)
        border_color = FIREFIGHTER_ACTIVE_PURPLE

    for tx, ty in target_cells:
        rect = pygame.Rect(tx * CELL_SIZE, ty * CELL_SIZE, CELL_SIZE, CELL_SIZE)
        screen.blit(preview_overlay, rect.topleft)
        pygame.draw.rect(screen, border_color, rect, 1)


def draw_button(rect, label, selected=False, use_small=False):
    mouse_pos = pygame.mouse.get_pos()

    if selected:
        color = BUTTON_SELECTED_COLOR
    elif rect.collidepoint(mouse_pos):
        color = BUTTON_HOVER_COLOR
    else:
        color = BUTTON_COLOR

    pygame.draw.rect(screen, color, rect)
    pygame.draw.rect(screen, (130, 130, 130), rect, 1)

    used_font = small_font if use_small else font
    text_surface = used_font.render(label, True, WHITE)
    text_rect = text_surface.get_rect(center=rect.center)
    screen.blit(text_surface, text_rect)


def format_wind_speed(value):
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def format_elapsed_time(total_seconds):
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_area_km2(cell_count):
    return f"{cell_count * CELL_AREA_M2 / 1_000_000:.4f} km2"


def area_km2_value(cell_count):
    return cell_count * CELL_AREA_M2 / 1_000_000


def count_fire_area_cells():
    leaf_count = 0
    stem_count = 0
    total_burned_count = 0

    for x in range(GRID_WIDTH):
        for y in range(GRID_HEIGHT):
            cell = grid[x][y]
            if cell.state == STATE_LEAF_BURNING:
                leaf_count += 1
            elif cell.state == STATE_STEM_BURNING:
                stem_count += 1

            if cell.ever_burned:
                total_burned_count += 1

    return leaf_count, stem_count, total_burned_count


def initialize_fire_area_log():
    with FIRE_AREA_LOG_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "tick",
            "elapsed_time",
            "elapsed_hours",
            "leaf_cells",
            "stem_cells",
            "total_burned_cells",
            "leaf_area_km2",
            "stem_area_km2",
            "total_burned_area_km2",
        ])

    print("Fire area CSV log:", FIRE_AREA_LOG_FILE)


def log_fire_area_tick():
    leaf_count, stem_count, total_burned_count = count_fire_area_cells()
    elapsed_seconds = elapsed_ticks * SIMULATION_SECONDS_PER_TICK
    elapsed_hours = elapsed_seconds / 3600
    elapsed_time = format_elapsed_time(elapsed_seconds)
    leaf_area = area_km2_value(leaf_count)
    stem_area = area_km2_value(stem_count)
    total_burned_area = area_km2_value(total_burned_count)

    print(
        f"Tick {elapsed_ticks} | "
        f"Time {elapsed_time} | "
        f"Leaf area: {leaf_area:.4f} km2 | "
        f"Stem area: {stem_area:.4f} km2 | "
        f"Total burned area: {total_burned_area:.4f} km2"
    )

    with FIRE_AREA_LOG_FILE.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            elapsed_ticks,
            elapsed_time,
            f"{elapsed_hours:.6f}",
            leaf_count,
            stem_count,
            total_burned_count,
            f"{leaf_area:.6f}",
            f"{stem_area:.6f}",
            f"{total_burned_area:.6f}",
        ])


def set_humidity_from_slider_x(mx):
    global humidity_percent

    if humidity_slider_rect.width <= 0:
        return

    ratio = (mx - humidity_slider_rect.x) / humidity_slider_rect.width
    ratio = max(0.0, min(1.0, ratio))
    humidity_percent = int(round(ratio * 100 / 5) * 5)
    refresh_thresholds()


def commit_wind_input():
    global wind_speed_kmh
    global wind_input_text

    try:
        value = float(wind_input_text)
    except ValueError:
        wind_input_text = format_wind_speed(wind_speed_kmh)
        return

    wind_speed_kmh = max(WIND_SPEED_MIN_KMH, value)
    wind_input_text = format_wind_speed(wind_speed_kmh)


def draw_humidity_slider(rect):
    track_y = rect.centery
    pygame.draw.line(screen, (120, 120, 120), (rect.x, track_y), (rect.right, track_y), 3)

    for value in range(0, 101, 25):
        tick_x = rect.x + int(rect.width * value / 100)
        pygame.draw.line(screen, TEXT_MUTED, (tick_x, track_y - 4), (tick_x, track_y + 4), 1)

    knob_x = rect.x + int(rect.width * humidity_percent / 100)
    knob_rect = pygame.Rect(0, 0, 12, 12)
    knob_rect.center = (knob_x, track_y)
    pygame.draw.circle(screen, BUTTON_SELECTED_COLOR, knob_rect.center, 7)
    pygame.draw.circle(screen, WHITE, knob_rect.center, 7, 1)


def draw_wind_input(rect):
    border_color = WHITE if wind_input_active else (130, 130, 130)
    pygame.draw.rect(screen, BUTTON_COLOR, rect)
    pygame.draw.rect(screen, border_color, rect, 1)

    text = wind_input_text if wind_input_active else format_wind_speed(wind_speed_kmh)
    text_surface = small_font.render(text, True, WHITE)
    text_rect = text_surface.get_rect(midright=(rect.right - 5, rect.centery))
    screen.blit(text_surface, text_rect)


def draw_target_input(rect, text, is_active):
    border_color = WHITE if is_active else (130, 130, 130)
    pygame.draw.rect(screen, BUTTON_COLOR, rect)
    pygame.draw.rect(screen, border_color, rect, 1)

    text_surface = small_font.render(text, True, WHITE)
    text_rect = text_surface.get_rect(midright=(rect.right - 5, rect.centery))
    screen.blit(text_surface, text_rect)


def apply_target_cell():
    global target_cell

    try:
        x = int(target_x_text)
        y = int(target_y_text)
    except ValueError:
        print("Target cell not set. Enter integer x and y values.")
        return

    if not in_bounds(x, y):
        print(f"Target cell out of range: x={x}, y={y} / valid x=0-{GRID_WIDTH - 1}, y=0-{GRID_HEIGHT - 1}")
        return

    target_cell = (x, y)
    print(f"Target cell highlighted: x={x}, y={y}")


def draw_sidebar(leaf_count, stem_count):
    pygame.draw.rect(screen, SIDEBAR_GRAY, (sidebar_x, 0, SIDEBAR_WIDTH, SCREEN_HEIGHT))

    x0 = sidebar_x + SIDEBAR_PADDING
    content_w = SIDEBAR_WIDTH - SIDEBAR_PADDING * 2
    y = 10
    line_h = 18
    small_line_h = 14
    heading_gap = 17

    status = "RUNNING" if is_running else "PAUSED"
    status_color = (80, 255, 120) if is_running else (255, 230, 80)

    draw_text(f"Status: {status}", x0, y, status_color)
    y += 22

    elapsed_seconds = elapsed_ticks * SIMULATION_SECONDS_PER_TICK
    draw_text(f"Elapsed ticks: {elapsed_ticks}", x0, y)
    y += line_h

    draw_text(f"Elapsed time: {format_elapsed_time(elapsed_seconds)}", x0, y)
    y += 22

    draw_text(f"Leaf burning: {leaf_count} cells", x0, y, LEAF_FIRE_ORANGE)
    y += line_h

    draw_text(f"Leaf area: {format_area_km2(leaf_count)}", x0, y, LEAF_FIRE_ORANGE, use_small=True)
    y += small_line_h

    draw_text(f"Stem burning: {stem_count} cells", x0, y, STEM_FIRE_RED)
    y += line_h

    draw_text(f"Stem area: {format_area_km2(stem_count)}", x0, y, STEM_FIRE_RED, use_small=True)
    y += small_line_h

    _, _, total_burned_count = count_fire_area_cells()
    draw_text(f"Total burned: {total_burned_count} cells", x0, y, LEAF_BURNED_BROWN)
    y += line_h

    draw_text(f"Total burned area: {format_area_km2(total_burned_count)}", x0, y, LEAF_BURNED_BROWN, use_small=True)
    y += 22

    draw_text(f"Humidity: {humidity_percent}%", x0, y)
    y += line_h

    humidity_slider_rect.update(x0, y + 3, content_w, 16)
    draw_humidity_slider(humidity_slider_rect)
    y += 21

    leaf_threshold = calculate_leaf_threshold()
    draw_text(f"Leaf threshold: {leaf_threshold:,.0f} kJ", x0, y, TEXT_MUTED, use_small=True)
    y += 21

    draw_text("Wind speed:", x0, y)
    wind_input_rect.update(x0 + 100, y - 3, 60, 22)
    draw_wind_input(wind_input_rect)
    draw_text("km/h", wind_input_rect.right + 7, y + 1, TEXT_MUTED, use_small=True)
    y += 27

    draw_text(f"Wind direction: {wind_dir_name}", x0, y)
    y += 24

    draw_text("Wind direction", x0, y)
    y += heading_gap + 2

    wind_gap = 4
    wind_button_w = (content_w - wind_gap * (len(wind_buttons) - 1)) // len(wind_buttons)
    for i, button in enumerate(wind_buttons):
        button_x = x0 + i * (wind_button_w + wind_gap)
        button_w = wind_button_w
        if i == len(wind_buttons) - 1:
            button_w = x0 + content_w - button_x
        button["rect"].update(button_x, y, button_w, WIND_BUTTON_HEIGHT)
        selected = button["name"] == wind_dir_name
        draw_button(button["rect"], button["name"], selected, use_small=True)

    y += WIND_BUTTON_HEIGHT + SECTION_GAP

    mode_label = "Weather: CSV AUTO" if weather_data_mode else "Weather: MANUAL"
    weather_mode_button.update(x0, y, content_w, BUTTON_HEIGHT)
    draw_button(weather_mode_button, mode_label, weather_data_mode, use_small=True)
    y += BUTTON_HEIGHT + 4

    if weather_data_mode:
        record = get_current_weather_record()
        if record is not None:
            area_text = "--" if record["observed_area_km2"] is None else f'{record["observed_area_km2"]:.3f} km2'
            draw_text(f'Data: {record["hour"]:g} h / observed {area_text}', x0, y, TEXT_MUTED, use_small=True)
            y += small_line_h + 3

    draw_text("Controls", x0, y)
    y += heading_gap

    draw_text("Space: run / pause", x0, y, TEXT_MUTED, use_small=True)
    y += small_line_h
    draw_text("R: reset fire only", x0, y, TEXT_MUTED, use_small=True)
    y += small_line_h
    draw_text("S: slope borders", x0, y, TEXT_MUTED, use_small=True)
    y += heading_gap

    speed_button.update(x0, y, content_w, BUTTON_HEIGHT)
    draw_button(speed_button, "Speed: 5x", is_fast_mode)
    y += BUTTON_HEIGHT + 5

    slope_border_button.update(x0, y, content_w, BUTTON_HEIGHT)
    draw_button(slope_border_button, "Slope borders", show_slope_borders)
    y += BUTTON_HEIGHT + 5

    reset_button.update(x0, y, content_w, BUTTON_HEIGHT)
    draw_button(reset_button, "Reset world")
    y += BUTTON_HEIGHT + SECTION_GAP

    draw_text("Target cell", x0, y)
    y += heading_gap

    input_w = 58
    target_gap = 6
    draw_text("X", x0, y + 2, TEXT_MUTED, use_small=True)
    target_x_input_rect.update(x0 + 15, y - 2, input_w, 22)
    draw_target_input(target_x_input_rect, target_x_text, target_input_active == "x")

    y_input_x = target_x_input_rect.right + target_gap + 16
    draw_text("Y", target_x_input_rect.right + target_gap, y + 2, TEXT_MUTED, use_small=True)
    target_y_input_rect.update(y_input_x, y - 2, input_w, 22)
    draw_target_input(target_y_input_rect, target_y_text, target_input_active == "y")

    target_cell_button.update(target_y_input_rect.right + target_gap, y - 2, x0 + content_w - target_y_input_rect.right - target_gap, 22)
    draw_button(target_cell_button, "Target", use_small=True)
    y += 27

    if target_cell is not None:
        draw_text(f"Selected: x={target_cell[0]}, y={target_cell[1]}", x0, y, TARGET_CELL_BORDER, use_small=True)
        y += small_line_h + 3

    draw_text("Suppression tools", x0, y)
    y += heading_gap
    draw_text("Firefighter / Firebreak / Truck / Heli / Plane implemented.", x0, y, TEXT_MUTED, use_small=True)
    y += small_line_h + 3

    for button in tool_buttons:
        button["rect"].update(x0, y, content_w, BUTTON_HEIGHT)
        selected = selected_tool == button["tool_id"]
        draw_button(button["rect"], button["label"], selected, use_small=True)
        y += BUTTON_HEIGHT + TOOL_BUTTON_GAP

    # 범례
    y += SECTION_GAP + 4
    legend_y = y
    draw_text("Legend", x0, legend_y)
    legend_y += heading_gap + 3

    legend_box_size = 11
    legend_row_gap = 18

    legend_single_items = [
        (LEAF_BURNED_BROWN, "Burned"),
        (PRE_LEAF_IGNITION_YELLOW, "Heating"),
    ]

    for color, label in legend_single_items:
        rect = pygame.Rect(x0, legend_y, legend_box_size, legend_box_size)
        pygame.draw.rect(screen, color, rect)
        pygame.draw.rect(screen, WHITE, rect, 1)
        draw_text(label, x0 + 15, legend_y - 2, TEXT_MUTED, use_small=True)
        legend_y += legend_row_gap

    leaf_swatches_x = x0
    leaf_label_x = leaf_swatches_x + len(LEAF_FIRE_ORANGE_PALETTE) * (legend_box_size + 2) + 4
    for idx, color in enumerate(LEAF_FIRE_ORANGE_PALETTE):
        rect = pygame.Rect(
            leaf_swatches_x + idx * (legend_box_size + 2),
            legend_y,
            legend_box_size,
            legend_box_size,
        )
        pygame.draw.rect(screen, color, rect)
        pygame.draw.rect(screen, WHITE, rect, 1)

    draw_text("Leaf", leaf_label_x, legend_y - 2, TEXT_MUTED, use_small=True)
    legend_y += legend_row_gap

    rect = pygame.Rect(x0, legend_y, legend_box_size, legend_box_size)
    pygame.draw.rect(screen, STEM_FIRE_RED, rect)
    pygame.draw.rect(screen, WHITE, rect, 1)
    draw_text("Stem", x0 + 15, legend_y - 2, TEXT_MUTED, use_small=True)


# ============================================================
# 12. 입력 처리
# ============================================================

def handle_keydown(event):
    global is_running
    global humidity_percent
    global wind_speed_kmh
    global wind_input_text
    global wind_input_active
    global target_x_text
    global target_y_text
    global target_input_active
    global selected_tool
    global show_slope_borders

    if target_input_active is not None:
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            apply_target_cell()
            target_input_active = None
            return

        if event.key == pygame.K_ESCAPE:
            target_input_active = None
            return

        if event.key == pygame.K_TAB:
            target_input_active = "y" if target_input_active == "x" else "x"
            return

        if event.key == pygame.K_BACKSPACE:
            if target_input_active == "x":
                target_x_text = target_x_text[:-1]
            else:
                target_y_text = target_y_text[:-1]
            return

        if event.unicode.isdigit():
            if target_input_active == "x":
                target_x_text += event.unicode
            else:
                target_y_text += event.unicode
            return

        return

    if wind_input_active:
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            commit_wind_input()
            wind_input_active = False
            return

        if event.key == pygame.K_ESCAPE:
            wind_input_text = format_wind_speed(wind_speed_kmh)
            wind_input_active = False
            return

        if event.key == pygame.K_BACKSPACE:
            wind_input_text = wind_input_text[:-1]
            return

        if event.unicode.isdigit():
            wind_input_text += event.unicode
            commit_wind_input()
            return

        if event.unicode == "." and "." not in wind_input_text:
            wind_input_text += event.unicode
            return

        return

    if event.key == pygame.K_SPACE:
        is_running = not is_running

        # 실행 중에는 도구 선택을 해제한다.
        if is_running:
            selected_tool = None

    elif event.key in (pygame.K_EQUALS, pygame.K_PLUS) and not weather_data_mode:
        wind_speed_kmh += WIND_SPEED_STEP_KMH
        wind_input_text = format_wind_speed(wind_speed_kmh)

    elif event.key == pygame.K_MINUS and not weather_data_mode:
        wind_speed_kmh = max(
            WIND_SPEED_MIN_KMH,
            wind_speed_kmh - WIND_SPEED_STEP_KMH,
        )
        wind_input_text = format_wind_speed(wind_speed_kmh)

    elif event.key == pygame.K_r:
        reset_fire_only()

    elif event.key == pygame.K_s:
        show_slope_borders = not show_slope_borders


def handle_sidebar_click(mx, my):
    global wind_dir_name
    global wind_input_active
    global wind_input_text
    global target_x_text
    global target_y_text
    global target_input_active
    global humidity_slider_dragging
    global selected_tool
    global is_fast_mode
    global show_slope_borders
    global last_tick_time
    global weather_data_mode
    global current_weather_record_index

    if weather_mode_button.collidepoint(mx, my) and weather_timeline:
        weather_data_mode = not weather_data_mode
        wind_input_active = False
        if weather_data_mode:
            current_weather_record_index = -1
            apply_weather_for_elapsed_tick(force=True)
        return


    if wind_input_active and not wind_input_rect.collidepoint(mx, my):
        commit_wind_input()
        wind_input_active = False

    if target_input_active is not None and not target_x_input_rect.collidepoint(mx, my) and not target_y_input_rect.collidepoint(mx, my):
        target_input_active = None

    if target_x_input_rect.collidepoint(mx, my):
        target_input_active = "x"
        wind_input_active = False
        target_x_text = ""
        return

    if target_y_input_rect.collidepoint(mx, my):
        target_input_active = "y"
        wind_input_active = False
        target_y_text = ""
        return

    if target_cell_button.collidepoint(mx, my):
        apply_target_cell()
        target_input_active = None
        wind_input_active = False
        return

    if humidity_slider_rect.collidepoint(mx, my):
        if not weather_data_mode:
            set_humidity_from_slider_x(mx)
            humidity_slider_dragging = True
        return

    if wind_input_rect.collidepoint(mx, my):
        if not weather_data_mode:
            wind_input_active = True
            wind_input_text = ""
        return

    if speed_button.collidepoint(mx, my):
        is_fast_mode = not is_fast_mode
        last_tick_time = pygame.time.get_ticks()
        return

    if slope_border_button.collidepoint(mx, my):
        show_slope_borders = not show_slope_borders
        return

    if reset_button.collidepoint(mx, my):
        reset_world()
        return

    for button in wind_buttons:
        if button["rect"].collidepoint(mx, my):
            if not weather_data_mode:
                wind_dir_name = button["name"]
            return

    for button in tool_buttons:
        if button["rect"].collidepoint(mx, my):
            tool_id = button["tool_id"]

            if selected_tool == tool_id:
                selected_tool = None
            else:
                selected_tool = tool_id

            return


def handle_mousemotion(mx, my):
    if humidity_slider_dragging and not weather_data_mode:
        set_humidity_from_slider_x(mx)


def handle_mouseup(event):
    global humidity_slider_dragging

    if event.button == 1:
        humidity_slider_dragging = False


def handle_grid_click(mx, my, mouse_button):
    gx = mx // CELL_SIZE
    gy = my // CELL_SIZE

    if not in_bounds(gx, gy):
        return

    if mouse_button == 1:
        if selected_tool == TOOL_FIREBREAK:
            if deploy_firebreak(gx, gy) and not is_running:
                add_suppression_marker(selected_tool, gx, gy)
            return

        if selected_tool == TOOL_TRUCK:
            if deploy_truck_block(gx, gy) and not is_running:
                add_suppression_marker(selected_tool, gx, gy)
            return

        # 헬기와 비행기는 선택 후 격자를 클릭하면 해당 지점에 즉시 1회 투하한다.
        if selected_tool == TOOL_HELI:
            deploy_helicopter(gx, gy)
            if not is_running:
                add_suppression_marker(selected_tool, gx, gy)
            return

        if selected_tool == TOOL_PLANE:
            deploy_plane(gx, gy)
            if not is_running:
                add_suppression_marker(selected_tool, gx, gy)
            return

        if selected_tool == TOOL_FIREFIGHTER:
            if deploy_firefighter_l_shape(gx, gy) and not is_running:
                add_suppression_marker(selected_tool, gx, gy)
            return

        if selected_tool is not None:
            return

        # 도구가 선택되어 있지 않으면 발화 지점을 만든다.
        ignite_leaf_cell(gx, gy)

    elif mouse_button == 3:
        # 우클릭은 테스트 편의를 위한 해당 셀 화재 제거다.
        clear_cell_fire(gx, gy)


# ============================================================
# 13. 메인 루프
# ============================================================

reset_world()

running = True

while running:
    clock.tick(60)
    current_time = pygame.time.get_ticks()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN:
            handle_keydown(event)

        elif event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos

            if mx >= sidebar_x:
                if event.button == 1:
                    handle_sidebar_click(mx, my)
            else:
                if wind_input_active:
                    commit_wind_input()
                    wind_input_active = False
                handle_grid_click(mx, my, event.button)

        elif event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            handle_mousemotion(mx, my)

        elif event.type == pygame.MOUSEBUTTONUP:
            handle_mouseup(event)

    tick_interval_ms = FAST_TICK_INTERVAL_MS if is_fast_mode else NORMAL_TICK_INTERVAL_MS

    # 실행 중이면 현재 배속 간격마다 1틱 진행한다.
    if is_running and current_time - last_tick_time >= tick_interval_ms:
        update_fire_one_tick()
        elapsed_ticks += 1
        apply_weather_for_elapsed_tick()
        log_fire_area_tick()
        last_tick_time = current_time

    screen.fill(BLACK)

    leaf_count, stem_count = draw_grid()
    draw_suppression_markers()
    draw_aerial_drop_preview()
    draw_ground_suppression_preview()
    draw_sidebar(leaf_count, stem_count)

    pygame.display.flip()

pygame.quit()
