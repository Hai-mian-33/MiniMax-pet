@echo off
REM ============================================================
REM  MiniMax Pet - check the standby sentinel / pet status
REM  查看待命哨兵与桌宠状态（中英双语）
REM ============================================================
setlocal
cd /d "%~dp0.."
python pet_watcher.py --status %*
pause
endlocal