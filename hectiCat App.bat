@echo off
setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "VENV=%PROJECT_DIR%\.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "URL=http://127.0.0.1:8765"
set "LOG_DIR=%PROJECT_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\app.log"

cd /d "%PROJECT_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo == hectiCat App ==

if exist "%PY%" goto :haveenv
echo Creating local Python environment...
py -3 -m venv "%VENV%" 2>nul || python -m venv "%VENV%"

:haveenv
echo Installing app requirements...
"%PIP%" install --quiet --upgrade pip
"%PIP%" install --quiet -r "%PROJECT_DIR%\requirements.txt"

curl --silent --fail "%URL%/api/health" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :running

echo Starting hectiCat...
start "hectiCat" /min cmd /c ""%PY%" -m uvicorn app:app --host 127.0.0.1 --port 8765 >>"%LOG_FILE%" 2>&1"

set "READY="
for /L %%i in (1,1,40) do (
  curl --silent --fail "%URL%/api/health" >nul 2>&1
  if !ERRORLEVEL! EQU 0 (
    set "READY=1"
    goto :ready
  )
  timeout /t 1 /nobreak >nul
)

:ready
if not defined READY (
  echo hectiCat failed to start. See: %LOG_FILE%
  exit /b 1
)

:running
echo Opening %URL%
start "" "%URL%"

echo.
echo hectiCat is running locally. Use Stop dashboard in the app to quit the server.
