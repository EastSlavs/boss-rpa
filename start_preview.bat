@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0" || exit /b 1
set "BOSS_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%BOSS_PYTHON%" (
  echo Please run install.bat first.
  pause
  exit /b 1
)
"%BOSS_PYTHON%" -X utf8 main.py --preview
set "BOSS_EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %BOSS_EXIT_CODE%
