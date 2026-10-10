@echo off
cd /d "%~dp0"
set UV_CACHE_DIR=%CD%\.cache\uv
set NEXT_TELEMETRY_DISABLED=1
where uv >nul 2>nul
if errorlevel 1 (
  echo Install uv or use the manual setup instructions in README.md.
  exit /b 1
)
if not exist .venv\Scripts\python.exe uv venv --python 3.13 .venv
if errorlevel 1 exit /b 1
uv pip install --python .venv\Scripts\python.exe -r requirements.lock
if errorlevel 1 exit /b 1
if not exist .env copy .env.example .env
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m synthetic_data generate --all --seed 42
if errorlevel 1 exit /b 1
cd frontend
call npm.cmd ci --cache ..\.cache\npm --no-audit --no-fund
if errorlevel 1 exit /b 1
if not exist public mkdir public
copy /y node_modules\pdfjs-dist\build\pdf.worker.min.mjs public\pdf.worker.min.mjs >nul
call npm.cmd run build
if errorlevel 1 exit /b 1
cd ..
echo Setup complete. Run start-local.cmd.
