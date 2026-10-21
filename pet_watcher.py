# -*- coding: utf-8 -*-
"""
pet_watcher.py —— 待命哨兵（无界面）
==============================================================================
登录时由 Startup 里的 MiniMaxPet.vbs 拉起。它**什么都不显示**：没有窗口、
没有托盘图标、连 PyQt5 都不 import，只做一件事——盯着 MiniMax Code 的进程。

    MiniMax Code 在跑  →  桌宠必须在（状态驱动，不只是边沿触发）
    MiniMax Code 没跑  →  桌宠自己退出（exit_with_app 默认已改开）

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
    python pet_watcher.py --ensure    幂等的「确保有人活着」（Windows 计划任务用）
    python pet_watcher.py --unpause   解除「用户手动退出桌宠」的暂停
    python pet_watcher.py --lang en   指定日志语言（默认读上次选择）
"""
import ctypes
import os
import subprocess
import sys
import tempfile
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
# 桌宠自己的单实例锁（QLockFile），用来判断「桌宠还在不在」
PET_LOCK_PATH = os.path.join(tempfile.gettempdir(), "minimax-pet.lock")
# 用户主动「退出桌宠」的暂停标记
PAUSE_PATH = os.path.join(BASE, "pet_paused.flag")

POLL_SEC = 1.5
APP_PROCESS_HINT = "minimax code"
# 拉起桌宠后多久之内不再重复拉（宽限期）
SPAWN_GRACE = 12.0
# 心跳间隔
HEARTBEAT_SEC = 600.0
# 「用户手动退出桌宠」的暂停时长。纯作兜底：正常路径下暂停只由用户显式解除
# （--unpause / 双击 scripts/run_pet.bat / 重新登录），不会因为应用重开而失效，
# 否则「手动关闭」等于没关。TTL 只是防止标记永久遗留。
PAUSE_TTL = 3 * 24 * 3600.0
_START_TS = time.time()

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
# _PROCESSENTRY32W 必须定义在**模块级**。曾经它写在 _iter_processes() 内部，
# 于是每次调用都新建一个类对象，而 argtypes 里绑定的 POINTER(...) 只认第一次
# 那个类；第二次扫描起 ctypes 就抛 ArgumentError。异常被吞掉之后，
# app_running() 永远返回 False —— 哨兵以为 MiniMax Code 一直没开，桌宠就
# 再也不会被拉起来。这是个非常难查的坑。
class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("th32Threads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


# 不声明 restype 的话，ctypes 按 c_int 返回 HANDLE，64 位下高位会被截断；
# 再把这个被截断的值喂给 CloseHandle，关掉的就不是那个句柄了。
_K32_BOUND = False


def _bind_kernel32():
    global _K32_BOUND
    if _K32_BOUND or _k32 is None:
        return
    try:
        _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        _k32.Process32FirstW.restype = wintypes.BOOL
        _k32.Process32FirstW.argtypes = [wintypes.HANDLE,
                                         ctypes.POINTER(_PROCESSENTRY32W)]
        _k32.Process32NextW.restype = wintypes.BOOL
        _k32.Process32NextW.argtypes = [wintypes.HANDLE,
                                        ctypes.POINTER(_PROCESSENTRY32W)]
        _k32.CloseHandle.restype = wintypes.BOOL
        _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    except Exception:
        pass
    _K32_BOUND = True


def _iter_processes():
    if _k32 is None:
        return
    _bind_kernel32()
    snap = _k32.CreateToolhelp32Snapshot(0x00000002, 0)
    if not snap or snap == 0xFFFFFFFF:
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


# ========== 暂停标记（用户手动退出桌宠）==========
def paused():
    """用户主动退出过桌宠？暂停期间不拉它。"""
    try:
        with open(PAUSE_PATH, "r", encoding="utf-8") as f:
            ts = float(f.read().strip() or 0)
    except Exception:
        return False
    if ts <= 0:
        return False
    now = time.time()
    if ts - now > PAUSE_TTL:          # 内容损坏或被改过 -> 当作没有
        return False
    return now < ts


def pause_remaining():
    """还剩几秒解除暂停；没在暂停返回 0。"""
    try:
        with open(PAUSE_PATH, "r", encoding="utf-8") as f:
            ts = float(f.read().strip() or 0)
        left = ts - time.time()
        return int(left) if 0 < left <= PAUSE_TTL else 0
    except Exception:
        return 0


def set_pause(seconds=PAUSE_TTL):
    """由桌宠在「用户主动退出」时调用。"""
    try:
        with open(PAUSE_PATH, "w", encoding="utf-8") as f:
            f.write("%.0f" % (time.time() + seconds))
    except Exception:
        pass


def clear_pause():
    try:
        os.remove(PAUSE_PATH)
    except Exception:
        pass


# ========== 桌宠在不在（靠它自己的单实例锁）==========
def pet_running():
    """桌宠是否在跑（**不限于**是不是本哨兵拉起来的那个）。

    靠桌宠自己的单实例锁来判断。QLockFile 在 Windows 上会以独占方式持有
    %TEMP%\\minimax-pet.lock，所以：
        连 open() 都被拒      -> 文件正被别人占着 -> 桌宠活着
        能打开但字节锁抢不到   -> 有人锁着           -> 桌宠活着
        能打开且锁也能抢到     -> 没人锁             -> 桌宠没了

    ⚠️ 本函数必须**只读**：既不能用 "a+b" 创建/写入这个文件，也不能往里写
    任何字节。曾经这里对空文件写了个 b"0"，而桌宠干净退出时 Qt 会把锁文件
    清空——于是文件内容变成 "0"，QLockFile 从此**永久**拒绝加锁。后果是桌宠
    再也起不来，而哨兵会变成每 20 秒拉一个、每个 1 秒退、桌面永远空着的
    死循环。这个坑非常隐蔽，因为 QLockFile 抢锁失败时只 print，
    pythonw 下谁也看不见。

    除 FileNotFoundError（文件不存在 = 桌宠没在跑）外，任何异常都返回 True：
    宁可漏拉也不制造拉起风暴。
    """
    try:
        import msvcrt
        try:
            f = open(PET_LOCK_PATH, "r+b")        # r+b：只读打开，绝不创建
        except FileNotFoundError:
            return False                          # 文件都没有 = 没有桌宠
        except PermissionError:
            return True                           # 被独占 = 桌宠在跑
        except OSError:
            return True
        try:
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return True                       # 字节锁抢不到 = 桌宠在跑
            return False                          # 打开成功 + 锁也抢到 = 桌宠没了
        finally:
            try:
                f.close()
            except Exception:
                pass
    except Exception:
        return True


def break_pet_lock(reason):
    """删掉桌宠的单实例锁文件，让下一次启动有机会重新建一个。

    只在确认「连续多次拉起都被单实例锁挡回、却根本没有桌宠在跑」时才调用
    ——那种情况一定是锁文件本身坏了。
    """
    try:
        if os.path.exists(PET_LOCK_PATH):
            with open(PET_LOCK_PATH, "r", encoding="utf-8", errors="replace") as f:
                bad = f.read(120)
            os.remove(PET_LOCK_PATH)
            log(t("watch.lock_broken", reason, bad))
            return True
    except Exception as e:
        log(t("watch.lock_break_fail", e))
    return False


def _pythonw():
    pyw = os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                       "pythonw.exe")
    if os.path.exists(pyw):
        return pyw
    return sys.executable


