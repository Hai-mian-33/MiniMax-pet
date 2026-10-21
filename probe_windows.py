# -*- coding: utf-8 -*-
"""「召唤 MiniMax Code」离屏探针：不碰真实 MiniMax Code 也能验证决策树。

跑法：  python probe_windows.py

分两部分：
  A. 真实 Win32 —— 造一个「线程还在泵消息」的窗口和一个「线程已经卡死」的
     窗口，验证 window_responsive() 真的能区分它们。
  B. 打桩场景 —— 把 app_windows / window_responsive / _kill_stuck / spawn_app
     全部替换掉，逐个走 _activate_win() 的分支，确认：
       · 有活窗口时绝不复活僵死窗口（本 bug 的核心回归）
       · 全僵死 → WM_CLOSE → 结束僵死进程树 → 拉新实例
       · 枚举失败时绝不顺手下拉一个新实例
       · 受保护进程（桌宠的祖先）一律不杀
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minimax_pet as P                                        # noqa: E402

FAILED = []
_REAL_SLEEP = time.sleep          # 打桩时要绕开它自己，不能用 time.sleep


def check(name, cond, extra=""):
    if cond:
        print("  [ok] " + name)
    else:
        print("  [!!] " + name + ("  <- " + extra if extra else ""))
        FAILED.append(name)


# ============ A. 真实 Win32：活窗口 vs 僵死窗口 ============
_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)
_KEEPALIVE = []          # WNDPROC / WNDCLASS 一旦被 GC，窗口类就废了


class _WNDCLASS(ctypes.Structure):
    """ctypes.wintypes 里根本没有 WNDCLASS（只有 WNDCLASSEXW），自己补一个。"""
    _fields_ = [("style", wintypes.UINT),
                ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HMODULE),
                ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(wintypes.DWORD)]
_k32.GetProcessHandleCount.restype = wintypes.BOOL
_k32.GetCurrentProcess.restype = wintypes.HANDLE
_k32.GetModuleHandleW.restype = wintypes.HMODULE
_k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_u32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
_u32.CreateWindowExW.restype = wintypes.HWND
_u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                 wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                 wintypes.HANDLE, wintypes.HINSTANCE,
                                 ctypes.c_void_p]
_u32.DestroyWindow.argtypes = [wintypes.HWND]


_DefWindowProcW = ctypes.windll.user32.DefWindowProcW
_DefWindowProcW.restype = ctypes.c_long
_DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                            wintypes.WPARAM, wintypes.LPARAM]


def _proc(h, m, w, l):
    # 必须走 DefWindowProc：自己 return 1 的话 ShowWindow(SW_MINIMIZE)
    # 根本不会被处理，IsIconic 永远 False，_window_state 就测不准了。
    return _DefWindowProcW(h, m, w, l)


def _make_class(name):
    wc = _WNDCLASS()
    wc.lpfnWndProc = _WNDPROC(_proc)
    wc.hInstance = _k32.GetModuleHandleW(None)
    wc.lpszClassName = name
    _KEEPALIVE.append(wc.lpfnWndProc)
    _KEEPALIVE.append(wc)
    if not _u32.RegisterClassW(ctypes.byref(wc)):
        raise ctypes.WinError()
    return name


def _spawn_window(alive):
    """alive=True：窗口线程照常泵消息；alive=False：建完窗口就一直卡住。"""
    hbox = {}
    started = threading.Event()
    cls = "MiniMaxPetProbe_%d" % time.time_ns()

    def run():
        try:
            _make_class(cls)
            hbox["hwnd"] = _u32.CreateWindowExW(
                0, cls, "MiniMax Code", 0x00CF0000, 0, 0, 320, 200,
                None, None, None, None)
        except Exception as e:
            hbox["err"] = repr(e)
        started.set()
        if alive:
            msg = wintypes.MSG()
            while True:
                if not _u32.GetMessageW(ctypes.byref(msg), None, 0, 0):
                    break
                _u32.TranslateMessage(ctypes.byref(msg))
                _u32.DispatchMessageW(ctypes.byref(msg))
        else:
            while True:                                     # 故意不泵消息 = 僵死
                time.sleep(0.5)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    started.wait(3.0)
    return hbox.get("hwnd", 0)


def test_real_win32():
    print("A. 真实 Win32 探活")
    P._bind_extra()
    h_alive = _spawn_window(True)
    h_dead = _spawn_window(False)
    time.sleep(0.4)
    check("造出活窗口", bool(h_alive))
    check("造出僵死窗口", bool(h_dead))

    t0 = time.time()
    r_alive = P.window_responsive(h_alive, 800)
    check("活窗口判定为 responsive", r_alive,
          "耗时 %.2fs" % (time.time() - t0))

    t0 = time.time()
    r_dead = P.window_responsive(h_dead, 800)
    t2 = time.time() - t0
    check("僵死窗口判定为不 responsive", not r_dead)
    check("僵死探测有超时兜底（<2s）", t2 < 2.0, "%.2fs" % t2)

    # 重复探 5 次，SendMessageTimeout 不能把句柄/线程搞坏
    ok = all(P.window_responsive(h_alive, 400) == r_alive for _ in range(5))
    check("重复探活结果稳定", ok)

    # 关闭窗口收尾，别把桌面留脏
    for h in (h_alive, h_dead):
        try:
            _u32.DestroyWindow(h)
        except Exception:
            pass


def test_window_state():
    """_window_state 是这次修复的核心判定：可见 / 最小化 / 已被关闭。"""
    print("A2. 真实 Win32 窗口状态判定")
    h = _spawn_window(True)
    time.sleep(0.4)
    check("造出窗口", bool(h))
    st = P._window_state(h)
    check("刚建好（未显示）判为 hidden", st == "hidden", st)

    _u32.ShowWindow(h, 5)                 # SW_SHOW
    time.sleep(0.4)
    st = P._window_state(h)
    check("显示后判为 visible", st == "visible", st)

    _u32.ShowWindow(h, 0)                 # SW_HIDE
    time.sleep(0.4)
    st = P._window_state(h)
    check("隐藏后判为 hidden", st == "hidden", st)

    _u32.ShowWindow(h, 5)                 # SW_SHOW
    time.sleep(0.3)
    _u32.ShowWindow(h, 6)                 # SW_MINIMIZE
    time.sleep(0.4)
    st = P._window_state(h)
    check("最小化后判为 minimized", st == "minimized", st)

    # 最小化之后又隐藏：IsIconic 还是真，但用户已经看不见了 —— 必须判 hidden
    _u32.ShowWindow(h, 0)
    time.sleep(0.4)
    st = P._window_state(h)
    check("最小化后再隐藏判为 hidden（不是 minimized）", st == "hidden", st)

    try:
        _u32.DestroyWindow(h)
    except Exception:
        pass


# ============ B. 打桩：逐个走 activate_app() 的分支 ============
class _Stub(object):
    """替身集合。windows 按 hwnd → (title, 状态) 描述。

    状态只有三种，和 _window_state() 对齐：
      visible   窗口本来就开着
      minimized 只是最小化了，渲染进程肯定还活着
      hidden    已经被用户关掉了 —— 复活它只会得到一具僵尸
    """

    def __init__(self, windows):
        self.windows = windows                  # {hwnd: (title, state)}
        self.calls = {"kill": [], "spawn": 0,
                      "front": [], "focus_only": []}
        self.spawn_gives = "spawned"            # spawn_app 的返回
        self.new_window = None                  # 拉起后冒出来的新 hwnd
        self.raise_enumerate = False
        self.kill_ok = ["k1"]
        self.focus_ok = []                      # 置前能成功的 hwnd

    def app_windows(self):
        if self.raise_enumerate:
            raise RuntimeError("枚举失败（模拟）")
        out = [(h, t, st == "visible", 900000)
               for h, (t, st) in self.windows.items()]
        out.sort(key=lambda x: (0 if x[2] else 1, -x[3]))
        return out

    def state(self, hwnd):
        w = self.windows.get(hwnd)
        return w[1] if w else "hidden"

    def responsive(self, hwnd, ms=600):
        # _spawn_and_wait 靠它确认新窗口真的冒出来了
        return hwnd in self.windows

    def focus_only(self, hwnd):
        self.calls["focus_only"].append(hwnd)
        return hwnd in self.focus_ok

    def front(self, hwnd):
        self.calls["front"].append(hwnd)
        return hwnd in self.focus_ok

    def kill_stuck(self, stuck, guard, alive):
        self.calls["kill"].append([d[0] for d in stuck])
        if not self.kill_ok:
            return []
        for w in stuck:                       # 真结束掉，窗口就没了
            self.windows.pop(w[0], None)
        return list(self.kill_ok)

    def spawn(self):
        self.calls["spawn"] += 1
        if self.new_window is not None:
            self.windows = dict(self.windows)
            self.windows[self.new_window] = ("MiniMax Code", "visible")
        return self.spawn_gives

    def ancestor(self):
        return {1, 2}


def run_scenario(name, stub, expect, allow_kill=True):
    """打桩跑一遍 activate_app()，比对该返回的 how。"""
    real = {
        "app_windows": P.app_windows, "window_pid": P.window_pid,
        "window_responsive": P.window_responsive,
        "_window_state": P._window_state, "_focus_only": P._focus_only,
        "_bring_to_front": P._bring_to_front, "_kill_stuck": P._kill_stuck,
        "spawn_app": P.spawn_app, "ancestor_pids": P.ancestor_pids,
        "time.sleep": time.sleep, "CLOSE_GRACE_S": 1.2, "RELAUNCH_WAIT_S": 9.0,
    }
    P.app_windows = stub.app_windows
    P.window_pid = lambda h: 1000 + int(h)
    P.window_responsive = stub.responsive
    P._window_state = stub.state
    P._focus_only = stub.focus_only
    P._bring_to_front = stub.front
    P._kill_stuck = stub.kill_stuck
    P.spawn_app = stub.spawn
    P.ancestor_pids = stub.ancestor
    # P.time 就是全局 time 模块，直接改它的 sleep 会连下面这行一起改掉
    # （自己调自己 = 无限递归）。所以先把真 sleep 抓出来再用。
    P.time.sleep = lambda *_a, **_k: _REAL_SLEEP(0.005)
    P.CLOSE_GRACE_S = 0.0
    P.RELAUNCH_WAIT_S = 0.06
    try:
        res = P.activate_app(allow_kill)
    except Exception as e:                         # pragma: no cover
        res = {"ok": False, "how": "raised", "note": repr(e)}
    finally:
        for k, v in real.items():
            setattr(P, k, v)
    got = (res.get("how"), bool(res.get("ok")))
    check(name, got == expect,
          "得到 %s，期望 %s（%s）" % (got, expect, res.get("note")))
    return res, stub


def test_branches():
    print("B. 分支决策树（打桩，不碰真实进程）")

    # A1 窗口本来就开着 → 只置前，一个 ShowWindow 都不发
    s = _Stub({100: ("MiniMax Code", "visible")})
    s.focus_ok = [100]
    res, s = run_scenario("A1 开着→focus", s, ("focus", True))
    check("A1 没有杀进程", not s.calls["kill"])
    check("A1 没有 spawn", s.calls["spawn"] == 0)

    # A2 只是最小化 → SW_RESTORE 置前（渲染进程确定还活着）
    s = _Stub({100: ("MiniMax Code", "minimized")})
    s.focus_ok = [100]
    res, s = run_scenario("A2 最小化→focus", s, ("focus", True))
    check("A2 置前的是最小化窗口", 100 in s.calls["front"])
    check("A2 没有杀进程", not s.calls["kill"])
    check("A2 没有 spawn", s.calls["spawn"] == 0)

    # A3 可见 + 最小化并存 → 可见优先，不去碰最小化那个
    s = _Stub({100: ("MiniMax Code", "visible"),
               101: ("MiniMax Code", "minimized")})
    s.focus_ok = [100]
    res, s = run_scenario("A3 可见优先", s, ("focus", True))
    check("A3 置前的是可见窗口", 100 in s.calls["focus_only"])

    # ★ 可见窗口 vs 已关闭窗口并存 → 必须用可见那个，不碰关闭那个
    s = _Stub({200: ("MiniMax Code", "hidden"),
               100: ("MiniMax Code", "visible")})
    s.focus_ok = [100]
    res, s = run_scenario("★ 开着时优先用它", s, ("focus", True))
    check("★ 置前的是可见窗口", 100 in s.calls["focus_only"],
          "focus_only=%s" % s.calls["focus_only"])
    check("★ 没碰已关闭的窗口",
          200 not in s.calls["front"] and 200 not in s.calls["focus_only"])
    check("★ 没有杀进程", not s.calls["kill"])
    check("★ 没有 spawn", s.calls["spawn"] == 0)

    # ★★ 本次 bug 的核心：窗口已被关闭 → 绝不置前，必须重启
    s = _Stub({200: ("MiniMax Code", "hidden")})
    s.new_window = 900
    res, s = run_scenario("★★ 已关闭的窗口→relaunch", s, ("relaunch", True))
    check("★★ 清理了残留进程", bool(s.calls["kill"]), "kill=%s" % s.calls["kill"])
    check("★★ 拉起了新实例", s.calls["spawn"] == 1)
    check("★★ 从没把它置前过",
          200 not in s.calls["front"] and 200 not in s.calls["focus_only"])

    # B1 一个窗口都没有 → spawn
    s = _Stub({})
    s.new_window = 900
    res, s = run_scenario("B1 无窗口→spawn", s, ("spawn", True))
    check("B1 确实拉起了", s.calls["spawn"] == 1)

    # C1 后台有任务在跑（allow_kill=False）→ 只还原，不杀不拉
    s = _Stub({200: ("MiniMax Code", "hidden")})
    s.focus_ok = [200]
    res, s = run_scenario("C1 任务在跑→show", s, ("show", True), allow_kill=False)
    check("C1 没有杀进程", not s.calls["kill"])
    check("C1 没有 spawn", s.calls["spawn"] == 0)

    # C2 allow_kill=False 且还原失败 → 也不能去杀
    s = _Stub({200: ("MiniMax Code", "hidden")})
    s.focus_ok = []
    res, s = run_scenario("C2 任务在跑+还原失败", s, ("probe-error", False),
                          allow_kill=False)
    check("C2 依然没有杀进程", not s.calls["kill"])
    check("C2 依然没有 spawn", s.calls["spawn"] == 0)

    # D1 枚举失败 → probe-error，且**绝不能**顺手下拉一个实例
    s = _Stub({100: ("MiniMax Code", "visible")})
    s.raise_enumerate = True
    res, s = run_scenario("D1 枚举失败→probe-error", s, ("probe-error", False))
    check("D1 没有 spawn（防止平白多开）", s.calls["spawn"] == 0)

    # E1 发完 WM_CLOSE 窗口自己回来了 → 直接置前，不杀进程
    s = _Stub({200: ("MiniMax Code", "hidden")})
    s.focus_ok = [100]
    state = {"n": 0}

    def seq():
        state["n"] += 1
        if state["n"] == 1:                          # 第一次：已被关闭
            return [(200, "MiniMax Code", False, 900000)]
        return [(100, "MiniMax Code", True, 900000)]  # 之后：自己回来了
    s.app_windows = seq
    s.windows = {100: ("MiniMax Code", "visible")}
    res, s = run_scenario("E1 WM_CLOSE 后自愈→focus", s, ("focus", True))
    check("E1 没有杀进程", not s.calls["kill"])
    check("E1 没有 spawn", s.calls["spawn"] == 0)

    # F1 拉不动也起不来 → relaunch-failed
    s = _Stub({200: ("MiniMax Code", "hidden")})
    s.new_window = None
    res, s = run_scenario("F1 重拉失败→relaunch-failed", s,
                          ("relaunch-failed", False))

    # G1 找不到 exe → spawn-failed
    s = _Stub({})
    s.spawn_gives = ""
    res, s = run_scenario("G1 无 exe→spawn-failed", s, ("spawn-failed", False))

    # H1 残留进程清不掉（受保护）→ 仍拉新实例
    s = _Stub({200: ("MiniMax Code", "hidden")})
    s.kill_ok = []
    s.new_window = 900
    res, s = run_scenario("H1 清不掉→spawn", s, ("spawn", True))
    check("H1 拉起了新实例", s.calls["spawn"] == 1)


def test_kill_guard():
    print("C. 杀进程的三道闸")
    real_map = P._pid_parent_map
    real_wpid = P.window_pid
    # 1000 是假想僵死窗口的宿主；700 是桌宠自己的祖先链成员
    P._pid_parent_map = lambda: {1000: 500, 1001: 1000,
                                 700: 1, 701: 700,
                                 900: 800, 901: 900}
    P.window_pid = lambda h: {300: 700, 301: 701, 400: 1000,
                              401: 1001, 402: 900}.get(h, 0)
    killed = []
    P._u32 = _FakeU32()
    real_k32 = P._k32
    P._k32 = _FakeK32(killed)

    # C1 祖先链上的窗口 → 一律不杀
    r1 = P._kill_stuck([(300, "t", True, 1)], {700, 701}, [])
    check("C1 祖先链上的僵死窗口不杀", r1 == [], "killed=%s" % r1)

    # C2 僵死窗口和活窗口在**同一棵进程树**里 → 整棵树都不杀
    r2 = P._kill_stuck([(400, "t", True, 1)], {700, 701}, [(401, "t", True, 1)])
    check("C2 同树有活窗口则不杀", r2 == [], "killed=%s" % r2)

    # C3 干净的僵死树 → 子进程一起结束（只收后代，不含已不存在的老祖先）
    r3 = P._kill_stuck([(400, "t", True, 1)], {700, 701}, [])
    check("C3 干净的僵死树会被结束", set(r3) == {1000, 1001},
          "killed=%s" % r3)
    check("C3 祖先链始终没被碰", 700 not in r3 and 701 not in r3)

    # C4 另一棵不相干的僵死树（900）该照杀不误
    r4 = P._kill_stuck([(402, "t", True, 1)], {700, 701}, [])
    check("C4 别的僵死树照杀", set(r4) == {900, 901}, "killed=%s" % r4)

    P._pid_parent_map = real_map
    P.window_pid = real_wpid
    P._k32 = real_k32
    P._u32 = None                                  # 交给后面重新解析
    if P._u32 is None and sys.platform == "win32":
        import ctypes as _c
        P._u32 = _c.windll.user32


class _FakeU32(object):
    """只实现 user32 需要的最小面。"""

    def CloseHandle(self, h):
        return True


class _FakeK32(object):
    """记录被 TerminateProcess 掉的 pid（OpenProcess 在 kernel32，不在 user32）。"""

    def __init__(self, killed):
        self.killed = killed

    def OpenProcess(self, access, inherit, pid):
        return 1000 + int(pid)

    def TerminateProcess(self, h, code):
        self.killed.append(h - 1000)
        return True

    def CloseHandle(self, h):
        return True


def test_helpers():
    print("D. 辅助函数")
    pids = P.app_pids()
    check("D1 app_pids 能认出 MiniMax Code", bool(pids), "pids=%s" % len(pids))
    check("D2 app_running 为真", P.app_running())

    exe = P.app_exe_path()
    check("D3 能定位 exe", bool(exe) and os.path.isfile(exe), str(exe))

    guard = P.ancestor_pids()
    check("D4 祖先链含自己", os.getpid() in guard, str(guard))

    wins = P.app_windows()
    check("D5 能枚举到窗口", isinstance(wins, list), "n=%d" % len(wins))
    alive, dead = P._split_windows(wins)
    check("D6 活/僵能劈开", isinstance(alive, list) and isinstance(dead, list),
          "alive=%d dead=%d" % (len(alive), len(dead)))
    for w in wins[:3]:
        print("      窗口 hwnd=%s alive=%s visible=%s title=%r"
              % (w[0], P.window_responsive(w[0], 400), w[2], w[1][:40]))

    m = P._pid_parent_map()
    check("D7 父子表非空", len(m) > 50, "n=%d" % len(m))
    tree = P._collect_tree(1000, {1000: 500, 1001: 1000, 2000: 1001, 3000: 9})
    check("D8 进程树收集正确", set(tree) == {1000, 1001, 2000}, str(tree))

    # _bring_to_front 对空 / 脏 hwnd 不能抛
    try:
        P._bring_to_front(0)
        ok = True
    except Exception:
        ok = False
    check("D9 _bring_to_front 容错", ok)

    # D10 签名必须真的绑上了（曾经把 OpenProcess 写成 user32.OpenProcess，
    #      异常被吞掉之后，后面几条签名全都没绑，静默退化成句柄截断）
    P._bind_extra()
    check("D10 _k32.OpenProcess 签名已绑",
          P._k32.OpenProcess.restype is wintypes.HANDLE,
          str(P._k32.OpenProcess.restype))
    check("D11 _k32.TerminateProcess 签名已绑",
          P._k32.TerminateProcess.restype is wintypes.BOOL)
    check("D12 _u32.SendMessageTimeoutW 签名已绑",
          P._u32.SendMessageTimeoutW.restype is ctypes.c_size_t)
    check("D13 _k32.QueryFullProcessImageNameW 签名已绑",
          P._k32.QueryFullProcessImageNameW.restype is wintypes.BOOL,
          str(getattr(P._k32.QueryFullProcessImageNameW, "restype", None)))

    # D14 问一个真 pid 的 exe 路径
    real = sorted(P.app_pids())[:3]
    imgs = [P._process_image(p) for p in real]
    check("D15 问得到 exe 路径",
          bool(imgs) and all(str(x).lower().endswith(".exe") for x in imgs),
          str(imgs))

    # D16 句柄不能泄漏（OpenProcess/CloseHandle 配对）
    def _handles():
        n = wintypes.DWORD(0)
        P._k32.GetProcessHandleCount(P._k32.GetCurrentProcess(), ctypes.byref(n))
        return int(n.value)

    base = _handles()
    for p in real * 40:
        P._process_image(p)
    check("D16 句柄数不增长", _handles() - base <= 2,
          "增长 %d" % (_handles() - base))


def test_app_foreground():
    """app_foreground()：跟的是「窗口在不在」，不是「进程在不在」。

    这正是用户反馈过的场景：点关闭键之后后台进程还留着，按进程判的话
    桌宠会以为应用还开着，明明窗口都关了就还杵在桌面上。
    """
    print("A3. app_foreground()：显隐跟窗口，退出跟进程")
    real_w, real_st, real_run = P.app_windows, P._window_state, P.app_running

    def scenario(name, wins, states, expect):
        def _wins():
            if isinstance(wins, Exception):
                raise wins
            return [(h, "MiniMax Code", st == "visible", 900000)
                    for h, st in states.items()]

        P.app_windows = _wins
        P._window_state = lambda h: states.get(h, "hidden")
        try:
            got = P.app_foreground()
        finally:
            P.app_windows, P._window_state = real_w, real_st
        check(name, got == expect, "得到 %s，期望 %s" % (got, expect))

    scenario("E1 窗口开着 → True", None,
             {100: "visible"}, True)
    scenario("E2 只有最小化窗口 → True", None,
             {100: "minimized"}, True)
    scenario("E3 窗口全被关闭 → False（进程还在也不算数）", None,
             {100: "hidden", 101: "hidden"}, False)
    scenario("E4 一个开着 + 一个已关闭 → True", None,
             {100: "hidden", 101: "visible"}, True)
    scenario("E5 一个窗口都没有 → False", None, {}, False)

    # 探测失败必须退回 app_running()，不能凭空返回 False（那会让桌宠消失）
    P.app_windows = lambda: (_ for _ in ()).throw(RuntimeError("模拟故障"))
    P.app_running = lambda: True
    try:
        check("E6 枚举失败 → 按存活兜底（不凭空消失）",
              P.app_foreground() is True)
    finally:
        P.app_running = real_run
        P.app_windows = real_w

    # 真实环境：这台机器上 app_foreground 必须和窗口状态一致
    try:
        wins = real_w()
        st = {h: P._window_state(h) for h, _t, _v, _a in wins}
        fg = P.app_foreground()
        want = any(s in ("visible", "minimized") for s in st.values())
        check("E7 真实环境自洽", fg == want, "窗口状态=%s 实得=%s" % (st, fg))
    except Exception as e:
        check("E7 真实环境自洽", False, repr(e))


def test_follow_matrix():
    """真造一个 PetWindow（离屏），把「随应用显隐 + 手动开关」整个矩阵走一遍。

    这是用户明确要的那两条路：既随 MiniMax Code 开关，又随时能手动开关。
    这里跑的是**真方法**，不是打桩出来的假逻辑。
    """
    print("E. 跟随 / 手动 显隐矩阵（真 PetWindow，离屏）")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    real_run, real_fg = P.app_running, P.app_foreground
    real_save = P.save_state
    saved = {}
    P.save_state = lambda st: saved.update(st)      # 别把探针结果写进真状态文件

    class _Cfg(object):
        running = True
        fg = True

    P.app_running = lambda: _Cfg.running
    P.app_foreground = lambda: _Cfg.fg

    try:
        w = P.PetWindow(server=False, tray=False, hotkey=False,
                        port=0, follow=True, exit_with_app=False,
                        follow_mode=P.FOLLOW_MODE_PROCESS)
        w.show()
        app.processEvents()

        def tick(n=3):
            """跑 n 轮 _check_app（连续两次才算数，所以至少 2 轮）。"""
            for _ in range(n):
                w._check_app()
                app.processEvents()

        # ---- 默认口径：按进程 ----
        check("E0 默认依据是「按进程」",
              w.follow_mode == P.FOLLOW_MODE_PROCESS, w.follow_mode)

        _Cfg.running = _Cfg.fg = True
        tick()
        check("E1 跟随开、应用开 → 显示", w.isVisible())

        # ★ 用户明确要的：关掉窗口、后台进程还活着 → 桌宠继续显示
        _Cfg.fg = False                            # 窗口关了，进程还在
        tick()
        check("E2 ★ 按进程：窗口关但进程在 → 继续显示", w.isVisible())

        # 进程也没了 → 隐藏
        _Cfg.running = False
        tick()
        check("E3 进程也没了 → 隐藏", not w.isVisible())

        _Cfg.running = _Cfg.fg = True
        tick()
        check("E4 再打开 → 自动显示回来", w.isVisible())

        # ---- 切到按窗口：窗口关了就该藏 ----
        w._set_follow_mode(P.FOLLOW_MODE_WINDOW)
        app.processEvents()
        _Cfg.fg = False
        tick()
        check("E5 按窗口：窗口关 → 隐藏", not w.isVisible())
        _Cfg.fg = True
        tick()
        check("E6 按窗口：窗口开 → 显示", w.isVisible())

        # 切回按进程
        w._set_follow_mode(P.FOLLOW_MODE_PROCESS)
        app.processEvents()
        _Cfg.fg = False
        tick()
        check("E7 切回按进程：窗口关但进程在 → 继续显示", w.isVisible())
        _Cfg.fg = True
        tick()

        # ---- 手动：绝不改 follow ----
        w.toggle_visible()
        app.processEvents()
        check("E8 手动隐藏生效", not w.isVisible())
        check("E9 ★ 手动隐藏没有关掉 follow", w.follow is True,
              "follow=%s" % w.follow)

        w.toggle_visible()
        app.processEvents()
        check("E10 手动显示生效", w.isVisible())
        check("E11 ★ 手动显示没有关掉 follow", w.follow is True,
              "follow=%s" % w.follow)
        check("E11b ★ 手动操作也没改跟随依据",
              w.follow_mode == P.FOLLOW_MODE_PROCESS, w.follow_mode)

        # ---- 手动隐藏是「临时覆盖」：应用重开时跟随重新接管 ----
        w.toggle_visible()                          # 隐藏
        app.processEvents()
        _Cfg.fg = False
        tick()
        _Cfg.running = False
        tick()
        _Cfg.running = _Cfg.fg = True
        tick()
        check("E12 手动隐藏后，应用重开会恢复跟随", w.isVisible())

        # ---- 关掉跟随：应用关闭也不再管它 ----
        w._set_follow(False)
        app.processEvents()
        check("E13 关掉跟随即刻放出来", w.isVisible())
        _Cfg.running = False
        tick()
        check("E14 关掉跟随后，应用关闭桌宠仍留着", w.isVisible())
        check("E15 落盘的是 follow=false", saved.get("follow") is False,
              str(saved.get("follow")))

        # ---- 再打开跟随，立刻生效 ----
        _Cfg.running = _Cfg.fg = True
        w._set_follow(True)
        app.processEvents()
        tick()
        check("E16 重新打开跟随后应用开 → 显示", w.isVisible())
        _Cfg.running = False
        tick()
        check("E17 按进程模式：进程没了 → 隐藏", not w.isVisible())
        _Cfg.running = True
        tick()
        check("E18 又回来", w.isVisible())

        w.hide()
    finally:
        P.app_running, P.app_foreground = real_run, real_fg
        P.save_state = real_save


def main():
    test_helpers()
    test_real_win32()
    test_window_state()
    test_app_foreground()
    test_kill_guard()
    test_branches()
    test_follow_matrix()
    print("-" * 50)
    if FAILED:
        print("PROBE_FAIL %d 项：" % len(FAILED))
        for f in FAILED:
            print("   - " + f)
        return 1
    print("PROBE_OK 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
