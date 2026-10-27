@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title C: drive cleanup launcher

set "SCRIPT=%~dp0_c_drive_cleanup.ps1"
if not exist "%SCRIPT%" (
    echo [ERROR] _c_drive_cleanup.ps1 not found next to this .cmd file.
    echo Expected path: %SCRIPT%
    pause
    exit /b 1
)

:menu
cls
echo ==================================================
echo   C: drive cleanup  -  choose an option
echo ==================================================
echo.
echo   [1] Preview A tier only   (dry run, no changes)
echo   [2] Clean A tier          (safe caches, ~12 GB)
echo   [3] Clean A + B           (interactive, per item confirm)
echo   [4] Clean A + B + D       (elevated admin, full incl. DISM)
echo   [5] Redirect caches only  (move gradle/nuget/npm/pip to another drive)
echo   [6] Clean A + redirect    (recommended combo)
echo   [7] Preview everything    (dry run A+B+D)
echo   [0] Exit
echo.
choice /C 12345670 /N /M "Select: "
if errorlevel 8 goto end
if errorlevel 7 goto preview_all
if errorlevel 6 goto combo
if errorlevel 5 goto redirect
if errorlevel 4 goto full
if errorlevel 3 goto ab
if errorlevel 2 goto a_only
if errorlevel 1 goto preview_a

:preview_a
call powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Mode A -WhatIf
pause
goto menu

:a_only
call powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Mode A
pause
goto menu

:ab
call powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Mode Interactive
pause
goto menu

:full
echo Requesting administrator elevation...
call powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-File','\"%SCRIPT%\"','-Mode','Full'"
goto menu

:redirect
set "TARGET="
set /p TARGET=Target path [Enter = E\dev-cache]: 
if "!TARGET!"=="" set "TARGET=E:\dev-cache"
call powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Mode A -Redirect "!TARGET!" -WhatIf
echo.
echo Above is PREVIEW. Re-run option [5] without -WhatIf to actually move.
echo Or run option [6] below which does A tier + redirect for real.
pause
goto menu

:combo
set "TARGET="
set /p TARGET=Redirect target [Enter = E\dev-cache]: 
if "!TARGET!"=="" set "TARGET=E:\dev-cache"
call powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Mode A -Redirect "!TARGET!"
pause
goto menu

:preview_all
call powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Mode Full -WhatIf
pause
goto menu

:end
echo Bye.
endlocal
exit /b 0
