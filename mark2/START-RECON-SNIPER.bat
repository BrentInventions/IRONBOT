@echo off
:: Bot HUD stays in a window so a crash cannot vanish silently.
cd /d "%~dp0.."
if not exist "%cd%\START-RECON-SNIPER.bat" cd /d "%~dp0"
call "%cd%\START-RECON-SNIPER.bat"
