# -*- coding: utf-8 -*-
"""
MiniMax Pet —— MiniMax Code 桌面版任务进度桌宠
================================================
主视觉：MiniMax 官方吉祥物。由官方安装目录的 icon.icns 提取 mascot.png（像素级一致），
        再叠加会眨眼 / 说话 / 思考 / 等你确认 / 庆祝的表情与状态条。

数据源：**只读**监听 MiniMax Code 的会话转录
        ~/.minimax/v2/sessions/<年>/<月>/<日>/<会话>/messages.jsonl
        由 user / assistant(toolCall) / toolResult 三类消息实时推导出：
          提交任务   → 思考中
          调用工具   → 执行中，显示工具名与步数
          工具已发出但迟迟没有回结果 → 等你确认（橙色提醒）
          回合收尾   → 绿色 ✓ 与步数 / 用时，常驻直到你点开查看
        多会话各自独立成卡片，互不覆盖。

        user 消息里混着 harness 注入的 <system-reminder>（agent-context /
        todo-cadence / tool 清单）。程序用消息自带的 canonicalTextRange 精确切出
        真实提问；切不出内容就整条跳过，**不**把噪声当任务标题，也不重置步数。
        被压缩过的会话（首条是 compactionSummary）标题取自回顾正文。

约束：本程序**只读取**上述转录，不写入 MiniMax Code 的任何配置目录；
      自身状态（位置等）也只落在本项目目录内。

生命周期：随 MiniMax Code 进程「打开→显示 / 关闭→隐藏」；也可手动开关。
          若希望进程本身一起退出，可在托盘勾选「MiniMax 退出时一并退出桌宠」。

运行：  python minimax_pet.py [--demo] [--selftest] [--port 8766] [--no-follow]
依赖：  pip install PyQt5
"""
import argparse
import html
import json
import math
import os
import random
import re
import sys
import tempfile
import threading
import time

try:
    from PyQt5.QtCore import (Qt, QTimer, pyqtSignal, QObject, QPoint, QPointF,
                              QRectF, QSize, QLockFile, QAbstractNativeEventFilter)
    from PyQt5.QtGui import (QPainter, QColor, QPen, QFont, QFontMetrics, QIcon,
                             QPixmap, QGuiApplication, QPainterPath)
    from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                                 QHBoxLayout, QMenu, QSystemTrayIcon,
                                 QActionGroup)
except ImportError as _imp_err:      # pragma: no cover
    sys.stderr.write("缺少依赖 PyQt5，请先执行: pip install PyQt5\n"
                     "Missing dependency PyQt5 — run: pip install PyQt5\n"
                     "(%s)\n" % _imp_err)
    sys.exit(1)

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# 双语文案。所有面向用户的字符串都走 i18n.t()，这里只 import 不硬编码。
from i18n import t, set_lang, get_lang, system_lang, LANGS as I18N_LANGS

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
MASCOT_PATH = os.path.join(ASSETS, "mascot.png")
MASCOT_TRAY_PATH = os.path.join(ASSETS, "mascot_tray.png")
MASCOT_SHADOW_PATH = os.path.join(ASSETS, "mascot_shadow.png")
MASCOT_GLOW_PATH = os.path.join(ASSETS, "mascot_glow.png")
STATE_PATH = os.path.join(BASE, "pet_state.json")
LOG_PATH = os.path.join(BASE, "pet.log")

# MiniMax Code 的会话转录根目录（只读）
SESSIONS_ROOT = os.path.join(os.path.expanduser("~"), ".minimax", "v2", "sessions")

# ========== MiniMax 品牌 Token（取自官方吉祥物）==========
BRAND     = "#0091FF"   # 品牌蓝
BLUE_DEEP = "#0A6FE0"   # 团子顶部深蓝
BLUE_MID  = "#00A6FF"   # 团子中部亮蓝
BLUE_PALE = "#C9FAFF"   # 团子底部浅青
FACE_INK  = "#0A3A63"   # 表情深蓝（画在蓝色身体上）
BG        = "#161616"
BORDER    = "#2A2A2A"
FG        = "#FFFFFF"
FG_SUBTLE = "#A1A1A1"
SUCCESS   = "#4ADE80"
DESTRUCT  = "#EF4444"
WARNING   = "#FBBF24"
WAITING   = "#F97316"

DEFAULT_PORT = 8766
MAX_CARDS    = 6

# 「跟随 MiniMax Code」到底跟什么，两个口径，用户可切换：
#   process —— 进程还在就算开着。**这是默认**：用户要的是「关掉窗口、后台
#              agent 继续跑，桌宠也继续显示」；Electron 关窗口常常只隐藏界面，
#              后台进程赖着不走，按进程判才不会莫名其妙把桌宠也藏了。
#   window  —— 非要有 visible/minimized 的窗口才算开着。按窗口关掉 → 桌宠跟着藏。
# 退出永远只看进程（app_running），跟这个选择无关。
FOLLOW_MODE_PROCESS = "process"
FOLLOW_MODE_WINDOW = "window"
FOLLOW_MODES = (FOLLOW_MODE_PROCESS, FOLLOW_MODE_WINDOW)
FOLLOW_MODE_TEXT = {
    FOLLOW_MODE_PROCESS: "follow.mode_process",
    FOLLOW_MODE_WINDOW: "follow.mode_window",
}


def follow_mode_text(mode):
    """跟随依据的说明（走 i18n）。"""
    k = FOLLOW_MODE_TEXT.get(mode)
    return t(k) if k else t("follow.mode_menu")


# MiniMax Code 桌面版进程名特征（实测 exe = "MiniMax Code.exe"）
APP_PROCESS_HINT = "minimax code"
APP_TITLE_HINT   = "minimax code"

# 聚合优先级：数字越小越优先显示在团子脸上
PRIORITY = {"waiting": 0, "executing": 1, "thinking": 2, "error": 3,
            "done": 4, "idle": 5}
# 「正在跑」的状态集合：这几个状态下团子脸必须跟着走，哪怕用户点过卡片
ACTIVE_STATES = ("thinking", "executing", "waiting", "error")

# 合成会话的保留 key：不对应磁盘转录，poll 清理过期会话时必须跳过
SYNTH_KEYS = ("__demo__", "__http__")

# 工具已发出但迟迟没有回结果 → 认为在等你确认（秒）
PENDING_ASK_SEC = 4.0
# 首次全量读取单份转录的上限（字节）
INITIAL_READ_CAP = 12 * 1024 * 1024
# 只关心最近这么多小时的会话
ACTIVE_WINDOW_H = 12.0

# 全部合法状态值。标签是带语言的（mood_name()），校验只认这些 key。
MOOD_KEYS = ("idle", "thinking", "executing", "waiting", "done", "error")


def mood_name(state):
    """状态标签，跟随当前语言。"""
    return t("mood." + state) if state in MOOD_KEYS else t("mood.idle")


MOOD_COLOR = {"idle": FG_SUBTLE, "thinking": WARNING, "executing": BRAND,
              "waiting": WAITING, "done": SUCCESS, "error": DESTRUCT}

# 整体缩放旋钮。SIZE_RATIO 是设计稿的比例：0.8 表示桌宠只有设计稿的 80%。
# 想改桌宠大小只动这一个数——所有几何尺寸、表情动画幅度都跟着走。
SIZE_RATIO = 0.8
# 字号**不**跟 SIZE_RATIO 一起缩：文字有可读性下限，窗口变窄不等于字也要变小，
# 否则卡片里 12px 的中文会被压到 10px 以下，看着费劲。独立一个旋钮，想再调只动它。
FONT_SCALE = 1.2
# UI_SCALE 仅供 --selftest-scale 用（按 N 倍渲染当前实际尺寸查细节），正常运行为 1.0
UI_SCALE = 1.0

# ========== 显示器缩放补偿 ==========
# 为什么需要它
# ------------------------------------------------------------------------------
# 以前所有几何都是**逻辑像素**。Qt 渲染时会按所在屏幕的 DPR（缩放比例）把逻辑
# 像素再放大一次，于是物理尺寸 = 逻辑尺寸 × DPR：
#     100% 缩放的外接显示器  → 102 × 1.0 = 102 物理像素（刚好的样子）
#     200% 缩放的笔记本内屏  → 102 × 2.0 = 204 物理像素（突然大一倍）
# 这就是「接显示器时刚好好、拔掉显示器后桌宠偏大」的根因。
#
# 怎么修
# ------------------------------------------------------------------------------
# 把尺寸**锚定在物理像素**：逻辑 = 物理 ÷ 缩放比例。渲染时再乘回同一个比例，
# 一除一乘正好抵消，不管插拔显示器、不管系统缩放是 100% 还是 200%，
# **屏幕上的物理大小恒定**。显示器变化时重新量一次即可。
_SCREEN_DPR = 1.0            # 当前锚定屏幕的 Qt DPR（初值，量过之后以实测为准）
# 实测出来的「逻辑像素 → 物理像素」比例。Qt 报的 devicePixelRatio 通常是对的，
# 但不保证在所有缩放组合下都准（多屏混合缩放、DPI 虚拟化、驱动默认值都可能
# 让它和窗口实际表现对不上）。所以窗口出来之后用 GetWindowRect 量一次真实值，
# 对不上就按实测重算——不信任任何单一来源。
_PX_FACTOR = None
# 当前屏幕名，缓存给 HTTP 诊断接口用（那个 handler 跑在子线程，不能直接问 Qt）
_SCREEN_NAME = t("screen.unknown")

# 用户档位（右键菜单可调，存在 pet_state.json 里）
SIZE_LEVEL = 1.0
SIZE_LEVELS = [0.75, 0.9, 1.0, 1.15, 1.35]
SIZE_LEVEL_NAMES = {0.75: "size.level.0.75", 0.9: "size.level.0.9",
                   1.0: "size.level.1.0", 1.15: "size.level.1.15",
                   1.35: "size.level.1.35"}


def size_level_name(level):
    """档位名（走 i18n，界面语言切换后立即跟着变）。"""
    k = SIZE_LEVEL_NAMES.get(level)
    return t(k) if k else t("size.level.custom")


def _dpr():
    """当前锚定屏幕的 DPR。取不到就用 1.0（等价于不做任何补偿）。"""
    d = _SCREEN_DPR
    try:
        if d and 0.25 < float(d) < 8.0:
            return float(d)
    except Exception:
        pass
    return 1.0


def _scale():
    """真正用于换算的比例：优先实测值，没有实测值才退回 Qt 的 DPR。"""
    if _PX_FACTOR:
        try:
            f = float(_PX_FACTOR)
            if 0.25 < f < 8.0:
                return f
        except Exception:
            pass
    return _dpr()


def _fsize():
    """几何/字号的公共缩放因子：设计稿 → 逻辑像素。"""
    return UI_SCALE * SIZE_LEVEL / _scale()

# 字体栈：Qt 会按这个顺序做「逐字形」回退，顺序错了就会掉进豆腐块。
#   Segoe UI            -> 拉丁字母与数字
#   Segoe UI Symbol     -> ✓ ⏸ ✕ ▶ 等符号（实测唯一覆盖 U+2713/U+23F8 的字体，必须紧跟主字体）
#   Microsoft YaHei     -> 简体中文
#   Segoe UI Emoji      -> 彩色 emoji
#   Arial Unicode MS   -> 兜底
# 注意：Qt 样式表里的 font-family 不做逐字形回退，必须用 QFont.setFamilies() 设置。
FONT_FAMILIES = ["Segoe UI", "Segoe UI Symbol", "Microsoft YaHei",
                 "Segoe UI Emoji", "Arial Unicode MS"]


def ui_font(px_size, bold=True):
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(max(6, int(px_size)))
    f.setBold(bold)
    return f


def _px(v):
    """几何尺寸换算：跟 UI_SCALE × SIZE_RATIO × 档位走，再除以屏幕 DPR。

    除 DPR 这一步是为了让**物理**尺寸与显示器缩放无关，见上面 _SCREEN_DPR 的说明。
    """
    return max(1, int(round(v * UI_SCALE * SIZE_RATIO * _fsize())))


def _fpx(v):
    """字号换算：跟 UI_SCALE × 档位走，但用 FONT_SCALE 而不是 SIZE_RATIO。

    桌宠缩小了字不该跟着缩——卡片变窄只影响能放几个字，不影响字本身多清晰。
    字号同样要除 DPR：窗口整体缩了，里面的字不缩就会撑爆。
    """
    return max(7, int(round(v * UI_SCALE * FONT_SCALE * _fsize())))


# 表情动画幅度：跟**视觉尺寸**走，不是跟字号走。
# 运行时读取，所以 --selftest-scale 改 UI_SCALE、换 DPR 改档位后依然正确。
def _draw_k():
    return UI_SCALE * SIZE_RATIO * _fsize()


# ========== 尺寸（全部由 SIZE_RATIO 驱动）==========
# 设计稿原始尺寸
_D_BODY_W, _D_BODY_H, _D_CHIP_H = 128, 132, 22


def recalc_pet_size():
    """按当前 DPR 与档位重算「提前换算过」的几何常量。

    BODY_W / CHIP_H 有几处是直接拿来用的（控件 setFixedSize、胶囊高度），
    不走 _px()，所以档位或 DPR 变了必须显式重算。返回新的 PET_SIZE。
    """
    global BODY_W, BODY_H, CHIP_H, PET_SIZE
    BODY_W = _px(_D_BODY_W)
    BODY_H = _px(_D_BODY_H)
    CHIP_H = _px(_D_CHIP_H)
    PET_SIZE = (BODY_W, BODY_H + CHIP_H + _px(6))
    return PET_SIZE


BODY_W   = _px(_D_BODY_W)
BODY_H   = _px(_D_BODY_H)
CHIP_H   = _px(_D_CHIP_H)
PET_SIZE = (BODY_W, BODY_H + CHIP_H + _px(6))
# 任务卡片：所有使用点都自带 _px()，因此这里保持设计稿原值，不要提前缩放
CARD_W   = 322
CARD_H   = 66
CARD_GAP = 7
# 折叠/展开提示条的高度（设计稿原值，同上）
FOOTER_H = 22
# 折叠状态下只露几行卡片。其余的收进提示条，点它才完全展开。
COLLAPSED_ROWS = 1


# ========== 日志 / 本地状态（只写本项目目录）==========
def log(kind, msg):
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 512 * 1024:
            open(LOG_PATH, "w", encoding="utf-8").close()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S") + " [" + str(kind) + "] " + str(msg) + "\n")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ========== Windows 进程 / 窗口 ==========
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    _u32 = ctypes.windll.user32
    _k32 = ctypes.windll.kernel32
    _ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _TH32CS_SNAPPROCESS = 0x2
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _K32_BOUND = False
else:
    _u32 = _k32 = None
    _ENUMPROC = None
    _TH32CS_SNAPPROCESS = 0x2
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _INVALID_HANDLE_VALUE = -1
    _K32_BOUND = True


# PROCESSENTRY32W 必须定义在**模块级**。
# 如果写在 _iter_processes() 内部，每次调用都会新建一个类对象，于是
# argtypes 里绑定的 POINTER(_PE32) 只认第一次那个类；第二次扫描起
# ctypes 就抛 ArgumentError。而 app_pids() 会把异常吞掉返回空集，
# app_running() 因此永远返回 False —— 桌宠会误以为 MiniMax Code 没了，
# 先把自己藏起来，几秒后再自杀退出。这是个非常难查的坑，必须模块级。
class _PE32(ctypes.Structure):
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
    """遍历系统进程，产出 (pid, exe 名)。"""
    global _K32_BOUND
    if _k32 is None:
        return

    if not _K32_BOUND:
        # 不声明 restype 的话，ctypes 按 c_int 返回 HANDLE，64 位下高位会被
        # 截断；再把这个被截断的值喂给 CloseHandle，关掉的就不是那个句柄了。
        try:
            _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
            _k32.Process32FirstW.restype = wintypes.BOOL
            _k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PE32)]
            _k32.Process32NextW.restype = wintypes.BOOL
            _k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PE32)]
            _k32.CloseHandle.restype = wintypes.BOOL
            _k32.CloseHandle.argtypes = [wintypes.HANDLE]
        except Exception:
            pass
        _K32_BOUND = True

    snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == _INVALID_HANDLE_VALUE:
        return
    try:
        e = _PE32()
        e.dwSize = ctypes.sizeof(e)
        if _k32.Process32FirstW(snap, ctypes.byref(e)):
            while True:
                yield int(e.th32ProcessID), str(e.szExeFile)
                if not _k32.Process32NextW(snap, ctypes.byref(e)):
                    break
    finally:
        _k32.CloseHandle(snap)


