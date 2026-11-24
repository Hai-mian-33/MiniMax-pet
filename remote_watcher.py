# -*- coding: utf-8 -*-
"""
remote_watcher.py —— 通过 SSH 读取远端 MiniMax Code 的会话转录
==============================================================================
桌宠除了看本机的会话，也可以在 SSH 得通的服务器上看同一套东西：远端跑的
MiniMax Code 会把转录写在 `~/.minimax/v2/sessions/<Y>/<M>/<D>/<会话>/messages.jsonl`，
格式和本机**完全一样**，所以只要把那段字节拉回来，用同一套解析逻辑处理就行。

设计要点
------------------------------------------------------------------------------
* **只读**：远端只被读（open(...,'rb')），不写、不装东西、不改配置。
* **一条常驻 SSH 通道**：每台机器起一个 `ssh host "python3 -u -"` 常驻进程，
  本地写一行 JSON 请求、远端回一行 JSON 响应。比每次重新握手快得多，
  也不会在系统日志里留下一堆短连接。
* **按字节偏移增量拉**：本地把每个会话已经读到哪告诉远端，远端只回新增的字节。
  这一条很关键——解析里 `steps += 1` 不是幂等的，重复喂旧行会把步数算飞。
* **解析逻辑不复制**：真正的状态推导留在 minimax_pet.py 里（_apply_msg），
  本模块只管「把字节搞到手」。

远端脚本（REMOTE_SCRIPT）跑在服务器的 python3 上，逻辑很简单：
收到一行请求 → 扫一遍会话目录 → 把每个会话的新字节 base64 回去。
"""
import base64
import json
import os
import subprocess
import sys
import threading
import time

# ========== 远端脚本（会被喂给 ssh 的 python3 -） ==========
REMOTE_SCRIPT = r'''
import base64, json, os, re, sys, time

ROOT = os.environ.get("MINIMAX_SESSIONS_ROOT") or \
    os.path.expanduser("~/.minimax/v2/sessions")
WINDOW_H = 12                 # 只看最近 12 小时内动过的会话
CAP = 2 * 1024 * 1024         # 首次全量读的上限（远端别一次吐太多）
RE_CWD = re.compile(r"Primary working directory:\s*(.+)")
_proj_cache = {}

def project_of(d):
    """项目名：llm-call.json 的 systemPrompt 里带工作目录。

    这段规则和本机 minimax_pet._project_of() 一致（同一份约定，必须同步改）。
    """
    p = os.path.join(d, "llm-call.json")
    try:
        st = os.stat(p)
        sig = (st.st_mtime, st.st_size)
    except OSError:
        return ""
    hit = _proj_cache.get(d)
    if hit and hit[0] == sig:
        return hit[1]
    name = ""
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read(2_000_000)
        blob = raw
        try:
            o = json.loads(raw)
            if isinstance(o, dict):
                blob = str(o.get("systemPrompt") or "")
        except Exception:
            pass
        m = RE_CWD.search(blob)
        if m:
            cwd = m.group(1).strip().strip("\\/")
            if cwd and len(cwd) <= 200 and " " not in cwd:
                name = os.path.basename(cwd) or ""
    except Exception:
        name = ""
    _proj_cache[d] = (sig, name)
    return name

def scan(offsets):
    out = []
    now = time.time()
    for dp, _dn, fn in os.walk(ROOT):
        if "messages.jsonl" not in fn:
            continue
        mf = os.path.join(dp, "messages.jsonl")
        try:
            st = os.stat(mf)
        except OSError:
            continue
        if now - st.st_mtime > WINDOW_H * 3600:
            continue
        size = st.st_size
        off = int(offsets.get(dp, 0) or 0)
        if size < off:                       # 被截断/替换 -> 从头再来
            off = 0
        start = off
        if start == 0 and size > CAP:
            start = size - CAP
        try:
            with open(mf, "rb") as f:
                f.seek(start)
                data = f.read(size - start)
        except OSError:
            continue
        out.append({"path": dp, "size": size, "start": start,
                    "data": base64.b64encode(data).decode("ascii"),
                    "project": project_of(dp)})
    return out

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        res = {"sessions": scan(req.get("offsets") or {})}
    except Exception as e:
        res = {"error": str(e)}
    try:
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()
    except Exception:
        break
'''

SSH_BASE_ARGS = [
    "-o", "BatchMode=yes",          # 绝不交互等密码
    "-o", "ConnectTimeout=8",
    "-o", "ConnectionAttempts=1",
    "-o", "ServerAliveInterval=20",
    "-o", "ServerAliveCountMax=3",
    "-o", "LogLevel=ERROR",
]


