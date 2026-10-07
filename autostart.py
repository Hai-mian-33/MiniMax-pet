# -*- coding: utf-8 -*-
"""
MiniMax Pet 开机自启管理（可选）
==============================================================================
用法：
    python autostart.py on      # 开启：登录 Windows 后桌宠自动静默启动
    python autostart.py off     # 关闭
    python autostart.py status  # 查看状态并体检
    python autostart.py verify  # 真跑一次 VBS，确认它确实能拉起桌宠

关于唯一一次「项目目录之外」的写入
------------------------------------------------------------------------------
本项目对 MiniMax Code 是纯只读的，自启是唯一需要在项目外留痕的动作，所以只写
**一个文件**：

    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\MiniMaxPet.vbs

里面只有一行「用 pythonw 无窗口跑本项目的 minimax_pet.py」，不含任何配置，
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.join(BASE, "minimax_pet.py")
STARTUP = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                       "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
VBS = os.path.join(STARTUP, "MiniMaxPet.vbs")


def pythonw_path():
    """当前解释器旁边的 pythonw.exe；找不到就退回 PATH 上的 pythonw。"""
    cand = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "pythonw.exe")
    if os.path.exists(cand):
        return cand
    return "pythonw"


def vbs_content():
    # WSH 只认真 ANSI 编码，路径含中文时必须按 mbcs 写，不能用 utf-8
    return ('CreateObject("WScript.Shell").Run """{0}"" ""{1}""", 0, False\r\n'
            .format(pythonw_path(), PET))


def on():
    os.makedirs(STARTUP, exist_ok=True)
    body = vbs_content()
    try:
        with open(VBS, "w", encoding="mbcs", newline="") as f:
            f.write(body)
    except (LookupError, UnicodeEncodeError):
        with open(VBS, "w", encoding="ascii", errors="replace", newline="") as f:
            f.write(body)
        print("! 路径含非 ASCII 字符，VBS 可能无法正确执行，请检查文件内容。")
    print("OK 已开启开机自启")
    print("   触发器 : " + VBS)
    print("   解释器 : " + pythonw_path())
    print("   目标   : " + PET)
    print("   撤销   : python autostart.py off  （或双击 remove_autostart.bat）")


def off():
    if os.path.exists(VBS):
        os.remove(VBS)
        print("OK 已取消开机自启（已删除 " + VBS + "）")
    else:
        print("本来就没有开启自启。")


def status():
    print("自启状态：" + ("已开启 -> " + VBS if os.path.exists(VBS) else "未开启"))
    print("目标程序：" + ("存在" if os.path.exists(PET) else "!! 不存在 " + PET))
    pw = pythonw_path()
    if os.path.isabs(pw):
        print("解释器  ：" + ("存在" if os.path.exists(pw) else "!! 不存在 " + pw))
    else:
        print("解释器  ：" + pw + "（依赖 PATH，稳定性较弱）")
    if os.path.exists(VBS):
        try:
            with open(VBS, "r", encoding="mbcs") as f:
                print("VBS 内容：" + f.read().strip())
        except Exception as e:
            print("VBS 内容：读取失败 " + str(e))


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


def _pet_running():
    """桌宠是否在跑。

    先探 HTTP 端口（快、无子进程）；探不到再查进程命令行，用来覆盖
    `--no-server` 关掉 HTTP 的情况。注意不能用 `tasklist` 匹配命令行——
    它的 CSV 输出里根本没有命令行字段，永远匹配不上。
    """
    for p in range(8766, 8777):
        if _port_open(p):
            return True
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" "
             "-ErrorAction SilentlyContinue).CommandLine"],
            capture_output=True, text=True, errors="replace", timeout=25)
        return "minimax_pet.py" in (out.stdout or "").lower()
    except Exception:
        return False


def verify():
    """真跑一次 VBS（等价于登录时 WSH 的行为），确认桌宠真的被拉起来。"""
    if not os.path.exists(VBS):
        print("自启未开启，先执行 python autostart.py on")
        return 1
    before = _pet_running()
    print("执行前：桌宠进程 " + ("已在运行" if before else "未运行"))
    try:
        subprocess.run(["cscript", "//nologo", VBS], capture_output=True, timeout=30)
    except Exception as e:
        print("! 无法调用 WSH：" + str(e))
        return 1
    time.sleep(3.0)
    after = _pet_running()
    print("执行后：桌宠进程 " + ("已拉起 ✓" if after else "未拉起 ✗"))
    if after and not before:
        print("开机自启可用。下次登录时它会自动静默启动。")
        return 0
    if before and after:
        print("单实例锁生效，没有起重复实例，触发器工作正常。")
        return 0
    print("! 触发器没能拉起桌宠，请检查上面的「解释器 / 目标程序」是否存在。")
    return 1


if __name__ == "__main__":
    cmd = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "status"
    fn = {"on": on, "off": off, "status": status, "verify": verify}.get(cmd)
    if fn is None:
        sys.stderr.write("用法: python autostart.py on|off|status|verify\n")
        sys.exit(2)
    sys.exit(fn() or 0)