def app_pids():
    """MiniMax Code 桌面版的所有进程 id 集合。

    扫描本身出问题时必须抛出去，不能安静地返回空集：空集会被 app_running()
    读成「应用没开」，于是桌宠误以为 MiniMax Code 关闭了，先隐藏自己，
    再自杀退出。宁可让上层按「探测失败=按存活处理」兜底。
    """
    out = set()
    seen_any = False
    try:
        for pid, exe in _iter_processes():
            seen_any = True
            if APP_PROCESS_HINT in exe.lower():
                out.add(pid)
    except Exception:
        raise
    if not seen_any:
        raise RuntimeError(t("log.win.scan_empty"))
    return out


def app_running():
    """进程是否存在（探测失败时按存活处理，宁可多留不可误退）。"""
    if _k32 is None:
        return True
    try:
        pids = app_pids()
        return bool(pids)
    except Exception:
        return True


def app_foreground():
    """应用是不是「开着」——**真的有窗口**才算开着。

    必须和 app_running() 分开看，因为这两个口径回答的是不同问题：

    · app_running()   —— 进程在吗？管「应用要不要退出 / 哨兵要不要守」。
    · app_foreground()—— 窗口在吗？管「桌宠要不要显示」。

    用户反馈过「点关闭键之后后台进程还留着」：这时候 app_running() 仍是 True，
    按它判显隐的话，窗口都关了的桌宠还会一直杵在桌面上，而菜单里那条开关
    写的就是「跟随 MiniMax Code 开关」——跟的是窗口，不是进程。

    探测失败时退回 app_running()，宁可多显示也不要凭空消失。
    """
    try:
        wins = app_windows()
    except Exception:
        return app_running()
    for h, _t, _v, _a in wins:
        if _window_state(h) in ("visible", "minimized"):
            return True
    return False


def _dwm_cloaked(hwnd):
    """DWM 判定窗口是否被隐藏（收进托盘时窗口仍可能 IsWindowVisible）。"""
    try:
        value = ctypes.c_int(0)
        ok = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), 14, ctypes.byref(value), ctypes.sizeof(value))
        return bool(ok and value.value)
    except Exception:
        return False


def _window_title(hwnd):
    n = _u32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    _u32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def app_windows():
    """枚举 MiniMax Code 顶层窗口 → [(hwnd, title, visible, area)]，可见的大窗口优先。"""
    if _u32 is None:
        return []
    pids = app_pids()
    if not pids:
        return []
    out = []

    def _cb(h, _l):
        try:
            pid = wintypes.DWORD()
            _u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value not in pids:
                return True
            title = _window_title(h)
            if not title:
                return True
            r = wintypes.RECT()
            if not _u32.GetWindowRect(h, ctypes.byref(r)):
                return True
            area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
            if area <= 0:
                return True
            visible = bool(_u32.IsWindowVisible(h)) and not _dwm_cloaked(h)
            out.append((h, title, visible, area))
        except Exception:
            pass
        return True

    _u32.EnumWindows(_ENUMPROC(_cb), 0)
    out.sort(key=lambda t: (0 if t[2] else 1, -t[3]))
    return out


# ---------- 召唤 MiniMax Code：绝不去「复活」一个僵死的窗口 ----------
#
# 要防的现象：用户点关闭键之后，Electron 主进程还活着（后台 agent 还在跑），
# 但浏览器窗口已经销毁 / 僵死 —— HWND 还在、最后一帧还留在屏幕上，
# 渲染进程却已经没了。这时候对窗口 ShowWindow(SW_SHOW) 去「复活」它，
# 结果就是**界面完整渲染、但整个点不动**，正是用户截图里那个卡死的窗口。
#
# 所以顺序必须是：
#   1. 先探窗口线程还活不活（SendMessageTimeout + SMTO_ABORTIFHUNG）；
#   2. 只有「活着」的窗口才允许被还原 / 置前；
#   3. 全是僵死窗口 → 先 WM_CLOSE 让它体面退，再结束掉仍僵的进程树，
#      最后拉起一个全新实例。
#
# ⚠️ 整套探测最坏要好几秒（探活 + 等体面退出 + 等新窗口冒头），
#    所以 activate_app() **只在子线程里调用**，绝不能放 Qt 主线程，
#    否则桌宠自己会被冻住。
WM_NULL_ = 0x0000
WM_CLOSE_ = 0x0010
SMTO_BLOCK_ = 0x0001
SMTO_ABORTIFHUNG_ = 0x0002
PROC_TERMINATE_ = 0x0001
PROC_SYNCHRONIZE_ = 0x0400
PROC_QUERY_LIMITED_ = 0x1000

HUNG_PROBE_MS = 600        # 粗探：僵死窗口会**立刻**返回，所以并不贵
HUNG_CONFIRM_MS = 1200     # 动刀之前的复核
CLOSE_GRACE_S = 1.2        # WM_CLOSE 之后留给它体面退出的时间
RELAUNCH_WAIT_S = 9.0      # 等新窗口冒头
_MAX_PROBE_WINDOWS = 6     # 一次最多探这么多个窗口

_EXTRA_BOUND = False
_ANCESTORS = None


