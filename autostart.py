# -*- coding: utf-8 -*-
"""
autostart.py —— 登录待命哨兵管理（可选）
==============================================================================
用法：
    python autostart.py on      # 开启：登录 Windows 后静默启动「待命哨兵」
    python autostart.py off     # 关闭
    python autostart.py status  # 查看状态并体检
    python autostart.py verify  # 真跑一次 VBS，确认哨兵确实能拉起来

登录时启动的是 pet_watcher.py，不是桌宠本身
------------------------------------------------------------------------------
哨兵不显示任何东西（无窗口、无托盘、不 import Qt），它只盯着 MiniMax Code 的
进程：一发现应用打开，就用 pythonw 把桌宠拉起来；应用一关，桌宠自己退出。
所以开机后桌面上不会出现任何东西，直到你真的打开 MiniMax Code。

关于唯一一次「项目目录之外」的写入
------------------------------------------------------------------------------
本项目对 MiniMax Code 是纯只读的，登录待命是唯一需要在项目外留痕的动作，
所以只写**一个文件**：

    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\MiniMaxPet.vbs

里面只有一行「用 pythonw 无窗口跑本项目的 pet_watcher.py」，不含任何配置，
不碰 MiniMax Code，也不碰注册表。`off` 就是删掉它。

为什么写绝对路径而不是 `pythonw`
------------------------------------------------------------------------------
Startup 项在登录时由 WSH 执行，那时的 PATH 未必带 Python。写死当前解释器的
pythonw 绝对路径才稳；万一以后 Python 搬家，`status` 会明确告诉你失效了。
"""
import os
import socket
import subprocess
import sys
import time

from i18n import t, set_lang, get_lang, system_lang

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.join(BASE, "minimax_pet.py")
WATCHER = os.path.join(BASE, "pet_watcher.py")
STATE_PATH = os.path.join(BASE, "pet_state.json")
STARTUP = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                       "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
VBS = os.path.join(STARTUP, "MiniMaxPet.vbs")

# 控制台里标签要左对齐。中英标签的「显示宽度」差别很大，所以按终端列宽
# （中文/全角算 2 列）补空格，而不是按 len()。
_PAD_COLS = 16


def _cols(s):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in s)


def _row(label, value):
    head = label + ":"
    print("  " + head + " " * max(1, _PAD_COLS - _cols(head)) + value)


def pythonw_path():
    """当前解释器旁边的 pythonw.exe；找不到就退回 PATH 上的 pythonw。"""
    cand = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "pythonw.exe")
    if os.path.exists(cand):
        return cand
    return "pythonw"


def vbs_content():
    # WSH 只认真 ANSI 编码，路径含中文时必须按 mbcs 写，不能用 utf-8
    return ('CreateObject("WScript.Shell").Run """{0}"" ""{1}""", 0, False\r\n'
            .format(pythonw_path(), WATCHER))


def on():
    os.makedirs(STARTUP, exist_ok=True)
    body = vbs_content()
    try:
        with open(VBS, "w", encoding="mbcs", newline="") as f:
            f.write(body)
    except (LookupError, UnicodeEncodeError):
        with open(VBS, "w", encoding="ascii", errors="replace", newline="") as f:
            f.write(body)
        print(t("auto.warn_ascii"))
    print(t("auto.on_ok"))
    _row(t("auto.trigger"), VBS)
    _row(t("auto.interp"), pythonw_path())
    _row(t("auto.watcher"), WATCHER)
    _row(t("auto.pet"), PET + " " + t("auto.pet_note"))
    _row(t("auto.undo"), t("auto.undo_cmd"))


def off():
    if os.path.exists(VBS):
        os.remove(VBS)
        print(t("auto.off_ok", VBS))
    else:
        print(t("auto.off_none"))


