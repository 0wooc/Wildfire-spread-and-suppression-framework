package com.genius.firespread;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.res.AssetManager;
import android.os.Bundle;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Locale;

public class FireEngineInstrumentation extends Instrumentation {
    private static final String[] MAPS = {"flat_square", "bulam", "california"};
    private static final String[] WIND_NAMES = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"};

    private static final Scenario[] SCENARIOS = {
            new Scenario("flat_square", 0, 0, "N", 60, 0, 0, 1),
            new Scenario("flat_square", 0, 10, "E", 60, 56, 9, 66),
            new Scenario("flat_square", 50, 10, "E", 60, 19, 2, 24),
            new Scenario("flat_square", 0, 20, "SW", 60, 395, 426, 821),
            new Scenario("flat_square", 100, 10, "NW", 60, 7, 1, 9),
            new Scenario("bulam", 0, 0, "N", 60, 0, 0, 1),
            new Scenario("bulam", 0, 10, "E", 60, 91, 22, 113),
            new Scenario("bulam", 50, 10, "E", 60, 26, 7, 36),
            new Scenario("bulam", 0, 20, "SW", 60, 484, 548, 1032),
            new Scenario("bulam", 100, 10, "NW", 60, 7, 2, 9),
            new Scenario("california", 0, 0, "N", 60, 0, 0, 1),
            new Scenario("california", 0, 10, "E", 60, 104, 49, 153),
            new Scenario("california", 50, 10, "E", 60, 48, 21, 72),
            new Scenario("california", 0, 20, "SW", 60, 550, 707, 1257),
            new Scenario("california", 100, 10, "NW", 60, 19, 4, 25),
            new Scenario("flat_square", 0, 10, "E", "firebreak", 3, 0, 60, 54, 8, 63),
            new Scenario("flat_square", 0, 10, "E", "truck", 1, -1, 60, 38, 4, 43),
            new Scenario("flat_square", 0, 10, "E", "firefighter", 0, 0, 60, 0, 1, 1),
            new Scenario("flat_square", 0, 10, "E", "heli", 0, 0, 60, 0, 0, 1),
            new Scenario("flat_square", 0, 10, "E", "plane", 0, 0, 60, 0, 0, 1),
    };

