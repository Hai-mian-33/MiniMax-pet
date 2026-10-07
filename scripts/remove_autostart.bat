@echo off
REM ============================================================
REM  MiniMax Pet - disable login standby
REM  关闭登录待命（删除 Startup 里的 MiniMaxPet.vbs）
REM ============================================================
setlocal
cd /d "%~dp0.."
python autostart.py off %*
pause
endlocal