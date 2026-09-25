@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Could not find .venv - run "Run MiceTracker.bat" once first to set it up.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m gui.kit_sheet
if errorlevel 1 (
    echo.
    echo The preview closed with an error. See above for details.
    pause
)
