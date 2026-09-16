@echo off
setlocal EnableExtensions
title IRONBOT - Create Desktop Shortcut
cd /d "%~dp0"

echo.
echo  Creating Desktop shortcut for IRONBOT...
echo.

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "TARGET=%ROOT%\launch-bot.vbs"
if not exist "%TARGET%" (
  echo ERROR: launch-bot.vbs missing in:
  echo   %ROOT%
  pause
  exit /b 1
)

set "DESK=%USERPROFILE%\Desktop"
if exist "%USERPROFILE%\OneDrive\Desktop" set "DESK=%USERPROFILE%\OneDrive\Desktop"

set "LNK=%DESK%\IRONBOT.lnk"
set "ICON=%ROOT%\assets\icons\iron-bot.ico"
if not exist "%ICON%" set "ICON=%ROOT%\assets\icons\impulse-pro.ico"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
  "$s.TargetPath = '%TARGET%';" ^
  "$s.WorkingDirectory = '%ROOT%';" ^
  "$s.WindowStyle = 1;" ^
  "$s.Description = 'IRONBOT';" ^
  "if (Test-Path -LiteralPath '%ICON%') { $s.IconLocation = '%ICON%,0' };" ^
  "$s.Save();" ^
  "if (-not (Test-Path -LiteralPath '%LNK%')) { exit 1 }"

if errorlevel 1 (
  echo ERROR: could not create IRONBOT shortcut.
  pause
  exit /b 1
)

echo.
echo  Created Desktop shortcut:
echo    %LNK%
echo      -^> %TARGET%
echo.
pause
endlocal
