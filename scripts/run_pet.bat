@echo off
REM ============================================================
REM  MiniMax Pet - start the pet
REM  启动桌宠（会自动切到脚本所在目录）
REM
REM  不带参数时自动加 --resume：清掉「用户主动退出桌宠」的暂停标记，
REM  所以双击本文件就能把手动关掉的桌宠重新拉起来。带了参数就原样传。
REM
REM  NOTE: keep this file ASCII-only. cmd.exe reads .bat in the console
REM  codepage (936 here); UTF-8 Chinese comments get mis-decoded into
REM  garbage and cmd then tries to execute the fragments as commands.
REM ============================================================
setlocal
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
    echo [MiniMax Pet] python not found in PATH.
    echo [MiniMax Pet] Install Python 3.9+ from https://www.python.org/downloads/
    echo [MiniMax Pet] 未找到 python，请先从 https://www.python.org/downloads/ 安装 Python 3.9+
    pause
    exit /b 1
)

python -c "import PyQt5" >nul 2>nul
if errorlevel 1 (
    echo [MiniMax Pet] Installing PyQt5 ...
    echo [MiniMax Pet] 正在安装 PyQt5，请稍候……
    python -m pip install PyQt5
)

if "%~1"=="" (python minimax_pet.py --resume) else (python minimax_pet.py %*)
if errorlevel 1 pause
endlocal
