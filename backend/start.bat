@echo off
setlocal
chcp 65001 >nul
rem 海关视觉智能识别系统 - Windows 本地启动入口
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m app.main
) else (
  python -m app.main
)
if errorlevel 1 (
  echo.
  echo 启动失败，请检查上面的错误信息。
  pause
)
endlocal
