@echo off
rem Runs the Korea AI bet pipeline: ingest, build, validate.
rem Optional: set ECOS_API_KEY=<your key> first for faster ECOS downloads.
setlocal
set PYTHONUTF8=1
set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
    echo [ERROR] %PY% not found. Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)
"%PY%" -I scripts\01_ingest.py %* || exit /b 1
"%PY%" -I scripts\02_build_warehouse.py || exit /b 1
"%PY%" -I scripts\03_validate.py || exit /b 1
echo [SUCCESS] Pipeline finished.
