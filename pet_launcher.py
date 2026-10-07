# -*- coding: utf-8 -*-
"""
MiniMax Pet 单实例静默拉起器
============================
用途：在不方便开命令行的地方（快捷方式、VBS、任务计划）静默启动桌宠。

行为：探测 8766~8776 端口（与 minimax_pet.py 的 EventServer 顺延范围一致），
      已有桌宠在跑就立刻退出；没有就用 pythonw 无窗口拉起一个。
      永远 0 秒退出、永不报错。

注意：本项目不再安装任何钩子，这个脚本不会被 MiniMax Code 自动调用，
      属于纯手动/可选的启动方式。桌宠与 MiniMax Code 的显隐跟随
      是桌宠自己轮询进程实现的，不依赖本脚本。
"""
import os
import socket
import subprocess
import sys
import time

PORT_RANGE = range(8766, 8777)
BASE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.join(BASE, "minimax_pet.py")


def pet_running():
    for port in PORT_RANGE:
        s = socket.socket()
        s.settimeout(0.25)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
    return False


def start_pet():
    py = sys.executable or "pythonw"
    if os.path.basename(py).lower() != "pythonw.exe":
        cand = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.exists(cand):
            py = cand
    flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen([py, PET], close_fds=True, creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     cwd=BASE)


def main():
    try:
        if os.path.exists(PET) and not pet_running():
            start_pet()
            time.sleep(0.2)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
