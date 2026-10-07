@echo off
REM ============================================================
REM  MiniMax Pet - remove autostart
REM  取消开机自启
REM ============================================================
setlocal
cd /d "%~dp0.."
python autostart.py uninstall %*
pause
endlocal
