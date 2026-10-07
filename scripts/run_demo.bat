@echo off
REM ============================================================
REM  MiniMax Pet - run the demo (no real sessions touched)
REM  演示一轮合成任务，不碰真实会话
REM ============================================================
setlocal
cd /d "%~dp0.."
python minimax_pet.py --demo %*
endlocal
