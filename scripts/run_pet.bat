@echo off
REM ============================================================
REM  MiniMax Pet - start the pet
REM  启动桌宠（会自动切到脚本所在目录）
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

python minimax_pet.py %*
if errorlevel 1 pause
endlocal
