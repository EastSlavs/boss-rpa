@echo off
setlocal
cd /d "%~dp0"
echo Installing in a local .venv - Python 3.10 to 3.12 x64 required.
if exist ".venv\Scripts\python.exe" goto install
py -3.12 -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 (
  py -3.12 -m venv .venv
  goto check
)
py -3.11 -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 (
  py -3.11 -m venv .venv
  goto check
)
py -3.10 -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 (
  py -3.10 -m venv .venv
  goto check
)
python -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,12) and sys.maxsize > 2**32" >nul 2>&1
if errorlevel 1 (
  echo Please install Python 3.12 x64 and enable the Python launcher or Add to PATH.
  pause
  exit /b 1
)
python -m venv .venv
:check
if not exist ".venv\Scripts\python.exe" (
  echo Failed to create .venv.
  pause
  exit /b 1
)
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installation failed. Check network and Python version.
  pause
  exit /b 1
)
echo Done. Run start_preview.bat first, then start_auto.bat when ready.
pause
