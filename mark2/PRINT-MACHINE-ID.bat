@echo off
cd /d "%~dp0.."
py -3 -m mark2.licensing
if errorlevel 1 python -m mark2.licensing
pause