def remote_command():
    """远端要执行的那条命令。

    脚本用 base64 塞进 `-c`：`-c` 的参数里不能有换行/引号，base64 只有
    [A-Za-z0-9+/=]，直接放进双引号里给远端 shell 解析，绝对安全。

    ⚠️ **不能**用 `python3 -`：那样脚本会把 stdin 整个读走，而我们的请求
    协议也要走 stdin —— 脚本还没开始跑，stdin 就已经空了，通道会一直挂着。
    """
    b64 = base64.b64encode(REMOTE_SCRIPT.encode("utf-8")).decode("ascii")
    return ("exec python3 -u -c \"import base64;"
            "exec(base64.b64decode('%s'))\"" % b64)


def ssh_argv(host):
    return ["ssh"] + SSH_BASE_ARGS + [host, remote_command()]


class RemoteHost(object):
    """一台远端机器：一条常驻 SSH 通道 + 请求/响应。

    线程模型：调用方（桌宠的轮询线程）负责串行调用 poll()；本类内部自己
    加锁，保证同一台机器上不会有两条请求同时写进通道。
    """

    def __init__(self, name, timeout=25.0):
        self.name = name
        self.timeout = timeout
        self._proc = None
        self._lock = threading.Lock()
        self._last_error = ""
        self._last_ok = 0.0

    # ---- 通道生命周期 ----
    def _ensure_channel(self):
        if self._proc is not None and self._proc.poll() is None:
            return True
        self._proc = None
        try:
            self._proc = subprocess.Popen(
                ssh_argv(self.name),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # 缓冲很重要：响应可能有好几 MB（base64 后的转录尾巴），
                # 逐字节读会慢到离谱。stdin 每次写完立刻 flush，不受影响。
                bufsize=-1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            self._last_error = "spawn: %s" % e
            self._proc = None
            return False
        # 脚本是通过 `python3 -c` 送过去的，**不能**再往 stdin 写一遍 ——
        # stdin 现在只走请求协议。
        return True

    def close(self):
        p = self._proc
        self._proc = None
        if p is None:
            return
        for s in (p.stdin, p.stdout, p.stderr):
            try:
                if s:
                    s.close()
            except Exception:
                pass
        try:
            p.terminate()
        except Exception:
            pass

    # ---- 一次请求 ----
    def poll(self, offsets):
        """发一次请求，返回远端解析好的 {path: {...}}，失败返回 None。"""
        with self._lock:
            if not self._ensure_channel():
                return None
            req = json.dumps({"offsets": offsets or {}}, ensure_ascii=False)
            try:
                self._proc.stdin.write((req + "\n").encode("utf-8"))
                self._proc.stdin.flush()
            except Exception as e:
                self._last_error = "write: %s" % e
                self.close()
                return None
            line = self._readline()
            if line is None:
                self.close()
                return None
            try:
                res = json.loads(line)
            except Exception as e:
                self._last_error = "bad json: %s" % e
                return None
            if res.get("error"):
                self._last_error = str(res["error"])
                return None
            self._last_error = ""
            self._last_ok = time.time()
            return res.get("sessions") or []

    def _readline(self):
        """从 stdout 读一行 JSON。远端是按行回的，所以读到换行为止。"""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if line:
                return line.decode("utf-8", "replace")
        return None

    # ---- 状态 ----
    @property
    def alive(self):
        return (time.time() - self._last_ok) < 90.0

    @property
    def error(self):
        return self._last_error


# ========== 主机清单 ==========
def hosts_path(state_home):
    return os.path.join(state_home, "remote_hosts.json")


def load_hosts(state_home):
    """读远端主机清单。返回 [别名, ...]；没有文件就是空清单。"""
    p = hosts_path(state_home)
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            o = json.load(f)
        hs = o.get("hosts") if isinstance(o, dict) else o
        if isinstance(hs, list):
            return [str(h).strip() for h in hs if str(h).strip()]
    except Exception:
        pass
    return []


def save_hosts(state_home, hosts):
    p = hosts_path(state_home)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"hosts": list(hosts)}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def ssh_config_aliases():
    """从 ~/.ssh/config 里把 Host 别名扒出来（给用户当候选，不自动连）。"""
    p = os.path.join(os.path.expanduser("~"), ".ssh", "config")
    out = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if ln.lower().startswith("host "):
                    for a in ln[5:].split():
                        if a and "*" not in a and "?" not in a and a not in out:
                            out.append(a)
    except Exception:
        pass
    return out
