@echo off
title Combined Bot Setup (Windows)
color 0a

echo ==========================================
echo      COMBINED BOT - WINDOWS SETUP
echo ==========================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from python.org and tick "Add Python to PATH".
    pause
    exit /b
)
echo [OK] Python found.

:: 2. Upgrade PIP
echo.
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip

:: 3. Install Requirements
echo.
echo [INFO] Installing requirements from requirements.txt...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements!
    pause
    exit /b
)
echo [OK] Requirements installed.

:: 4. Check FFmpeg
echo.
echo [INFO] Checking for FFmpeg...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] FFmpeg is NOT found in your PATH!
    echo.
    echo To play music, you MUST install FFmpeg:
    echo 1. Download from: https://www.gyan.dev/ffmpeg/builds/ffmpeg-git-essentials.7z
    echo 2. Extract the 'bin' folder (ffmpeg.exe).
    echo 3. Copy 'ffmpeg.exe' into THIS folder (%~dp0).
    echo.
) else (
    echo [OK] FFmpeg found.
)

echo.
echo ==========================================
echo        SETUP COMPLETE!
echo ==========================================
echo You can now run 'run_bot.bat' to start the bot.
pause