def spawn_watcher():
    """桌宠反拉哨兵用（互相看门）。"""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([_pythonw(), os.path.abspath(__file__)],
                         creationflags=flags, close_fds=True)
        log(t("watch.watcher_spawned"))
        return True
    except Exception as e:
        log(t("watch.watcher_spawn_fail", e))
        return False


# ========== 拉起桌宠 ==========
def _pet_argv():
    """用 pythonw 拉起桌宠，避免每次开应用都闪一个黑框。"""
    # 显式带上 --exit-with-app：即使状态文件里被人改过，这里也保证
    # 「MiniMax Code 退出 → 桌宠退出」这条不受托盘勾选影响
    return [_pythonw(), PET, "--exit-with-app"]


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


# ========== 命令行扫描（按项目目录锚定）==========
def _running_cmdlines():
    """全部进程命令行的**列表**（小写）。

    ⚠️ 必须返回列表。返回「拼成一整块的文本」再 `"minimax_pet.py" in cl`
    是脆弱的子串匹配——本机还装着另外两个桌宠，只要哪个项目的路径里恰好
    含有同样的片段，status 就会把别人的进程当成自己的。
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue).CommandLine"],
            capture_output=True, text=True, errors="replace", timeout=25)
        return [ln.strip().lower() for ln in (out.stdout or "").splitlines()
                if ln.strip()]
    except Exception:
        return []


def pet_in_cmdlines():
    """命令行里有没有**本项目**的桌宠（要求同时命中项目目录名）。"""
    proj = os.path.basename(BASE).lower()
    return any("minimax_pet.py" in ln and proj in ln
               for ln in _running_cmdlines())


def _row(label, value):
    head = label + ":"
    print("  " + head + " " * max(1, _PAD_COLS - _cols(head)) + value)


def status():
    _row(t("watch.row_watcher"),
         t("watch.yes") if lock_held_by_other() else t("watch.no"))
    _row(t("watch.row_pet"),
         t("watch.yes") if pet_in_cmdlines() else t("watch.pet_idle"))
    _row(t("watch.row_app"),
         t("watch.yes") if app_running() else t("watch.no"))
    left = pause_remaining()
    if left:
        _row(t("watch.row_paused"), t("watch.paused_left", left // 60))
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


def ensure_alive():
    """幂等的「确保有人活着」——给 Windows 计划任务用。

    这是**不能靠互相看门自己解决**的那个盲区：哨兵和桌宠在同一瞬间一起
    没了，就再也没人拉起它们（登录启动项只在登录那一刻跑一次）。定时任务
    定期跑这个函数，把这个状态补上。

    ⚠️ 这里**绝不能**用 --resume 那套逻辑：resume 会清掉「用户主动退出
    桌宠」的暂停标记。定时任务每 5 分钟清一次的话，你手动关掉的桌宠 5 分钟
    后就自己回来了 —— 手动关闭必须真的是关闭。所以：

      · 暂停中（用户手动退出过）-> 什么都不做，尊重用户
      · 哨兵在跑                    -> 什么都不做
      · 哨兵不在                    -> 把哨兵拉起来（哨兵自己会管桌宠）
    """
    try:
        if paused():
            log(t("watch.ensure_paused"))
            return 0
        if lock_held_by_other():
            return 0                      # 哨兵还在，不用管
        log(t("watch.ensure_spawn"))
        spawn_watcher()
    except Exception as e:
        log(t("watch.ensure_fail", e))
    return 0


def main():
    _lang, rest = _resolve_lang(sys.argv[1:])
    try:
        import json
        with open(STATE_PATH, "r", encoding="utf-8-sig") as f:
            _saved = (json.load(f) or {}).get("lang")
    except Exception:
        _saved = None
    set_lang(_lang or _saved or system_lang())

    if "--status" in rest:
        status()
        return 0
    if "--ensure" in rest:
        return ensure_alive()
    if "--unpause" in rest or "--resume" in rest:
        was = pause_remaining()
        clear_pause()
        log(t("watch.unpaused", was // 60))
        print(t("watch.unpaused_msg"))
        return 0

    lock = acquire_lock()
    if lock is None:
        log(t("watch.already"))
        return 0

    log(t("watch.start"))
    # 状态驱动：每一轮都问「应用在吗？桌宠在吗？」，而不是只在边沿动作。
    # 最早的哨兵是纯边沿触发的，只在 MiniMax Code「无 -> 有」那一刻拉一次，
    # 之后桌宠死掉就再也不管了 —— 踩过一次桌面空了一整天的坑。
    was_app = False
    spawned_at = 0.0
    n_respawn = 0
    blocked = 0
    last_beat = time.time()
    while True:
        try:
            now = app_running()
            if now != was_app:
                if now:
                    log(t("watch.app_seen"))
                else:
                    log(t("watch.app_gone"))
                was_app = now

            if not now:
                # 应用不在：不管桌宠的死活（应用重新打开时自然会拉）
                spawned_at = 0.0
                time.sleep(POLL_SEC)
                continue

            if paused():
                # 用户主动退出过桌宠：尊重选择
                if blocked == 0:
                    log(t("watch.paused", pause_remaining() // 60))
                blocked += 1
                time.sleep(POLL_SEC)
                continue
            blocked = 0

            if not pet_running():
                # 桌宠不在了 —— 拉起来。但要留宽限期：刚拉起的那个可能还在
                # 抢单实例锁的途中，这时候再拉一个只会得到一个秒退的副本。
                if time.time() - spawned_at > SPAWN_GRACE:
                    if spawn_pet():
                        spawned_at = time.time()
                        n_respawn += 1

            if time.time() - last_beat > HEARTBEAT_SEC:
                last_beat = time.time()
                pet = t("watch.no") if not pet_running() else t("watch.yes")
                if paused():
                    pet += t("watch.paused_tag")
                log(t("watch.heartbeat", int(time.time() - _START_TS) // 60,
                      n_respawn, pet))
        except Exception:
            # 任何单次异常都不许把哨兵带崩：落盘之后继续跑
            try:
                import traceback
                log(t("watch.tick_fail", traceback.format_exc()))
            except Exception:
                pass
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
