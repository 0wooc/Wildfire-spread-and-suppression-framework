# Wildfire Spread and Suppression Framework

A cell-based wildfire simulator for exploring fire spread and suppression strategies.

I wanted to build something that would help people understand how wildfires spread, why suppression is difficult, and why prevention matters.
I started a school project to develop an interactive simulator that could eventually run on mobile devices.
The challenge was to represent a large, complex natural process with limited computing resources.
Hope that this can be useful to understand about wildfires. 

## Installation

The Python version requires Python 3.10 or later.

From the repository root:

```sh
python -m pip install -r desktop/requirements.txt
python desktop/v9.4_firespread_firefighter.py
```

The earlier v9.3 implementation is also available in `desktop/`.

## Features

- Cell-based heat transfer and combustion
- Wind speed, wind direction, and humidity
- Terrain-dependent spread using elevation and slope data
- Firebreaks, aircraft, helicopters, fire engines, and firefighters
- Burned-area tracking and CSV output
- Terrain preprocessing and map generation
- Native Android implementation

Available controls and suppression tools vary by version.

Heat transferred between cells is accumulated separately and applied after each simulation step. This prevents newly received heat from propagating repeatedly within the same step simply because of cell traversal order.

## Android

Open `android_bulam_fire` in Android Studio with Android SDK 36 and a JDK compatible with the project's Gradle configuration.

To build a debug APK:

```sh
cd android_bulam_fire
./gradlew assembleDebug
```

On Windows, use `gradlew.bat assembleDebug`.

The APK is written to `app/build/outputs/apk/debug/`. Release signing credentials are not included.

## Touchscreen Version

```sh
python -m pip install -r exhibit/requirements.txt
python exhibit/exhibit_v2.py
```

This version uses a 1080 × 1920 portrait layout. Running from source opens a scaled preview window.

On Windows, run `exhibit/build_exhibit.bat` to create a fullscreen executable. The first build requires Python and an internet connection. Maps, images, and fonts are bundled into the executable.

## Documentation

- [Model and version notes](docs/MODEL.md)
- [Data sources and asset notices](docs/ASSETS.md)
- [Map generation](desktop/map_builder.py)

To check the Android implementation's constants, map assets, and reference scenarios:

```sh
python android_bulam_fire/verification/verify_android_fidelity.py
```

This project is intended for education and experimentation, not operational wildfire forecasting.
