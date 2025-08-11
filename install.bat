@echo off
set SCRIPT_DIR=%~dp0
set PYTHON_URL=https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/server.py
set SERVER_FILE=%SCRIPT_DIR%server.py

echo Checking for Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python not found in PATH. Attempting to install Python 3.11 via Winget...
    winget.exe install --id "Python.Python.3.11" --exact --source winget --accept-source-agreements --disable-interactivity --silent --accept-package-agreements --force
    if %errorlevel% neq 0 (
        echo Failed to install Python via Winget. Please install Python 3.x and add it to your PATH manually.
        echo https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo Python 3.11 installed successfully.
)

echo Installing/updating Python dependencies...
python -m pip install -r "%SCRIPT_DIR%requirements.txt" --upgrade --no-warn-script-location
if %errorlevel% neq 0 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
)

echo Fetching latest server.py...
powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%SERVER_FILE%' -ErrorAction Stop"
if %errorlevel% neq 0 (
    echo Failed to fetch server.py.
    pause
    exit /b 1
)

echo Installation/Update complete.
echo You can now run: python server.py
echo Or to install as a startup service (with UAC prompt): python server.py --install
pause
exit /b 0
