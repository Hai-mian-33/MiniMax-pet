@echo off
REM ============================================================
REM  MiniMax Pet - run the test suite
REM  运行测试（语法 / 双语 key 对齐 / 复数 / 离屏渲染）
REM ============================================================
setlocal
cd /d "%~dp0.."
python tests\run_tests.py %*
if errorlevel 1 pause
endlocal
