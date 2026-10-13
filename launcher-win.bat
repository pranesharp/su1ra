@echo off
REM ============================================================
REM  Su1ra dev launcher (Windows)
REM  - cd to the repo (the folder this script lives in)
REM  - create .venv if missing
REM  - activate it (install requirements on first run / when missing)
REM  - run desktop.py
REM
REM  Usage: double-click launcher-win.bat, or run from a terminal.
REM  Needs Python 3.10+ on PATH as "python" (or set PYTHON=py -3.14 etc).
REM ============================================================
setlocal
setlocal enabledelayedexpansion

REM 1) current directory = where this script lives (repo root)
cd /d "%~dp0"

REM pick the interpreter: env var PYTHON wins, else try python, else py launcher
set "PY=%PYTHON%"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo error: python not found on PATH - install from python.org or use the py launcher
  pause
  exit /b 1
)

REM 2) make a new venv in the dir if there isn't one
if not exist ".venv\Scripts\python.exe" (
  echo [su1ra] creating venv in %cd%\.venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo error: venv creation failed
    pause
    exit /b 1
  )
)

REM 3) use that venv
call ".venv\Scripts\activate.bat"

REM first run (or new deps): install requirements
".venv\Scripts\python.exe" -c "import webview, fastapi, uvicorn, httpx, pptx, docx, openpyxl, reportlab, PIL" >nul 2>nul
if errorlevel 1 (
  echo [su1ra] installing backend requirements ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt pillow
  if errorlevel 1 (
    echo error: pip install failed
    pause
    exit /b 1
  )
)

REM frontend must be built for the app to serve the ui
if not exist "frontend\dist\index.html" (
  echo [su1ra] frontend\dist missing - building it ^(needs yarn or npm^) ...
  pushd frontend
  where yarn >nul 2>nul
  if not errorlevel 1 (
    call yarn && call yarn build
  ) else (
    call npm install && call npm run build
  )
  popd
  if not exist "frontend\dist\index.html" (
    error: frontend build failed - run it manually in frontend\
    pause
    exit /b 1
  )
)

REM 4) run the app
echo [su1ra] starting ^(python: %PYTHON_HOME_SET%!VIRTUAL_ENV!^)
".venv\Scripts\python.exe" desktop.py

REM keep the window open if it crashed, so the error is readable
if errorlevel 1 (
  echo.
  echo [su1ra] exited with an error - window kept open.
  pause
)
endlocal
