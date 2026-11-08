@echo off
setlocal EnableExtensions
title GaiaNet Earth - Launcher
:: Always run from the project folder, even from a shortcut or another directory.
cd /d "%~dp0"

set "PORT=8000"
set "URL=http://localhost:%PORT%"

echo ==========================================
echo    GaiaNet Earth - Digital Twin of Earth
echo ==========================================

:: --- 0. Python available? ---------------------------------------------------
:: (python --version, not "where", so the Microsoft Store stub does not count)
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found. Install Python 3.11+ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

:: --- 1. Stop any old server still holding the port ----------------------------
:: An old server left running keeps serving OLD code, so it is always replaced.
set "STOPPED=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
    set "STOPPED=1"
)
if "%STOPPED%"=="1" (
    echo [1/4] Stopped the old server on port %PORT%.
    timeout /t 1 /nobreak >nul
) else (
    echo [1/4] No old server running.
)

:: --- 2. Virtual environment and dependencies --------------------------------
:: pip runs only on the first start or when requirements.txt has changed.
cd backend
if not exist "venv\Scripts\python.exe" (
    echo [2/4] Creating virtual environment - first run only...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

set "NEED_INSTALL=1"
if exist "venv\requirements.installed.txt" (
    fc /b "requirements.txt" "venv\requirements.installed.txt" >nul 2>&1 && set "NEED_INSTALL=0"
)
if "%NEED_INSTALL%"=="1" (
    echo [2/4] Installing dependencies...
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies. See the messages above.
        pause
        exit /b 1
    )
    copy /y "requirements.txt" "venv\requirements.installed.txt" >nul
) else (
    echo [2/4] Dependencies up to date.
)

if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo [!] Created backend\.env from .env.example - add your API keys there.
    )
)

:: --- 3. Start the server in its own minimised window ---------------------------
echo [3/4] Starting server...
start "GaiaNet Earth Server" /min cmd /k "venv\Scripts\python.exe main.py"
cd ..

:: --- 4. Open the dashboard as soon as the server answers -----------------------
:: Checks the port on 127.0.0.1 directly. "localhost" resolves to IPv6 (::1)
:: first on Windows, but the server listens on IPv4 only, and a refused
:: connection takes ~2 s to fail on Windows, so a localhost check can time
:: out even though the server is up. A plain TCP check also skips any proxy.
echo [4/4] Waiting for the server to respond...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline = (Get-Date).AddSeconds(90); while ((Get-Date) -lt $deadline) { $c = New-Object System.Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', %PORT%); $c.Close(); exit 0 } catch { $c.Close(); Start-Sleep -Milliseconds 500 } }; exit 1"
if errorlevel 1 (
    echo [WARNING] Could not confirm the server within 90 seconds - opening the dashboard anyway.
    echo           If the page does not load, check the "GaiaNet Earth Server" window for an error.
    start "" "%URL%"
    pause
    exit /b 1
)

start "" "%URL%"

echo ==========================================
echo    GaiaNet Earth is running
echo    Dashboard : %URL%
echo    API docs  : %URL%/docs
echo    To stop   : close the "GaiaNet Earth Server" window
echo    Page looks unchanged? Press Ctrl+Shift+R
echo ==========================================
timeout /t 5 >nul
exit /b 0
