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

rem Qoder forwards a second launch to an existing instance. In that case the
rem user-data-dir argument is lost and a new login could replace the default
rem HH session, so do not proceed while any Qoder CN instance is still alive.
tasklist /fi "IMAGENAME eq Qoder CN.exe" /nh | find /i "Qoder CN.exe" >nul
if not errorlevel 1 (
    echo Qoder CN is still running, including a possible tray/background process.
    echo Close every Qoder CN process first. No profile was opened.
    pause
    exit /b 2
)

echo Starting isolated Qoder CN profile "%QODER_PROFILE%".
echo Do not sign in yet. The launcher will first verify that Qoder accepted the profile directory.
start "" "%QODER_EXE%" "--user-data-dir=%QODER_DATA%"

for /l %%I in (1,1,15) do (
    if exist "%QODER_DATA%\Local State" goto profile_ready
    timeout /t 2 /nobreak >nul
)

echo.
echo Profile directory was not activated. Do NOT sign in in the Qoder window.
echo Close Qoder CN and keep using the default account until this is investigated.
pause
exit /b 3

:profile_ready
echo.
echo Isolated profile verified. You can now sign in to the intended Qoder account.
pause
