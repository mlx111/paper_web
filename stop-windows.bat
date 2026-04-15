@echo off
chcp 65001 >nul

echo ====================================
echo Stopping MyPaperWeb Services
echo ====================================
echo.

REM Stop backend
echo [1/3] Stopping MyPaperWeb backend...
taskkill /FI "WINDOWTITLE eq MyPaperWeb API*" /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] MyPaperWeb backend is not running or already stopped
) else (
    echo [OK] MyPaperWeb backend stopped
)
echo.

REM Stop frontend
echo [2/3] Stopping MyPaperWeb frontend...
taskkill /FI "WINDOWTITLE eq MyPaperWeb Frontend*" /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] MyPaperWeb frontend is not running or already stopped
) else (
    echo [OK] MyPaperWeb frontend stopped
)
echo.

REM Stop Docker containers
echo [3/3] Stopping Milvus containers...
docker ps --format "{{.Names}}" | findstr "milvus" >nul 2>&1
if not errorlevel 1 (
    docker compose -f vector-database.yml down
    if errorlevel 1 (
        echo [ERROR] Failed to stop Milvus containers
    ) else (
        echo [OK] Milvus containers stopped
    )
) else (
    echo [INFO] Milvus containers are not running
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
