@echo off
setlocal

cd /d "%~dp0"
chcp 65001 >nul

set "PYTHON_EXE=%~1"
set "BOUND_PLATFORMS=%~2"
if defined PYTHON_EXE (
    if not exist "%PYTHON_EXE%" (
        echo Python was not found at: %PYTHON_EXE%
        pause
        exit /b 9009
    )
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found for this Windows user.
        pause
        exit /b 9009
    )
    set "PYTHON_EXE=python"
)

set "CHECKIN_ARGS=--bound-only"
if defined BOUND_PLATFORMS set "CHECKIN_ARGS=%CHECKIN_ARGS% --bound-platforms=%BOUND_PLATFORMS%"
"%PYTHON_EXE%" -X utf8 "%~dp0DailyCheckin.py" %CHECKIN_ARGS%
set "CHECKIN_EXIT_CODE=%ERRORLEVEL%"

echo.
if "%CHECKIN_EXIT_CODE%"=="0" (
    echo Done.
) else (
    echo The check-in script ended with exit code %CHECKIN_EXIT_CODE%.
)
pause
exit /b %CHECKIN_EXIT_CODE%
