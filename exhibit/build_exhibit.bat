@echo off
setlocal
cd /d "%~dp0.."

if exist "wildfire_exhibit_v2.exe" goto :run

py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 (
    set "EXHIBIT_PYTHON=py -3"
    goto :build
)
python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 (
    set "EXHIBIT_PYTHON=python"
    goto :build
)
echo Python 3.10 or newer is required to create the EXE.
echo Install Python from https://www.python.org/downloads/windows/
echo Then run this file again.
goto :error

:build
echo Creating the exhibit EXE. Internet access is required for the first build.
%EXHIBIT_PYTHON% -m venv ".build_env"
if errorlevel 1 goto :error
".build_env\Scripts\python.exe" -m pip install --disable-pip-version-check pygame==2.6.1 pyinstaller
if errorlevel 1 goto :error
".build_env\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name wildfire_exhibit_v2 --distpath "." --workpath ".build" --specpath ".build" --add-data "maps;maps" --add-data "assets;assets" exhibit/exhibit_v2.py
if errorlevel 1 goto :error
if not exist "wildfire_exhibit_v2.exe" goto :error

:run
start "" "wildfire_exhibit_v2.exe"
exit /b 0

:error
echo Build did not complete. Please keep this window open to view the error.
pause
exit /b 1
