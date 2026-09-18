@echo off
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

echo OS: Windows

python -c "import fastapi, httpx, uvicorn" 2>nul
if errorlevel 1 (
  echo Missing Python runtime packages. Run: python -m pip install -r "%PROJECT_DIR%\requirements.txt"
  exit /b 1
)

echo Runtime prerequisites are ready. Start hectiCat with: "%PROJECT_DIR%\run.bat"
echo.
echo Optional automation dependencies:
curl --silent --fail http://127.0.0.1:11434/api/tags >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  echo - Ollama: available
) else (
  echo - Ollama: unavailable at http://127.0.0.1:11434
)

where hermes >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  for /f "delims=" %%p in ('where hermes') do echo - Hermes: %%p
) else (
  echo - Hermes: unavailable
)
