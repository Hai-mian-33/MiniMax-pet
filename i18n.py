# -*- coding: utf-8 -*-
"""
i18n.py —— 桌宠界面的中英双语文案
==============================================================================
只有一个真源：`STRINGS`。界面里所有面向用户的字符串都从这里取，
其余代码不许硬编码文案。

用法：
    from i18n import t, set_lang, get_lang
    label = t("menu.quit")            # 无参数
    tip   = t("foot.more", n)         # 位置参数 {0}

为什么用位置参数而不是 f-string / 具名参数
------------------------------------------------------------------------------
`str.format` 对 `{0,3}` 这种写法会抛 KeyError（Python 3.12 实测），
而具名参数（`{n=}`）又要求所有调用点都记得传同样的名字。这里统一用
`{0} {1}`，两边都安全，翻译时顺序一目了然。

语言如何决定（优先级从高到低）
------------------------------------------------------------------------------
1. `--lang` 命令行参数
2. `pet_state.json` 里记住的上次选择（托盘切换后写回）
3. 系统语言：Windows 上读 `LANG`/`LC_ALL` 环境变量
4. `DEFAULT_LANG`（中文）
"""
import os

LANGS = ("zh", "en")
DEFAULT_LANG = "zh"

STRINGS = {
    "zh": {
        # ---- 状态（团子胶囊 / 卡片状态行）----
        "mood.idle": "待命",
        "mood.thinking": "思考中",
        "mood.executing": "执行中",
        "mood.waiting": "等你确认",
        "mood.done": "完成",
        "mood.error": "出错",

        "card.exec": "执行 {0}…",
        "card.exec_generic": "执行中…",
        "card.wait": "等你确认 · {0}",
        "card.thinking": "思考中…",
        "card.error": "出错 · {0}",
        "card.done": "完成 · {0} 步",
        "card.tool_generic": "工具",
        "card.untitled": "（未命名任务）",

        "chip.exec_generic": "执行中",
        "chip.done": "{0} 步 · {1}",

        "foot.more": "还有 {0} 个任务",
        "foot.collapse": "收起",

        # ---- 菜单 ----
        "menu.show_pet": "显示 / 隐藏桌宠",
        "menu.show_cards": "显示 / 隐藏任务卡片",
        "menu.hide_cards": "隐藏任务卡片",
        "menu.fold_cards": "折叠任务卡片（还有 {0} 个）",
        "menu.expand_cards": "展开全部任务（{0} 个）",
        "menu.follow": "跟随 MiniMax Code 开关",
        "menu.exit_with": "MiniMax 退出时一并退出桌宠",
        "menu.jump": "跳转到 MiniMax Code",
        "menu.demo": "演示一轮任务",
        "menu.reset": "重置位置",
        "menu.opendir": "打开所在目录",
        "menu.quit": "退出桌宠",
        "menu.language": "语言 / Language",

        # ---- 气泡提示 ----
        "toast.jumped": "已跳转 MiniMax Code",
        "toast.no_window": "未找到 MiniMax Code 窗口",
        "toast.expand": "已展开 {0} 个任务",
        "toast.collapse": "已折叠",
        "toast.collapse_n": "已折叠（还有 {0} 个）",
        "toast.demo": "演示一轮任务…",
        "toast.ask_perm": "等你确认权限",
        "toast.done": "任务完成",

        # ---- 系统通知 ----
        "notify.wait": "等你确认 · {0}",
        "notify.tool_generic": "工具",
        "notify.done": "任务完成",

        # ---- 窗口标题 ----
        "win.pet": "MiniMax Pet",
        "win.cards": "MiniMax Pet 任务状态",

        # ---- 日志 ----
        "log.session": "发现会话 {0}",
        "log.session_proj": "（{0}）",
        "log.new_task": "新任务：{0}",
        "log.compacted": "压缩会话，标题取自回顾：{0}",
        "log.tool_step": "{0} · 第 {1} 步",
        "log.turn_end": "回合结束 · {0} 步",
        "log.port": "事件端口 {0}",
        "log.port_busy": "端口被占用，跳过 HTTP 入口",
        "log.app_seen": "检测到 MiniMax Code 进程 ✓",
        "log.app_gone": "MiniMax Code 进程已关闭",
        "log.follow": "跟随 MiniMax Code = {0}",
        "log.hide_manual": "手动隐藏桌宠",
        "log.show_manual": "手动显示桌宠",
        "log.card_kept": "跳转中，任务未结束，卡片保留（{0}）",
        "log.card_dismissed": "任务已结束，卡片收起（{0}）",
        "log.jump_ok": "跳转 MiniMax Code ✓",
        "log.jump_fail": "跳转 MiniMax Code（未找到窗口）",
        "log.http_push": "HTTP 推送：{0}",
        "log.http_push_tool": " · {0}",
        "log.quit": "桌宠退出",
        "log.start": "桌宠启动（跟随={0}，随应用退出={1}）",
        "log.lang": "界面语言 = {0}",

        "http.project": "外部推送",

        # 演示 / 自检用的假任务标题（要出现在双语截图里，所以也得双语）
        "demo.t1": "演示：重构 utils/date.py 并跑通单元测试",
        "demo.t2": "修复对话框底部文字被裁的问题",
        "demo.t3": "排查桌宠生命周期跟随失效",
        "demo.t4": "把状态胶囊宽度改成自适应",
        "demo.t5": "收尾：同步 README",
    },

    "en": {
        "mood.idle": "Idle",
        "mood.thinking": "Thinking",
        "mood.executing": "Running",
        "mood.waiting": "Needs you",
        "mood.done": "Done",
        "mood.error": "Failed",

        "card.exec": "Running {0}…",
        "card.exec_generic": "Running…",
        "card.wait": "Needs you · {0}",
        "card.thinking": "Thinking…",
        "card.error": "Failed · {0}",
        "card.done": ("Done · {0} step", "Done · {0} steps"),
        "card.tool_generic": "tool",
        "card.untitled": "(Untitled task)",

        "chip.exec_generic": "Running",
        "chip.done": ("{0} step · {1}", "{0} steps · {1}"),

        "foot.more": ("{0} more task", "{0} more tasks"),
        "foot.collapse": "Collapse",

        "menu.show_pet": "Show / Hide Pet",
        "menu.show_cards": "Show / Hide Task Cards",
        "menu.hide_cards": "Hide Task Cards",
        "menu.fold_cards": "Collapse cards ({0} hidden)",
        "menu.expand_cards": "Expand all tasks ({0})",
        "menu.follow": "Follow MiniMax Code",
        "menu.exit_with": "Exit pet when MiniMax exits",
        "menu.jump": "Jump to MiniMax Code",
        "menu.demo": "Play Demo Task",
        "menu.reset": "Reset Position",
        "menu.opendir": "Open Install Folder",
        "menu.quit": "Quit Pet",
        "menu.language": "语言 / Language",

        "toast.jumped": "Jumped to MiniMax Code",
        "toast.no_window": "MiniMax Code window not found",
        "toast.expand": ("Expanded {0} task", "Expanded {0} tasks"),
        "toast.collapse": "Collapsed",
        "toast.collapse_n": "Collapsed ({0} hidden)",
        "toast.demo": "Playing demo task…",
        "toast.ask_perm": "Permission needed",
        "toast.done": "Task complete",

        "notify.wait": "Needs you · {0}",
        "notify.tool_generic": "tool",
        "notify.done": "Task complete",

        "win.pet": "MiniMax Pet",
        "win.cards": "MiniMax Pet — Task Status",

        "log.session": "Session discovered: {0}",
        "log.session_proj": " ({0})",
        "log.new_task": "New task: {0}",
        "log.compacted": "Compacted session, title from summary: {0}",
        "log.tool_step": ("{0} · step {1}", "{0} · steps {1}"),
        "log.turn_end": ("Turn finished · {0} step", "Turn finished · {0} steps"),
        "log.port": "Event port {0}",
        "log.port_busy": "Port busy, HTTP entry disabled",
        "log.app_seen": "MiniMax Code process detected ✓",
        "log.app_gone": "MiniMax Code process exited",
        "log.follow": "Follow MiniMax Code = {0}",
        "log.hide_manual": "Pet hidden manually",
        "log.show_manual": "Pet shown manually",
        "log.card_kept": "Jumped, task still running, card kept ({0})",
        "log.card_dismissed": "Task finished, card dismissed ({0})",
        "log.jump_ok": "Jumped to MiniMax Code ✓",
        "log.jump_fail": "Jumped to MiniMax Code (window not found)",
        "log.http_push": "HTTP push: {0}",
        "log.http_push_tool": " · {0}",
        "log.quit": "Pet exited",
        "log.start": "Pet started (follow={0}, exit_with_app={1})",
        "log.lang": "Interface language = {0}",

        "http.project": "External push",

        "demo.t1": "Demo: refactor utils/date.py and pass its unit tests",
        "demo.t2": "Fix bottom text clipped in the task card",
        "demo.t3": "Investigate lifecycle-follow failing to trigger",
        "demo.t4": "Make the status pill width adaptive",
        "demo.t5": "Wrap up: sync the README",
    },
}

