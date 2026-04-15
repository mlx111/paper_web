@echo off
chcp 65001 >nul
setlocal
set PYTHON_CMD=D:\anaconda3\envs\deepagents\python.exe
set FRONTEND_DIR=%~dp0frontend

echo ====================================
echo Starting MyPaperWeb Services
echo ====================================
echo.

REM Check Docker availability
echo [1/4] Checking Docker...
docker version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is unavailable. Please start Docker Desktop first.
    pause
    exit /b 1
)
echo [OK] Docker is available
echo.

REM Start Milvus containers
echo [2/4] Starting Milvus containers...
docker ps --format "{{.Names}}" | findstr "milvus-standalone" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Milvus container is already running
) else (
    docker compose -f vector-database.yml up -d
    if errorlevel 1 (
        echo [ERROR] Failed to start Milvus containers
        pause
        exit /b 1
    )
    echo [INFO] Waiting for Milvus to start - 10 seconds...
    timeout /t 10 /nobreak >nul
)
echo [OK] Milvus is ready
echo.

REM Check frontend dependencies
echo [3/4] Checking frontend environment...
if not exist "%PYTHON_CMD%" (
    echo [ERROR] Python interpreter not found: %PYTHON_CMD%
    pause
    exit /b 1
)
if not exist "%FRONTEND_DIR%" (
    echo [ERROR] Frontend directory not found: %FRONTEND_DIR%
    pause
    exit /b 1
)
call npm -v >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm is unavailable. Please install Node.js first.
    pause
    exit /b 1
)
if not exist "%FRONTEND_DIR%\node_modules" (
    echo [ERROR] Frontend dependencies are missing. Please run "npm install" in the frontend directory first.
    pause
    exit /b 1
)
echo [OK] Frontend environment is ready
echo.

REM Start application services
echo [4/4] Starting MyPaperWeb services...
start "MyPaperWeb API" cmd /k "cd /d %~dp0app && ""%PYTHON_CMD%"" main.py"
start "MyPaperWeb Frontend" cmd /k "cd /d %FRONTEND_DIR% && call npm run dev"
echo [OK] MyPaperWeb backend and frontend started
echo.

echo ====================================
echo Services started successfully
echo ====================================
echo Frontend: http://127.0.0.1:5173
echo Backend API: http://127.0.0.1:8080
echo API Docs: http://127.0.0.1:8080/docs
echo Stop services: stop-windows.bat
echo ====================================
echo.
pause