def _bind_extra():
    """补齐「探窗口 / 结束进程 / 问 exe 路径」这批 API 的签名。

    restype / argtypes 必须在第一次调用**之前**绑好：ctypes 默认按 c_int
    收返回值，64 位下 HANDLE 高位会被截断，拿到的根本不是那个句柄
    （老坑：截断后的句柄再拿去 CloseHandle，关掉的是另一个句柄）。

    每条**单独** try：曾经把 OpenProcess 写成了 user32.OpenProcess，
    一失败整个块中断在中间，排在它后面的 QueryFullProcessImageName /
    TerminateProcess / CloseHandle 签名全都没绑上 —— 静默地退化成
    64 位句柄截断，比直接报错难查得多。
    """
    global _EXTRA_BOUND
    if _EXTRA_BOUND or _u32 is None:
        return _EXTRA_BOUND
    _SZ = ctypes.c_size_t
    _P_SZ = ctypes.POINTER(ctypes.c_size_t)
    specs = [
        # (库, 函数名, restype, argtypes)
        (_u32, "SendMessageTimeoutW", _SZ,
         [wintypes.HWND, wintypes.UINT, _SZ, _SZ, wintypes.UINT,
          wintypes.UINT, _P_SZ]),
        (_u32, "PostMessageW", wintypes.BOOL,
         [wintypes.HWND, wintypes.UINT, _SZ, _SZ]),
        (_k32, "QueryFullProcessImageNameW", wintypes.BOOL,
         [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
          ctypes.POINTER(wintypes.DWORD)]),
        (_k32, "OpenProcess", wintypes.HANDLE,
         [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
        (_k32, "TerminateProcess", wintypes.BOOL,
         [wintypes.HANDLE, wintypes.UINT]),
        (_k32, "CloseHandle", wintypes.BOOL, [wintypes.HANDLE]),
        (_k32, "GetCurrentProcessId", wintypes.DWORD, []),
    ]
    for lib, name, restype, argtypes in specs:
        try:
            fn = getattr(lib, name)
            fn.restype = restype
            fn.argtypes = argtypes
        except Exception as e:
            log("warn", t("log.win.bind_fail", name, e))
    _EXTRA_BOUND = True
    return _EXTRA_BOUND


def window_pid(hwnd):
    pid = wintypes.DWORD(0)
    try:
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def window_responsive(hwnd, ms=HUNG_PROBE_MS):
    """窗口所属线程还在泵消息吗？

    探不出来（异常 / 平台不支持）时**按「活着」处理**——宁可照常显示，
    也不能因为探测失败就把用户正在用的窗口杀掉。
    """
    if _u32 is None:
        return True
    try:
        if not _u32.IsWindow(hwnd):
            return False
        _bind_extra()
        res = ctypes.c_size_t(0)
        r = _u32.SendMessageTimeoutW(wintypes.HWND(hwnd), WM_NULL_, 0, 0,
                                      SMTO_ABORTIFHUNG_ | SMTO_BLOCK_,
                                      int(ms), ctypes.byref(res))
        return bool(r)
    except Exception as e:
        log("warn", t("log.win.probe_exc", e))
        return True


def _pid_parent_map():
    """pid → ppid 全表。"""
    out = {}
    if _k32 is None:
        return out
    try:
        list(_iter_processes())          # 顺手把 _K32_BOUND 那套绑完
        snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snap or snap == _INVALID_HANDLE_VALUE:
            return out
        try:
            e = _PE32()
            e.dwSize = ctypes.sizeof(e)
            if _k32.Process32FirstW(snap, ctypes.byref(e)):
                while True:
                    out[int(e.th32ProcessID)] = int(e.th32ParentProcessID)
                    if not _k32.Process32NextW(snap, ctypes.byref(e)):
                        break
        finally:
            _k32.CloseHandle(snap)
    except Exception as e:
        log("warn", t("log.win.ppid_fail", e))
    return out


def _collect_tree(root, m):
    """root 以及它的全部后代 pid。"""
    out = [root]
    i = 0
    while i < len(out):
        cur = out[i]
        i += 1
        for c, p in m.items():
            if p == cur and c not in out:
                out.append(c)
    return out


def _ancestor_chain(pid, m):
    """pid 往上到根的所有祖先。"""
    out = []
    for _ in range(32):
        pp = m.get(pid)
        if not pp or pp in out or pp <= 4:
            break
        out.append(pp)
        pid = pp
    return out


def ancestor_pids():
    """自己 + 整条祖先进程链。

    桌宠正常由开机哨兵拉起，MiniMax Code 不会出现在这条链里；但开发 /
    手工启动时它完全可能被挂在某个 MiniMax Code 底下。那种情况下
    **绝不能**去杀它，否则连自己这条会话一起送走。
    """
    global _ANCESTORS
    if _ANCESTORS is not None:
        return _ANCESTORS
    out = set([os.getpid()])
    try:
        m = _pid_parent_map()
        cur = int(_k32.GetCurrentProcessId())
        out.add(cur)
        for _ in range(32):
            pp = m.get(cur)
            if not pp or pp in out or pp <= 4:
                break
            out.add(pp)
            cur = pp
    except Exception as e:
        log("warn", t("log.win.anc_fail", e))
    _ANCESTORS = out
    return out


def _process_image(pid):
    """问系统要某个 pid 的 exe 完整路径；拿不到返回空串。"""
    if _u32 is None or _k32 is None or not pid:
        return ""
    h = None
    try:
        _bind_extra()
        h = _k32.OpenProcess(PROC_QUERY_LIMITED_, False, int(pid))
        if not h:
            return ""
        n = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
    except Exception:
        pass
    finally:
        if h:
            try:
                _k32.CloseHandle(h)
            except Exception:
                pass
    return ""


def app_exe_path():
    """MiniMax Code 的可执行文件：先问活着的进程要，再退回常见安装目录。"""
    cands = []
    try:
        for pid in sorted(app_pids()):
            p = _process_image(pid)
            if p:
                cands.append(p)
    except Exception:
        pass
    local = os.environ.get("LOCALAPPDATA") or ""
    if local:
        cands.append(os.path.join(local, "Programs", "MiniMax Code",
                                  "MiniMax Code.exe"))
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return cands[0] if cands else ""


def spawn_app():
    """拉起一个新的 MiniMax Code 实例。成功返回启动方式说明，失败返回空串。"""
    exe = app_exe_path()
    if exe:
        try:
            subprocess.Popen([exe], close_fds=True)
            log("info", t("log.win.spawned", exe))
            return exe
        except Exception as e:
            log("warn", t("log.win.spawn_exe_fail", e))
    lnk = os.path.join(os.environ.get("APPDATA") or "", "Microsoft", "Windows",
                       "Start Menu", "Programs", "MiniMax Code.lnk")
    try:
        if os.path.isfile(lnk):
            os.startfile(lnk)
            log("info", t("log.win.spawned_lnk"))
            return lnk
    except Exception as e:
        log("warn", t("log.win.lnk_fail", e))
    return ""


def _window_state(hwnd):
    """窗口现在是「看得见」「最小化」还是「已经被关掉了」。

    这三个状态对应**完全不同的处置**，必须分开：

    · visible   —— 直接置前即可，一个字节的 ShowWindow 都不用发
    · minimized —— 最小化时渲染进程一定活着，SW_RESTORE 是安全的
    · hidden    —— **用户已经把窗口关掉了**（含收进托盘 / DWM cloaked）。
                   这时候 ShowWindow 把它放回来，拿到的是「界面完整、
                   但消息循环已经不在了」的僵尸 —— 就是那个卡死窗口。
                   唯一的正解是：结束残留进程，重新拉一个。
    先判「看不看得见」再判「最小没最小」：顺序反了会踩坑——一个被最小化
    之后又隐藏的窗口 `IsIconic()` 仍然为真，会被误判成最小化，于是我们
    对它 SW_RESTORE，又把用户已经关掉的窗口放回屏幕。凡是**看不见**的，
    一律算「已关闭」。
    """
    try:
        if not _u32.IsWindowVisible(hwnd) or _dwm_cloaked(hwnd):
            return "hidden"
        if _u32.IsIconic(hwnd):
            return "minimized"
        return "visible"
    except Exception:
        return "visible"


def _focus_only(hwnd):
    """只置前，不发任何 ShowWindow（窗口本来就可见时最安全的一步）。"""
    try:
        fg = _u32.GetForegroundWindow()
        cur = _k32.GetCurrentThreadId()
        fgt = _u32.GetWindowThreadProcessId(fg, None) if fg else 0
        if fgt and fgt != cur:
            _u32.AttachThreadInput(cur, fgt, True)
        _u32.SetForegroundWindow(hwnd)
        _u32.BringWindowToTop(hwnd)
        _u32.SetActiveWindow(hwnd)
        if fgt and fgt != cur:
            _u32.AttachThreadInput(cur, fgt, False)
    except Exception:
        return False
    for _ in range(6):
        time.sleep(0.05)
        fg = _u32.GetForegroundWindow()
        if fg == hwnd:
            return True
    tgt = window_pid(hwnd)
    return bool(fg and tgt and window_pid(fg) == tgt)


def _bring_to_front(hwnd):
    """置前 + 复核。

    只有**最小化**的窗口才允许 `SW_RESTORE`：最小化时渲染进程一定还活着，
    还原是安全操作。对一个已经被用户关掉的窗口调 ShowWindow，等于把僵尸
    重新摆到屏幕上 —— 那就是要修的那个 bug。
    """
    try:
        if _u32.IsIconic(hwnd):
            _u32.ShowWindow(hwnd, 9)          # SW_RESTORE，仅限最小化窗口
    except Exception:
        pass
    return _focus_only(hwnd)


def _pick_from(wins):
    """在（已经确认活着的）候选窗口里挑最合适的那个。"""
    for h, title, visible, _a in wins:
        if visible and APP_TITLE_HINT in title.lower():
            return h
    for h, _t, visible, _a in wins:
        if visible:
            return h
    return wins[0][0] if wins else 0


def _split_windows(wins, ms=HUNG_PROBE_MS):
    """把窗口列表劈成「还活着」和「已经僵了」两堆。"""
    alive, dead = [], []
    for w in wins[:_MAX_PROBE_WINDOWS]:
        (alive if window_responsive(w[0], ms) else dead).append(w)
    return alive, dead


def pick_app_window():
    """挑最适合置前的窗口：**可见的**优先，其次最小化的。

    已经被关掉的窗口不在候选里——复活它只会得到一个点不动的空壳。
    """
    try:
        wins = app_windows()
    except Exception:
        return None
    ok = [w for w in wins if _window_state(w[0]) in ("visible", "minimized")]
    return _pick_from(ok) or None


def _kill_stuck(stuck_windows, guard, alive_windows):
    """结束掉「关掉了窗口、却还赖着不走」的进程树。

    三道闸，任何一道不过就整棵树放弃：
      · 该进程在桌宠的祖先链里（可能是拉起桌宠的那家，绝不能杀）；
      · 该进程树里还有任何**活着 / 开着**的窗口（说不定用户正用着别的窗口）；
      · 该进程树不在上面两者的**祖先闭包**里（杀父会顺手带走活的）。
    """
    m = _pid_parent_map()
    protect = set(guard)

    def _protect_tree(pid):
        """保护 pid 这棵子树**以及它所有祖先的子树**。

        只保护后代是不够的：活窗口常在渲染子进程里，残留窗口在它的父进程上，
        杀父会顺手把活的那个带走。祖先闭包才是真正安全的那一圈。
        """
        for r in [pid] + _ancestor_chain(pid, m):
            protect.update(_collect_tree(r, m))

    for p in list(guard):
        _protect_tree(p)
    for h, _t, _v, _a in alive_windows:
        p = window_pid(h)
        if p:
            _protect_tree(p)
    roots, skipped = [], 0
    for h, _t, _v, _a in stuck_windows:
        p = window_pid(h)
        if not p:
            continue
        if p in protect:
            skipped += 1
            continue
        if p not in roots:
            roots.append(p)
    targets = []
    for p in roots:
        for node_pid in _collect_tree(p, m):
            if node_pid not in protect and node_pid not in targets:
                targets.append(node_pid)
    killed = []
    for pid in targets:
        try:
            h = _k32.OpenProcess(PROC_TERMINATE_ | PROC_SYNCHRONIZE_, False, int(pid))
            if not h:
                continue
            try:
                if _k32.TerminateProcess(h, 0):
                    killed.append(pid)
            finally:
                _k32.CloseHandle(h)
        except Exception:
            pass
    log("info", t("log.act.killed", len(killed), skipped))
    if skipped:
        log("warn", t("log.act.protected", skipped))
    return killed


def _spawn_and_wait(how, note):
    """发起启动，并等一个新窗口真的冒出来。"""
    started = spawn_app()
    if not started:
        return {"ok": False, "how": "spawn-failed",
                "note": t("log.act.n_noexe")}
    deadline = time.time() + RELAUNCH_WAIT_S
    h = 0
    while time.time() < deadline:
        time.sleep(0.4)
        try:
            wins = app_windows()
        except Exception:
            continue
        for w in wins[:_MAX_PROBE_WINDOWS]:
            # 必须真的有窗口「开起来了」。只认 hidden 的话，进程里那个
            # 关着的旧窗口会冒充成新窗口，召唤会假成功。
            if _window_state(w[0]) == "hidden":
                continue
            if window_responsive(w[0]):
                h = w[0]
                break
        if h:
            break
    if not h:
        fail = "relaunch-failed" if how == "relaunch" else "spawn-failed"
        return {"ok": False, "how": fail, "note": t("log.act.n_nowin", note)}
    _bring_to_front(h)
    return {"ok": True, "how": how, "note": note}


def activate_app(allow_kill=True):
    """把 MiniMax Code 带到前台，返回 {"ok": bool, "how": str, "note": str}。

    allow_kill=False 时不允许结束任何进程（后台还有任务在跑时用）。

    how：focus   置前一个本来就开着 / 只是最小化的窗口
         spawn   进程活着但一个窗口都没有 → 拉起新实例
         relaunch 窗口已被关闭但进程还在 → 清掉残留进程后重新拉起
         show    清不掉残留进程（桌宠的宿主），只能把窗口还原出来
         spawn-failed / relaunch-failed / probe-error
    """
    if _u32 is None:
        return {"ok": False, "how": "probe-error", "note": t("log.act.n_notwin")}
    try:
        return _activate_win(allow_kill)
    except Exception as e:
        log("warn", t("log.act.exc", e))
        return {"ok": False, "how": "probe-error", "note": "%s" % e}


def _rebuild_app(hidden_windows, guard, allow_kill):
    """窗口已经被用户关掉了 —— 不要复活它，结束残留进程、拉一个全新实例。

    「关闭后进程还活着」时把窗口放回来之所以会卡死，是因为那具窗口的渲染
    进程已经没了，只剩最后一帧像素。而 `SendMessageTimeout(WM_NULL)` 照样
    查不出来：Chromium 只要消息泵还在就会回 WM_NULL，界面死没死它不知道。
    所以这条路径**不靠检测，靠策略**——被关掉的窗口一律不复活。
    """
    if not allow_kill:
        # 后台还有任务在跑，结束进程会把任务一起杀掉。那就老实地还原它，
        # 但要说清楚：这条路上拿到的不一定是活的。
        h = _pick_from(hidden_windows)
        if _bring_to_front(h):
            return {"ok": True, "how": "show",
                    "note": t("log.act.n_running")}
        return {"ok": False, "how": "probe-error", "note": t("log.act.n_restore_failed")}

    # 先礼：WM_CLOSE，让 Electron 有机会体面退出并释放单实例锁
    for h, _t, _v, _a in hidden_windows:
        try:
            _bind_extra()
            _u32.PostMessageW(wintypes.HWND(h), WM_CLOSE_, 0, 0)
        except Exception:
            pass
    log("info", t("log.act.wm_close", len(hidden_windows), "%.1f" % CLOSE_GRACE_S))
    time.sleep(CLOSE_GRACE_S)

    # 窗口自己回来了？说明它其实还活着，那就置前，别杀。
    back = []
    try:
        back = [w for w in app_windows() if _window_state(w[0]) != "hidden"]
    except Exception:
        pass
    if back:
        h = _pick_from(back)
        if _bring_to_front(h):
            return {"ok": True, "how": "focus",
                    "note": t("log.act.n_back")}

    try:
        left = [w for w in app_windows() if _window_state(w[0]) == "hidden"]
    except Exception:
        left = list(hidden_windows)
    if not left:
        return _spawn_and_wait("spawn", t("log.act.n_gone"))

    killed = _kill_stuck(left, guard, back)
    if killed:
        time.sleep(0.8)
        return _spawn_and_wait(
            "relaunch", t("log.act.n_cleared", len(killed)))
    log("warn", t("log.act.cant_kill"))
    return _spawn_and_wait("spawn", t("log.act.n_protected"))


def _activate_win(allow_kill=True):
    guard = ancestor_pids()

    # ---------- 0. 枚举失败就什么都别做 ----------
    # app_windows() 内部是 app_pids()，扫描失败会抛。这种时候绝不能
    # 顺着走进「没窗口 → 拉新实例」分支，那会平白多开一个实例。
    try:
        wins = app_windows()
    except Exception as e:
        return {"ok": False, "how": "probe-error", "note": t("log.act.n_enum_fail", e)}

    if not wins:
        return _spawn_and_wait("spawn", "进程还在但没有窗口")

    by_state = {"visible": [], "minimized": [], "hidden": []}
    for w in wins:
        by_state[_window_state(w[0])].append(w)

    # ---------- 1. 窗口本来就开着 → 只置前，一个 ShowWindow 都不发 ----------
    if by_state["visible"]:
        h = _pick_from(by_state["visible"])
        if _focus_only(h) or _bring_to_front(h):
            return {"ok": True, "how": "focus",
                    "note": t("log.act.n_visible", len(by_state["visible"]))}

    # ---------- 2. 最小化 → SW_RESTORE（渲染进程确定还活着）----------
    if by_state["minimized"]:
        h = _pick_from(by_state["minimized"])
        if _bring_to_front(h):
            return {"ok": True, "how": "focus",
                    "note": t("log.act.n_minimized",
                             len(by_state["minimized"]))}

    # ---------- 3. 只剩「已经被用户关掉」的窗口了 ----------
    hidden = by_state["hidden"]
    if not hidden:
        # 状态判不出来（EnumWindows 到了但分类没落进去）——最后退一步硬置前
        h = _pick_from(by_state["visible"] + by_state["minimized"])
        if h and _bring_to_front(h):
            return {"ok": True, "how": "focus", "note": t("log.act.n_nostate")}
        return {"ok": False, "how": "probe-error", "note": t("log.act.n_badstate")}

    log("info", t("log.act.closed_windows", len(hidden)))
    return _rebuild_app(hidden, guard, allow_kill)


# ========== 会话转录 → 任务状态（只读）==========
_RE_TAG = re.compile(r"<[^>]{1,64}>")
_RE_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_RE_CWD = re.compile(r"Primary working directory:\s*(.+)")


def _clean_prompt(text, ctr):
    """取出用户真实提问；**取不到就返回空串**。

    两条路：
    1. 消息自带 canonicalTextRange —— 权威区间，直接切。区间为空说明这条 user
       消息里根本没有真人输入。
    2. 没有该字段 —— 退化到剥掉 <system-reminder> 与尖括号标签。

    两条路都可能得到空串，而这**永远**意味着「这不是一条新任务」，只是 harness 往
    user 通道里塞的环境上下文（agent-context / todo-cadence / tool 清单等）。
    调用方必须据此跳过，否则会把噪声当成任务标题，还会错误地把 steps/errors
    归零、把状态从 executing 打回 thinking。
    """
    if not isinstance(text, str) or not text:
        return ""
    if isinstance(ctr, dict):
        s, e = ctr.get("startOffset"), ctr.get("endOffset")
        if isinstance(s, int) and isinstance(e, int) and 0 <= s <= e <= len(text):
            return text[s:e].strip()
        return ""
    body = _RE_REMINDER.sub(" ", text)
    body = _RE_TAG.sub(" ", body)
    return " ".join(body.split())


def _short(text, limit=90):
    """把任务标题压成一行，避免卡片被整段 schema 撑爆。"""
    # 局部变量别叫 t：会遮蔽模块级的 i18n 翻译函数 t()
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


_GENERIC_HEAD = {
    "goal", "summary", "overview", "context", "background", "task", "tasks",
    "objective", "objectives", "notes", "status", "pending", "todo", "todos",
    "current state", "completed work", "completed", "constraints", "preferences",
    "key decisions", "blockers", "critical context", "next steps", "in progress",
}


def _summary_title(text, limit=90):
    """从 compactionSummary 这种 markdown 回顾里挑一行能当标题的。

    光秃秃的分节名（"## Goal"）单独当标题毫无信息量，跳过它，取下面第一句
    有内容的话；只有整篇都没有实质内容时才退回第一行。
    """
    for ln in (text or "").splitlines():
        raw = ln.strip()
        if not raw:
            continue
        body = raw.lstrip("#").lstrip("*").strip()
        if raw.startswith("#") and body.strip(":：").lower() in _GENERIC_HEAD:
            continue
        if len(body) < 4:
            continue
        return _short(body, limit)
    return _short(text, limit)


def _new_state(key):
    return {"key": key, "state": "idle", "task": "", "tool": "", "steps": 0,
            "errors": 0, "t0": 0.0, "t_end": 0.0, "last_ts": 0.0, "pending": {},
            "result": "", "acked": False, "project": "", "path": "",
            "compacted": False}


class SessionWatcher(QObject):
    """增量 tail 各会话的 messages.jsonl，推导实时任务状态。

    纯只读：只 open(..., 'r') 这些转录文件。首次全量读一次（受 INITIAL_READ_CAP
    限制），之后只读新增字节，因此每轮开销在亚毫秒级。"""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sess = {}          # key -> state
        self._off = {}          # key -> 已读字节数
        self._partial = {}      # key -> 尚未读全的行尾
        self._proj_cache = {}   # dir -> (mtime, size, project)
        self._last_scan = 0.0

    # ---- 发现会话文件 ----
    def _scan_files(self):
        found = []
        if not os.path.isdir(SESSIONS_ROOT):
            return found
        now = time.time()
        for dp, _dn, fn in os.walk(SESSIONS_ROOT):
            if "messages.jsonl" not in fn:
                continue
            mf = os.path.join(dp, "messages.jsonl")
            try:
                mt = os.path.getmtime(mf)
            except OSError:
                continue
            if now - mt > ACTIVE_WINDOW_H * 3600:
                continue
            found.append((mt, dp, mf))
        found.sort(reverse=True)
        return found

    def _project_of(self, sdir):
        """项目名：llm-call.json 的 systemPrompt 里带工作目录，按 (mtime,size) 缓存。"""
        p = os.path.join(sdir, "llm-call.json")
        try:
            st = os.stat(p)
            sig = (st.st_mtime, st.st_size)
        except OSError:
            return ""
        hit = self._proj_cache.get(sdir)
        if hit and hit[0] == sig:
            return hit[1]
        name = ""
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read(2_000_000)
            # llm-call.json 是单行 JSON，systemPrompt 里的换行是字面量 "\n"；
            # 直接当纯文本 grep 会把整行（含工具 schema）一起吞掉，必须先解析。
            blob = raw
            try:
                o = json.loads(raw)
                if isinstance(o, dict):
                    blob = str(o.get("systemPrompt") or "")
            except Exception:
                pass
            m = _RE_CWD.search(blob)
            if m:
                cwd = m.group(1).strip().strip("\\/")
                # 兜底：解析失败时仍可能吃到超长单行，只认像路径的短串
                if cwd and len(cwd) <= 200 and " " not in cwd:
                    name = os.path.basename(cwd) or ""
        except Exception:
            name = ""
        self._proj_cache[sdir] = (sig, name)
        return name

    # ---- 主循环 ----
    def poll(self):
        now = time.time()
        rescan = now - self._last_scan > 12.0
        if rescan:
            self._last_scan = now
            files = self._scan_files()
        else:
            files = []
            for key, s in self.sess.items():
                mf = os.path.join(s["path"], "messages.jsonl")
                try:
                    files.append((os.path.getmtime(mf), s["path"], mf))
                except OSError:
                    pass
            files.sort(reverse=True)

        live = set()
        for _mt, sdir, mf in files:
            key = os.path.basename(sdir)
            live.add(key)
            if key not in self.sess:
                s = _new_state(key)
                s["path"] = sdir
                s["project"] = self._project_of(sdir)
                self.sess[key] = s
                self._off[key] = 0
                self._partial[key] = ""
                log("session", t("log.session", key[:28]) +
                    (t("log.session_proj", s["project"]) if s["project"] else ""))
            s = self.sess[key]
            s["path"] = sdir
            if not s["project"]:
                s["project"] = self._project_of(sdir)
            try:
                size = os.path.getsize(mf)
            except OSError:
                continue
            off = self._off.get(key, 0)
            if size < off:                       # 被截断/替换 → 从头再来
                off = 0
                self._partial[key] = ""
                s = _new_state(key)
                s["path"] = sdir
                s["project"] = self._project_of(sdir)
                self.sess[key] = s
            if size == off:
                self._settle(s, now)
                continue
            start = off
            if start == 0 and size > INITIAL_READ_CAP:
                start = size - INITIAL_READ_CAP
            try:
                with open(mf, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(start)
                    chunk = f.read(size - start)
            except OSError:
                continue
            lines = (self._partial.get(key, "") + chunk).split("\n")
            self._partial[key] = lines.pop()      # 末尾可能半行，留到下次
            self._off[key] = size
            for line in lines:
                line = line.strip()
                if line:
                    self._apply(s, line)
            self._settle(s, now)

        for key in list(self.sess.keys()):
            # 合成会话（演示 / HTTP 推送）不对应磁盘上的转录，不能被当成过期会话清掉，
            # 否则演示刚起步就会被下一轮 poll 抹掉。
            if key in SYNTH_KEYS:
                continue
            if key not in live:
                self.sess.pop(key, None)
                self._off.pop(key, None)
                self._partial.pop(key, None)
        if files:
            self.changed.emit()

    # ---- 单条消息 ----
    def _apply(self, s, line):
        try:
            o = json.loads(line)
        except Exception:
            return
        m = o.get("message") or {}
        role = m.get("role")
        ts = m.get("timestamp") or 0
        if ts:
            s["last_ts"] = ts / 1000.0
        if role in ("user", "assistant", "toolResult"):
            # 又来了新动静 → 任务重新活过来，解除用时冻结；
            # 真正收尾时（assistant 纯文本 / _settle 超时）会再把 t_end 盖上。
            s["t_end"] = 0.0
        parts = m.get("content")
        if isinstance(parts, str):
            parts = [{"type": "text", "text": parts}]

        if role == "user":
            text = ""
            for c in parts or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    text = c.get("text") or ""
                    break
            prompt = _clean_prompt(text, m.get("canonicalTextRange"))
            if not prompt:
                # 纯系统注入，不是新任务：状态、步数、错误数一律保持不动。
                return
            s.update(state="thinking", task=_short(prompt) or t("card.untitled"),
                     steps=0, errors=0, t0=(ts / 1000.0) or time.time(),
                     t_end=0.0, pending={}, result="", acked=False)
            log("task", t("log.new_task", _short(prompt, 70)))

        elif role == "compactionSummary":
            # 被压缩过的会话：原始提问已被回顾替换，用 summary 补一个像样的标题。
            # 不改 state / steps —— 这是历史摘要，不代表当前回合。
            title = _summary_title(m.get("summary") or "")
            if title and not s["task"]:
                s["task"] = title
                s["compacted"] = True
                log("task", t("log.compacted", title[:60]))

        elif role == "assistant":
            calls, has_text, has_thinking = [], False, False
            for c in parts or []:
                if not isinstance(c, dict):
                    continue
                # 注意：局部变量不能叫 t，会遮蔽模块级的 i18n 翻译函数 t()
                ctype = c.get("type")
                if ctype == "toolCall":
                    calls.append((str(c.get("id") or ""), str(c.get("name") or "?")))
                elif ctype == "text":
                    if (c.get("text") or "").strip():
                        has_text = True
                elif ctype == "thinking":
                    has_thinking = True
            if calls:
                for cid, cname in calls:
                    s["pending"][cid] = cname
                s["tool"] = calls[-1][1]
                s["state"] = "executing"
                log("run", "▶ " + calls[-1][1])
            elif has_text:
                txt = ""
                for c in parts or []:
                    if isinstance(c, dict) and c.get("type") == "text":
                        txt = (c.get("text") or "").strip()
                        break
                s["state"] = "done"
                s["t_end"] = s["last_ts"] or time.time()   # 冻结用时，别再往下走
                s["result"] = txt
                log("ok", t("log.turn_end", s["steps"]))
            elif has_thinking:
                s["state"] = "thinking"

        elif role == "toolResult":
            cid = str(m.get("toolCallId") or "")
            s["pending"].pop(cid, None)
            s["steps"] += 1
            failed = bool(m.get("isError"))
            if failed:
                s["errors"] += 1
            name = str(m.get("toolName") or s["tool"] or "?")
            s["tool"] = name
            s["state"] = "error" if failed and not s["pending"] else "executing"
            log("fail" if failed else "ok",
                t("log.tool_step", ("✗ " if failed else "✓ ") + name, s["steps"]))

    # ---- 回合收尾 ----
    def _settle(self, s, now):
        if s["pending"]:
            # 工具已发出但没有回结果：先按执行中，超过阈值再判定为等你确认
            s["state"] = "waiting"
            return
        if s["state"] == "done":
            if s["last_ts"] and now - s["last_ts"] > 900:
                s["state"] = "idle"
            return
        if s["state"] in ("executing", "error", "thinking") and s["last_ts"]:
            if now - s["last_ts"] > 45:
                s["state"] = "done" if s["task"] else "idle"
                if s["state"] == "done":
                    s["t_end"] = now      # 同上：用时停在这一刻

    # ---- 对外 ----
    def visible_sessions(self):
        """值得显示的会话：进行中 / 未被点掉的。

        acked = 用户点过这张卡去跳转了，就不再打扰；新的一轮 user 消息会把
        acked 重置回 False，所以下一条任务仍会正常冒出来。
        """
        now = time.time()
        out = []
        for s in self.sess.values():
            if s["acked"]:
                continue
            if s["state"] == "idle":
                if not s["task"]:
                    continue
                if now - s["last_ts"] > 600:
                    continue
            out.append(s)
        out.sort(key=lambda s: (PRIORITY.get(s["state"], 9), -s["last_ts"]))
        return out[:MAX_CARDS]

    def active(self):
        """团子脸要显示的会话。

        - 正在跑的永远优先，哪怕用户点过它的卡片（他可能只是去看一眼，任务还在跑）；
        - 没人跑的时候只看**没被点掉**的会话：点完上一张卡，团子立刻切到下一个
          任务，没有下一个就回待命——不会一直停在旧任务的完成态上；
        - 全部点掉且没有新任务 → 返回一个空的 idle 态，不保留上一个任务的记忆。
        """
        all_s = list(self.sess.values())
        running = [s for s in all_s if s["state"] in ACTIVE_STATES]
        if running:
            cands = running
        else:
            cands = [s for s in all_s if s["task"] and not s.get("acked")]
        if not cands:
            return _new_state("-")
        cands.sort(key=lambda s: (PRIORITY.get(s["state"], 9), -s["last_ts"]))
        return cands[0]

    def count_active(self):
        return sum(1 for s in self.sess.values()
                   if s["state"] in ACTIVE_STATES)


# ========== 可选：本地 HTTP 事件入口（便于外部脚本推送 / 演示）==========
class _Bridge(QObject):
    event_received = pyqtSignal(dict)
    # 召唤结果回传：探测 / 重拉可能要好几秒，必须走子线程再切回主线程
    activate_result = pyqtSignal(dict)


BRIDGE = _Bridge()


class _EventHandler(BaseHTTPRequestHandler):
    server_version = "MiniMaxPet/1.0"

    def do_POST(self):
        if self.path.rstrip("/") not in ("/event", "/events"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n > 0 else b""
            payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
            if not isinstance(payload, dict):
                payload = {"raw": str(payload)}
        except Exception as e:
            payload = {"parse_error": str(e)}
        try:
            self.send_response(204)          # 空响应，避免调用方打印任何东西
            self.end_headers()
        except Exception:
            pass
        BRIDGE.event_received.emit(payload)

    def do_GET(self):
        body = ("MiniMax Pet ok  app_running=%s\n" % app_running()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class EventServer:
    def __init__(self, preferred_port):
        self.httpd = None
        self.port = None
        self.thread = None
        self.preferred = preferred_port

    def start(self):
        for p in range(self.preferred, self.preferred + 11):
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", p), _EventHandler)
                self.port = p
                break
            except OSError:
                continue
        if self.httpd is None:
            return False
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={"poll_interval": 0.2}, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass


# ========== 全局热键 Ctrl+Alt+M ==========
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL = 0x1, 0x2
VK_M = 0x4D
HOTKEY_ID = 0x4D50


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._cb()
                    return True, 0
        except Exception:
            pass
        return False, 0


# ========== 团子：官方吉祥物 + 表情 ==========
class MascotFace(QWidget):
    """官方吉祥物贴图 + 拟人表情：眨眼、说话、思考、等你确认、庆祝。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.mood = "idle"
        self.blink = False
        self.tick = 0
        self.look = [0.0, 0.0]
        self._shake = 0.0

        self._body = QPixmap(MASCOT_PATH) if os.path.exists(MASCOT_PATH) else QPixmap()
        self._shadow = QPixmap(MASCOT_SHADOW_PATH) \
            if os.path.exists(MASCOT_SHADOW_PATH) else QPixmap()
        self._glow = QPixmap(MASCOT_GLOW_PATH) \
            if os.path.exists(MASCOT_GLOW_PATH) else QPixmap()
        # 投影图比吉祥物向外扩边一圈；用这个比例让投影与身体精确对齐
        if not self._shadow.isNull() and not self._body.isNull():
            self._pad_fx = (self._shadow.width() - self._body.width()) / float(self._body.width())
            self._pad_fy = (self._shadow.height() - self._body.height()) / float(self._body.height())
        else:
            self._pad_fx = self._pad_fy = 0.0
        # 发光同理；没有发光图就按投影的比例来（尺寸本来一样）
        if not self._glow.isNull() and not self._body.isNull():
            self._glow_fx = (self._glow.width() - self._body.width()) / float(self._body.width())
            self._glow_fy = (self._glow.height() - self._body.height()) / float(self._body.height())
        else:
            self._glow_fx = self._glow_fy = 0.0

        self.setFixedSize(BODY_W, BODY_H)
        self.blink_timer = QTimer(self, timeout=self._do_blink,
                                  interval=random.randint(2600, 4800))
        self.blink_timer.start()
        QTimer(self, timeout=self._wander, interval=2400).start()
        self.anim = QTimer(self, timeout=self._step, interval=90)
        self.anim.start()

    # ---- 动画 ----
    def _do_blink(self):
        if self.mood == "done":
            return
        self.blink = True
        self.update()
        QTimer.singleShot(130, self._end_blink)

    def _end_blink(self):
        self.blink = False
        self.update()

    def _wander(self):
        if self.mood in ("idle", "thinking"):
            self.look = [random.uniform(-2.6, 2.6) * _draw_k(),
                         random.uniform(-1.8, 1.8) * _draw_k()]
            self.update()

    def _step(self):
        self.tick += 1
        if self._shake > 0:
            self._shake = max(0.0, self._shake - 0.45)
        self.update()

    def set_mood(self, m):
        if m != self.mood:
            self.mood = m
            self.blink = False
            self.look = [0.0, 0.0]
            self.update()

    def shake(self):
        self._shake = 7.0 * _draw_k()

    # ---- 绘制 ----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tk = self.tick
        w, h = float(self.width()), float(self.height())
        k = _draw_k()

        dx = dy = 0.0
        if self._shake > 0:
            dx = math.sin(tk * 1.7) * self._shake * 0.7
        if self.mood == "executing":
            dy = abs(math.sin(tk / 2.6)) * -2.0 * k
        elif self.mood == "waiting":
            dy = abs(math.sin(tk / 1.9)) * -2.4 * k
        elif self.mood == "thinking":
            dy = math.sin(tk / 6.0) * 1.3 * k
        elif self.mood == "error":
            dx = math.sin(tk / 1.4) * 2.2 * k

        # 身体矩形：顶部留出「头顶区」放思考气泡 / 感叹号，其余留内边距
        head = h * 0.165
        pad_x, pad_bot = w * 0.035, h * 0.035
        if not self._body.isNull():
            src = self._body
            avail_w, avail_h = w - pad_x * 2, h - head - pad_bot
            ar = src.width() / float(src.height())
            bw = avail_h * ar if avail_w / avail_h > ar else avail_w
            bh = bw / ar
            bx = (w - bw) / 2.0 + dx
            by = head + (avail_h - bh) / 2.0 + dy
            if not self._glow.isNull():
                # 发光是居中的，不能跟着投影一起下移，否则上方会露出偏移的边
                p.drawPixmap(QRectF(bx - self._glow_fx / 2.0 * bw,
                                    by - self._glow_fy / 2.0 * bh,
                                    bw * (1 + self._glow_fx), bh * (1 + self._glow_fy)),
                             self._glow, QRectF(self._glow.rect()))
            if not self._shadow.isNull():
                # 投影整体下移一点 → 落地阴影，而不是一圈描边
                p.drawPixmap(QRectF(bx - self._pad_fx / 2.0 * bw,
                                    by - self._pad_fy / 2.0 * bh + bh * 0.055,
                                    bw * (1 + self._pad_fx), bh * (1 + self._pad_fy)),
                             self._shadow, QRectF(self._shadow.rect()))
            p.drawPixmap(QRectF(bx, by, bw, bh), src, QRectF(src.rect()))
        else:
            bx, by, bw, bh = 4.0 * k, head, w - 8.0 * k, h - head - 4.0 * k

        # 表情锚点（bx/by 已含 dx/dy）
        cx = bx + bw / 2.0
        eye_y = by + bh * 0.335
        eye_dx = bw * 0.152
        er = bw * 0.052
        mouth_y = by + bh * 0.470

        ink = QColor(FACE_INK)
        p.setPen(Qt.NoPen)

        # ---- 眼睛 ----
        for side in (-1, 1):
            ex = cx + side * eye_dx + self.look[0]
            ey = eye_y + self.look[1]
            if self.mood == "done":                       # 开心弯月眼
                p.setPen(QPen(ink, max(1.0, er * 0.42), Qt.SolidLine, Qt.RoundCap))
                p.setBrush(Qt.NoBrush)
                p.drawArc(QRectF(ex - er * 1.05, ey - er * 0.75, er * 2.1, er * 1.7),
                          20 * 16, 140 * 16)
            elif self.blink:
                p.setPen(QPen(ink, max(1.0, er * 0.40), Qt.SolidLine, Qt.RoundCap))
                p.setBrush(Qt.NoBrush)
                p.drawLine(QPointF(ex - er, ey), QPointF(ex + er, ey))
            else:
                ry = er * (1.16 if self.mood == "waiting" else
                           (0.92 if self.mood == "executing" else 1.0))
                p.setPen(Qt.NoPen)
                p.setBrush(ink)
                p.drawEllipse(QPointF(ex, ey), er, ry)
                p.setBrush(QColor(255, 255, 255, 235))
                p.drawEllipse(QPointF(ex + er * 0.34, ey - ry * 0.38), er * 0.33, er * 0.33)
                p.setBrush(QColor(255, 255, 255, 150))
                p.drawEllipse(QPointF(ex - er * 0.30, ey + ry * 0.34), er * 0.17, er * 0.17)

        # ---- 嘴巴 ----
        p.setBrush(Qt.NoBrush)
        if self.mood == "waiting":                      # 张口：等你确认
            p.setPen(Qt.NoPen)
            p.setBrush(ink)
            p.drawEllipse(QPointF(cx, mouth_y), er * 0.62, er * 0.92)
        elif self.mood in ("executing", "error"):       # 专注的小嘴
            p.setPen(Qt.NoPen)
            p.setBrush(ink)
            p.drawEllipse(QPointF(cx, mouth_y), er * 0.50, er * 0.60)
        elif self.mood == "done":                       # 开心笑
            p.setPen(QPen(ink, max(1.0, er * 0.40), Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(cx - er * 1.15, mouth_y - er * 0.90, er * 2.3, er * 1.8),
                      200 * 16, 140 * 16)
        elif self.mood == "thinking":                   # 一条线：思考
            p.setPen(QPen(ink, max(1.0, er * 0.36), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx - er * 0.85, mouth_y), QPointF(cx + er * 0.85, mouth_y))
        else:                                          # 微笑
            p.setPen(QPen(ink, max(1.0, er * 0.36), Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(cx - er * 1.0, mouth_y - er * 0.75, er * 2.0, er * 1.5),
                      200 * 16, 140 * 16)

        # ---- 思考：头顶 M 字气泡 ----
        if self.mood == "thinking":
            rise = (tk // 5) % 3 * 1.2 * k
            for i in range(3):
                fz = (7.0 + i * 2.0) * k
                mx = cx + (i - 1) * 15 * k
                my = head * 0.72 - i * 2.0 * k - rise
                c = QColor(BLUE_MID)
                c.setAlpha((105, 175, 255)[(tk // 3 + i) % 3])
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.setFont(QFont("Arial", max(4, int(round(fz))), QFont.Black))
                p.drawText(QRectF(mx - fz, my - fz * 0.62, fz * 2, fz * 1.25),
                           Qt.AlignCenter, "M")

        # ---- 等待 / 出错：头顶感叹号 ----
        if self.mood in ("waiting", "error"):
            color = WAITING if self.mood == "waiting" else DESTRUCT
            ax, ay = cx + bw * 0.38, head * 0.46
            if self.mood == "waiting":
                pulse = 0.65 + 0.35 * abs(math.sin(tk / 2.0))
                glow = QColor(color)
                glow.setAlpha(int(58 * pulse))
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(QPointF(ax, ay), 10.0 * k, 10.0 * k)
                c = QColor(color)
                c.setAlpha(int(255 * pulse))
                p.setBrush(c)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(color))
            p.drawEllipse(QPointF(ax, ay), 7.6 * k, 7.6 * k)
            p.setBrush(QColor(255, 255, 255))
            p.setFont(QFont("Arial", max(4, int(round(10 * k))), QFont.Black))
            p.drawText(QRectF(ax - 9 * k, ay - 9 * k, 18 * k, 18 * k),
                       Qt.AlignCenter, "!")

        # ---- 完成：四角闪光 ----
        if self.mood == "done":
            for (fx, fy) in ((bx + 2 * k, by + 10 * k), (bx + bw - 4 * k, by + 20 * k),
                             (bx + 6 * k, by + bh - 12 * k),
                             (bx + bw - 10 * k, by + bh - 4 * k)):
                c = QColor(SUCCESS)
                c.setAlpha(110 + int(120 * abs(math.sin((tk + fx) / 3.0))))
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawEllipse(QPointF(fx, fy), 2.1 * k, 2.1 * k)


# ========== 绘制基元 ==========
# 说明：状态条与卡片全部用 QPainter 自绘。原因有二：
#   1) Qt 样式表的 font-family 会覆盖 setFont()，且样式表不做逐字形回退，
#      ✓ / ⏸ 这类字形会变成豆腐块（实测本机 Qt5 就是如此）；
#   2) 图标用矢量路径画，比挑字体字形更可控、也更清晰。
def _icon_path(kind, cx, cy, r):
    """返回一个只含子路径的 QPainterPath，调用方按需 fill/stroke。"""
    path = QPainterPath()
    if kind == "thinking":                       # 半圆：像在转的进度
        path.addEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    elif kind == "executing":                    # 右向三角
        path.moveTo(cx - r * 0.75, cy - r)
        path.lineTo(cx + r * 0.95, cy)
        path.lineTo(cx - r * 0.75, cy + r)
        path.closeSubpath()
    elif kind == "waiting":                      # 暂停双竖条
        path.addRoundedRect(QRectF(cx - r * 0.85, cy - r, r * 0.7, 2 * r), r * 0.3, r * 0.3)
        path.addRoundedRect(QRectF(cx + r * 0.15, cy - r, r * 0.7, 2 * r), r * 0.3, r * 0.3)
    elif kind == "done":                         # 对勾
        path.moveTo(cx - r * 0.9, cy + r * 0.05)
        path.lineTo(cx - r * 0.25, cy + r * 0.7)
        path.lineTo(cx + r * 0.95, cy - r * 0.7)
    elif kind == "error":                        # 叉
        path.moveTo(cx - r * 0.7, cy - r * 0.7)
        path.lineTo(cx + r * 0.7, cy + r * 0.7)
        path.moveTo(cx + r * 0.7, cy - r * 0.7)
        path.lineTo(cx - r * 0.7, cy + r * 0.7)
    else:                                        # idle：实心圆点
        path.addEllipse(QRectF(cx - r * 0.8, cy - r * 0.8, r * 1.6, r * 1.6))
    return path


def _draw_icon(p, kind, cx, cy, r, color, fill=True):
    path = _icon_path(kind, cx, cy, r)
    p.setBrush(QColor(color) if fill else Qt.NoBrush)
    if kind in ("done", "error"):                # 勾/叉用描边
        p.setPen(QPen(QColor(color), max(1.0, r * 0.34), Qt.SolidLine, Qt.RoundCap,
                      Qt.RoundJoin))
    else:
        p.setPen(Qt.NoPen)
    p.drawPath(path)


def _draw_text(p, rect, text, font, color, align=Qt.AlignLeft | Qt.AlignVCenter):
    p.setFont(font)
    p.setPen(QColor(color))
    p.drawText(rect, align, text)


class StatusPill(QWidget):
    """团子下方的状态条：圆角胶囊 + 矢量图标 + 文字。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._text = t("mood.idle")
        self._color = FG_SUBTLE
        self._kind = "idle"
        self.setFixedHeight(CHIP_H)

    def set_status(self, text, color, kind):
        self._text, self._color, self._kind = text, color, kind
        # 必须 updateGeometry()：文字变了 sizeHint 就变了，而布局缓存着上一次的
        # 几何尺寸，只调 update() 的话胶囊会一直保持旧宽度，文字就被裁掉
        # （实测「19 步 · 02:34」只剩「19 步 · 02」）。
        self.updateGeometry()
        self.update()
        lay = self.parentWidget().layout() if self.parentWidget() else None
        if lay is not None:
            lay.activate()

    def _metrics(self):
        """胶囊的图标半径、左右留白、以及总横向开销。

        paintEvent 和 minimumSizeHint 必须共用这一份。之前一个用
        pad*2 + ir*2 + _px(4)、另一个写死 _px(34)，两处各自漂移，
        算出来的宽度和实际画得出来的对不上，文字就被裁掉了。
        """
        ir = _px(5)
        pad = _px(7)
        return ir, pad, pad * 2 + ir * 2 + _px(3)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2.0
        font = ui_font(_fpx(11))
        from PyQt5.QtGui import QFontMetrics
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(self._text)
        ir, pad, total = self._metrics()
        width = min(w, tw + total)
        x0 = (w - width) / 2.0
        body = QRectF(x0, 0, width, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(18, 20, 24, 210))
        p.drawRoundedRect(body, r, r)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        cx = x0 + pad + ir
        _draw_icon(p, self._kind, cx, h / 2.0, ir, self._color)
        # 文字可用宽度按**控件**宽度算，不是按胶囊圆角矩形宽度算，
        # 否则右边会白留一段、看起来又是被截断。
        tx = cx + ir + _px(4)
        _draw_text(p, QRectF(tx, 0, max(0.0, w - tx), h), self._text, font, self._color)

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        fm = QFontMetrics(ui_font(_fpx(11)))
        return QSize(fm.horizontalAdvance(self._text) + self._metrics()[2], CHIP_H)


def ellipsize(text, n):
    text = " ".join(str(text).split())
    return text[:n] + "…" if len(text) > n else text


def elapsed_str(s):
    """任务用时。任务结束后**冻结**在 t_end，不再继续走。

    之前只认 t0，于是「已完成」的卡片用时一秒一秒地涨——任务都结束了还显示
    07:40、08:20，看着像还在跑。这里在进入 done 的那一刻记下 t_end。
    """
    if not s.get("t0"):
        return "00:00"
    end = s.get("t_end") or time.time()
    sec = max(0, int(end - s["t0"]))
    return "%02d:%02d" % (sec // 60, sec % 60)


# ========== 任务卡片窗口 ==========
class TaskCard(QWidget):
    """单张任务卡：标题 + 状态 + 项目/用时，整卡可点（跳转 MiniMax Code）。"""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(_px(CARD_H))
        self.d = {"title": "", "status": "", "meta": "", "color": FG_SUBTLE,
                  "kind": "idle", "key": ""}
        self._hover = False

    def set_data(self, d):
        self.d = d
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        e.accept()

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = _px(11)
        body = QRectF(0, 0, w, h)
        p.setPen(QPen(QColor(255, 255, 255, 30 if self._hover else 18), 1))
        p.setBrush(QColor(24, 26, 30, 242 if self._hover else 232))
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        # 左侧状态色条
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.d["color"]))
        p.drawRoundedRect(QRectF(0, h * 0.22, _px(3), h * 0.56), _px(1.5), _px(1.5))

        pad = _px(13)
        right = _px(12)
        icon_r = _px(6)
        icon_cx = w - right - icon_r
        _draw_icon(p, self.d["kind"], icon_cx, h / 2.0, icon_r, self.d["color"])

        f_title = ui_font(_fpx(12))
        f_status = ui_font(_fpx(11))
        f_meta = ui_font(_fpx(10), bold=False)
        fm_t, fm_s, fm_m = (QFontMetrics(f) for f in (f_title, f_status, f_meta))
        meta_w = fm_m.horizontalAdvance(self.d["meta"]) + _px(2)
        text_w = icon_cx - icon_r - _px(8) - (pad + _px(4))

        # 行高由字体度量决定，不能写死 _px(17)/_px(16)——那跟着 SIZE_RATIO 缩，
        # 字号一旦独立放大就会被裁掉。两行整体在卡片里垂直居中。
        row_t, row_b = fm_t.height(), max(fm_s.height(), fm_m.height())
        gap = max(2, _px(3))
        top = (h - (row_t + gap + row_b)) / 2.0
        top_rect = QRectF(pad, top, text_w, row_t)
        bot_rect = QRectF(pad, top + row_t + gap, text_w, row_b)
        _draw_text(p, top_rect, _elide(fm_t, self.d["title"], text_w),
                   f_title, FG, Qt.AlignLeft | Qt.AlignVCenter)
        _draw_text(p, bot_rect, _elide(fm_s, self.d["status"], text_w),
                   f_status, self.d["color"], Qt.AlignLeft | Qt.AlignVCenter)
        _draw_text(p, QRectF(icon_cx - icon_r - _px(6) - meta_w,
                             bot_rect.y(), meta_w, row_b),
                   self.d["meta"], f_meta, FG_SUBTLE, Qt.AlignRight | Qt.AlignVCenter)


def _elide(fm, text, width):
    """按像素宽度截断并加省略号。"""
    if fm.horizontalAdvance(text) <= width:
        return text
    ell = "…"
    out = text
    while out and fm.horizontalAdvance(out + ell) > width:
        out = out[:-1]
    return out + ell


def _chevron(p, cx, cy, r, up, color, width):
    """矢量折线箭头，不依赖字体符号字形。

    up=True 顶点朝上（▲，收起），False 顶点朝下（▼，展开）。
    注意屏幕 y 轴向下，所以「朝上」= 顶点 y 更小。
    """
    p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if up:
        vx, vy = cx, cy - r * 0.55
        ay = cy + r * 0.45
    else:
        vx, vy = cx, cy + r * 0.55
        ay = cy - r * 0.45
    p.drawLine(QPointF(cx - r, ay), QPointF(vx, vy))
    p.drawLine(QPointF(vx, vy), QPointF(cx + r, ay))


class CardFooter(QWidget):
    """折叠 / 展开提示条。

    折叠时：「还有 N 个任务」（往下指，点一下全展开）
    展开时：「收起」（往上指，点一下收回一行）
    """

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(_px(FOOTER_H))
        self.text = ""
        self.up = False
        self._hover = False

    def set_state(self, text, up):
        if (self.text, self.up) != (text, up):
            self.text, self.up = text, up
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        e.accept()

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(255, 255, 255, 34 if self._hover else 20), 1))
        p.setBrush(QColor(24, 26, 30, 236 if self._hover else 214))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), _px(9), _px(9))

        f = ui_font(_fpx(11))
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(self.text)
        ar = _px(4.5)
        gap = _px(6)
        cx = (w - (tw + ar * 2 + gap)) / 2.0 + ar
        _chevron(p, cx, h / 2.0, ar, self.up, FG_SUBTLE, max(1.0, _px(1.3)))
        _draw_text(p, QRectF(cx + ar + gap, 0, tw + 2, h), self.text,
                   f, FG_SUBTLE, Qt.AlignLeft | Qt.AlignVCenter)


