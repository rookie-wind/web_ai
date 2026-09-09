@echo off
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
for %%i in ("%SCRIPT_DIR%..\") do set "ROOT_DIR=%%~fi"

REM Activate venv
call "%ROOT_DIR%\.venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [X] Virtual environment not found, please run install.bat first
    pause
    exit /b 1
)

REM Read Token from .env
set "MCP_AUTH_TOKEN="
if exist "%SCRIPT_DIR%.env" (
    for /f "tokens=1,2 delims==" %%a in (%SCRIPT_DIR%.env) do set "%%a=%%b"
)

if "%MCP_AUTH_TOKEN%"=="" (
    echo [X] MCP_AUTH_TOKEN not set
    echo     Please run install.bat first to configure Token
    echo     Or set manually: set MCP_AUTH_TOKEN=your_token
    pause
    exit /b 1
)

echo ============================================
echo   PCA MCP Server
echo ============================================
echo.
echo   Token:  %MCP_AUTH_TOKEN%
echo   URL:    http://localhost:8765/mcp
echo   Tools:  7 (1 implemented + 6 stubs)
echo.
echo   Press Ctrl+C to stop
echo ============================================
echo.

python "%SCRIPT_DIR%server.py"