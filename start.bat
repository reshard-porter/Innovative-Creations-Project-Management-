@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 (
    python -m venv .venv
) else (
    py -3 -m venv .venv
)
if errorlevel 1 goto failed
:install
.venv\Scripts\python.exe -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 or newer is required.'"
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe app.py
goto end
:failed
echo Install Python 3.11 or newer and try again.
pause
:end
endlocal
