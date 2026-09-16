@echo off
title BRENTS TRADING BOT
color 0C
cd /d "%~dp0.."
if not exist "%cd%\mark2\tcm8_watch.py" cd /d "%~dp0\.."
set "PYTHONPATH=%cd%"
set "PYTHONUNBUFFERED=1"
set "MARK2_OFFLINE_OK=1"
chcp 65001 >nul
py -3 -m mark2.tcm8_watch
if errorlevel 1 python -m mark2.tcm8_watch
echo.
echo BRENTS TRADING BOT window closed. The bot keeps running.
pause