class CardStack(QWidget):
    """悬浮在团子上方的实时任务卡片堆；点卡片跳转 MiniMax Code。

    默认**只显示 COLLAPSED_ROWS 张**，其余收进底部的折叠条；点折叠条才完全展开。
    被用户点过（acked）的任务根本不会进 items —— 既不出现在折叠内容里，也不在
    展开列表里。
    """

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(t("win.cards"))
        self.setFixedWidth(_px(CARD_W))
        self.rows = []
        self.items = []
        self.expanded = False
        self.on_card = None
        self.on_background = None
        self.on_toggle = None
        self._sig = None
        self._cards = []
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(_px(CARD_GAP))
        self.footer = CardFooter()
        self.footer.hide()
        self.footer.mousePressEvent = self._make_toggle()
        self.box.addWidget(self.footer)

    # ---------- 折叠 / 展开 ----------
    def set_expanded(self, flag):
        flag = bool(flag)
        if flag == self.expanded:
            return False
        self.expanded = flag
        self.rebuild(self.items)
        return True

    def toggle_expanded(self):
        return self.set_expanded(not self.expanded)

    def _make_toggle(self):
        def handler(e):
            if e.button() == Qt.LeftButton and self.on_toggle:
                self.on_toggle()
        return handler

    def _shown_items(self):
        return self.items if self.expanded else self.items[:COLLAPSED_ROWS]

    def _sync_footer(self, hidden):
        """折叠条：有得展开才显示「还有 N 个」；展开态显示「收起」。"""
        if self.expanded:
            if not self.items:
                self.footer.hide()
                return
            self.footer.set_state(t("foot.collapse"), True)
        elif hidden > 0:
            self.footer.set_state(t("foot.more", hidden), False)
        else:
            self.footer.hide()
            return
        self.footer.show()

    def _content_height(self, hidden):
        n = len(self._cards)
        if not n:
            return 8
        h = _px(n * CARD_H + (n - 1) * CARD_GAP)
        if hidden or (self.expanded and self.items):
            h += _px(CARD_GAP) + _px(FOOTER_H)
        return h

    def rebuild(self, items):
        """结构不变就原地更新（每秒的用时刷新不该重建控件）；结构变了才重建。"""
        self.items = items
        shown = self._shown_items()
        hidden = len(items) - len(shown)
        keys = [d["key"] for d in shown]
        sig = (keys, self.expanded, hidden)
        if sig == self._sig and len(self._cards) == len(shown):
            for c, d in zip(self._cards, shown):
                c.set_data(d)
            self._sync_footer(hidden)
            self.setFixedHeight(self._content_height(hidden))
            return
        self._sig = sig
        while self.box.count():
            it = self.box.takeAt(0)
            w = it.widget()
            if w is None or w is self.footer:
                # footer 是常驻控件，takeAt 只是把它摘出布局，不能销毁，
                # 否则第二帧起折叠条就没了。
                continue
            w.deleteLater()
        self.rows = []
        self._cards = []
        for d in shown:
            c = TaskCard()
            c.set_data(d)
            c.mousePressEvent = self._make_handler(d["key"])
            self.box.addWidget(c)
            self._cards.append(c)
            self.rows.append(d["key"])
        self.footer.hide()
        self.box.addWidget(self.footer)
        self._sync_footer(hidden)
        self.setFixedHeight(self._content_height(hidden))

    def _make_handler(self, key):
        def handler(e, _k=key):
            if e.button() == Qt.LeftButton and self.on_card:
                self.on_card(_k)
        return handler

    def count(self):
        """当前**显示出来的**任务卡数（不含折叠条）。"""
        return len(self._cards)

    def total(self):
        """没被点掉、值得显示的任务总数（含折叠起来的）。"""
        return len(self.items)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        y = e.pos().y()
        pitch = _px(CARD_H + CARD_GAP)
        idx = y // pitch if y >= 0 else -1
        if 0 <= idx < len(self.rows) and (y - idx * pitch) <= _px(CARD_H):
            if self.on_card:
                self.on_card(self.rows[idx])
        elif self.on_background:
            self.on_background()

    def popup(self, pet):
        self.reposition(pet)
        self.show()
        self.raise_()

    def reposition(self, pet):
        scr = QGuiApplication.screenAt(pet.geometry().center()) or \
            QGuiApplication.primaryScreen()
        geo = scr.availableGeometry()
        x = pet.x() + (pet.width() - self.width()) // 2
        x = min(max(x, geo.left() + 2), geo.right() - self.width() - 1)
        y = pet.y() - self.height() - 8
        if y < geo.top() + 2:
            below = pet.y() + pet.height() + 8
            if below + self.height() <= geo.bottom() - 1:
                y = below
        self.move(max(x, geo.left() + 2), max(y, geo.top() + 2))


