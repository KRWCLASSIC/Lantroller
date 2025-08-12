@echo off
set INSTALL_DIR=%LOCALAPPDATA%\Lantroller
set PYTHON_URL=https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/server.py
set REQUIREMENTS_URL=https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/requirements.txt
set SERVER_FILE=%INSTALL_DIR%\server.py
set REQUIREMENTS_FILE=%INSTALL_DIR%\requirements.txt

if "%~1"=="--continue" goto CONTINUE

echo Creating installation directory %INSTALL_DIR%...
mkdir "%INSTALL_DIR%" 2>nul

echo Checking for Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python not found in PATH. Checking for Winget...
    where winget >nul 2>nul
    if %errorlevel% neq 0 (
        echo Winget not found. Installing Winget ^(App Installer^)
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm asheroto.com/winget | iex"
        if %errorlevel% neq 0 (
            echo Failed to install Winget automatically. Please install Winget ^(App Installer^) from Microsoft Store.
            pause
            exit /b 1
        )
        echo Winget installed.
    )
    echo Installing Python 3.11 via Winget...
    winget.exe install --id "Python.Python.3.11" --exact --source winget --accept-source-agreements --disable-interactivity --silent --accept-package-agreements --force
    if %errorlevel% neq 0 (
        echo Failed to install Python via Winget. Please install Python 3.x and add it to your PATH manually.
        echo https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo Python 3.11 installed successfully.
    echo Restarting installer to refresh PATH...
    start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "cmd /c \"\"%~f0\" --continue\""
    exit /b 0
)

:CONTINUE

rem Ensure installation directory exists in the resume path as well
mkdir "%INSTALL_DIR%" 2>nul

echo Fetching latest requirements.txt...
powershell -Command "Invoke-WebRequest -Uri '%REQUIREMENTS_URL%' -OutFile '%REQUIREMENTS_FILE%' -ErrorAction Stop"
if %errorlevel% neq 0 (
    echo Failed to fetch requirements.txt. Proceeding without it, but dependencies may be missing.
)

echo Installing/updating Python dependencies...
python -m pip install -r "%REQUIREMENTS_FILE%" --upgrade --no-warn-script-location
if %errorlevel% neq 0 (
    echo Failed to install Python dependencies. Some features may not work.
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

echo Running server.py with --install in a new PowerShell session to refresh PATH...
start powershell.exe -NoExit -Command "cd '%INSTALL_DIR%'; python server.py --install; Read-Host 'Press Enter to continue...'"

exit /b 0
