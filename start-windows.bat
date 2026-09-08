@echo off
chcp 65001 >nul
setlocal

set "PYTHON_CMD=D:\anaconda3\envs\deepagents\python.exe"
set "FRONTEND_DIR=%~dp0frontend"
set "RUNTIME_DIR=%~dp0runtime"
set "BACKEND_PID_FILE=%RUNTIME_DIR%\backend.pid"
set "FRONTEND_PID_FILE=%RUNTIME_DIR%\frontend.pid"

echo ====================================
echo Starting MyPaperWeb Services
echo ====================================
echo.

if not exist "%RUNTIME_DIR%" (
    mkdir "%RUNTIME_DIR%"
)

if exist "%BACKEND_PID_FILE%" del /f /q "%BACKEND_PID_FILE%" >nul 2>&1
if exist "%FRONTEND_PID_FILE%" del /f /q "%FRONTEND_PID_FILE%" >nul 2>&1

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
docker ps --format "{{.Names}}" | findstr /x "milvus-standalone" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Milvus standalone is already running
) else (
    docker ps -a --format "{{.Names}}" | findstr "milvus-" >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Found existing Milvus containers, cleaning compose state...
        docker compose -f vector-database.yml down
        if errorlevel 1 (
            echo [ERROR] Failed to clean existing Milvus containers
            pause
            exit /b 1
        )
        echo [INFO] Removing stale Milvus containers by fixed names...
        docker rm -f milvus-etcd milvus-minio milvus-standalone milvus-attu >nul 2>&1
    )

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
for /f %%i in ('powershell -NoProfile -Command "$p = Start-Process -FilePath cmd.exe -WorkingDirectory '%~dp0app' -ArgumentList '/k','%PYTHON_CMD% main.py' -PassThru; $p.Id"') do set "BACKEND_PID=%%i"
if not defined BACKEND_PID (
    echo [ERROR] Failed to start MyPaperWeb backend
    pause
    exit /b 1
)
> "%BACKEND_PID_FILE%" echo %BACKEND_PID%

for /f %%i in ('powershell -NoProfile -Command "$p = Start-Process -FilePath cmd.exe -WorkingDirectory '%FRONTEND_DIR%' -ArgumentList '/k','npm run dev' -PassThru; $p.Id"') do set "FRONTEND_PID=%%i"
if not defined FRONTEND_PID (
    echo [ERROR] Failed to start MyPaperWeb frontend
    pause
    exit /b 1
)
> "%FRONTEND_PID_FILE%" echo %FRONTEND_PID%

echo [OK] MyPaperWeb backend started (PID: %BACKEND_PID%)
echo [OK] MyPaperWeb frontend started (PID: %FRONTEND_PID%)
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