# ========== 主窗口 ==========
class PetWindow(QWidget):
    def __init__(self, server=True, tray=True, hotkey=True,
                 port=DEFAULT_PORT, follow=True, exit_with_app=False,
                 follow_mode=FOLLOW_MODE_PROCESS):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(t("win.pet"))
        self.setFixedSize(*PET_SIZE)

        self.follow = follow
        self.follow_mode = (follow_mode if follow_mode in FOLLOW_MODES
                            else FOLLOW_MODE_PROCESS)
        self.exit_with_app = exit_with_app
        self.manual_hidden = False
        self.cards_manual = False
        self._drag_from = None
        self._win_from = None
        self._moved = False
        self._face_mood = ""
        self._toast = ""
        self._toast_until = 0.0
        self._watcher_checked = 0.0
        self._act_busy = False
        self.state = load_state()

        self.watcher = SessionWatcher(self)
        self.watcher.changed.connect(self.refresh)

        self._build_ui()
        self._restore_pos()

        # 生命周期跟随
        # 起始状态就先探一次：桌宠通常是被 pet_watcher 在检测到 MiniMax Code
        # 打开时才拉起来的，这时 app_seen 应该是 True；如果用户手动双击
        # run_pet.bat 而 MiniMax Code 没开，就必须是 False，否则
        # _check_app 的「连续两次没检测到才判关闭」分支永远不会触发。
        self.app_seen = app_running()
        self.app_miss = 0
        # 召唤结果统一回到主线程再改 UI —— 子线程里绝对不碰任何控件
        BRIDGE.activate_result.connect(self._on_activate_result)
        self.app_timer = QTimer(self, timeout=self._check_app, interval=3000)
        self.app_timer.start()

        # 插拔显示器 / 主屏切换 → 重新按新屏幕的 DPR 换算一次。
        # 这是「拔掉外接显示器桌宠突然变大」的直接修复点。
        try:
            _gui = QGuiApplication.instance()
            _gui.screenAdded.connect(self._on_screens_changed)
            _gui.screenRemoved.connect(self._on_screens_changed)
            _gui.primaryScreenChanged.connect(self._on_screens_changed)
        except Exception:
            pass

        # 可选 HTTP 事件入口
        self.srv = None
        self.port = None
        if server:
            self.srv = EventServer(port)
            if self.srv.start():
                self.port = self.srv.port
                BRIDGE.event_received.connect(self._on_http_event)
                log("info", t("log.port", self.port))
            else:
                log("warn", t("log.port_busy"))

        self.poll = QTimer(self, timeout=self._poll, interval=700)
        self.poll.start()
        self.clock = QTimer(self, timeout=self._clock, interval=1000)
        self.clock.start()

        self.tray = None
        if tray and QSystemTrayIcon.isSystemTrayAvailable():
            self._init_tray()

        self.hotkey_ok = False
        self._hk = None
        if hotkey and sys.platform == "win32":
            try:
                if _u32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_M):
                    self._hk = HotkeyFilter(self.toggle_visible)
                    QApplication.instance().installNativeEventFilter(self._hk)
                    self.hotkey_ok = True
            except Exception:
                pass

        self.watcher.poll()
        self.refresh()
        self._check_app()

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget(self)
        v = QVBoxLayout(root)
        v.setContentsMargins((PET_SIZE[0] - BODY_W) // 2, 0, 0, 0)
        v.setSpacing(0)

        self.face = MascotFace()
        v.addWidget(self.face, 0, Qt.AlignHCenter)

        self.chip = StatusPill()
        v.addWidget(self.chip, 0, Qt.AlignHCenter)
        v.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        self.cards = CardStack()
        self.cards.on_card = self._on_card_click
        self.cards.on_background = self.toggle_cards
        self.cards.on_toggle = self._on_cards_toggle

    def _init_tray(self):
        if os.path.exists(MASCOT_TRAY_PATH):
            icon = QIcon(QPixmap(MASCOT_TRAY_PATH))
        elif os.path.exists(MASCOT_PATH):
            icon = QIcon(QPixmap(MASCOT_PATH))
        else:
            icon = QIcon()
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("MiniMax Pet — 任务进度桌宠")
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(
            lambda r: self.toggle_visible() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _add_lang_menu(self, m):
        """语言子菜单：中英随时切换，选择写回 pet_state.json。"""
        sub = m.addMenu(t("menu.language"))
        for lg in I18N_LANGS:
            a = sub.addAction("简体中文" if lg == "zh" else "English")
            a.setCheckable(True)
            a.setChecked(get_lang() == lg)
            a.triggered.connect(lambda _c=False, l=lg: self._set_lang(l))
        return sub

    def _build_menu(self):
        m = QMenu()
        m.addAction(t("menu.show_pet"), self.toggle_visible)
        m.addAction(t("menu.show_cards"), self.toggle_cards)
        m.addSeparator()
        self._add_follow_menu(m)
        m.addSeparator()
        m.addAction(t("menu.jump"), lambda: self.jump_app(None))
        m.addAction(t("menu.demo"), self.run_demo)
        self._add_size_menu(m)
        m.addAction(t("menu.reset"), self.reset_pos)
        m.addAction(t("menu.opendir"), self._open_dir)
        m.addSeparator()
        self._add_lang_menu(m)
        m.addSeparator()
        m.addAction(t("menu.quit"), lambda: self.quit(reason="user"))
        return m

    def _open_dir(self):
        try:
            if sys.platform == "win32":
                os.startfile(BASE)      # noqa: S606
        except Exception:
            pass

    # ---------- 位置（只存本项目目录）----------
    def _default_pos(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        return QPoint(geo.right() - self.width() - 40, geo.bottom() - self.height() - 48)

    def _restore_pos(self):
        pos = self.state.get("pos")
        if isinstance(pos, list) and len(pos) == 2 and self._on_screen(QPoint(int(pos[0]),
                                                                              int(pos[1]))):
            self.move(QPoint(int(pos[0]), int(pos[1])))
        else:
            self.move(self._default_pos())

    def _on_screen(self, pos):
        for scr in QGuiApplication.screens():
            if scr.availableGeometry().adjusted(-60, -60, 60, 60).contains(pos):
                return True
        return False

    def _clamp_pos(self):
        scr = QGuiApplication.screenAt(self.geometry().center()) or \
            QGuiApplication.primaryScreen()
        geo = scr.availableGeometry()
        p = self.pos()
        x = min(max(p.x(), geo.left()), geo.right() - self.width() + 1)
        y = min(max(p.y(), geo.top()), geo.bottom() - self.height() + 1)
        if (x, y) != (p.x(), p.y()):
            self.move(QPoint(x, y))

    def reset_pos(self):
        self.move(self._default_pos())
        self._save_pos()

    def _save_pos(self):
        self.state["pos"] = [self.x(), self.y()]
        save_state(self.state)

    def moveEvent(self, e):
        if self.cards.isVisible():
            self.cards.reposition(self)
        e.accept()

    # ---------- 生命周期跟随 ----------
    def _check_app(self):
        """显隐跟随。

        两个口径分得很清：
        · 「显示 / 隐藏」跟 **app_foreground()**（窗口在不在）——这才是
          菜单里那条「跟随 MiniMax Code 开关」承诺的行为；
        · 「退出」跟 **app_running()**（进程在不在）——只有进程真没了才退出，
          否则「关掉窗口、后台还留着」会把桌宠也一起带走，多余且吓人。

        manual_hidden 是手动对跟随的**临时覆盖**：手动隐藏后本次不打扰，
        等应用下次重新打开，跟随重新接管。手动开关**永远不改 follow 开关
        本身**（以前这里会偷偷把 follow 关掉并写进状态文件，用户只是想让
        桌宠出来一下，从此就再也不跟随了）。
        """
        running = app_running()
        # 「显示 / 隐藏」跟什么由 follow_mode 决定（默认跟进程）；
        # 「退出」永远只看进程 —— 窗口关了但后台还活着时，桌宠不该跟着自杀。
        # getattr：_check_app 会被裸对象（没跑过 __init__）直接调用，
        # 取不到 follow_mode 就退回默认，别把生命周期契约炸掉。
        mode = getattr(self, "follow_mode", FOLLOW_MODE_PROCESS)
        fg = (running if mode == FOLLOW_MODE_PROCESS
              else app_foreground())

        if fg:
            if not self.app_seen:
                log("lifecycle", t("log.app_seen"))
                if self.follow and self.manual_hidden:
                    self.manual_hidden = False
                    log("info", t("log.follow_resume"))
            self.app_seen = True
            self.app_miss = 0
            if self.follow and not self.manual_hidden and not self.isVisible():
                self._sync_visibility(True)
        elif self.app_seen:
            self.app_miss += 1
            if self.app_miss >= 2:            # 连续两次没有才判关闭，避免闪烁误判
                log("lifecycle", t("log.app_gone"))
                if self.exit_with_app and not running:
                    self.quit()
                elif self.follow and not self.manual_hidden:
                    self._sync_visibility(False)
                self.app_seen = False
                self.app_miss = 0
        if running:
            try:
                self._ensure_watcher()
            except Exception:
                pass

    def _ensure_watcher(self):
        """反向看门：哨兵没了就把它拉回来。

        哨兵管「应用在 → 桌宠必须在」，桌宠管「应用在 → 哨兵必须在」，
        两者互相保险。除非两个进程在同一瞬间一起被杀，桌面不会再空着。
        _check_app 每 3 秒调一次，这里再限流到 9 秒一次。
        """
        now = time.time()
        last = getattr(self, "_watcher_checked", 0.0)
        if now - last < 9.0:
            return
        try:
            self._watcher_checked = now
        except Exception:
            pass
        try:
            import pet_watcher
            if not pet_watcher.lock_held_by_other():
                log("lifecycle", t("log.watcher_restore"))
                pet_watcher.spawn_watcher()
        except Exception:
            pass

    def _sync_visibility(self, running):
        if running:
            if not self.isVisible():
                self.show()
                self.raise_()
        else:
            if self.isVisible():
                self.hide()
            if self.cards.isVisible():
                self.cards.hide()

    def _set_follow(self, on):
        self.follow = bool(on)
        self.state["follow"] = self.follow
        save_state(self.state)
        log("info", t("log.follow", self.follow))
        if self.follow:
            # 刚打开跟随：解除手动覆盖，并立刻按当前状态重新判一次显隐，
            # 免得勾了还要等下一个轮询周期。
            self.manual_hidden = False
            self.app_seen = False
            self.app_miss = 0
            self._check_app()
        else:
            # 关掉跟随 = 「桌宠不再由应用支配」，那就先把已经藏起来的它放出来
            self._sync_visibility(True)
        self._refresh_menus()

    def _set_follow_mode(self, mode):
        if mode not in FOLLOW_MODES:
            return
        self.follow_mode = mode
        self.state["follow_mode"] = mode
        save_state(self.state)
        log("info", t("log.follow_mode", follow_mode_text(mode)))
        if self.follow:                    # 立刻按新口径重新判一次
            self.app_seen = False
            self.app_miss = 0
            self._check_app()
        self._refresh_menus()

    def _refresh_menus(self):
        """开关变了就重建托盘菜单，否则勾选状态会一直停在旧值上。"""
        if self.tray:
            try:
                self.tray.setContextMenu(self._build_menu())
            except Exception:
                pass

    def _add_follow_menu(self, m):
        """跟随相关的菜单项。托盘和右键共用，别再各写一份。"""
        a1 = m.addAction(t("menu.follow"))
        a1.setCheckable(True)
        a1.setChecked(self.follow)
        a1.triggered.connect(self._set_follow)
        sub = m.addMenu(t("follow.mode_menu"))
        group = QActionGroup(sub)
        group.setExclusive(True)
        for mode in FOLLOW_MODES:
            a = sub.addAction(follow_mode_text(mode))
            a.setCheckable(True)
            a.setChecked(self.follow_mode == mode)
            a.triggered.connect(
                lambda _c=False, m_=mode: self._set_follow_mode(m_))
            group.addAction(a)
        a2 = m.addAction(t("menu.exit_with"))
        a2.setCheckable(True)
        a2.setChecked(self.exit_with_app)
        a2.triggered.connect(self._set_exit_with_app)
        return m

    # ---------- 尺寸：物理像素锚定 + 档位 ----------
    def _current_dpr(self):
        """桌宠**当前所在**屏幕的 Qt DPR；取不到就用主屏；再取不到用 1.0。

        顺带把屏幕名缓存下来给 HTTP 诊断用（那个 handler 在子线程上，
        不能自己去问 Qt）。注意这只是**初值**，最终以 _measure_scale()
        的实测为准。
        """
        global _SCREEN_NAME
        try:
            scr = QGuiApplication.screenAt(self.geometry().center())
            if scr is None:
                scr = QGuiApplication.primaryScreen()
            if scr is not None:
                _SCREEN_NAME = scr.name()
                return float(scr.devicePixelRatio())
        except Exception:
            pass
        return 1.0

    def _measure_scale(self):
        """用 Win32 量一次「逻辑像素 → 物理像素」的真实比例。

        为什么要有实测这一步：尺子本身也可能是错的。Qt 的 devicePixelRatio
        在多屏混合缩放、DPI 虚拟化等组合下未必等于窗口实际被放大的倍数，
        而拿一个 DPI-unaware 的进程去量还会再被虚拟化一次（量出来会小 1.5 倍，
        本机就踩过这个坑，一度以为 Qt 报错了）。
        量高度而不是宽度——_fit_width() 会按状态胶囊文字动态改宽度，
        用宽度量会被文字长度污染。
        """
        global _PX_FACTOR
        if sys.platform != "win32" or _u32 is None or _k32 is None:
            return None
        try:
            hwnd = wintypes.HWND(int(self.winId()))
            rect = wintypes.RECT()
            if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            phys_h = float(rect.bottom - rect.top)
            log_h = max(1.0, float(self.height()))
            k = phys_h / log_h
            if 0.25 < k < 8.0:
                _PX_FACTOR = k
                return k
        except Exception as e:
            log("info", t("log.size.measure_fail", e))
        return None

    def _apply_size(self, force=False, measure=False):
        """把当前比例 + 档位落到窗口、团子、胶囊和卡片上。

        measure=True 时先按现有比例应用，再实测一次真实比例，不一致就改用
        实测值重算——这样启动和换屏都能自动收敛到正确的物理大小。
        """
        if measure:
            self._apply_size_once(force=force)
            try:
                QApplication.processEvents()
            except Exception:
                pass
            before = _scale()
            k = self._measure_scale()
            if k and abs(k - before) > 0.02:
                self._apply_size_once(force=True)
                log("info", t("log.size.remeasured", "%.3f" % k, "%.2f" % _dpr()))
            return
        self._apply_size_once(force=force)

    def _apply_size_once(self, force=False):
        new = recalc_pet_size()
        old_w, old_h = self.width(), self.height()
        try:
            self.face.setFixedSize(BODY_W, BODY_H)
            self.chip.setFixedHeight(CHIP_H)
            self.setFixedSize(*PET_SIZE)
            if getattr(self, "_inner_layout", None) is not None:
                self._inner_layout.setContentsMargins(
                    (PET_SIZE[0] - BODY_W) // 2, 0, 0, 0)
            self.cards.setFixedWidth(_px(CARD_W))
        except Exception as e:
            log("info", t("log.size.apply_fail", e))
            return
        # 窗口变大时保持团子在屏幕上的位置不动（以中心为锚）
        if (old_w, old_h) != new and not force:
            try:
                c = self.geometry().center()
                self.move(c.x() - new[0] // 2, c.y() - new[1] // 2)
            except Exception:
                pass
        self._clamp_pos()
        try:
            self.cards.reposition(self)
        except Exception:
            pass

    def _sync_size_to_screen(self, force=False, quiet=False):
        """按桌宠所在屏幕重新换算尺寸。"""
        dpr = self._current_dpr()
        global _SCREEN_DPR, _PX_FACTOR
        _PX_FACTOR = None          # 换屏了，之前实测的比例作废
        _SCREEN_DPR = dpr
        self._apply_size(measure=True)
        if not quiet:
            # 明细串做成语言中性的（DPR / scale / logical / physical），
            # 前后缀走 i18n —— 词表里每个 key 最多两个占位符。
            log("info", t("log.size.sync",
                          "DPR %.2f / scale %.3f / logical %s / physical %dx%d"
                          % (dpr, _scale(), "%dx%d" % PET_SIZE,
                             round(PET_SIZE[0] * _scale()),
                             round(PET_SIZE[1] * _scale()))))
        return True

    def _on_screens_changed(self, *_):
        """插拔显示器 / 主屏切换。延迟一点，等 Qt 自己把 screen 列表更新完。"""
        QTimer.singleShot(200, self._guard_sync_size)

    def _guard_sync_size(self):
        """换屏回调的外壳。

        这个回调是 Qt 信号连过来的，一旦抛异常，PyQt5 会直接 abort()，
        桌宠当场崩掉——而且崩点在用户插拔显示器的瞬间，最难复现也最难查。
        所以这里必须兜住，落盘之后继续跑。
        """
        try:
            self._sync_size_to_screen()
        except Exception:
            try:
                import traceback
                log("info", t("log.size.sync_fail", traceback.format_exc()))
            except Exception:
                pass

    def set_size_level(self, level):
        """右键菜单改大小。档位写进 pet_state.json，重启后保持。"""
        global SIZE_LEVEL
        try:
            level = round(float(level), 2)
        except Exception:
            return
        if level not in SIZE_LEVELS:
            return
        if abs(level - SIZE_LEVEL) < 0.001:
            return
        SIZE_LEVEL = level
        self.state["size_level"] = level
        save_state(self.state)
        self._apply_size()
        self.update()
        log("info", t("log.size.level", size_level_name(level), "%.2f" % level))

    def _add_size_menu(self, menu):
        """把「大小」子菜单挂到任意 QMenu 上（托盘菜单和右键菜单共用）。"""
        sm = menu.addMenu(t("size.menu"))
        for lv in SIZE_LEVELS:
            cur = abs(self.state.get("size_level", SIZE_LEVEL) - lv) < 0.01
            act = sm.addAction(size_level_name(lv))
            act.setCheckable(True)
            act.setChecked(cur)
            act.triggered.connect(
                lambda _checked=False, v=lv: self.set_size_level(v))
        sm.addSeparator()
        sm.addAction(t("size.recalibrate"),
                     lambda: self._sync_size_to_screen(force=True))
        sm.addAction(t("size.show_info"), self._show_size_info)
        return sm

    def _show_size_info(self):
        scr = None
        try:
            scr = QGuiApplication.screenAt(self.geometry().center())
        except Exception:
            pass
        name = scr.name() if scr is not None else t("screen.unknown")
        k = _scale()
        detail = ("DPR %.2f / scale %.3f / level %.2f (%s)"
                  " / logical %d x %d / physical %d x %d"
                  % (_dpr(), k, SIZE_LEVEL, size_level_name(SIZE_LEVEL),
                     PET_SIZE[0], PET_SIZE[1],
                     round(PET_SIZE[0] * k), round(PET_SIZE[1] * k)))
        msg = t("size.info", name + chr(10) + detail)
        try:
            self._toast_msg(msg, 6.0)
        except Exception:
            pass
        log("info", msg)

    def _set_lang(self, lang):
        """切换界面语言：立刻重写窗口标题、菜单、卡片并写回 pet_state.json。

        不重启进程——所有文案都是渲染时现取的，`refresh(force=True)` 即可整体换掉。
        """
        lang = set_lang(lang)
        self.state["lang"] = lang
        save_state(self.state)
        self.setWindowTitle(t("win.pet"))
        self.cards.setWindowTitle(t("win.cards"))
        if self.tray:
            self.tray.setToolTip(t("win.pet"))
        log("info", t("log.lang", lang))
        self._clear_toast()
        self.refresh(force=True)

    def _clear_toast(self):
        """丢掉正在显示的气泡提示，否则会留着切换前那种语言的旧文案。"""
        self._toast = ""
        self._toast_until = 0.0

    def _set_exit_with_app(self, on):
        self.exit_with_app = bool(on)
        self.state["exit_with_app"] = self.exit_with_app
        save_state(self.state)

    # ---------- 显示开关（手动）----------
    def toggle_visible(self):
        """手动显示 / 隐藏。

        **绝不改 follow 开关。** 跟随和手动是两个正交的维度：跟随管「应用
        开/关那一刻的自动显隐」，手动管「用户当下想看还是不想看」。以前这里
        在手动显示时把 follow 静默改成 False 并落盘，用户只是想唤出桌宠，
        结果从此再也不跟随了 —— 而且没有任何提示，属于典型的静默副作用。
        """
        if self.isVisible():
            self.manual_hidden = True
            self.hide()
            if self.cards.isVisible():
                self.cards.hide()
            log("info", t("log.hide_manual"))
            self._toast_msg(
                t("toast.hidden_follow") if self.follow else t("toast.hidden"),
                2.0)
        else:
            self.manual_hidden = False
            self._sync_visibility(True)
            log("info", t("log.show_manual"))
            self._toast_msg(t("toast.shown"), 1.5)

    def toggle_cards(self):
        if self.cards.isVisible():
            self.cards_manual = True
            self.cards.hide()
        else:
            self.cards_manual = False
            self.refresh(force=True)
            if self.cards.count():
                self.cards.popup(self)

    def _on_cards_toggle(self):
        """点折叠条：展开全部 / 收回一行。"""
        self.cards.toggle_expanded()
        hidden = self.cards.total() - self.cards.count()
        self.cards.popup(self)
        if self.cards.expanded:
            msg = t("toast.expand", self.cards.total())
        else:
            msg = t("toast.collapse_n", hidden) if hidden else t("toast.collapse")
        self._toast_msg(msg, 1.8)

    # ---------- 拖动 / 点击 / 右键 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_from = e.globalPos()
            self._win_from = self.pos()
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag_from and (e.buttons() & Qt.LeftButton):
            d = e.globalPos() - self._drag_from
            if d.manhattanLength() > 6:
                self._moved = True
            if self._moved:
                self.move(self._win_from + d)
                self._clamp_pos()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_from is not None:
            if not self._moved and self.face.geometry().contains(e.pos()):
                self.jump_app(None)
            self._drag_from = None
            self._clamp_pos()
            self._save_pos()

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction(t("menu.show_pet"), self.toggle_visible)
        m.addAction(t("menu.hide_cards") if self.cards.isVisible()
                    else t("menu.show_cards"), self.toggle_cards)
        n_hidden = self.cards.total() - self.cards.count()
        m.addAction(t("menu.fold_cards", n_hidden) if self.cards.expanded
                    else t("menu.expand_cards", self.cards.total()),
                    self._on_cards_toggle)
        self._add_follow_menu(m)
        m.addSeparator()
        m.addAction(t("menu.jump"), lambda: self.jump_app(None))
        m.addAction(t("menu.demo"), self.run_demo)
        self._add_size_menu(m)
        m.addAction(t("menu.reset"), self.reset_pos)
        m.addSeparator()
        self._add_lang_menu(m)
        m.addSeparator()
        m.addAction(t("menu.quit"), lambda: self.quit(reason="user"))
        m.exec_(e.globalPos())

    # ---------- 数据 → 显示 ----------
    def _poll(self):
        self.watcher.poll()

    def _clock(self):
        self.refresh()

    def _on_http_event(self, ev):
        """本地 HTTP 事件入口：外部脚本可直接把任务状态推给桌宠。

        POST {"state": "...", "task": "...", "tool": "...", "project": "..."}
        state 取值见 MOOD_KEYS（idle/thinking/executing/waiting/done/error）；
        没给或给错就退回内置演示，方便随手 curl 一下看效果。
        """
        if not isinstance(ev, dict) or not ev:
            return
        state = str(ev.get("state") or "").strip()
        if state not in MOOD_KEYS:
            self.run_demo()
            return
        task = _short(str(ev.get("task") or ""), 90)
        tool = _short(str(ev.get("tool") or ""), 24)
        project = _short(str(ev.get("project") or t("http.project")), 40)
        self._push_synthetic("__http__", project, state, task, tool)
        log("event", t("log.http_push", state) +
            (t("log.http_push_tool", tool) if tool else "") +
            (" · " + task[:40] if task else ""))

    def _card_items(self):
        out = []
        for s in self.watcher.visible_sessions():
            state = s["state"]
            color = MOOD_COLOR.get(state, FG_SUBTLE)
            tool = s.get("tool") or ""
            tool_generic = t("card.tool_generic")
            if state == "executing":
                status = (t("card.exec", tool) if tool else t("card.exec_generic"))
            elif state == "waiting":
                status = t("card.wait", tool or tool_generic)
            elif state == "thinking":
                status = t("card.thinking")
            elif state == "error":
                status = t("card.error", tool or tool_generic)
            elif state == "done":
                status = t("card.done", s["steps"])
            else:
                status = mood_name(state)
            proj = s.get("project") or ""
            meta = (proj + " · " if proj else "") + elapsed_str(s)
            out.append({"key": s["key"],
                        "title": s["task"] or t("card.untitled"),
                        "status": status, "meta": meta,
                        "color": color, "kind": state})
        return out

    def _chip_text(self, s):
        if self._toast and time.time() < self._toast_until:
            return self._toast, MOOD_COLOR.get(s["state"], FG_SUBTLE), s["state"]
        state = s["state"]
        n = self.watcher.count_active()
        bits = {
            "thinking": t("mood.thinking"),
            "executing": ellipsize(s.get("tool") or t("chip.exec_generic"), 10),
            "waiting": t("mood.waiting"),
            "error": t("mood.error"),
            "done": t("chip.done", s["steps"], elapsed_str(s)),
            "idle": t("mood.idle"),
        }.get(state, t("mood.idle"))
        if n > 1:
            bits += " +" + str(n - 1)
        return bits, MOOD_COLOR.get(state, FG_SUBTLE), state

    def _toast_msg(self, text, secs=2.5):
        self._toast = text
        self._toast_until = time.time() + secs

    def refresh(self, force=False):
        s = self.watcher.active()
        if s["state"] != self._face_mood:
            self._face_mood = s["state"]
            self.face.set_mood(s["state"])
        txt, color, kind = self._chip_text(s)
        self.chip.set_status(txt, color, kind)
        self._fit_width()
        items = self._card_items()
        # 只剩一个任务时展开态没有意义（而且折叠条只剩一个「收起」可点），
        # 直接收回折叠态，省得用户对着一个空壳点。
        if self.cards.expanded and len(items) <= 1:
            self.cards.expanded = False
        self.cards.rebuild(items)
        # 有进行中的任务就自动亮出卡片（除非用户手动关过）。
        # 注意必须先确认还有卡片：全部被点掉之后如果别的会话仍在跑，
        # 光看 count_active() 会弹出一个空的 8px 窗口。
        if (self.cards.count() and self.watcher.count_active() > 0
                and not self.cards_manual and self.isVisible()):
            self.cards.popup(self)
        elif not self.cards.count():
            self.cards.hide()

    def _fit_width(self):
        """窗口宽度跟着状态胶囊走。

        胶囊文字会变长（「待命」→「19 步 · 02:34」），而窗口宽度是固定的
        BODY_W，于是胶囊里那段文字会被裁掉（实测「02:34」只剩「02」）。
        这里让窗口按胶囊实际需要的宽度加宽；加宽时同步左移，保证团子本体
        在屏幕上的位置纹丝不动，不会看着桌宠一会儿跳一下。
        """
        need = max(BODY_W, self.chip.minimumSizeHint().width() + 2)
        cur = self.width()
        if need == cur:
            return
        cx = self.x() + cur / 2.0            # 团子在屏幕上的中心 x
        self.setFixedWidth(need)
        self.move(QPoint(int(round(cx - need / 2.0)), self.y()))
        self._clamp_pos()

    # ---------- 跳转 ----------
    # ---------- 跳转 ----------
    _ACT_TIPS = {
        "focus": "act.focus",
        "show": "act.show",
        "spawn": "act.spawn",
        "relaunch": "act.relaunch",
        "spawn-failed": "act.spawn_failed",
        "relaunch-failed": "act.relaunch_failed",
        "probe-error": "act.probe_error",
    }

    def jump_app(self, key):
        """召唤 MiniMax Code。

        整个过程丢给子线程：里面要探窗口状态、等残留进程体面退出、
        再等新窗口冒头，最坏十几秒。放在 Qt 主线程里做这些，桌宠自己先冻住
        ——那才是字面意义上的界面卡死。
        """
        if self._act_busy:
            self._toast_msg(t("toast.jump_busy"), 1.5)
            return
        self._act_busy = True
        self._toast_msg(t("toast.jumping"), 2.5)
        # 后台还有任务在跑的话不能结束进程 —— 会把任务一起杀掉
        allow_kill = self.watcher.count_active() == 0
        if not allow_kill:
            log("info", t("log.jump_keep_proc"))
        log("info", t("log.jump_start", allow_kill))

        def _work():
            try:
                res = activate_app(allow_kill)
            except Exception as e:            # 兜底：绝不让子线程静默死掉
                res = {"ok": False, "how": "probe-error", "note": "%s" % e}
            if not isinstance(res, dict):     # 兼容任何还在返回 bool 的老实现
                res = {"ok": bool(res), "how": "focus", "note": ""}
            res["key"] = key
            try:
                BRIDGE.activate_result.emit(res)
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _on_activate_result(self, res):
        """召唤结束（主线程）。收卡 / 提示 / 刷新都放这里。"""
        self._act_busy = False
        ok = bool(res.get("ok"))
        how = str(res.get("how") or "")
        note = str(res.get("note") or "")
        key = res.get("key")
        if not key:
            # 点的是团子本身：顺手把「已经跑完」的那个任务也收掉，让团子立刻
            # 切到下一个任务或回到待命，不留在旧任务的完成态上。
            # 还在跑的不动——那种点击只是想瞄一眼，不该打断。
            cur = self.watcher.active()
            if cur["key"] != "-" and cur["state"] not in ACTIVE_STATES and cur["task"]:
                key = cur["key"]
        if key:
            s = self.watcher.sess.get(key)
            # 正在跑的任务：点了只跳转，卡片必须留着——它还没结束，
            # 用户还需要盯着进度条。等它跑完再点，才收起来。
            if s and s.get("state") in ACTIVE_STATES:
                log("info", t("log.card_kept", key[:24]))
            elif s and not s.get("acked"):
                s["acked"] = True
                log("info", t("log.card_dismissed", key[:24]))
        log("info", t("log.jump_result",
                    ("%s [%s]" % ("✓" if ok else "✗", how)), note))
        tip_key = self._ACT_TIPS.get(how)
        if not tip_key:
            tip_key = "act.focus" if ok else "act.probe_error"
        self._toast_msg(t(tip_key), 3.0)
        self.refresh(force=True)
        if not self.cards.count():
            self.cards.hide()

    def _on_card_click(self, key):
        self.jump_app(key)

    # ---------- 演示 ----------
    def run_demo(self, _ev=None):
        """演示一轮完整任务，便于直观验收效果（不触碰真实会话）。"""
        script = [
            (0, "thinking", t("demo.t1"), ""),
            (1300, "executing", "", "Read"),
            (2600, "executing", "", "Edit"),
            (3900, "waiting", "", "Bash"),
            (5600, "executing", "", "Bash"),
            (6900, "error", "", "Bash"),
            (8400, "executing", "", "Edit"),
            (9900, "done", "", "Edit"),
        ]
        self._toast_msg(t("toast.demo"), 2.0)
        for delay, state, task, tool in script:
            QTimer.singleShot(300 + delay,
                              lambda st=state, tk=task, tl=tool: self._demo_step(st, tk, tl))

    def _demo_step(self, state, task, tool):
        self._push_synthetic("__demo__", "MiniMax-pet", state, task, tool)

    def _push_synthetic(self, key, project, state, task, tool):
        """把一条合成状态（演示 / HTTP 推送）写进 watcher 并刷新。"""
        prev = self.watcher.sess.get(key)
        s = _new_state(key)
        s["project"] = project or (prev["project"] if prev else "")
        s["state"] = state
        s["tool"] = tool
        s["t0"] = time.time()
        if task:
            s["task"] = task
        if prev:
            s["steps"] = max(s["steps"], prev["steps"])
            s["t0"] = prev["t0"] or s["t0"]
            s["task"] = prev["task"] or s["task"]
        if state in ("executing", "waiting", "error", "done"):
            s["steps"] = max(s["steps"], 1)
        if state == "done":
            s["t_end"] = time.time()        # 演示/推送的完成态同样冻结用时
        s["last_ts"] = time.time()
        self.watcher.sess[key] = s
        if state == "waiting":
            self._toast_msg(t("toast.ask_perm"), 3.0)
            if self.tray:
                self.tray.showMessage(
                    t("win.pet"),
                    t("notify.wait", tool or t("notify.tool_generic")),
                    QSystemTrayIcon.Warning, 5000)
        elif state == "done":
            self._toast_msg(t("toast.done"), 3.0)
            if self.tray:
                self.tray.showMessage(t("win.pet"), t("notify.done"),
                                      QSystemTrayIcon.Information, 4000)
        self.refresh(force=True)

    # ---------- 退出 ----------
    def quit(self, reason="exit"):
        """reason=user 表示「用户主动从托盘/右键退出」。

        这时必须留个痕迹，否则看门狗哨兵会以为桌宠是意外掉的，隔几秒又把它
        拉起来——用户点「退出」结果永远退不掉。

        痕迹的**对称解除口**有两个，都不需要命令行知识：
          · 双击 scripts/run_pet.bat（内部就是 --resume）
          · 重新登录（登录启动项会拉起哨兵）
        所以应用被重新打开时**不再**自动清这个痕迹，否则「手动关闭」会被
        应用重开无声推翻。
        """
        if reason == "user":
            try:
                import pet_watcher
                pet_watcher.set_pause()
            except Exception:
                pass
        self._save_pos()
        if self.srv:
            self.srv.stop()
        if self.cards:
            self.cards.close()
        if self._hk:
            try:
                _u32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass
        if self.tray:
            self.tray.hide()
        log("info", t("log.quit"))
        QApplication.quit()

    def closeEvent(self, e):
        self._save_pos()
        e.accept()


# ========== 自检：离屏渲染各状态 ==========
def run_selftest(scale=1.0, live=False):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    global UI_SCALE, BODY_W, BODY_H, CHIP_H, PET_SIZE
    if scale != 1.0:
        UI_SCALE = scale
        BODY_W = _px(_D_BODY_W)
        BODY_H = _px(_D_BODY_H)
        CHIP_H = _px(_D_CHIP_H)
        PET_SIZE = (BODY_W, BODY_H + CHIP_H + _px(6))
    app = QApplication(sys.argv)
    try:
        from PyQt5.QtGui import QFontDatabase
        for f in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "arial.ttf",
                  "arialbd.ttf", "msyh.ttc", "msyhbd.ttc", "consola.ttf"):
            p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", f)
            if os.path.exists(p):
                QFontDatabase.addApplicationFont(p)
    except Exception:
        pass
    # 截图按语言分文件名的后缀落到 docs/images/，仓库里 README 引用的就是
    # pet-xxx-zh.png / pet-xxx-en.png 这一对。live 模式另加 live- 前缀。
    suffix = "-" + get_lang()
    out = os.path.join(BASE, "docs", "images")
    os.makedirs(out, exist_ok=True)

    pet = PetWindow(server=False, tray=False, hotkey=False, follow=False)
    pet.show()
    if not live:
        # 隔离真实会话，保证截图状态确定、可复现
        pet.poll.stop()
        pet.clock.stop()
        pet.watcher.sess.clear()

    def snap(name):
        for _ in range(3):
            app.processEvents()
        pet.face.tick += 17
        pet.grab().save(os.path.join(out, name + suffix + ".png"))

    def snap_cards(name):
        for _ in range(3):
            app.processEvents()
        pet.cards.grab().save(os.path.join(out, name + suffix + ".png"))

    # live 模式下真实会话仍在轮询，优先级高的真实任务会盖掉演示态，
    # 所以演示帧另起前缀，别把 1-…7- 这套「确定可复现」的截图覆盖掉。
    pre = ("live-" if live else "")

    if live:
        # 实况快照：先让 SessionWatcher 真正读一轮真实会话，再落盘 PNG + 状态摘要，
        # 这样 --selftest-live 才能证明「读到的是真的」而不是演示数据。
        t0 = time.time()
        while time.time() - t0 < 2.0:
            app.processEvents()
            time.sleep(0.05)
        s = pet.watcher.active()
        for _ in range(3):
            app.processEvents()
        st = s["state"]
        pet.face.tick += 17
        pet.grab().save(os.path.join(out, "L0-live-%s%s.png" % (st, suffix)))
        with open(os.path.join(out, "L0-live-state.txt"), "w", encoding="utf-8") as f:
            f.write("sessions= %d\n" % len(pet.watcher.sess))
            f.write("state   = %s\n" % st)
            f.write("task    = %s\n" % s["task"])
            f.write("tool    = %s\n" % s["tool"])
            f.write("steps   = %s\n" % s["steps"])
            f.write("errors  = %s\n" % s["errors"])
            f.write("project = %s\n" % s["project"])
            f.write("session = %s\n" % s["path"])
        print("LIVE %s | %s | steps=%s err=%s | %s" %
              (st, s["project"], s["steps"], s["errors"], s["task"][:60]))

    pet._demo_step("idle", "", "")
    snap(pre + "1-idle")
    pet._demo_step("thinking", t("demo.t1"), "")
    snap(pre + "2-thinking")
    pet._demo_step("executing", "", "Edit")
    snap(pre + "3-executing")
    pet._demo_step("waiting", "", "Bash")
    snap(pre + "4-waiting")
    snap_cards(pre + "5-cards-waiting")
    pet._demo_step("error", "", "Bash")
    snap(pre + "6-error")
    pet._demo_step("done", "", "Edit")
    snap(pre + "7-done")

    if not live:
        # ---- 折叠 / 展开 / 点掉后不再出现 ----
        # 用确定性的假会话，别拿真实会话凑截图（会随时间变）。
        specs = [
            ("waiting",  t("demo.t1"), "Bash", 0),
            ("executing", t("demo.t2"), "Edit", 7),
            ("thinking", t("demo.t3"), "", 2),
            ("done",     t("demo.t4"), "Read", 19),
        ]

        def seed():
            pet.watcher.sess.clear()
            now = time.time()
            for i, (state, task, tool, steps) in enumerate(specs):
                k = "__card_%d__" % i
                t0 = now - 90 * (i + 1)
                s = _new_state(k)
                s.update(state=state, task=task, tool=tool, steps=steps,
                         project="MiniMax-pet", t0=t0,
                         t_end=(t0 + 48) if state == "done" else 0.0,
                         last_ts=int(t0 * 1000))
                pet.watcher.sess[k] = s
            pet.refresh(force=True)

        seed()
        pet.cards.expanded = False
        pet.cards.rebuild(pet._card_items())
        snap_cards(pre + "8-cards-collapsed")
        pet.cards.expanded = True
        pet.cards.rebuild(pet._card_items())
        snap_cards(pre + "9-cards-expanded")

        # 点掉「已完成」那张（等价于点卡片跳转），再收回折叠态：
        # 它既不该出现在折叠的那一张里，也不该出现在展开列表里。
        pet.watcher.sess["__card_3__"]["acked"] = True
        pet.cards.expanded = False
        pet.refresh(force=True)
        snap_cards(pre + "10-cards-after-ack")

        # 只剩一个任务时自动收回折叠态
        pet.watcher.sess.clear()
        now = time.time()
        k = "__card_0__"
        s = _new_state(k)
        s.update(state="thinking", task=t("demo.t5"), t0=now, last_ts=int(now * 1000))
        pet.watcher.sess[k] = s
        pet.cards.expanded = True
        pet.refresh(force=True)
        snap_cards(pre + "11-cards-single-autocollapse")
        pet.watcher.sess.clear()
        pet.refresh(force=True)

    try:
        from PIL import Image
        m = Image.open(MASCOT_PATH).convert("RGBA")
        side = 260
        m = m.resize((side, int(side * m.height / m.width)), Image.LANCZOS)
        canvas = Image.new("RGBA", (side + 20, m.height + 20), (22, 22, 22, 255))
        canvas.alpha_composite(m, (10, 10))
        canvas.save(os.path.join(out, "0-official-mascot.png"))
    except Exception as e:
        print("compare skipped:", e)

    print("SELFTEST_OK " + out)
    return 0


def run_activate_probe():
    """Print every step of the "summon MiniMax Code" pipeline and exit.

    Developer diagnostic, so the output is plain English on purpose — it is
    not part of the localised UI surface and does not need i18n keys.

    The desktop app is the host of the agent session, so the real
    "close the app -> summon it" path cannot be reproduced from inside the
    app itself. This probe exists so that path can be inspected from the
    outside.
    """
    print("=== MiniMax Code summon pipeline ===")
    try:
        pids = sorted(app_pids())
    except Exception as e:
        print("process scan failed: %s" % e)
        return 1
    print("processes: %d %s" % (len(pids), pids))
    guard = ancestor_pids()
    print("pet + ancestor pids: %s" % sorted(guard))
    print("  -> MiniMax Code pids inside that chain: %s"
          % sorted(set(pids) & guard))
    print("executable: %s" % (app_exe_path() or "(not found)"))

    try:
        wins = app_windows()
    except Exception as e:
        print("window enumeration failed: %s" % e)
        return 1
    counts = {"visible": 0, "minimized": 0, "hidden": 0}
    print("top-level windows: %d" % len(wins))
    for h, title, visible, area in wins:
        st = _window_state(h)
        counts[st] = counts.get(st, 0) + 1
        print("   hwnd=%-9d state=%-9s responsive=%-5s area=%-9d %r"
              % (h, st, window_responsive(h, 600), area, title[:44]))
    print("visible %d / minimised %d / closed %d"
          % (counts["visible"], counts["minimized"], counts["hidden"]))
    if counts["hidden"]:
        print("-> closed windows are NOT revived; the app is relaunched "
              "instead (unless they belong to a protected process).")
        for w in wins:
            if _window_state(w[0]) == "hidden":
                p = window_pid(w[0])
                print("   leftover window pid=%s%s"
                      % (p, " **protected (pet ancestor) - left alone**"
                         if p in guard else ""))

    t0 = time.time()
    res = activate_app()
    print("activate_app() -> %s  (%.2fs)"
          % (json.dumps(res, ensure_ascii=False), time.time() - t0))
    print("ui tip: %s" % PetWindow._ACT_TIPS.get(res.get("how"), "?"))
    print("PROBE_ACTIVATE_OK")
    return 0


# ========== 入口 ==========
def main():
    ap = argparse.ArgumentParser(
        description="MiniMax Pet — MiniMax Code 任务进度桌宠 / task-progress desktop pet")
    ap.add_argument("--demo", action="store_true",
                    help="启动后演示一轮任务 / play one demo task on start")
    ap.add_argument("--lang", choices=list(I18N_LANGS), default=None,
                    help="界面语言：zh 或 en（默认读上次选择，再读系统语言）"
                         " / UI language; defaults to saved choice, then system")
    ap.add_argument("--selftest", action="store_true",
                    help="离屏渲染各状态 PNG 后退出 / render state PNGs offscreen and exit")
    ap.add_argument("--selftest-scale", type=float, default=1.0,
                    help="自检渲染放大倍数 / selftest render scale")
    ap.add_argument("--selftest-live", action="store_true",
                    help="自检时读取真实会话 / selftest against live sessions")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help="事件端口（默认 8766） / event port")
    ap.add_argument("--no-follow", action="store_true",
                    help="不跟随 MiniMax Code 显示/隐藏 / do not follow app visibility")
    ap.add_argument("--exit-with-app", action="store_true",
                    help="MiniMax Code 退出时桌宠一并退出（默认已开）"
                         " / exit pet with the app (on by default)")
    ap.add_argument("--always-show", action="store_true",
                    help="启动就显示，不等 MiniMax Code（手动调试用）"
                         " / show at launch regardless of the app")
    ap.add_argument("--no-server", action="store_true",
                    help="不开启本地 HTTP 事件入口 / disable the local HTTP event API")
    ap.add_argument("--resume", action="store_true",
                    help="手动重新启用桌宠：先清掉「用户退出」的暂停标记再启动"
                         " / clear the 'user quit' pause flag, then start")
    ap.add_argument("--probe-activate", action="store_true",
                    help="只跑一遍「召唤 MiniMax Code」链路并打印每一步后退出"
                         " / print the summon pipeline step by step, then exit")
    a = ap.parse_args()

    st = load_state()
    # 语言优先级：命令行 > 上次选择 > 系统语言
    set_lang(a.lang or st.get("lang") or system_lang())

    if a.resume:
        # 「手动关闭」的对称面必须好找：桌宠退出后托盘也没了，用户手上
        # 唯一能点到的入口就是这个参数（scripts/run_pet.bat 传的就是它）。
        try:
            import pet_watcher
            was = pet_watcher.pause_remaining()
            pet_watcher.clear_pause()
            log("info", t("log.resume", was))
        except Exception as e:
            log("warn", t("log.resume_fail", e))

    if a.probe_activate:
        sys.exit(run_activate_probe())

    if a.selftest:
        sys.exit(run_selftest(a.selftest_scale, a.selftest_live))

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("MiniMax Pet")

    lock = QLockFile(os.path.join(tempfile.gettempdir(), "minimax-pet.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        print("MiniMax Pet 已在运行，本次启动已退出。"
              " / MiniMax Pet is already running; this launch exited.")
        return 0

    follow = (not a.no_follow) and st.get("follow", True) is not False
    # 「MiniMax Code 退出 → 桌宠退出」默认开启，这才是同生共死。
    # pet_watcher 拉起时还会显式再传一次 --exit-with-app 兜底。
    exit_with = a.exit_with_app or st.get("exit_with_app", True) is not False
    # 「跟随」跟进程还是跟窗口：默认跟进程（关掉窗口、后台 agent 继续跑时
    # 桌宠也继续显示）。写坏了的值一律退回默认。
    fm = st.get("follow_mode", FOLLOW_MODE_PROCESS)
    follow_mode = fm if fm in FOLLOW_MODES else FOLLOW_MODE_PROCESS
    # ---- 大小：先把档位和「起始屏幕的 DPR」定下来再建控件 ----
    # 必须在 PetWindow 之前算好，因为控件在构造里就 setFixedSize 了。
    global SIZE_LEVEL, _SCREEN_DPR, _SCREEN_NAME
    lv = st.get("size_level")
    if lv is not None:
        try:
            lv = round(float(lv), 2)
            if lv in SIZE_LEVELS:
                SIZE_LEVEL = lv
        except Exception:
            pass
    try:
        _scr0 = QGuiApplication.primaryScreen()
        if _scr0 is not None:
            _SCREEN_DPR = float(_scr0.devicePixelRatio())
            _SCREEN_NAME = _scr0.name()
    except Exception:
        pass
    pet = PetWindow(server=not a.no_server, tray=True, hotkey=True, port=a.port,
                    follow=follow, exit_with_app=exit_with,
                    follow_mode=follow_mode)
    # 起始可见性必须跟 _check_app 用**同一个口径**，否则会出现「先闪一下
    # 再自己藏起来」。按进程模式下只要进程在就显示——窗口关着也算开着。
    show_now = (a.always_show or a.demo or not follow
                or (app_running() if follow_mode == FOLLOW_MODE_PROCESS
                    else app_foreground()))
    if show_now:
        pet.show()
    # 位置是构造时才恢复的，真实所在屏幕这会儿才知道；而且 Qt 报的 DPR
    # 在部分缩放组合下不可信，所以窗口出来后再实测一次缩放并收敛到
    # 正确的**物理**大小。这是「拔掉显示器桌宠突然变大」的根治点。
    pet._apply_size(measure=True)
    if a.demo:
        QTimer.singleShot(700, pet.run_demo)
    log("info", t("log.lang", get_lang()))
    log("info", t("log.start", follow, exit_with))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
