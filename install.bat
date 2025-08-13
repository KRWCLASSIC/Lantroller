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
    echo Python 3.11 installed successfully.
)

rem Resolve full Python path
set "PYTHON_EXE="
call :findRealPython
if not defined PYTHON_EXE (
    echo Could not resolve a usable Python interpreter.
    echo Please sign out/in or reboot, then re-run the installer.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_EXE%

echo Fetching latest requirements.txt...
powershell -Command "Invoke-WebRequest -Uri '%REQUIREMENTS_URL%' -OutFile '%REQUIREMENTS_FILE%' -ErrorAction Stop"
if %errorlevel% neq 0 (
    echo Failed to fetch requirements.txt. Proceeding without it, but dependencies may be missing.
)

echo Installing/updating Python dependencies...
"%PYTHON_EXE%" -m pip install -r "%REQUIREMENTS_FILE%" --upgrade --no-warn-script-location
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
echo You can now run: "%PYTHON_EXE%" "%SERVER_FILE%"
echo Or to install as a startup service ^(with UAC prompt^): "%PYTHON_EXE%" "%SERVER_FILE%" --install

echo Running server.py with --install in a new PowerShell session to refresh PATH...
start powershell.exe -NoExit -Command "cd '%INSTALL_DIR%'; & '%PYTHON_EXE%' 'server.py' --install; Read-Host 'Press Enter to continue...'"

exit /b 0

:resolveWinget
rem Prefer user-local WindowsApps shim, then PATH
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe" set "WINGET_EXE=%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe"
if not defined WINGET_EXE where winget >nul 2>nul && set "WINGET_EXE=winget"
if not defined WINGET_EXE if exist "%SystemRoot%\System32\winget.exe" set "WINGET_EXE=%SystemRoot%\System32\winget.exe"
exit /b 0

:findRealPython
echo Looking for Python interpreter
set "PYTHON_EXE="
rem 1) Prefer py launcher to get actual interpreter path
for /f "usebackq delims=" %%E in (`python -c "import sys; print(sys.executable)" 2^>nul`) do (
  if not defined PYTHON_EXE set "PYTHON_EXE=%%E"
)
if defined PYTHON_EXE goto :findRealPython_done

rem 2) Common user installs
for /f "delims=" %%P in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" 2^>nul') do (
  if not defined PYTHON_EXE (
    "%%P" -c "import sys;print(1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=%%P"
  )
)
if defined PYTHON_EXE goto :findRealPython_done

rem 3) Program Files installs
for /f "delims=" %%P in ('dir /b /s "%ProgramFiles%\Python311\python.exe" 2^>nul') do (
  if not defined PYTHON_EXE (
    "%%P" -c "import sys;print(1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=%%P"
  )
)
if defined PYTHON_EXE goto :findRealPython_done

:findRealPython_done
exit /b 0