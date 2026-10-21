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
# ---- 运行时状态目录：固定在 MiniMax Code 自己的配置目录下 -------------
# 跟代码目录无关（详见 minimax_pet.py 里的同一段说明）：配置落在
# %USERPROFILE%\.minimax\MiniMaxPet\，代码目录可以随时删。
# 需要放到别处时用环境变量 MINIMAX_PET_HOME 覆盖。
_STATE_HOME = os.environ.get("MINIMAX_PET_HOME") or os.path.join(
    os.path.expanduser("~"), ".minimax", "MiniMaxPet")
try:
    os.makedirs(_STATE_HOME, exist_ok=True)
except Exception:
    pass
STATE_PATH = os.path.join(_STATE_HOME, "pet_state.json")
PAUSE_PATH = os.path.join(_STATE_HOME, "pet_paused.flag")
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
    """pythonw 进程的命令行**列表**（小写，每行一个）。

    注意不能用 `tasklist` 匹配命令行——它的 CSV 输出里根本没有命令行字段，
    永远匹配不上。

    ⚠️ 这里必须返回**列表**。以前返回的是「把所有命令行拼成的一整块文本」，
    再拿 `"pet_watcher.py" in cl` 做子串判断——本机同时装着另外两个桌宠，
    它们的路径里正好含有这个子串，于是本项目的 status 把**别人的进程当成
    自己的**，一律报「在跑 ✓」。出问题时这句话极具误导性。
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" "
             "-ErrorAction SilentlyContinue).CommandLine"],
            capture_output=True, text=True, errors="replace", timeout=25)
        return [ln.strip().lower() for ln in (out.stdout or "").splitlines()
                if ln.strip()]
    except Exception:
        return []


def _mine(script, lines):
    """命令行里有没有**本项目**的这个脚本。

    要求同时命中脚本名和项目目录名（minimax-pet），这样别的项目里同名的
    pet_watcher.py 不会被认成我们的。
    """
    proj = os.path.basename(BASE).lower()
    return any(script in ln and proj in ln for ln in lines)


def _pet_http():
    """探桌宠的 HTTP 端口，并且**确认回话确实是它**。

    只 connect 不说话是有坑的：8766 被别的程序占着时也算「桌宠在跑」。
    这里 GET 一下并检查正文里的特征串。
    """
    for p in range(8766, 8777):
        s = socket.socket()
        s.settimeout(0.6)
        try:
            s.connect(("127.0.0.1", p))
            s.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            buf = b""
            while len(buf) < 400:
                chunk = s.recv(200)
                if not chunk:
                    break
                buf += chunk
            if b"minimax pet ok" in buf.lower():
                return True
        except Exception:
            continue
        finally:
            s.close()
    return False


def _pet_running():
    """桌宠是否在跑。

    先探 HTTP 端口（快、无子进程）并核对回话内容；探不到再查进程命令行，
    用来覆盖 `--no-server` 关掉 HTTP 的情况。
    """
    if _pet_http():
        return True
    return _mine("minimax_pet.py", _cmdlines())


def _watcher_running():
    return _mine("pet_watcher.py", _cmdlines())


def _pause_left():
    """「用户手动退出过桌宠」的剩余秒数；没在暂停返回 0。"""
    try:
        with open(PAUSE_PATH, "r", encoding="utf-8-sig") as f:
            ts = float(f.read().strip() or 0)
        left = ts - time.time()
        return int(left) if 0 < left <= 3 * 24 * 3600 else 0
    except Exception:
        return 0


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
    left = _pause_left()
    if left:
        print(t("auto.paused") + ": "
              + t("auto.paused_left", left // 60))
    print(t("auto.row_keepalive") + ": "
          + (t("auto.keepalive_on") if _task_present() else t("auto.keepalive_off")))
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


# ========== 计划任务：定时「确保有人活着」 ==========
# 互相看门有个绕不过去的盲区：哨兵和桌宠在同一瞬间一起没了，就再也没人
# 拉起它们（登录启动项只在登录那一刻跑一次）。计划任务定期跑
# `pet_watcher.py --ensure` 把这个状态补上。
#
# ⚠️ 用的是 --ensure 而不是 --resume：resume 会清掉「用户主动退出桌宠」的
# 暂停标记，定时清的话你手动关掉的桌宠 5 分钟后自己就回来了。ensure 尊重
# 暂停，只负责「没人看门了」这一种情况。
TASK_NAME = "MiniMaxPetKeepAlive"
TASK_MINUTES = 5


def _task_present():
    try:
        out = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True, text=True, errors="replace", timeout=30)
        return out.returncode == 0
    except Exception:
        return False


def _ps(script):
    """跑一段 PowerShell，返回 (rc, stdout+stderr)。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, errors="replace", timeout=120)
        return out.returncode, ((out.stdout or "") + (out.stderr or "")).strip()
    except Exception as e:
        return 1, str(e)


