@echo off
setlocal

rem Run from this batch file's directory.
cd /d "%~dp0"

rem Use UTF-8 for the Python script's console output.
chcp 65001 >nul

rem Use the working python command instead of the broken py -3 launcher.
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python or add it to PATH, then try again.
    pause
    exit /b 9009
)
python "%~dp0WorkBuddyDailyCheckin.py"

set "CHECKIN_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%CHECKIN_EXIT_CODE%"=="0" (
    echo Done.
) else (
    echo The check-in script ended with exit code %CHECKIN_EXIT_CODE%.
)

if /i not "%~1"=="--no-pause" pause
exit /b %CHECKIN_EXIT_CODE%
