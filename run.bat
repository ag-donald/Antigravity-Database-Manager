@echo off
:: ============================================================================
::  Agmercium Antigravity IDE History Recovery Tool — Windows Batch Launcher
:: ============================================================================
setlocal

echo.
echo  ============================================================
echo   Agmercium Antigravity IDE History Recovery Tool
echo   Launcher for Windows (run.bat)
echo  ============================================================
echo.

:: Locate Python — try 'python' first, then 'python3', then 'py'
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON=python"
    goto :found
)

where python3 >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON=python3"
    goto :found
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON=py"
    goto :found
)

echo [ERROR] Python is not installed or not in your PATH.
echo         Please install Python 3.7+ from https://www.python.org/downloads/
echo.
pause
exit /b 1

:found
echo [INFO ] Using: %PYTHON%
%PYTHON% --version
echo.

:: Run the recovery script from the same directory as this batch file
%PYTHON% "%~dp0antigravity_recover.py" %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] The recovery script exited with an error (code %errorlevel%).
    echo.
)

pause
endlocal
