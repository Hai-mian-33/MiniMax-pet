@echo off
REM ============================================================
REM  MiniMax Pet - install autostart (start with Windows)
REM  注册开机自启
REM ============================================================
setlocal
cd /d "%~dp0.."
python autostart.py install %*
pause
endlocal