def _port_open(port, timeout=0.3):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def _cmdlines():
    """pythonw 进程的命令行列表（小写）。

    注意不能用 `tasklist` 匹配命令行——它的 CSV 输出里根本没有命令行字段，
    永远匹配不上。
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" "
             "-ErrorAction SilentlyContinue).CommandLine"],
            capture_output=True, text=True, errors="replace", timeout=25)
        return (out.stdout or "").lower()
    except Exception:
        return ""


def _pet_running():
    """桌宠是否在跑。

    先探 HTTP 端口（快、无子进程）；探不到再查进程命令行，用来覆盖
    `--no-server` 关掉 HTTP 的情况。
    """
    for p in range(8766, 8777):
        if _port_open(p):
            return True
    return "minimax_pet.py" in _cmdlines()


def _watcher_running():
    return "pet_watcher.py" in _cmdlines()


def status():
    print(t("auto.row_trig") + ": "
          + (t("auto.on") + " -> " + VBS if os.path.exists(VBS) else t("auto.off")))
    print(t("auto.row_watcher") + ": "
          + (t("auto.exists") if os.path.exists(WATCHER)
             else t("auto.missing") + " " + WATCHER))
    print(t("auto.row_pet") + ": "
          + (t("auto.exists") if os.path.exists(PET)
             else t("auto.missing") + " " + PET))
    pw = pythonw_path()
    if os.path.isabs(pw):
        print(t("auto.row_interp") + ": "
              + (t("auto.exists") if os.path.exists(pw)
                 else t("auto.missing") + " " + pw))
    else:
        print(t("auto.row_interp") + ": " + pw + " " + t("auto.interp_path"))
    print(t("auto.row_running") + ": "
          + (t("auto.v_yes") if _watcher_running() else t("auto.v_no")))
    print(t("auto.row_pet_running") + ": "
          + (t("auto.v_yes") if _pet_running() else t("auto.pet_not_running")))
    if os.path.exists(VBS):
        try:
            with open(VBS, "r", encoding="mbcs") as f:
                print(t("auto.row_vbs") + ": " + f.read().strip())
        except Exception as e:
            print(t("auto.row_vbs") + ": " + t("auto.vbs_fail", e))


def verify():
    """真跑一次 VBS（等价于登录时 WSH 的行为），确认哨兵真的被拉起来。"""
    if not os.path.exists(VBS):
        print(t("auto.verify_first"))
        return 1
    before = _watcher_running()
    print(t("auto.v_before") + ": "
          + (t("auto.v_already") if before else t("auto.v_not"))
          + " / " + t("auto.row_pet") + ": "
          + (t("auto.v_pet_ok") if _pet_running() else t("auto.v_not")))
    try:
        subprocess.run(["cscript", "//nologo", VBS], capture_output=True, timeout=30)
    except Exception as e:
        print(t("auto.wsh_fail", e))
        return 1
    time.sleep(4.0)
    after = _watcher_running()
    print(t("auto.v_after") + ": " + (t("auto.v_ok") if after else t("auto.v_fail")))
    print("  " + t("auto.row_pet") + ": "
          + (t("auto.v_pet_ok") if _pet_running() else t("auto.v_pet_idle")))
    if after and not before:
        print(t("auto.v_works"))
        return 0
    if before and after:
        print(t("auto.v_single"))
        return 0
    print(t("auto.v_broken"))
    return 1


def _resolve_lang(argv):
    """返回 --lang 的值，并把它（连同它的参数）从 argv 里摘掉。

    不摘掉的话 `python autostart.py --lang en status` 会把 --lang
    当成子命令，直接报 usage。
    """
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


if __name__ == "__main__":
    _lang, _rest = _resolve_lang(sys.argv[1:])
    try:
        import json
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            _saved = (json.load(f) or {}).get("lang")
    except Exception:
        _saved = None
    set_lang(_lang or _saved or system_lang())

    cmd = _rest[0].strip().lower() if _rest else "status"
    fn = {"on": on, "off": off, "status": status, "verify": verify}.get(cmd)
    if fn is None:
        sys.stderr.write("用法 / usage: python autostart.py on|off|status|verify\n")
        sys.exit(2)
    sys.exit(fn() or 0)