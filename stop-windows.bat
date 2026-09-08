@echo off
chcp 65001 >nul
setlocal

set "RUNTIME_DIR=%~dp0runtime"
set "BACKEND_PID_FILE=%RUNTIME_DIR%\backend.pid"
set "FRONTEND_PID_FILE=%RUNTIME_DIR%\frontend.pid"

echo ====================================
echo Stopping MyPaperWeb Services
echo ====================================
echo.

REM Stop backend
echo [1/3] Stopping MyPaperWeb backend...
call :stop_process "%BACKEND_PID_FILE%" "MyPaperWeb backend" "MyPaperWeb API*"
echo.

REM Stop frontend
echo [2/3] Stopping MyPaperWeb frontend...
call :stop_process "%FRONTEND_PID_FILE%" "MyPaperWeb frontend" "MyPaperWeb Frontend*"
echo.

REM Stop Docker containers
echo [3/3] Stopping Milvus containers...
docker ps -a --format "{{.Names}}" | findstr "milvus-" >nul 2>&1
if not errorlevel 1 (
    docker compose -f vector-database.yml down
    if errorlevel 1 (
        echo [ERROR] Failed to stop Milvus containers
    ) else (
        echo [OK] Milvus containers stopped
    )
) else (
    echo [INFO] Milvus containers do not exist
)
echo.

echo ====================================
echo All services have been stopped
echo ====================================
echo.
echo Tips:
echo   - To remove Docker volumes completely, run:
echo     docker compose -f vector-database.yml down -v
echo.
pause
exit /b 0

:stop_process
set "PID_FILE=%~1"
set "SERVICE_NAME=%~2"
set "WINDOW_FILTER=%~3"
set "PID="

if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
)

if defined PID (
    taskkill /PID %PID% /T /F >nul 2>&1
    if errorlevel 1 (
        echo [INFO] %SERVICE_NAME% PID %PID% is not running, trying title fallback...
    ) else (
        echo [OK] %SERVICE_NAME% stopped by PID %PID%
        del /f /q "%PID_FILE%" >nul 2>&1
        goto :eof
    )
)

taskkill /FI "WINDOWTITLE eq %WINDOW_FILTER%" /T /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] %SERVICE_NAME% is not running or already stopped
) else (
    echo [OK] %SERVICE_NAME% stopped by window title
)

if exist "%PID_FILE%" del /f /q "%PID_FILE%" >nul 2>&1
goto :eof
