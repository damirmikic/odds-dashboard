@echo off
cd /d "%~dp0"
where node >nul 2>nul || (echo Node.js is required to build the React app.& pause & exit /b 1)
where npm >nul 2>nul || (echo npm is required to build the React app.& pause & exit /b 1)
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -m pip install -q -r requirements.txt
if not exist frontend\node_modules (
  call npm --prefix frontend install
  if errorlevel 1 (pause & exit /b 1)
)
call npm --prefix frontend run build
if errorlevel 1 (pause & exit /b 1)
%PY% pinnwire_dashboard.py %*
pause
