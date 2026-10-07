@echo off
REM ============================================================
REM  MiniMax Pet - regenerate the bilingual screenshots
REM  重新生成中英双语截图到 docs\images\
REM ============================================================
setlocal
cd /d "%~dp0.."
echo [1/2] Rendering zh ...
python minimax_pet.py --lang zh --selftest
echo [2/2] Rendering en ...
python minimax_pet.py --lang en --selftest
echo.
echo Done. Screenshots are in docs\images\  完成，截图在 docs\images\
endlocal