def keepalive_on():
    """建一个每 5 分钟跑一次 --ensure 的计划任务。"""
    if _task_present():
        print(t("auto.keepalive_recreate"))
        keepalive_off()
    exe = pythonw_path()
    arg = '"%s" --ensure' % WATCHER
    # 交互式登录（InteractiveToken）：必须跑在用户自己的会话里，否则它拉起
    # 的桌宠虽然是 GUI 进程，却不在你的桌面上。
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "$a = New-ScheduledTaskAction -Execute '%s' -Argument '%s'\n"
        "$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
        "-RepetitionInterval (New-TimeSpan -Minutes %d)\n"
        "$t.Repetition.Duration = 'P3650D'\n"
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -StartWhenAvailable "
        "-MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)\n"
        "$p = New-ScheduledTaskPrincipal -UserId (\"$env:USERDOMAIN\\$env:USERNAME\") "
        "-LogonType Interactive -RunLevel Limited\n"
        "Unregister-ScheduledTask -TaskName '%s' -Confirm:$false "
        "-ErrorAction SilentlyContinue\n"
        "Register-ScheduledTask -TaskName '%s' -Action $a -Trigger $t -Settings $s "
        "-Principal $p -Description 'MiniMax Pet keepalive' | Out-Null\n"
        "Write-Output 'CREATED'\n"
        % (exe.replace("'", "''"), arg.replace("'", "''"), TASK_MINUTES,
           TASK_NAME, TASK_NAME))
    rc, out = _ps(script)
    if rc != 0 or "CREATED" not in out:
        print(t("auto.keepalive_fail", out))
        return 1
    print(t("auto.keepalive_ok", TASK_NAME, TASK_MINUTES))
    _row(t("auto.row_keepalive_cmd"), exe + " " + arg)
    _row(t("auto.keepalive_note"), t("auto.keepalive_note_txt"))
    _row(t("auto.undo"), t("auto.keepalive_undo_cmd"))
    return 0


def keepalive_off():
    if not _task_present():
        print(t("auto.keepalive_none"))
        return 0
    rc, out = _ps("Unregister-ScheduledTask -TaskName '%s' -Confirm:$false; "
                  "Write-Output 'REMOVED'" % TASK_NAME)
    if rc != 0 or "REMOVED" not in out:
        print(t("auto.keepalive_fail", out))
        return 1
    print(t("auto.keepalive_removed", TASK_NAME))
    return 0


def keepalive_status():
    print(t("auto.row_keepalive") + ": "
          + (t("auto.keepalive_on") if _task_present()
             else t("auto.keepalive_off")))
    if _task_present():
        try:
            out = subprocess.run(
                ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
                capture_output=True, text=True, errors="replace", timeout=30)
            for line in (out.stdout or "").splitlines():
                line = line.strip()
                if line and not line.startswith("Folder:"):
                    print("   " + line)
        except Exception as e:
            print(t("auto.keepalive_fail", e))
    else:
        print(t("auto.keepalive_enable_cmd"))
    return 0


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
    if cmd == "keepalive":
        sub = _rest[1].strip().lower() if len(_rest) > 1 else "status"
        fn2 = {"on": keepalive_on, "off": keepalive_off,
               "status": keepalive_status}.get(sub)
        if fn2 is None:
            sys.stderr.write("用法 / usage: python autostart.py keepalive "
                             "on|off|status\n")
            sys.exit(2)
        sys.exit(fn2() or 0)
    fn = {"on": on, "off": off, "status": status, "verify": verify}.get(cmd)
    if fn is None:
        sys.stderr.write("用法 / usage: python autostart.py on|off|status|verify"
                         "|keepalive on|off|status\n")
        sys.exit(2)
    sys.exit(fn() or 0)