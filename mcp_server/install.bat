@echo off
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
for %%i in ("%SCRIPT_DIR%..\") do set "ROOT_DIR=%%~fi"

echo ============================================
echo   PCA MCP Server - Install
echo ============================================
echo.

REM 1. Check Python
echo [1/5] Check Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found, please install Python 3.10+
    echo     Download: https://www.python.org/downloads/
    echo     Check "Add Python to PATH" during installation
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set "PY_VER=%%i"
echo     Python %PY_VER% OK
echo.

REM 2. Create venv
echo [2/5] Create virtual environment...
if exist "%ROOT_DIR%\.venv" (
    echo     .venv exists, skip
) else (
    python -m venv "%ROOT_DIR%\.venv"
    if errorlevel 1 (
        echo [X] Virtual environment creation failed
        pause
        exit /b 1
    )
)
echo.

REM 3. Install dependencies
echo [3/5] Install dependencies...
call "%ROOT_DIR%\.venv\Scripts\activate.bat"
pip install -r "%SCRIPT_DIR%requirements.txt" -q
if errorlevel 1 (
    echo [X] Dependency installation failed, check network
    pause
    exit /b 1
)
echo     Dependencies installed
echo.

REM 4. Configure Token
echo [4/5] Configure Token...
echo     Token for MCP authentication. localhost = system level (read/write)
echo     Other IPs = user level (read-only)
echo     Other users get auto-assigned tokens via the access page
echo.
set "TOKEN="
set /p "TOKEN=    Enter admin Token (press Enter to auto-generate): "
if not defined TOKEN (
    for /f "delims=" %%i in ('python -c "import secrets; print('metam_pat_' + secrets.token_hex(16))"') do set "TOKEN=%%i"
)
echo     Admin Token: %TOKEN%

REM Write .env
> "%SCRIPT_DIR%.env" echo MCP_AUTH_TOKEN=%TOKEN%
echo     Saved mcp_server\.env

REM Write .trae/mcp.json
if not exist "%ROOT_DIR%\.trae" mkdir "%ROOT_DIR%\.trae"
echo {"mcpServers":{"protocol-converter":{"url":"http://localhost:8765/mcp","headers":{"Authorization":"Bearer %TOKEN%"}}}} > "%ROOT_DIR%\.trae\mcp.json"
echo     Updated .trae\mcp.json
echo.

REM 5. Done
echo [5/5] Install complete!
echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo   Start server:  double-click mcp_server\start.bat
echo   Or command:    mcp_server\start.bat
echo.
pause