_current = DEFAULT_LANG


def normalize(lang):
    """把各种写法收敛成 'zh' / 'en'；认不出来就回默认值。"""
    if not lang:
        return DEFAULT_LANG
    s = str(lang).strip().lower().replace("_", "-")
    if s.startswith("zh") or "chinese" in s:
        return "zh"
    if s.startswith("en") or "english" in s:
        return "en"
    return DEFAULT_LANG


def system_lang():
    """从环境变量猜系统语言。Windows 上 Git Bash / CMD 通常会带 LANG。"""
    for k in ("MINIMAX_PET_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(k)
        if v:
            n = normalize(v)
            # 只有明确是英文才算英文；中文环境下 LANG 常是 C / POSIX
            if n == "en" and not str(v).upper().startswith(("C", "POSIX")):
                return "en"
            if n == "zh":
                return "zh"
    return DEFAULT_LANG


def set_lang(lang):
    global _current
    _current = normalize(lang)
    return _current


def get_lang():
    return _current


def t(key, *args):
    """取文案并做位置参数替换。

    词表里的值可以是字符串，也可以是 `[单数, 复数]` 二元组（gettext ngettext
    风格）。用二元组时，取 `args` 里**第一个 int 参数**作为计数来决定单/复数
    —— 本项目里那个 int 总是步数或任务数，比如
    `t("card.done", steps)` / `t("chip.done", steps, "02:34")`。

    缺 key 时回退到中文表、再回退到 key 本身——宁可显示 key，也不要崩。
    """
    s = STRINGS.get(_current, {}).get(key)
    if s is None:
        s = STRINGS["zh"].get(key)
    if s is None:
        return key
    if isinstance(s, (list, tuple)):
        n = next((a for a in args if isinstance(a, int) and not isinstance(a, bool)), 1)
        s = s[0] if n == 1 else s[1]
    if not args:
        return s
    try:
        return s.format(*args)
    except (IndexError, KeyError):
        # 词表和调用点的参数个数对不上时，宁可少格式化也别抛异常打断界面
        return s
