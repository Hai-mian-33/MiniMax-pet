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
                                 QHBoxLayout, QMenu, QSystemTrayIcon)
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
    """几何尺寸换算：跟 UI_SCALE × SIZE_RATIO 走。"""
    return max(1, int(round(v * UI_SCALE * SIZE_RATIO)))


def _fpx(v):
    """字号换算：跟 UI_SCALE 走，但用 FONT_SCALE 而不是 SIZE_RATIO。

    桌宠缩小了字不该跟着缩——卡片变窄只影响能放几个字，不影响字本身多清晰。
    """
    return max(7, int(round(v * UI_SCALE * FONT_SCALE)))


# 表情动画幅度：跟**视觉尺寸**走（UI_SCALE × SIZE_RATIO），不是跟字号走。
# 运行时读取，所以 --selftest-scale 改 UI_SCALE 后依然正确。
def _draw_k():
    return UI_SCALE * SIZE_RATIO


# ========== 尺寸（全部由 SIZE_RATIO 驱动）==========
# 设计稿原始尺寸
_D_BODY_W, _D_BODY_H, _D_CHIP_H = 128, 132, 22
# 桌宠本体与状态胶囊：下面有几处是**不加 _px** 直接用的，所以这里先换算好
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
else:
    _u32 = _k32 = None
    _ENUMPROC = None


def _iter_processes():
    """遍历系统进程，产出 (pid, exe 名)。"""
    if _k32 is None:
        return

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

    snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == -1:
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
    """MiniMax Code 桌面版的所有进程 id 集合。"""
    out = set()
    try:
        for pid, exe in _iter_processes():
            if APP_PROCESS_HINT in exe.lower():
                out.add(pid)
    except Exception:
        pass
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


def pick_app_window():
    """挑最适合置前的窗口；全被隐藏时也返回它，以便从托盘还原。"""
    wins = app_windows()
    if not wins:
        return None
    for h, title, visible, _a in wins:
        if visible and APP_TITLE_HINT in title.lower():
            return h
    for h, _t, visible, _a in wins:
        if visible:
            return h
    return wins[0][0]


def activate_app():
    """把 MiniMax Code 带到前台；最小化 / 收进托盘都会还原。成功返回 True。"""
    hwnd = pick_app_window()
    if not hwnd:
        return False
    try:
        if _u32.IsIconic(hwnd):
            _u32.ShowWindow(hwnd, 9)          # SW_RESTORE
        else:
            _u32.ShowWindow(hwnd, 5)          # SW_SHOW
        fg = _u32.GetForegroundWindow()
        cur = _k32.GetCurrentThreadId()
        fgt = _u32.GetWindowThreadProcessId(fg, None) if fg else 0
        if fgt and fgt != cur:
            _u32.AttachThreadInput(cur, fgt, True)
        _u32.SetForegroundWindow(hwnd)
        _u32.BringWindowToTop(hwnd)
        _u32.SetActiveWindow(hwnd)
        _u32.SetFocus(hwnd)
        if fgt and fgt != cur:
            _u32.AttachThreadInput(cur, fgt, False)
        return True
    except Exception:
        return False


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
                 port=DEFAULT_PORT, follow=True, exit_with_app=False):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(t("win.pet"))
        self.setFixedSize(*PET_SIZE)

        self.follow = follow
        self.exit_with_app = exit_with_app
        self.manual_hidden = False
        self.cards_manual = False
        self._drag_from = None
        self._win_from = None
        self._moved = False
        self._face_mood = ""
        self._toast = ""
        self._toast_until = 0.0
        self.state = load_state()

        self.watcher = SessionWatcher(self)
        self.watcher.changed.connect(self.refresh)

        self._build_ui()
        self._restore_pos()

        # 生命周期跟随
        self.app_seen = False
        self.app_miss = 0
        self.app_timer = QTimer(self, timeout=self._check_app, interval=3000)
        self.app_timer.start()

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
        a1 = m.addAction(t("menu.follow"))
        a1.setCheckable(True)
        a1.setChecked(self.follow)
        a1.triggered.connect(self._set_follow)
        a2 = m.addAction(t("menu.exit_with"))
        a2.setCheckable(True)
        a2.setChecked(self.exit_with_app)
        a2.triggered.connect(self._set_exit_with_app)
        m.addSeparator()
        m.addAction(t("menu.jump"), lambda: self.jump_app(None))
        m.addAction(t("menu.demo"), self.run_demo)
        m.addAction(t("menu.reset"), self.reset_pos)
        m.addAction(t("menu.opendir"), self._open_dir)
        m.addSeparator()
        self._add_lang_menu(m)
        m.addSeparator()
        m.addAction(t("menu.quit"), self.quit)
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
        running = app_running()
        if running:
            if not self.app_seen:
                log("lifecycle", t("log.app_seen"))
            self.app_seen = True
            self.app_miss = 0
            if self.follow and not self.manual_hidden and not self.isVisible():
                self._sync_visibility(True)
        elif self.app_seen:
            self.app_miss += 1
            if self.app_miss >= 2:            # 连续两次没有才判关闭，避免重启瞬间误判
                log("lifecycle", t("log.app_gone"))
                if self.exit_with_app:
                    self.quit()
                elif self.follow and not self.manual_hidden:
                    self._sync_visibility(False)
                self.app_seen = False
                self.app_miss = 0

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
        if self.follow and app_running() and not self.manual_hidden:
            self._sync_visibility(True)

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

    # ---------- 显示开关 ----------
    def toggle_visible(self):
        if self.isVisible():
            self.manual_hidden = True
            self.hide()
            if self.cards.isVisible():
                self.cards.hide()
            log("info", t("log.hide_manual"))
        else:
            self.manual_hidden = False
            if self.follow:                   # 手动接管后不再被生命周期覆盖
                self.follow = False
                self.state["follow"] = False
                save_state(self.state)
                if self.tray:
                    self.tray.setContextMenu(self._build_menu())
            self._sync_visibility(True)
            log("info", t("log.show_manual"))

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
        a1 = m.addAction(t("menu.follow"))
        a1.setCheckable(True)
        a1.setChecked(self.follow)
        a1.triggered.connect(self._set_follow)
        m.addSeparator()
        m.addAction(t("menu.jump"), lambda: self.jump_app(None))
        m.addAction(t("menu.demo"), self.run_demo)
        m.addAction(t("menu.reset"), self.reset_pos)
        m.addSeparator()
        self._add_lang_menu(m)
        m.addSeparator()
        m.addAction(t("menu.quit"), self.quit)
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
    def jump_app(self, key):
        ok = activate_app()
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
        log("info", t("log.jump_ok") if ok else t("log.jump_fail"))
        self._toast_msg(t("toast.jumped") if ok else t("toast.no_window"), 2.0)
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
    def quit(self):
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
                    help="MiniMax Code 退出时桌宠一并退出 / exit pet with the app")
    ap.add_argument("--no-server", action="store_true",
                    help="不开启本地 HTTP 事件入口 / disable the local HTTP event API")
    a = ap.parse_args()

    st = load_state()
    # 语言优先级：命令行 > 上次选择 > 系统语言
    set_lang(a.lang or st.get("lang") or system_lang())

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
    exit_with = a.exit_with_app or bool(st.get("exit_with_app"))
    pet = PetWindow(server=not a.no_server, tray=True, hotkey=True, port=a.port,
                    follow=follow, exit_with_app=exit_with)
    pet.show()
    if a.demo:
        QTimer.singleShot(700, pet.run_demo)
    log("info", t("log.lang", get_lang()))
    log("info", t("log.start", follow, exit_with))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
