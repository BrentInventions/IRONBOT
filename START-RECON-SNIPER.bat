@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title IRONBOT
color 0A
set "MARK2_OFFLINE_OK=1"
set "PYTHONPATH=%~dp0"
set "MARK2_FRONTEND=%~dp0mark2\frontend"
set "RECON_APP_HOME=%~dp0"
set "PYTHONUNBUFFERED=1"
if not exist "%~dp0mark2\logs" mkdir "%~dp0mark2\logs"

echo.
echo  IRONBOT is running. Leave this window open.
echo  Closing it stops the bot.
echo.

py -3 -c "import sys" >nul 2>&1
if errorlevel 1 (
  set "PY=python"
) else (
  set "PY=py -3"
)

echo [%date% %time%] installing Python packages
%PY% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo  pip install failed. Run this in the IRONBOT folder:
  echo    %PY% -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

:retry
echo [%date% %time%] starting HUD
>> "%~dp0mark2\logs\last_launch.txt" echo %date% %time% START-RECON-SNIPER.bat starting HUD with %PY%
%PY% -u -m mark2
set "EC=%ERRORLEVEL%"
echo [%date% %time%] HUD stopped  exit=%EC%
>> "%~dp0mark2\logs\last_launch.txt" echo %date% %time% HUD stopped exit=%EC%
if "%EC%"=="0" (
  echo HUD window was closed. Bot stopped.
  pause
  exit /b 0
)
echo HUD crashed (exit %EC%). Restarting in 2 seconds...
timeout /t 2 /nobreak >nul
goto retry
