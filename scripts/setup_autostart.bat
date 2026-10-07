@echo off
REM ============================================================
REM  MiniMax Pet - enable login standby (start with Windows)
REM  开启登录待命：开机后只启动无界面的哨兵，不启动桌宠
REM ============================================================
setlocal
cd /d "%~dp0.."
python autostart.py on %*
pause
endlocal