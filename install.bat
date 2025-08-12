@echo off
setlocal EnableExtensions EnableDelayedExpansion
set INSTALL_DIR=%LOCALAPPDATA%\Lantroller
set PYTHON_URL=https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/server.py
set REQUIREMENTS_URL=https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/requirements.txt
set SERVER_FILE=%INSTALL_DIR%\server.py
set REQUIREMENTS_FILE=%INSTALL_DIR%\requirements.txt
set WINGET_EXE=

echo Creating installation directory %INSTALL_DIR%...
mkdir "%INSTALL_DIR%" 2>nul

echo Checking for Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python not found in PATH. Resolving Winget...
    call :resolveWinget
    if not defined WINGET_EXE (
        echo Winget not found. Installing Winget ^(App Installer^)...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm asheroto.com/winget | iex"
        echo Verifying Winget availability...
        call :resolveWinget
        if not defined WINGET_EXE (
            timeout /t 2 /nobreak >nul
            call :resolveWinget
        )
        if not defined WINGET_EXE (
            echo Failed to install Winget automatically. Please install Winget ^(App Installer^) from Microsoft Store.
            pause
            exit /b 1
        )
        echo Winget installed.
    )
    echo Installing Python 3.11 via Winget...
    "!WINGET_EXE!" install --id "Python.Python.3.11" --exact --source winget --accept-source-agreements --disable-interactivity --silent --accept-package-agreements --force
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        exit /b 1
    )
    echo Python 3.11 installed and detected on PATH.
)

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
echo Or to install as a startup service ^(with UAC prompt^): python server.py --install

echo Running server.py with --install in a new PowerShell session to refresh PATH...
start powershell.exe -NoExit -Command "cd '%INSTALL_DIR%'; python server.py --install; Read-Host 'Press Enter to continue...'"

exit /b 0

:resolveWinget
rem Prefer user-local WindowsApps shim, then PATH
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe" set "WINGET_EXE=%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe"
if not defined WINGET_EXE where winget >nul 2>nul && set "WINGET_EXE=winget"
if not defined WINGET_EXE if exist "%SystemRoot%\System32\winget.exe" set "WINGET_EXE=%SystemRoot%\System32\winget.exe"
exit /b 0
