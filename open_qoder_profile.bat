@echo off
setlocal

rem Each profile is a normal Qoder user-data directory owned by this Windows user.
set "QODER_EXE=%QODER_CN_EXECUTABLE%"
if not defined QODER_EXE set "QODER_EXE=D:\Qoder CN\Qoder CN.exe"

if not exist "%QODER_EXE%" (
    echo Qoder CN was not found.
    echo Set QODER_CN_EXECUTABLE to the full Qoder CN executable path, then try again.
    pause
    exit /b 1
)

set /p "QODER_PROFILE=Profile name, for example Villa: "
if not defined QODER_PROFILE (
    echo No profile name was entered.
    pause
    exit /b 1
)

set "QODER_PROFILE_ROOT=%APPDATA%\AgentCheckin\QoderProfiles"
set "QODER_DATA=%QODER_PROFILE_ROOT%\%QODER_PROFILE%"

echo Starting Qoder CN with profile "%QODER_PROFILE%".
echo Sign in to the intended account in the Qoder window.
start "" "%QODER_EXE%" "--user-data-dir=%QODER_DATA%"
