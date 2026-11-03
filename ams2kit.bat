@echo off
rem Start the ams2kit UI. Keeps the window open so errors can be read.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 run_ui.py %*) || (python run_ui.py %*)
if errorlevel 1 pause
