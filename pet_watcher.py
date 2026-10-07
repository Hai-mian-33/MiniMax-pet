# -*- coding: utf-8 -*-
"""
pet_watcher.py —— 待命哨兵（无界面）
==============================================================================
登录时由 Startup 里的 MiniMaxPet.vbs 拉起。它**什么都不显示**：没有窗口、
没有托盘图标、连 PyQt5 都不 import，只做一件事——盯着 MiniMax Code 的进程。

    MiniMax Code 进程「无 → 有」 → 用 pythonw 拉起 minimax_pet.py
    MiniMax Code 进程「有 → 无」 → 桌宠自己退出（exit_with_app 默认已改开）

于是开机后桌面上不会出现任何东西，直到你真的打开 MiniMax Code。

为什么不让桌宠自己「隐藏着等」
------------------------------------------------------------------------------
那样进程会**无条件常驻**，登录后哪怕你一周不开 MiniMax Code，它也一直挂着；
而且要卡住「MiniMax Code 启动」这个时机，只能改它的配置或装钩子。拆成
「一个十几 MB 的空转进程 + 用完即退的桌宠进程」之后，桌宠才是真正的同生共死：
开就出来，关就走人。

本进程常驻是有意为之的：它是唯一能在 MiniMax Code 下次启动时立刻反应的东西。
但它不占托盘、不占任务栏（pythonw 无窗口），关掉 MiniMax Code 也不会多留
一个看得见的进程。

用法：
    python pet_watcher.py             正常就是被 VBS 拉起，不用手动跑
    python pet_watcher.py --status    看一眼待命哨兵 / 桌宠是否在跑
    python pet_watcher.py --lang en   指定日志语言（默认读上次选择）
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

# 只 import i18n（纯 os 实现，不碰 Qt），保持「文案单一真源」
from i18n import t, set_lang, get_lang, system_lang

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.join(BASE, "minimax_pet.py")
LOG_PATH = os.path.join(BASE, "watcher.log")
LOCK_PATH = os.path.join(BASE, ".watcher.lock")
STATE_PATH = os.path.join(BASE, "pet_state.json")

POLL_SEC = 1.5
APP_PROCESS_HINT = "minimax code"

# 控制台里标签要左对齐。中英标签的「显示宽度」差别很大，所以按终端列宽
# （中文/全角算 2 列）补空格，而不是按 len()。
_PAD_COLS = 16


def _cols(s):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in s)

# MiniMax Code 进程名特征（实测 exe = "MiniMax Code.exe"）
try:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
except Exception:      # pragma: no cover - 非 Windows
    _k32 = None


def log(msg):
    """独立日志，不和桌宠抢 pet.log（两个进程同时写会互相干扰清空逻辑）。"""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 256 * 1024:
            open(LOG_PATH, "w", encoding="utf-8").close()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + str(msg) + "\n")
    except Exception:
        pass


# ========== 进程探测（与 minimax_pet 同源，但这里不 import Qt）==========
class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def _iter_processes():
    if _k32 is None:
        return
    snap = _k32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snap == -1 or snap == 0xFFFFFFFF:
        return
    e = _PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    try:
        if _k32.Process32FirstW(snap, ctypes.byref(e)):
            while True:
                yield str(e.szExeFile)
                if not _k32.Process32NextW(snap, ctypes.byref(e)):
                    break
    finally:
        _k32.CloseHandle(snap)


def app_running():
    """MiniMax Code 是否在跑。探测失败时按「在跑」处理，宁可多留不可误退。"""
    if _k32 is None:
        return True
    try:
        for exe in _iter_processes():
            if APP_PROCESS_HINT in exe.lower():
                return True
        return False
    except Exception:
        return True


# ========== 单实例锁 ==========
def acquire_lock():
    """返回持有锁的文件句柄；拿不到说明已有一个哨兵在跑。"""
    try:
        import msvcrt
        f = open(LOCK_PATH, "a+b")
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return f
    except Exception:
        return None


# ========== 拉起桌宠 ==========
def _pet_argv():
    """用 pythonw 拉起桌宠，避免每次开应用都闪一个黑框。"""
    pyw = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    # 显式带上 --exit-with-app：即使状态文件里被人改过，这里也保证
    # 「MiniMax Code 退出 → 桌宠退出」这条不受托盘勾选影响
    return [pyw, PET, "--exit-with-app"]


def spawn_pet():
    if not os.path.exists(PET):
        log(t("watch.no_pet", PET))
        return False
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(_pet_argv(), creationflags=flags, close_fds=True)
        log(t("watch.spawned"))
        return True
    except Exception as e:
        log(t("watch.spawn_fail", e))
        return False


def lock_held_by_other():
    """只探测「有没有别人锁着」，不会自己把锁拿走。

    不能直接调 acquire_lock() 做状态查询——那会把锁真的抢过来，
    正在跑的哨兵下次续租就断了。
    """
    try:
        import msvcrt
        f = open(LOCK_PATH, "a+b")
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return True               # 拿不到 = 已有哨兵在跑
        f.close()                     # 立刻放回
        return False
    except Exception:
        return False


def _running_cmdlines():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue).CommandLine"],
            capture_output=True, text=True, errors="replace", timeout=25)
        return out.stdout or ""
    except Exception:
        return ""


def _row(label, value):
    head = label + ":"
    print("  " + head + " " * max(1, _PAD_COLS - _cols(head)) + value)


def status():
    _row(t("watch.row_watcher"),
         t("watch.yes") if lock_held_by_other() else t("watch.no"))
    cl = _running_cmdlines().lower()
    _row(t("watch.row_pet"),
         t("watch.yes") if "minimax_pet.py" in cl else t("watch.pet_idle"))
    _row(t("watch.row_app"),
         t("watch.yes") if app_running() else t("watch.no"))
    _row(t("watch.row_log"), LOG_PATH)
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            tail = [l.rstrip() for l in f.readlines()[-6:]]
        for l in tail:
            print("   " + l)
    except Exception:
        pass


def _resolve_lang(argv):
    """返回 --lang 的值，并把它（连同它的参数）从 argv 里摘掉。"""
    rest, lang = [], None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
            i += 2
            continue
        if a.startswith("--lang="):
            lang = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    return lang, rest


def main():
    _lang, rest = _resolve_lang(sys.argv[1:])
    try:
        import json
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            _saved = (json.load(f) or {}).get("lang")
    except Exception:
        _saved = None
    set_lang(_lang or _saved or system_lang())

    if "--status" in rest:
        status()
        return 0

    lock = acquire_lock()
    if lock is None:
        log(t("watch.already"))
        return 0

    log(t("watch.start"))
    was = False
    while True:
        now = app_running()
        if now != was:
            if now:
                log(t("watch.app_seen"))
                spawn_pet()
            else:
                log(t("watch.app_gone"))
            was = now
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)