@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=E:\deep\travel-agent\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo  智能旅行助手 · 启动中
echo  运行环境：%PY%
echo ============================================================

"%PY%" server.py --port 8766 --open %*
if errorlevel 1 (
  echo.
  echo [错误] 启动失败。请检查 Python 环境或端口 8766 是否被占用。
  pause
)
endlocal
