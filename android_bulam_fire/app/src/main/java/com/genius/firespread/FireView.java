package com.genius.firespread;

import android.content.Context;
import android.content.res.AssetManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.View;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class FireView extends View {
    private static final int DIRS = 8;
    private static final int EMPTY = 0;
    private static final int LEAF_BURNING = 2;
    private static final int STEM_BURNING = 3;
    private static final int BURNED = 4;

    private static final int TOOL_IGNITE = 0;
    private static final int TOOL_FIREFIGHTER = 1;
    private static final int TOOL_TRUCK = 2;
    private static final int TOOL_HELI = 3;
    private static final int TOOL_PLANE = 4;
    private static final int TOOL_FIREBREAK = 5;

    private static final int BLOCK_NONE = 0;
    private static final int BLOCK_PENDING = 1;
    private static final int BLOCK_ACTIVE = 2;
    private static final int FIREBREAK_DEPLOY_TICKS = 10;
    private static final int FIREFIGHTER_DEPLOY_TICKS = 4;
    private static final int TRUCK_DEPLOY_TICKS = 8;
    private static final int TRUCK_DURATION_TICKS = 6;
    private static final int TRUCK_BLOCK_SIZE = 2;
    private static final double TRUCK_HEAT_COOL_PER_TICK_KJ = 154_000.0;
    private static final int HELI_DROP_WIDTH = 3;
    private static final int HELI_DROP_HEIGHT = 2;
    private static final int PLANE_DROP_WIDTH = 5;
    private static final int PLANE_DROP_HEIGHT = 3;
    private static final double HELI_COOLING_PER_CELL_KJ = 5_544_000.0;
    private static final double PLANE_COOLING_PER_CELL_KJ = 5_670_588.0;

    private static final double CELL_AREA_M2 = 900.0;
    private static final double LEAF_FUEL_MASS_PER_CELL = 1114.2;
    private static final double BASE_IGNITION_KJ_PER_KG = 581.0;
    private static final double WATER_EXTRA_KJ_PER_KG = 2596.0;
    private static final double STEM_IGNITION_THRESHOLD = 23_737_883.0;
    private static final double LEAF_HEAT_PER_TICK = 635_882.0;
    private static final double LEAF_RELEASE_PER_TICK = 77_813.0;
    private static final int LEAF_BURNING_MAX_TICKS = 32;
    private static final double DIAGONAL_WEIGHT = 1.0 / Math.sqrt(2.0);
    private static final double DIRECTION_WEIGHT_SUM = 4.0 + 4.0 * DIAGONAL_WEIGHT;
    private static final double WIND_MAIN_EXP_COEFFICIENT = 0.1783;
    private static final double[] LEAF_MOISTURE_BY_HUMIDITY = {
            0.000, 0.037, 0.051, 0.063, 0.072,
            0.081, 0.089, 0.096, 0.103, 0.109,
            0.116, 0.122, 0.129, 0.137, 0.146,
            0.158, 0.174, 0.196, 0.229, 0.240,
            0.250
    };

    private static final int[] DX = {0, 1, 1, 1, 0, -1, -1, -1};
    private static final int[] DY = {-1, -1, 0, 1, 1, 1, 0, -1};
    private static final double[] DIR_WEIGHT = {1.0, DIAGONAL_WEIGHT, 1.0, DIAGONAL_WEIGHT, 1.0, DIAGONAL_WEIGHT, 1.0, DIAGONAL_WEIGHT};
    private static final String[] WIND_NAMES = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"};
    private static final int[] WIND_DIR_INDEX = {0, 1, 2, 3, 4, 5, 6, 7};

    private static final int BLACK = Color.rgb(0, 0, 0);
    private static final int WHITE = Color.rgb(255, 255, 255);
    private static final int TEXT_MUTED = Color.rgb(200, 200, 200);
    private static final int SIDEBAR_GRAY = Color.rgb(55, 55, 55);
    private static final int BUTTON_COLOR = Color.rgb(45, 45, 45);
    private static final int BUTTON_SELECTED_COLOR = Color.rgb(110, 110, 110);
    private static final int PRE_HEAT_YELLOW = Color.rgb(255, 252, 220);
    private static final int STEM_FIRE_RED = Color.rgb(195, 25, 25);
    private static final int LEAF_BURNED_BROWN = Color.rgb(95, 70, 42);
    private static final int SLOPE_BORDER_10 = Color.rgb(120, 160, 255);
    private static final int SLOPE_BORDER_20 = Color.rgb(255, 215, 90);
    private static final int SLOPE_BORDER_30 = Color.rgb(255, 90, 90);
    private static final int AERIAL_PREVIEW_SKY_BLUE = Color.rgb(80, 220, 255);
    private static final int FIREFIGHTER_ACTIVE_PURPLE = Color.rgb(125, 85, 215);
    private static final int FIREFIGHTER_PENDING_PURPLE = Color.rgb(180, 150, 255);
    private static final int TRUCK_ACTIVE_GREEN = Color.rgb(0, 210, 0);
    private static final int FIREBREAK_ACTIVE_BLACK = Color.rgb(0, 0, 0);
    private static final int FIREBREAK_PENDING_TINT = Color.rgb(20, 20, 20);
    private static final int[] LEAF_FIRE_ORANGE_PALETTE = {
            Color.rgb(255, 214, 150),
            Color.rgb(255, 184, 96),
            Color.rgb(255, 146, 55),
            Color.rgb(245, 105, 28),
            Color.rgb(222, 72, 12)
    };

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<Button> buttons = new ArrayList<>();
    private final List<Button> portraitButtons = new ArrayList<>();
    private final RectF menuButton = new RectF();
    private final RectF closeButton = new RectF();
    private final RectF humiditySlider = new RectF();
    private final RectF windSpeedSlider = new RectF();
    private final RectF cellDrawRect = new RectF();

    private final MapPreset[] presets = {
            new MapPreset("flat_square", "Flat", "maps/flat_square/preview_map.png", "maps/flat_square/directional_slope_factor.npy", 145, 145),
            new MapPreset("bulam", "Bulam", "maps/bulam/preview_map.png", "maps/bulam/directional_slope_factor.npy", 74, 67),
            new MapPreset("california", "California", "maps/california/preview_map.png", "maps/california/directional_slope_factor.npy", 218, 145)
    };

    private MapPreset preset;
    private Bitmap mapBitmap;
    private float[][][] slopeFactor;
    private int[][] state;
    private int[][] age;
    private double[][] accumulatedHeat;
    private double[][] outgoingHeat;
    private double[][] heatDelta;
    private boolean[][] everBurned;
    private int[][] firebreakState;
    private int[][] firebreakTimer;
    private int[][] firefighterState;
    private int[][] firefighterTimer;
    private int[][] truckState;
    private int[][] truckTimer;
    private int[] burnoutX = new int[0];
    private int[] burnoutY = new int[0];
    private int gridW;
    private int gridH;
    private long lastTickMs;
    private long elapsedTicks;
    private boolean running = false;
    private boolean fastMode = false;
    private boolean showSlopeBorders = false;
    private boolean drawerOpen = false;
    private int selectedTool = TOOL_IGNITE;
    private int humidityPercent = 0;
    private int windSpeedKmh = 10;
    private int windDirIndex = 2;
    private boolean draggingHumidity = false;
    private boolean draggingWindSpeed = false;
    private boolean draggingSidebar = false;
    private boolean draggingMap = false;
    private boolean pinchingMap = false;
    private float lastSidebarY = 0f;
    private float sidebarScrollY = 0f;
    private float lastMapX = 0f;
    private float lastMapY = 0f;
    private float zoomScale = 1f;
    private float zoomOffsetX = 0f;
    private float zoomOffsetY = 0f;
    private float pinchStartDistance = 0f;
    private float pinchStartScale = 1f;
    private float pinchStartOffsetX = 0f;
    private float pinchStartOffsetY = 0f;
    private float pinchFocusX = 0f;
    private float pinchFocusY = 0f;
    private boolean pendingMapTap = false;
    private boolean mapTouchMoved = false;
    private int pendingMapX = -1;
    private int pendingMapY = -1;

    public FireView(Context context) {
        super(context);
        setKeepScreenOn(true);
        loadPreset(context.getAssets(), presets[1]);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (running) {
            tick();
        }
        drawMap(canvas);
        drawCells(canvas);
        drawToolPreview(canvas);
        drawChrome(canvas);
        postInvalidateDelayed(33);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX();
        float y = event.getY();
        int action = event.getActionMasked();

        if (action == MotionEvent.ACTION_POINTER_DOWN && event.getPointerCount() >= 2 && canStartMapGesture(event)) {
            pinchingMap = true;
            draggingMap = false;
            draggingHumidity = false;
            draggingWindSpeed = false;
            draggingSidebar = false;
            pendingMapTap = false;
            mapTouchMoved = false;
            pinchStartDistance = pointerDistance(event);
            pinchStartScale = zoomScale;
            pinchStartOffsetX = zoomOffsetX;
            pinchStartOffsetY = zoomOffsetY;
            pinchFocusX = pointerFocusX(event);
            pinchFocusY = pointerFocusY(event);
            return true;
        }

        if (action == MotionEvent.ACTION_POINTER_UP) {
            if (event.getPointerCount() <= 2) {
                pinchingMap = false;
            }
            return true;
        }

        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            if (action == MotionEvent.ACTION_UP && pendingMapTap && !mapTouchMoved) {
                applyTool(pendingMapX, pendingMapY);
            }
            draggingHumidity = false;
            draggingWindSpeed = false;
            draggingSidebar = false;
            draggingMap = false;
            pinchingMap = false;
            pendingMapTap = false;
            mapTouchMoved = false;
            return true;
        }

        if (action == MotionEvent.ACTION_MOVE) {
            if (pinchingMap && event.getPointerCount() >= 2) {
                updateZoomFromPinch(event);
            } else if (draggingHumidity) {
                setHumidityFromTouch(x);
            } else if (draggingWindSpeed) {
                setWindSpeedFromTouch(x);
            } else if (draggingSidebar) {
                sidebarScrollY = Math.max(0f, Math.min(maxSidebarScroll(), sidebarScrollY + lastSidebarY - y));
                lastSidebarY = y;
            } else if (draggingMap) {
                float dx = x - lastMapX;
                float dy = y - lastMapY;
                if (Math.abs(dx) + Math.abs(dy) > dp(2)) {
                    mapTouchMoved = true;
                }
                zoomOffsetX += dx;
                zoomOffsetY += dy;
                clampZoomOffset();
                lastMapX = x;
                lastMapY = y;
            }
            return true;
        }
        if (action != MotionEvent.ACTION_DOWN) {
            return true;
        }

        updateMenuButtonBounds();
        updateCloseButtonBounds();

        for (Button button : portraitButtons) {
            if (button.rect.contains(x, y)) {
                button.action.run();
                return true;
            }
        }
        float sidebarContentY = y + sidebarScrollY;
        if (sideVisible() && closeButton.contains(x, y)) {
            drawerOpen = false;
            return true;
        }
        if (!sideVisible() && menuButton.contains(x, y)) {
            drawerOpen = true;
            return true;
        }
        if (sideVisible() && sidebarArea().contains(x, y)) {
            draggingSidebar = true;
            lastSidebarY = y;
            if (humiditySlider.contains(x, sidebarContentY)) {
                draggingHumidity = true;
                setHumidityFromTouch(x);
                return true;
            }
            if (windSpeedSlider.contains(x, sidebarContentY)) {
                draggingWindSpeed = true;
                setWindSpeedFromTouch(x);
                return true;
            }
            for (Button button : buttons) {
                if (button.rect.contains(x, sidebarContentY)) {
                    button.action.run();
                    return true;
                }
            }
            return true;
        }

        int[] cell = cellFromPoint(x, y);
        if (cell == null) {
            return true;
        }
        if (zoomScale > 1.01f) {
            draggingMap = true;
            lastMapX = x;
            lastMapY = y;
            pendingMapTap = true;
            mapTouchMoved = false;
            pendingMapX = cell[0];
            pendingMapY = cell[1];
            return true;
        }
        applyTool(cell[0], cell[1]);
        return true;
    }

    private void loadPreset(AssetManager assets, MapPreset nextPreset) {
        try {
            Bitmap nextMap = BitmapFactory.decodeStream(assets.open(nextPreset.previewAsset));
            NpyData npyData = loadNpy(assets.open(nextPreset.slopeAsset));
            if (npyData.height != nextPreset.gridH || npyData.width != nextPreset.gridW || npyData.dirs != DIRS) {
                throw new IOException("Unexpected npy shape for " + nextPreset.id);
            }
            preset = nextPreset;
            mapBitmap = nextMap;
            slopeFactor = npyData.values;
            gridW = nextPreset.gridW;
            gridH = nextPreset.gridH;
            state = new int[gridW][gridH];
            age = new int[gridW][gridH];
            accumulatedHeat = new double[gridW][gridH];
            outgoingHeat = new double[gridW][gridH];
            heatDelta = new double[gridW][gridH];
            everBurned = new boolean[gridW][gridH];
            firebreakState = new int[gridW][gridH];
            firebreakTimer = new int[gridW][gridH];
            firefighterState = new int[gridW][gridH];
            firefighterTimer = new int[gridW][gridH];
            truckState = new int[gridW][gridH];
            truckTimer = new int[gridW][gridH];
            burnoutX = new int[gridW * gridH];
            burnoutY = new int[gridW * gridH];
            elapsedTicks = 0;
            drawerOpen = false;
            sidebarScrollY = 0f;
            resetZoom();
        } catch (IOException e) {
            throw new IllegalStateException("Failed to load map preset: " + nextPreset.id, e);
        }
    }

    private NpyData loadNpy(InputStream input) throws IOException {
        byte[] bytes = readAll(input);
        if (bytes.length < 16 || bytes[0] != (byte) 0x93 || bytes[1] != 'N' || bytes[2] != 'U') {
            throw new IOException("Invalid npy file");
        }

        int major = bytes[6] & 0xff;
        int headerStart;
        int headerLength;
        if (major == 1) {
            headerLength = (bytes[8] & 0xff) | ((bytes[9] & 0xff) << 8);
            headerStart = 10;
        } else {
            headerLength = (bytes[8] & 0xff)
                    | ((bytes[9] & 0xff) << 8)
                    | ((bytes[10] & 0xff) << 16)
                    | ((bytes[11] & 0xff) << 24);
            headerStart = 12;
        }

        String header = new String(bytes, headerStart, headerLength, StandardCharsets.US_ASCII);
        Matcher matcher = Pattern.compile("\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)").matcher(header);
        if (!header.contains("<f4") || !matcher.find()) {
            throw new IOException("Unexpected npy header: " + header);
        }

        int h = Integer.parseInt(matcher.group(1));
        int w = Integer.parseInt(matcher.group(2));
        int dirs = Integer.parseInt(matcher.group(3));
        float[][][] values = new float[h][w][dirs];
        ByteBuffer buffer = ByteBuffer.wrap(bytes, headerStart + headerLength, bytes.length - headerStart - headerLength);
        buffer.order(ByteOrder.LITTLE_ENDIAN);
        for (int yy = 0; yy < h; yy++) {
            for (int xx = 0; xx < w; xx++) {
                for (int dd = 0; dd < dirs; dd++) {
                    values[yy][xx][dd] = buffer.getFloat();
                }
            }
        }
        return new NpyData(w, h, dirs, values);
    }

    private byte[] readAll(InputStream input) throws IOException {
        try (InputStream in = input; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] chunk = new byte[8192];
            int read;
            while ((read = in.read(chunk)) != -1) {
                out.write(chunk, 0, read);
            }
            return out.toByteArray();
        }
    }

    private void tick() {
        long now = System.currentTimeMillis();
        long interval = fastMode ? 100 : 500;
        if (now - lastTickMs < interval) {
            return;
        }
        lastTickMs = now;
        updateFireOneTick();
        elapsedTicks++;
    }

    private void updateFireOneTick() {
        applySuppressionOneTick();
        int burnoutCount = 0;

        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                heatDelta[x][y] = 0.0;
                outgoingHeat[x][y] = 0.0;
            }
        }

        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                if (state[x][y] != LEAF_BURNING || isFirebreakActive(x, y)) {
                    continue;
                }

                age[x][y]++;
                accumulatedHeat[x][y] += LEAF_HEAT_PER_TICK;

                if (accumulatedHeat[x][y] >= STEM_IGNITION_THRESHOLD) {
                    state[x][y] = STEM_BURNING;
                    age[x][y] = 0;
                    continue;
                }

                if (isFirefighterActive(x, y)) {
                    continue;
                }

                outgoingHeat[x][y] = LEAF_RELEASE_PER_TICK;
                for (int d = 0; d < DIRS; d++) {
                    int nx = x + DX[d];
                    int ny = y + DY[d];
                    if (!inside(nx, ny) || isFirebreakActive(nx, ny) || state[nx][ny] == STEM_BURNING) {
                        continue;
                    }
                    double baseTransfer = LEAF_RELEASE_PER_TICK * DIR_WEIGHT[d] / DIRECTION_WEIGHT_SUM;
                    double finalTransfer = baseTransfer * windFactor(d) * slopeFactor[y][x][d];
                    heatDelta[nx][ny] += finalTransfer;
                }

                if (age[x][y] >= LEAF_BURNING_MAX_TICKS) {
                    burnoutX[burnoutCount] = x;
                    burnoutY[burnoutCount] = y;
                    burnoutCount++;
                }
            }
        }

        double threshold = leafThreshold();
        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                if (isFirebreakActive(x, y) || state[x][y] == STEM_BURNING || heatDelta[x][y] <= 0.0) {
                    continue;
                }

                accumulatedHeat[x][y] += heatDelta[x][y];
                if (state[x][y] == EMPTY && accumulatedHeat[x][y] >= threshold) {
                    state[x][y] = LEAF_BURNING;
                    age[x][y] = 0;
                    everBurned[x][y] = true;
                }
                if ((state[x][y] == LEAF_BURNING || state[x][y] == BURNED)
                        && accumulatedHeat[x][y] >= STEM_IGNITION_THRESHOLD) {
                    state[x][y] = STEM_BURNING;
                    age[x][y] = 0;
                }
            }
        }

        for (int i = 0; i < burnoutCount; i++) {
            int x = burnoutX[i];
            int y = burnoutY[i];
            if (state[x][y] == LEAF_BURNING) {
                state[x][y] = BURNED;
                outgoingHeat[x][y] = 0.0;
            }
        }
    }

    private double windFactor(int directionIndex) {
        if (windSpeedKmh <= 0) {
            return 1.0;
        }

        double mainFactor = Math.exp(WIND_MAIN_EXP_COEFFICIENT * windSpeedKmh);
        double adjacentFactor = Math.max(1.0, mainFactor / Math.sqrt(2.0));
        int leftIndex = (windDirIndex + DIRS - 1) % DIRS;
        int rightIndex = (windDirIndex + 1) % DIRS;

        if (directionIndex == windDirIndex) {
            return mainFactor;
        }
        if (directionIndex == leftIndex || directionIndex == rightIndex) {
            return adjacentFactor;
        }
        return 1.0;
    }

    private void applySuppressionOneTick() {
        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                if (firebreakState[x][y] == BLOCK_PENDING && --firebreakTimer[x][y] <= 0) {
                    firebreakState[x][y] = BLOCK_ACTIVE;
                    clearCellHeatAndFire(x, y);
                } else if (firebreakState[x][y] == BLOCK_ACTIVE) {
                    clearCellHeatAndFire(x, y);
                }

                if (firefighterState[x][y] == BLOCK_PENDING && --firefighterTimer[x][y] <= 0) {
                    firefighterState[x][y] = BLOCK_ACTIVE;
                    firefighterTimer[x][y] = 0;
                } else if (firefighterState[x][y] == BLOCK_ACTIVE) {
                    outgoingHeat[x][y] = 0.0;
                }

                if (truckState[x][y] == BLOCK_PENDING && --truckTimer[x][y] <= 0) {
                    truckState[x][y] = BLOCK_ACTIVE;
                    truckTimer[x][y] = TRUCK_DURATION_TICKS;
                } else if (truckState[x][y] == BLOCK_ACTIVE) {
                    truckTimer[x][y]--;
                    coolCellBy(x, y, TRUCK_HEAT_COOL_PER_TICK_KJ);
                    if (truckTimer[x][y] <= 0) {
                        truckState[x][y] = BLOCK_NONE;
                        truckTimer[x][y] = 0;
                    }
                }
            }
        }
    }

    private void applyTool(int x, int y) {
        switch (selectedTool) {
            case TOOL_FIREBREAK:
                deployFirebreak(x, y);
                break;
            case TOOL_FIREFIGHTER:
                deployFirefighter(x, y);
                break;
            case TOOL_TRUCK:
                deployTruck(x, y);
                break;
            case TOOL_HELI:
                coolArea(x, y, HELI_DROP_WIDTH, HELI_DROP_HEIGHT, HELI_COOLING_PER_CELL_KJ);
                break;
            case TOOL_PLANE:
                coolArea(x, y, PLANE_DROP_WIDTH, PLANE_DROP_HEIGHT, PLANE_COOLING_PER_CELL_KJ);
                break;
            default:
                ignite(x, y);
                break;
        }
    }

    private void ignite(int x, int y) {
        if (!inside(x, y) || state[x][y] == STEM_BURNING || state[x][y] == BURNED || isFirebreakActive(x, y)) {
            return;
        }
        state[x][y] = LEAF_BURNING;
        age[x][y] = 0;
        accumulatedHeat[x][y] = Math.max(accumulatedHeat[x][y], leafThreshold());
        everBurned[x][y] = true;
    }

    private void deployFirebreak(int x, int y) {
        if (!inside(x, y)) {
            return;
        }
        if (clearSuppressionAtCell(x, y)) {
            return;
        }
        if (!canPlaceGroundSuppression(x, y) || state[x][y] == LEAF_BURNING || state[x][y] == STEM_BURNING
                || firebreakState[x][y] != BLOCK_NONE) {
            return;
        }
        firebreakState[x][y] = BLOCK_PENDING;
        firebreakTimer[x][y] = FIREBREAK_DEPLOY_TICKS;
    }

    private void deployFirefighter(int x, int y) {
        int[][] cells = {{x, y}, {x + 1, y}, {x, y + 1}};
        for (int[] c : cells) {
            if (!canPlaceGroundSuppression(c[0], c[1]) || firebreakState[c[0]][c[1]] != BLOCK_NONE
                    || truckState[c[0]][c[1]] != BLOCK_NONE || firefighterState[c[0]][c[1]] != BLOCK_NONE) {
                return;
            }
        }
        for (int[] c : cells) {
            firefighterState[c[0]][c[1]] = BLOCK_PENDING;
            firefighterTimer[c[0]][c[1]] = FIREFIGHTER_DEPLOY_TICKS;
        }
    }

    private void deployTruck(int x, int y) {
        for (int xx = x; xx < x + TRUCK_BLOCK_SIZE; xx++) {
            for (int yy = y; yy < y + TRUCK_BLOCK_SIZE; yy++) {
                if (!canPlaceGroundSuppression(xx, yy) || firebreakState[xx][yy] != BLOCK_NONE
                        || truckState[xx][yy] != BLOCK_NONE || firefighterState[xx][yy] != BLOCK_NONE) {
                    return;
                }
            }
        }
        for (int xx = x; xx < x + TRUCK_BLOCK_SIZE; xx++) {
            for (int yy = y; yy < y + TRUCK_BLOCK_SIZE; yy++) {
                truckState[xx][yy] = BLOCK_PENDING;
                truckTimer[xx][yy] = TRUCK_DEPLOY_TICKS;
            }
        }
    }

    private void coolArea(int centerX, int centerY, int width, int height, double cooling) {
        int left = centerX - width / 2;
        int top = centerY - height / 2;
        for (int x = left; x < left + width; x++) {
            for (int y = top; y < top + height; y++) {
                if (!inside(x, y)) {
                    continue;
                }
                coolCellBy(x, y, cooling);
            }
        }
    }

    private void coolCellBy(int x, int y, double cooling) {
        accumulatedHeat[x][y] = Math.max(0.0, accumulatedHeat[x][y] - cooling);
        if (accumulatedHeat[x][y] <= 0.0) {
            if (state[x][y] == LEAF_BURNING || state[x][y] == STEM_BURNING) {
                state[x][y] = EMPTY;
            }
            outgoingHeat[x][y] = 0.0;
            age[x][y] = 0;
        }
    }

    private boolean isFirebreakActive(int x, int y) {
        return firebreakState[x][y] == BLOCK_ACTIVE;
    }

    private boolean isFirefighterActive(int x, int y) {
        return firefighterState[x][y] == BLOCK_ACTIVE;
    }

    private boolean canPlaceGroundSuppression(int x, int y) {
        return inside(x, y) && maxSlopeFactorAt(x, y) < 2.8f;
    }

    private boolean clearSuppressionAtCell(int x, int y) {
        boolean removed = false;
        if (firebreakState[x][y] != BLOCK_NONE) {
            firebreakState[x][y] = BLOCK_NONE;
            firebreakTimer[x][y] = 0;
            removed = true;
        }
        if (truckState[x][y] != BLOCK_NONE) {
            truckState[x][y] = BLOCK_NONE;
            truckTimer[x][y] = 0;
            removed = true;
        }
        if (firefighterState[x][y] != BLOCK_NONE) {
            firefighterState[x][y] = BLOCK_NONE;
            firefighterTimer[x][y] = 0;
            removed = true;
        }
        return removed;
    }

    private void clearCellHeatAndFire(int x, int y) {
        state[x][y] = EMPTY;
        age[x][y] = 0;
        accumulatedHeat[x][y] = 0.0;
        outgoingHeat[x][y] = 0.0;
    }

    private void resetWorld() {
        elapsedTicks = 0;
        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                state[x][y] = EMPTY;
                age[x][y] = 0;
                accumulatedHeat[x][y] = 0.0;
                outgoingHeat[x][y] = 0.0;
                heatDelta[x][y] = 0.0;
                everBurned[x][y] = false;
                firebreakState[x][y] = BLOCK_NONE;
                firefighterState[x][y] = BLOCK_NONE;
                truckState[x][y] = BLOCK_NONE;
                firebreakTimer[x][y] = 0;
                firefighterTimer[x][y] = 0;
                truckTimer[x][y] = 0;
            }
        }
    }

    private void clearFireOnly() {
        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                state[x][y] = EMPTY;
                age[x][y] = 0;
                accumulatedHeat[x][y] = 0.0;
                outgoingHeat[x][y] = 0.0;
                heatDelta[x][y] = 0.0;
                everBurned[x][y] = false;
            }
        }
        elapsedTicks = 0;
    }

    private void drawMap(Canvas canvas) {
        canvas.drawColor(Color.rgb(25, 30, 28));
        if (mapBitmap != null) {
            paint.setAlpha(255);
            paint.setStyle(Paint.Style.FILL);
            canvas.drawBitmap(mapBitmap, null, mapArea(), paint);
        }
    }

    private void drawCells(Canvas canvas) {
        RectF area = mapArea();
        float size = cellSize();
        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                cellDrawRect.set(area.left + x * size, area.top + y * size, area.left + (x + 1) * size, area.top + (y + 1) * size);
                int cellState = state[x][y];
                if (cellState != EMPTY || accumulatedHeat[x][y] > 0.0) {
                    paint.setStyle(Paint.Style.FILL);
                    paint.setAlpha(230);
                    paint.setColor(cellColor(x, y));
                    canvas.drawRect(cellDrawRect, paint);
                }
                drawDeployment(canvas, cellDrawRect, firebreakState[x][y], FIREBREAK_PENDING_TINT, FIREBREAK_ACTIVE_BLACK);
                drawDeployment(canvas, cellDrawRect, firefighterState[x][y], FIREFIGHTER_PENDING_PURPLE, FIREFIGHTER_ACTIVE_PURPLE);
                drawDeployment(canvas, cellDrawRect, truckState[x][y], Color.rgb(90, 200, 90), TRUCK_ACTIVE_GREEN);
                if (showSlopeBorders) {
                    drawSlopeBorder(canvas, cellDrawRect, x, y);
                }
            }
        }
        paint.setAlpha(255);
    }

    private void drawDeployment(Canvas canvas, RectF rect, int blockState, int pendingColor, int activeColor) {
        if (blockState == BLOCK_NONE) {
            return;
        }
        paint.setStyle(Paint.Style.FILL);
        paint.setAlpha(blockState == BLOCK_PENDING ? 145 : 230);
        paint.setColor(blockState == BLOCK_PENDING ? pendingColor : activeColor);
        canvas.drawRect(rect, paint);
        paint.setAlpha(255);
    }

    private void drawSlopeBorder(Canvas canvas, RectF rect, int x, int y) {
        float maxSlope = maxSlopeFactorAt(x, y);
        int color = maxSlope > 2.5f ? SLOPE_BORDER_30 : maxSlope > 1.7f ? SLOPE_BORDER_20 : maxSlope > 1.1f ? SLOPE_BORDER_10 : 0;
        if (color == 0) {
            return;
        }
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Math.max(1f, cellSize() * 0.08f));
        paint.setColor(color);
        canvas.drawRect(rect, paint);
    }

    private float maxSlopeFactorAt(int x, int y) {
        float maxSlope = 1f;
        for (int d = 0; d < DIRS; d++) {
            maxSlope = Math.max(maxSlope, slopeFactor[y][x][d]);
        }
        return maxSlope;
    }

    private int cellColor(int x, int y) {
        if (state[x][y] == STEM_BURNING) {
            return STEM_FIRE_RED;
        }
        if (state[x][y] == BURNED) {
            return LEAF_BURNED_BROWN;
        }
        if (state[x][y] == EMPTY) {
            return preHeatColor(x, y);
        }
        int index = Math.max(0, Math.min(LEAF_FIRE_ORANGE_PALETTE.length - 1, age[x][y] / 3));
        return LEAF_FIRE_ORANGE_PALETTE[index];
    }

    private int preHeatColor(int x, int y) {
        double ratio = Math.max(0.0, Math.min(1.0, accumulatedHeat[x][y] / Math.max(1.0, leafThreshold())));
        if (ratio >= 0.85) {
            return PRE_HEAT_YELLOW;
        }
        int alphaRed = 255;
        int green = (int) (252 - 56 * ratio);
        int blue = (int) (220 - 140 * ratio);
        return Color.rgb(alphaRed, Math.max(160, green), Math.max(80, blue));
    }

    private void drawToolPreview(Canvas canvas) {
        int[] cell = cellFromPoint(lastTouchX(), lastTouchY(), false);
        if (cell == null || selectedTool == TOOL_IGNITE) {
            return;
        }
        RectF area = mapArea();
        float size = cellSize();
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Math.max(1f, size * 0.12f));
        paint.setColor(selectedTool == TOOL_FIREBREAK ? FIREBREAK_ACTIVE_BLACK : selectedTool == TOOL_FIREFIGHTER ? FIREFIGHTER_ACTIVE_PURPLE : selectedTool == TOOL_TRUCK ? TRUCK_ACTIVE_GREEN : AERIAL_PREVIEW_SKY_BLUE);
        RectF r = toolBounds(cell[0], cell[1], size, area);
        if (r != null) {
            canvas.drawRect(r, paint);
        }
    }

    private RectF toolBounds(int x, int y, float size, RectF area) {
        int width = 1;
        int height = 1;
        int left = x;
        int top = y;
        if (selectedTool == TOOL_TRUCK) {
            width = TRUCK_BLOCK_SIZE;
            height = TRUCK_BLOCK_SIZE;
        } else if (selectedTool == TOOL_HELI) {
            width = HELI_DROP_WIDTH;
            height = HELI_DROP_HEIGHT;
            left = x - width / 2;
            top = y - height / 2;
        } else if (selectedTool == TOOL_PLANE) {
            width = PLANE_DROP_WIDTH;
            height = PLANE_DROP_HEIGHT;
            left = x - width / 2;
            top = y - height / 2;
        }
        return new RectF(area.left + left * size, area.top + top * size, area.left + (left + width) * size, area.top + (top + height) * size);
    }

    private float previewX = -1;
    private float previewY = -1;

    private float lastTouchX() {
        return previewX;
    }

    private float lastTouchY() {
        return previewY;
    }

    private void drawChrome(Canvas canvas) {
        buttons.clear();
        portraitButtons.clear();
        if (isPortrait()) {
            drawPortraitTopBar(canvas);
            drawPortraitBottomControls(canvas);
        }
        if (!sideVisible()) {
            drawMenuButton(canvas);
        }
        if (sideVisible()) {
            drawSidebar(canvas);
        }
    }

    private void drawPortraitTopBar(Canvas canvas) {
        float margin = dp(10);
        float top = dp(10);
        float panelH = dp(104);
        RectF panel = new RectF(margin, top, getWidth() - margin, top + panelH);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(45, 45, 45));
        paint.setAlpha(230);
        canvas.drawRoundRect(panel, dp(6), dp(6), paint);
        paint.setAlpha(255);

        float statusX = panel.left + dp(12);
        float legendX = panel.left + panel.width() * 0.64f;
        drawStatusBlock(canvas, statusX, panel.top + dp(20), 11, true);
        drawCompactLegend(canvas, legendX, panel.top + dp(20), 11);
    }

    private void drawPortraitBottomControls(Canvas canvas) {
        float margin = dp(10);
        float gap = dp(6);
        float bottomInset = dp(18);
        float buttonH = dp(42);
        float toolH = dp(38);
        float panelH = buttonH + toolH * 2 + gap * 3 + dp(16);
        float top = getHeight() - panelH - bottomInset;
        RectF panel = new RectF(margin, top, getWidth() - margin, getHeight() - bottomInset);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(45, 45, 45));
        paint.setAlpha(232);
        canvas.drawRoundRect(panel, dp(6), dp(6), paint);
        paint.setAlpha(255);

        float x = panel.left + dp(8);
        float y = panel.top + dp(8);
        float contentW = panel.width() - dp(16);
        float smallW = (contentW - gap) / 2f;

        RectF run = new RectF(x, y, x + smallW, y + buttonH);
        RectF clear = new RectF(x + smallW + gap, y, x + contentW, y + buttonH);
        drawButton(canvas, run, running ? "Pause" : "Run", running, 12);
        drawButton(canvas, clear, "Clear", false, 12);
        portraitButtons.add(new Button(run, () -> running = !running));
        portraitButtons.add(new Button(clear, this::clearFireOnly));

        y += buttonH + gap;
        float toolW = (contentW - gap * 2) / 3f;
        drawPortraitToolButton(canvas, x, y, toolW, toolH, "Ignite", TOOL_IGNITE);
        drawPortraitToolButton(canvas, x + toolW + gap, y, toolW, toolH, "Firefighter", TOOL_FIREFIGHTER);
        drawPortraitToolButton(canvas, x + (toolW + gap) * 2, y, toolW, toolH, "Firebreak", TOOL_FIREBREAK);
        y += toolH + gap;
        drawPortraitToolButton(canvas, x, y, toolW, toolH, "Truck", TOOL_TRUCK);
        drawPortraitToolButton(canvas, x + toolW + gap, y, toolW, toolH, "Heli", TOOL_HELI);
        drawPortraitToolButton(canvas, x + (toolW + gap) * 2, y, toolW, toolH, "Plane", TOOL_PLANE);
    }

    private void drawPortraitToolButton(Canvas canvas, float x, float y, float w, float h, String label, int tool) {
        RectF rect = new RectF(x, y, x + w, y + h);
        drawButton(canvas, rect, label, selectedTool == tool, 10);
        portraitButtons.add(new Button(rect, () -> selectedTool = tool));
    }

    private void drawCompactSwatch(Canvas canvas, float x, float y, int color, String label) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(color);
        canvas.drawRect(x, y - dp(10), x + dp(11), y + dp(1), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(1);
        paint.setColor(WHITE);
        canvas.drawRect(x, y - dp(10), x + dp(11), y + dp(1), paint);
        drawText(canvas, label, x + dp(16), y, TEXT_MUTED, 9, false);
    }

    private void drawMenuButton(Canvas canvas) {
        updateMenuButtonBounds();
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(SIDEBAR_GRAY);
        canvas.drawRoundRect(menuButton, dp(6), dp(6), paint);
        paint.setColor(WHITE);
        paint.setStrokeWidth(dp(2));
        for (int i = 0; i < 3; i++) {
            float y = menuButton.top + dp(13 + i * 9);
            canvas.drawLine(menuButton.left + dp(11), y, menuButton.right - dp(11), y, paint);
        }
    }

    private void drawSidebar(Canvas canvas) {
        RectF side = sidebarArea();
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(SIDEBAR_GRAY);
        canvas.drawRect(side, paint);

        canvas.save();
        canvas.clipRect(side);
        canvas.translate(0, -sidebarScrollY);

        float x = side.left + dp(14);
        float y = dp(24);
        float contentW = side.width() - dp(28);
        if (drawerOpen && isPortrait()) {
            y = dp(66);
        } else {
            closeButton.setEmpty();
        }

        float gap = dp(6);

        if (!isPortrait()) {
            drawStatusBlock(canvas, x, y, 12, false);
            drawCompactLegend(canvas, x + contentW * 0.55f, y, 12);
            y += dp(104);
            y = drawSidebarRunClearAndTools(canvas, x, y, contentW);
            y += dp(12);
        }

        drawText(canvas, "Fire Spread Simulation", x, y, WHITE, 16, true);
        y += dp(20);
        drawText(canvas, preset.label + "  " + gridW + " x " + gridH, x, y, TEXT_MUTED, 12, false);
        y += dp(24);

        drawText(canvas, "Maps", x, y, WHITE, 13, true);
        y += dp(8);
        float mapButtonW = (contentW - gap * 2) / 3f;
        for (int i = 0; i < presets.length; i++) {
            MapPreset candidate = presets[i];
            RectF rect = new RectF(x + i * (mapButtonW + gap), y, x + i * (mapButtonW + gap) + mapButtonW, y + dp(32));
            drawButton(canvas, rect, candidate.label, candidate == preset, 11);
            buttons.add(new Button(rect, () -> loadPreset(getContext().getAssets(), candidate)));
        }
        y += dp(48);

        drawText(canvas, "Humidity: " + humidityPercent + "%", x, y, WHITE, 13, false);
        y += dp(12);
        humiditySlider.set(x, y, x + contentW, y + dp(28));
        drawSlider(canvas, humiditySlider);
        y += dp(38);
        drawText(canvas, "Leaf threshold: " + formatKj(leafThreshold()), x, y, TEXT_MUTED, 11, false);
        y += dp(18);

        drawText(canvas, "Wind speed: " + windSpeedKmh + " km/h", x, y, WHITE, 13, false);
        y += dp(12);
        windSpeedSlider.set(x, y, x + contentW, y + dp(28));
        drawSlider(canvas, windSpeedSlider, windSpeedKmh / 100f);
        y += dp(42);

        drawText(canvas, "Wind direction: " + WIND_NAMES[windDirIndex], x, y, WHITE, 13, false);
        y += dp(8);
        float windButtonW = (contentW - gap * 3) / 4f;
        for (int i = 0; i < WIND_NAMES.length; i++) {
            int row = i / 4;
            int col = i % 4;
            RectF rect = new RectF(x + col * (windButtonW + gap), y + row * dp(34), x + col * (windButtonW + gap) + windButtonW, y + row * dp(34) + dp(28));
            drawButton(canvas, rect, WIND_NAMES[i], windDirIndex == i, 11);
            final int dir = WIND_DIR_INDEX[i];
            buttons.add(new Button(rect, () -> windDirIndex = dir));
        }
        y += dp(82);

        RectF speedButton = new RectF(x, y, x + contentW, y + dp(34));
        drawButton(canvas, speedButton, fastMode ? "Speed: 5x" : "Speed: 1x", fastMode, 12);
        buttons.add(new Button(speedButton, () -> fastMode = !fastMode));
        y += dp(42);

        RectF slopeButton = new RectF(x, y, x + contentW * 0.48f, y + dp(34));
        RectF resetButton = new RectF(x + contentW * 0.52f, y, x + contentW, y + dp(34));
        drawButton(canvas, slopeButton, "Slope borders", showSlopeBorders, 11);
        drawButton(canvas, resetButton, "Reset world", false, 11);
        buttons.add(new Button(slopeButton, () -> showSlopeBorders = !showSlopeBorders));
        buttons.add(new Button(resetButton, this::resetWorld));
        y += dp(50);

        if (!isPortrait()) {
            y += dp(12);
        }

        canvas.restore();
        if (drawerOpen && isPortrait()) {
            updateCloseButtonBounds();
            drawButton(canvas, closeButton, "X", false, 12);
        }
        drawScrollThumb(canvas, side);
    }

    private float drawSidebarRunClearAndTools(Canvas canvas, float x, float y, float contentW) {
        float gap = dp(6);
        float buttonH = dp(34);
        float halfW = (contentW - gap) / 2f;
        RectF run = new RectF(x, y, x + halfW, y + buttonH);
        RectF clear = new RectF(x + halfW + gap, y, x + contentW, y + buttonH);
        drawButton(canvas, run, running ? "Pause" : "Run", running, 12);
        drawButton(canvas, clear, "Clear", false, 12);
        buttons.add(new Button(run, () -> running = !running));
        buttons.add(new Button(clear, this::clearFireOnly));

        y += buttonH + gap;
        float toolW = (contentW - gap * 2) / 3f;
        drawSidebarToolButton(canvas, x, y, toolW, buttonH, "Ignite", TOOL_IGNITE);
        drawSidebarToolButton(canvas, x + toolW + gap, y, toolW, buttonH, "Firefighter", TOOL_FIREFIGHTER);
        drawSidebarToolButton(canvas, x + (toolW + gap) * 2, y, toolW, buttonH, "Firebreak", TOOL_FIREBREAK);
        y += buttonH + gap;
        drawSidebarToolButton(canvas, x, y, toolW, buttonH, "Truck", TOOL_TRUCK);
        drawSidebarToolButton(canvas, x + toolW + gap, y, toolW, buttonH, "Heli", TOOL_HELI);
        drawSidebarToolButton(canvas, x + (toolW + gap) * 2, y, toolW, buttonH, "Plane", TOOL_PLANE);
        return y + buttonH + gap;
    }

    private void drawSidebarToolButton(Canvas canvas, float x, float y, float w, float h, String label, int tool) {
        RectF rect = new RectF(x, y, x + w, y + h);
        drawButton(canvas, rect, label, selectedTool == tool, 10);
        buttons.add(new Button(rect, () -> selectedTool = tool));
    }

    private void drawStatusBlock(Canvas canvas, float x, float y, int sp, boolean compact) {
        drawText(canvas, running ? "Status: running" : "Status: paused", x, y, running ? Color.rgb(120, 240, 120) : TEXT_MUTED, sp, false);
        y += compact ? dp(16) : dp(18);
        drawText(canvas, compact ? "Ticks: " + elapsedTicks : "Elapsed ticks: " + elapsedTicks, x, y, WHITE, sp, false);
        y += compact ? dp(16) : dp(18);
        if (compact) {
            drawText(canvas, "Leaf: " + countState(LEAF_BURNING) + "  Stem: " + countState(STEM_BURNING), x, y, WHITE, sp - 1, false);
            y += dp(16);
            drawText(canvas, "Burned: " + countEverBurned(), x, y, LEAF_BURNED_BROWN, sp - 1, false);
            return;
        }
        drawText(canvas, "Leaf: " + countState(LEAF_BURNING) + " / " + formatArea(countState(LEAF_BURNING)), x, y, LEAF_FIRE_ORANGE_PALETTE[2], sp, false);
        y += dp(18);
        drawText(canvas, "Stem: " + countState(STEM_BURNING) + "  Burned: " + countEverBurned(), x, y, STEM_FIRE_RED, sp, false);
    }

    private void drawCompactLegend(Canvas canvas, float x, float y, int sp) {
        drawText(canvas, "Legend", x, y, WHITE, sp, true);
        y += dp(18);
        drawCompactSwatch(canvas, x, y, PRE_HEAT_YELLOW, "Heat");
        y += dp(16);
        drawCompactSwatch(canvas, x, y, LEAF_FIRE_ORANGE_PALETTE[2], "Leaf");
        y += dp(16);
        drawCompactSwatch(canvas, x, y, STEM_FIRE_RED, "Stem");
        y += dp(16);
        drawCompactSwatch(canvas, x, y, LEAF_BURNED_BROWN, "Burned");
    }

    private float drawToolButton(Canvas canvas, float x, float y, float contentW, String label, int tool) {
        RectF rect = new RectF(x, y, x + contentW, y + dp(30));
        drawButton(canvas, rect, label, selectedTool == tool, 12);
        buttons.add(new Button(rect, () -> selectedTool = tool));
        return y + dp(34);
    }

    private void drawButton(Canvas canvas, RectF rect, String label, boolean selected, int sp) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(selected ? BUTTON_SELECTED_COLOR : BUTTON_COLOR);
        canvas.drawRoundRect(rect, dp(4), dp(4), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(1);
        paint.setColor(Color.rgb(130, 130, 130));
        canvas.drawRoundRect(rect, dp(4), dp(4), paint);
        paint.setStyle(Paint.Style.FILL);
        paint.setTextAlign(Paint.Align.CENTER);
        drawText(canvas, label, rect.centerX(), rect.centerY() + textCenterOffset(sp), WHITE, sp, false);
        paint.setTextAlign(Paint.Align.LEFT);
    }

    private void drawSlider(Canvas canvas, RectF rect) {
        drawSlider(canvas, rect, humidityPercent / 100f);
    }

    private void drawSlider(Canvas canvas, RectF rect, float ratio) {
        float trackY = rect.centerY();
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(3));
        paint.setColor(Color.rgb(120, 120, 120));
        canvas.drawLine(rect.left, trackY, rect.right, trackY, paint);
        float knobX = rect.left + rect.width() * Math.max(0f, Math.min(1f, ratio));
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(BUTTON_SELECTED_COLOR);
        canvas.drawCircle(knobX, trackY, dp(8), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(1);
        paint.setColor(WHITE);
        canvas.drawCircle(knobX, trackY, dp(8), paint);
    }

    private void drawSwatch(Canvas canvas, float x, float y, int color, String label) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(color);
        canvas.drawRect(x, y - dp(12), x + dp(13), y + dp(1), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(1);
        paint.setColor(WHITE);
        canvas.drawRect(x, y - dp(12), x + dp(13), y + dp(1), paint);
        drawText(canvas, label, x + dp(20), y, TEXT_MUTED, 11, false);
    }

    private void drawText(Canvas canvas, String text, float x, float y, int color, int sp, boolean bold) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(color);
        paint.setTextSize(sp * getResources().getDisplayMetrics().scaledDensity);
        paint.setFakeBoldText(bold);
        canvas.drawText(text, x, y, paint);
        paint.setFakeBoldText(false);
    }

    private float textCenterOffset(int sp) {
        return sp * getResources().getDisplayMetrics().scaledDensity * 0.35f;
    }

    private void setHumidityFromTouch(float x) {
        float ratio = (x - humiditySlider.left) / Math.max(1f, humiditySlider.width());
        humidityPercent = Math.max(0, Math.min(100, Math.round(ratio * 20) * 5));
    }

    private void setWindSpeedFromTouch(float x) {
        float ratio = (x - windSpeedSlider.left) / Math.max(1f, windSpeedSlider.width());
        windSpeedKmh = Math.max(0, Math.min(100, Math.round(ratio * 100)));
    }

    private void drawScrollThumb(Canvas canvas, RectF side) {
        float maxScroll = maxSidebarScroll();
        if (maxScroll <= 0f) {
            return;
        }
        float thumbHeight = Math.max(dp(48), side.height() * side.height() / (side.height() + maxScroll));
        float thumbTop = side.top + (side.height() - thumbHeight) * (sidebarScrollY / maxScroll);
        RectF thumb = new RectF(side.right - dp(5), thumbTop, side.right - dp(2), thumbTop + thumbHeight);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(150, 150, 150));
        paint.setAlpha(180);
        canvas.drawRoundRect(thumb, dp(2), dp(2), paint);
        paint.setAlpha(255);
    }

    private float maxSidebarScroll() {
        float contentHeight = dp(940);
        return Math.max(0f, contentHeight - Math.max(1f, getHeight()));
    }

    private double leafThreshold() {
        int index = Math.max(0, Math.min(20, Math.round(humidityPercent / 5f)));
        double moisture = LEAF_MOISTURE_BY_HUMIDITY[index];
        return LEAF_FUEL_MASS_PER_CELL * (BASE_IGNITION_KJ_PER_KG + WATER_EXTRA_KJ_PER_KG * moisture);
    }

    private int countState(int targetState) {
        int count = 0;
        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                if (state[x][y] == targetState) {
                    count++;
                }
            }
        }
        return count;
    }

    private String formatArea(int cells) {
        double km2 = cells * CELL_AREA_M2 / 1_000_000.0;
        return String.format(Locale.US, "%.4f km2", km2);
    }

    private String formatKj(double value) {
        return String.format(Locale.US, "%,.0f kJ", value);
    }

    private int countEverBurned() {
        int count = 0;
        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                if (everBurned[x][y]) {
                    count++;
                }
            }
        }
        return count;
    }

    private int[] cellFromPoint(float x, float y) {
        return cellFromPoint(x, y, true);
    }

    private int[] cellFromPoint(float x, float y, boolean updatePreview) {
        if (updatePreview) {
            previewX = x;
            previewY = y;
        }
        RectF area = mapArea();
        if (!area.contains(x, y) || isPortraitChromeArea(x, y)) {
            return null;
        }
        float size = cellSize();
        int cx = Math.max(0, Math.min(gridW - 1, (int) ((x - area.left) / size)));
        int cy = Math.max(0, Math.min(gridH - 1, (int) ((y - area.top) / size)));
        return new int[]{cx, cy};
    }

    private boolean inside(int x, int y) {
        return x >= 0 && x < gridW && y >= 0 && y < gridH;
    }

    private boolean isPortraitChromeArea(float x, float y) {
        if (!isPortrait()) {
            return false;
        }
        return y < dp(126) || y > getHeight() - dp(174);
    }

    private boolean sideVisible() {
        return !isPortrait() || drawerOpen;
    }

    private boolean isPortrait() {
        return getHeight() > getWidth();
    }

    private RectF mapArea() {
        RectF base = baseMapArea();
        float width = base.width() * zoomScale;
        float height = base.height() * zoomScale;
        float centerX = base.centerX() + zoomOffsetX;
        float centerY = base.centerY() + zoomOffsetY;
        return new RectF(centerX - width * 0.5f, centerY - height * 0.5f, centerX + width * 0.5f, centerY + height * 0.5f);
    }

    private RectF baseMapArea() {
        float availableWidth = sideVisible() && !isPortrait() ? getWidth() - sidebarWidth() : getWidth();
        float availableHeight = getHeight();
        float size = Math.min(availableWidth / gridW, availableHeight / gridH);
        float width = gridW * size;
        float height = gridH * size;
        float left = (availableWidth - width) * 0.5f;
        float top = (availableHeight - height) * 0.5f;
        return new RectF(left, top, left + width, top + height);
    }

    private float cellSize() {
        RectF area = mapArea();
        return Math.min(area.width() / gridW, area.height() / gridH);
    }

    private RectF sidebarArea() {
        if (isPortrait()) {
            float width = Math.min(getWidth() * 0.92f, dp(360));
            return new RectF(getWidth() - width, 0, getWidth(), getHeight());
        }
        return new RectF(getWidth() - sidebarWidth(), 0, getWidth(), getHeight());
    }

    private float sidebarWidth() {
        return Math.max(dp(270), Math.min(dp(330), getWidth() * 0.30f));
    }

    private void updateMenuButtonBounds() {
        menuButton.set(getWidth() - dp(54), dp(10), getWidth() - dp(10), dp(54));
    }

    private void updateCloseButtonBounds() {
        if (drawerOpen && isPortrait()) {
            RectF side = sidebarArea();
            closeButton.set(side.right - dp(46), dp(10), side.right - dp(12), dp(44));
        } else {
            closeButton.setEmpty();
        }
    }

    private boolean canStartMapGesture(MotionEvent event) {
        float focusX = pointerFocusX(event);
        float focusY = pointerFocusY(event);
        return !isPortraitChromeArea(focusX, focusY) && (!sideVisible() || !sidebarArea().contains(focusX, focusY));
    }

    private float pointerDistance(MotionEvent event) {
        if (event.getPointerCount() < 2) {
            return 0f;
        }
        float dx = event.getX(0) - event.getX(1);
        float dy = event.getY(0) - event.getY(1);
        return (float) Math.sqrt(dx * dx + dy * dy);
    }

    private float pointerFocusX(MotionEvent event) {
        float total = 0f;
        for (int i = 0; i < event.getPointerCount(); i++) {
            total += event.getX(i);
        }
        return total / Math.max(1, event.getPointerCount());
    }

    private float pointerFocusY(MotionEvent event) {
        float total = 0f;
        for (int i = 0; i < event.getPointerCount(); i++) {
            total += event.getY(i);
        }
        return total / Math.max(1, event.getPointerCount());
    }

    private void updateZoomFromPinch(MotionEvent event) {
        float distance = pointerDistance(event);
        if (pinchStartDistance <= 0f || distance <= 0f) {
            return;
        }
        RectF base = baseMapArea();
        float oldScale = zoomScale;
        float nextScale = Math.max(1f, Math.min(4f, pinchStartScale * distance / pinchStartDistance));
        if (Math.abs(nextScale - oldScale) < 0.001f) {
            return;
        }

        float mapX = (pinchFocusX - (base.centerX() + pinchStartOffsetX)) / Math.max(1f, base.width() * pinchStartScale);
        float mapY = (pinchFocusY - (base.centerY() + pinchStartOffsetY)) / Math.max(1f, base.height() * pinchStartScale);
        zoomScale = nextScale;
        zoomOffsetX = pinchFocusX - base.centerX() - mapX * base.width() * zoomScale;
        zoomOffsetY = pinchFocusY - base.centerY() - mapY * base.height() * zoomScale;
        clampZoomOffset();
    }

    private void clampZoomOffset() {
        if (zoomScale <= 1f) {
            zoomScale = 1f;
            zoomOffsetX = 0f;
            zoomOffsetY = 0f;
            return;
        }
        RectF base = baseMapArea();
        float extraX = Math.max(0f, base.width() * (zoomScale - 1f) * 0.5f);
        float extraY = Math.max(0f, base.height() * (zoomScale - 1f) * 0.5f);
        zoomOffsetX = Math.max(-extraX, Math.min(extraX, zoomOffsetX));
        zoomOffsetY = Math.max(-extraY, Math.min(extraY, zoomOffsetY));
    }

    private void resetZoom() {
        zoomScale = 1f;
        zoomOffsetX = 0f;
        zoomOffsetY = 0f;
        pinchingMap = false;
        draggingMap = false;
        pendingMapTap = false;
        mapTouchMoved = false;
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }

    private static class MapPreset {
        final String id;
        final String label;
        final String previewAsset;
        final String slopeAsset;
        final int gridW;
        final int gridH;

        MapPreset(String id, String label, String previewAsset, String slopeAsset, int gridW, int gridH) {
            this.id = id;
            this.label = label;
            this.previewAsset = previewAsset;
            this.slopeAsset = slopeAsset;
            this.gridW = gridW;
            this.gridH = gridH;
        }
    }

    private static class NpyData {
        final int width;
        final int height;
        final int dirs;
        final float[][][] values;

        NpyData(int width, int height, int dirs, float[][][] values) {
            this.width = width;
            this.height = height;
            this.dirs = dirs;
            this.values = values;
        }
    }

    private static class Button {
        final RectF rect;
        final Runnable action;

        Button(RectF rect, Runnable action) {
            this.rect = new RectF(rect);
            this.action = action;
        }
    }
}
