@echo off
cd /d "%~dp0"
python -m worldstudio gui
if errorlevel 1 pause