    @Override
    public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        start();
    }

    @Override
    public void onStart() {
        Bundle result = new Bundle();
        try {
            String summary = runVerification();
            result.putString("summary", summary);
            finish(Activity.RESULT_OK, result);
        } catch (Throwable throwable) {
            result.putString("failure", stackTrace(throwable));
            finish(Activity.RESULT_CANCELED, result);
        }
    }

    private String runVerification() throws Exception {
        Context context = getTargetContext();
        FireView view = new FireView(context);
        Method loadPreset = FireView.class.getDeclaredMethod("loadPreset", AssetManager.class, mapPresetClass());
        Method ignite = FireView.class.getDeclaredMethod("ignite", int.class, int.class);
        Method applyTool = FireView.class.getDeclaredMethod("applyTool", int.class, int.class);
        Method updateFireOneTick = FireView.class.getDeclaredMethod("updateFireOneTick");
        loadPreset.setAccessible(true);
        ignite.setAccessible(true);
        applyTool.setAccessible(true);
        updateFireOneTick.setAccessible(true);

        StringBuilder summary = new StringBuilder();
        for (Scenario scenario : SCENARIOS) {
            Object preset = presetFor(view, scenario.mapId);
            loadPreset.invoke(view, context.getAssets(), preset);
            setInt(view, "humidityPercent", scenario.humidity);
            setInt(view, "windSpeedKmh", scenario.windSpeed);
            setInt(view, "windDirIndex", windIndex(scenario.windDir));

            int gridW = getInt(view, "gridW");
            int gridH = getInt(view, "gridH");
            ignite.invoke(view, gridW / 2, gridH / 2);
            if (scenario.toolName != null) {
                setInt(view, "selectedTool", toolId(scenario.toolName));
                applyTool.invoke(view, gridW / 2 + scenario.toolOffsetX, gridH / 2 + scenario.toolOffsetY);
            }
            for (int i = 0; i < scenario.ticks; i++) {
                updateFireOneTick.invoke(view);
            }

            Counts actual = count(view);
            if (actual.leaf != scenario.leaf || actual.stem != scenario.stem || actual.burned != scenario.burned) {
                throw new AssertionError(String.format(
                        Locale.US,
                        "%s h=%d wind=%d/%s expected leaf=%d stem=%d burned=%d, got leaf=%d stem=%d burned=%d",
                        scenario.mapId,
                        scenario.humidity,
                        scenario.windSpeed,
                        scenario.windDir,
                        scenario.leaf,
                        scenario.stem,
                        scenario.burned,
                        actual.leaf,
                        actual.stem,
                        actual.burned
                ));
            }
            summary.append(scenario.mapId)
                    .append(" h=").append(scenario.humidity)
                    .append(" wind=").append(scenario.windSpeed).append('/').append(scenario.windDir)
                    .append(scenario.toolName == null ? "" : " tool=" + scenario.toolName)
                    .append(" -> ").append(actual.leaf).append(',')
                    .append(actual.stem).append(',')
                    .append(actual.burned).append('\n');
        }
        verifySteepGroundSuppressionRejected(view, loadPreset, applyTool, context.getAssets());
        return summary.toString();
    }

    private void verifySteepGroundSuppressionRejected(FireView view, Method loadPreset, Method applyTool, AssetManager assets) throws Exception {
        loadPreset.invoke(view, assets, presetFor(view, "bulam"));
        float[][][] slopeFactor = (float[][][]) getField(view, "slopeFactor");
        int gridW = getInt(view, "gridW");
        int gridH = getInt(view, "gridH");
        int steepX = -1;
        int steepY = -1;
        for (int y = 0; y < gridH && steepX < 0; y++) {
            for (int x = 0; x < gridW; x++) {
                for (int d = 0; d < 8; d++) {
                    if (slopeFactor[y][x][d] >= 2.8f) {
                        steepX = x;
                        steepY = y;
                        break;
                    }
                }
                if (steepX >= 0) {
                    break;
                }
            }
        }
        if (steepX < 0) {
            throw new AssertionError("No steep Bulam cell found for placement rejection check");
        }
        setInt(view, "selectedTool", toolId("firebreak"));
        applyTool.invoke(view, steepX, steepY);
        int[][] firebreakState = (int[][]) getField(view, "firebreakState");
        if (firebreakState[steepX][steepY] != getStaticInt("BLOCK_NONE")) {
            throw new AssertionError("Firebreak was placed on a 30-degree-class steep cell");
        }
    }

    private Class<?> mapPresetClass() throws ClassNotFoundException {
        return Class.forName("com.genius.firespread.FireView$MapPreset");
    }

    private Object presetFor(FireView view, String mapId) throws Exception {
        Field presetsField = FireView.class.getDeclaredField("presets");
        presetsField.setAccessible(true);
        Object[] presets = (Object[]) presetsField.get(view);
        Field idField = mapPresetClass().getDeclaredField("id");
        idField.setAccessible(true);
        for (Object preset : presets) {
            if (mapId.equals(idField.get(preset))) {
                return preset;
            }
        }
        throw new AssertionError("Missing preset: " + mapId);
    }

    private Counts count(FireView view) throws Exception {
        int[][] state = (int[][]) getField(view, "state");
        boolean[][] everBurned = (boolean[][]) getField(view, "everBurned");
        int gridW = getInt(view, "gridW");
        int gridH = getInt(view, "gridH");
        int leafBurning = getStaticInt("LEAF_BURNING");
        int stemBurning = getStaticInt("STEM_BURNING");
        Counts counts = new Counts();
        for (int x = 0; x < gridW; x++) {
            for (int y = 0; y < gridH; y++) {
                if (state[x][y] == leafBurning) {
                    counts.leaf++;
                } else if (state[x][y] == stemBurning) {
                    counts.stem++;
                }
                if (everBurned[x][y]) {
                    counts.burned++;
                }
            }
        }
        return counts;
    }

    private int windIndex(String windName) {
        for (int i = 0; i < WIND_NAMES.length; i++) {
            if (WIND_NAMES[i].equals(windName)) {
                return i;
            }
        }
        throw new AssertionError("Unsupported wind: " + windName);
    }

    private int toolId(String toolName) throws Exception {
        if ("firebreak".equals(toolName)) {
            return getStaticInt("TOOL_FIREBREAK");
        }
        if ("truck".equals(toolName)) {
            return getStaticInt("TOOL_TRUCK");
        }
        if ("firefighter".equals(toolName)) {
            return getStaticInt("TOOL_FIREFIGHTER");
        }
        if ("heli".equals(toolName)) {
            return getStaticInt("TOOL_HELI");
        }
        if ("plane".equals(toolName)) {
            return getStaticInt("TOOL_PLANE");
        }
        throw new AssertionError("Unsupported tool: " + toolName);
    }

    private void setInt(FireView view, String fieldName, int value) throws Exception {
        Field field = FireView.class.getDeclaredField(fieldName);
        field.setAccessible(true);
        field.setInt(view, value);
    }

    private int getInt(FireView view, String fieldName) throws Exception {
        Field field = FireView.class.getDeclaredField(fieldName);
        field.setAccessible(true);
        return field.getInt(view);
    }

    private int getStaticInt(String fieldName) throws Exception {
        Field field = FireView.class.getDeclaredField(fieldName);
        field.setAccessible(true);
        return field.getInt(null);
    }

    private Object getField(FireView view, String fieldName) throws Exception {
        Field field = FireView.class.getDeclaredField(fieldName);
        field.setAccessible(true);
        return field.get(view);
    }

    private String stackTrace(Throwable throwable) {
        StringWriter writer = new StringWriter();
        throwable.printStackTrace(new PrintWriter(writer));
        return writer.toString();
    }

    private static class Counts {
        int leaf;
        int stem;
        int burned;
    }

    private static class Scenario {
        final String mapId;
        final int humidity;
        final int windSpeed;
        final String windDir;
        final String toolName;
        final int toolOffsetX;
        final int toolOffsetY;
        final int ticks;
        final int leaf;
        final int stem;
        final int burned;

        Scenario(String mapId, int humidity, int windSpeed, String windDir, int ticks, int leaf, int stem, int burned) {
            this(mapId, humidity, windSpeed, windDir, null, 0, 0, ticks, leaf, stem, burned);
        }

        Scenario(String mapId, int humidity, int windSpeed, String windDir, String toolName, int toolOffsetX, int toolOffsetY,
                 int ticks, int leaf, int stem, int burned) {
            this.mapId = mapId;
            this.humidity = humidity;
            this.windSpeed = windSpeed;
            this.windDir = windDir;
            this.toolName = toolName;
            this.toolOffsetX = toolOffsetX;
            this.toolOffsetY = toolOffsetY;
            this.ticks = ticks;
            this.leaf = leaf;
            this.stem = stem;
            this.burned = burned;
        }
    }
}
