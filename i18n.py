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

        # ---- 待命哨兵（pet_watcher.py）----
        "watch.start": "待命哨兵启动：只等 MiniMax Code，本进程不显示任何界面",
        "watch.already": "已有待命哨兵在跑，本次启动已退出",
        "watch.app_seen": "检测到 MiniMax Code 进程 ✓",
        "watch.app_gone": "MiniMax Code 进程已关闭（桌宠会自行退出）",
        "watch.spawned": "已拉起桌宠",
        "watch.no_pet": "!! 找不到 minimax_pet.py，无法拉起：{0}",
        "watch.spawn_fail": "!! 拉起桌宠失败：{0}",
        "watch.row_watcher": "待命哨兵",
        "watch.row_pet": "桌宠进程",
        "watch.row_app": "MiniMax",
        "watch.row_log": "日志",
        "watch.yes": "在跑 ✓",
        "watch.no": "未运行",
        "watch.pet_idle": "未运行（等 MiniMax Code 打开）",

        # ---- 开机自启（autostart.py）----
        "auto.on_ok": "OK 已开启登录待命",
        "auto.trigger": "触发器",
        "auto.interp": "解释器",
        "auto.watcher": "待命哨兵",
        "auto.pet": "桌宠",
        "auto.pet_note": "（由哨兵在检测到 MiniMax Code 打开时拉起）",
        "auto.undo": "撤销",
        "auto.undo_cmd": "python autostart.py off  （或双击 remove_autostart.bat）",
        "auto.off_ok": "OK 已取消登录待命（已删除 {0}）",
        "auto.off_none": "本来就没有开启登录待命。",
        "auto.warn_ascii": "! 路径含非 ASCII 字符，VBS 可能无法正确执行，请检查文件内容。",
        "auto.row_trig": "登录待命",
        "auto.on": "已开启",
        "auto.off": "未开启",
        "auto.row_watcher": "哨兵程序",
        "auto.row_pet": "桌宠程序",
        "auto.row_interp": "解释器",
        "auto.exists": "存在",
        "auto.missing": "!! 不存在",
        "auto.interp_path": "（依赖 PATH，稳定性较弱）",
        "auto.row_running": "哨兵在跑",
        "auto.row_pet_running": "桌宠在跑",
        "auto.pet_not_running": "否（等 MiniMax Code 打开）",
        "auto.row_vbs": "VBS 内容",
        "auto.vbs_fail": "读取失败 {0}",
        "auto.verify_first": "登录待命未开启，先执行 python autostart.py on",
        "auto.v_before": "执行前：哨兵",
        "auto.v_after": "执行后：哨兵",
        "auto.v_yes": "是 ✓",
        "auto.v_no": "否",
        "auto.v_already": "已在运行",
        "auto.v_not": "未运行",
        "auto.v_ok": "已拉起 ✓",
        "auto.v_fail": "未拉起 ✗",
        "auto.v_pet_ok": "在跑 ✓",
        "auto.v_pet_idle": "未跑（MiniMax Code 没开时这是对的）",
        "auto.v_works": "登录待命可用。下次登录时它会静默等 MiniMax Code 打开。",
        "auto.v_single": "单实例锁生效，没有起重复哨兵，触发器工作正常。",
        "auto.v_broken": "! 触发器没能拉起哨兵，请检查上面的「解释器 / 哨兵程序」是否存在。",
        "auto.wsh_fail": "! 无法调用 WSH：{0}",

        # 演示 / 自检用的假任务标题（要出现在双语截图里，所以也得双语）
        "demo.t1": "演示：重构 utils/date.py 并跑通单元测试",
        "demo.t2": "修复对话框底部文字被裁的问题",
        "demo.t3": "排查桌宠生命周期跟随失效",
        "demo.t4": "把状态胶囊宽度改成自适应",
        "demo.t5": "收尾：同步 README",
        # ---- v1.1 运行时修复新增 ----
        "size.menu": "桌宠大小",
        "size.level.0.75": "小",
        "size.level.0.9": "较小",
        "size.level.1.0": "标准",
        "size.level.1.15": "较大",
        "size.level.1.35": "大",
        "size.level.custom": "自定义",
        "size.recalibrate": "立即按当前屏幕校正",
        "size.show_info": "显示物理尺寸信息",
        "follow.mode_menu": "跟随依据",
        "follow.mode_process": "按进程存活（关掉窗口仍显示）",
        "follow.mode_window": "按窗口显隐（关掉窗口就隐藏）",
        "act.focus": "已跳转到 MiniMax Code",
        "act.show": "后台有任务在跑，只还原了窗口",
        "act.spawn": "已重新拉起 MiniMax Code",
        "act.relaunch": "旧窗口已失效，已重启 MiniMax Code",
        "act.spawn_failed": "没找到 MiniMax Code，请手动打开",
        "act.relaunch_failed": "旧窗口没清掉且新窗口没起来，请手动打开",
        "act.probe_error": "召唤失败，请手动打开",
        "toast.hidden": "已隐藏",
        "toast.hidden_follow": "已隐藏（跟随仍开着）",
        "toast.shown": "已显示",
        "toast.jump_busy": "正在召唤 MiniMax Code…",
        "toast.jumping": "正在召唤 MiniMax Code…",
        "screen.unknown": "未知",
        "log.win.bind_fail": "绑定 {0} 失败：{1}",
        "log.win.probe_exc": "窗口响应性探测异常，按活处理：{0}",
        "log.win.ppid_fail": "进程父子表扫描失败：{0}",
        "log.win.anc_fail": "祖先链解析失败：{0}",
        "log.win.spawned": "已拉起 MiniMax Code：{0}",
        "log.win.spawn_exe_fail": "直接启动 exe 失败（{0}），改用开始菜单快捷方式",
        "log.win.spawned_lnk": "已通过开始菜单快捷方式拉起 MiniMax Code",
        "log.win.lnk_fail": "快捷方式启动也失败：{0}",
        "log.act.killed": "召唤：结束残留进程 {0} 个（受保护而跳过的根 {1} 个）",
        "log.act.protected": "有 {0} 个残留窗口属于受保护进程，没动它（多半是桌宠自己挂着的宿主）",
        "log.act.exc": "召唤 MiniMax Code 异常：{0}",
        "log.act.wm_close": "召唤：{0} 个窗口已被关闭，发 WM_CLOSE 等它体面退出（{1}s）",
        "log.act.cant_kill": "召唤：残留进程清不掉（多半是桌宠自己挂着的宿主），仍尝试拉起新实例",
        "log.act.closed_windows": "召唤：{0} 个窗口已被关闭且进程还在 —— 不复活它，改拉新实例",
        "log.act.n_noexe": "找不到 MiniMax Code 可执行文件",
        "log.act.n_nowin": "{0}；已发起启动但窗口没出现",
        "log.act.n_notwin": "非 Windows 平台",
        "log.act.n_running": "后台有任务在跑，没结束进程，只还原了窗口",
        "log.act.n_restore_failed": "还原窗口失败",
        "log.act.n_back": "关掉的窗口自己回来了，直接置前（不结束进程）",
        "log.act.n_gone": "残留窗口已自行退出，直接拉新实例",
        "log.act.n_cleared": "清掉了 {0} 个残留进程后重新拉起",
        "log.act.n_protected": "残留进程清不掉，仍尝试拉起新实例",
        "log.act.n_enum_fail": "窗口枚举失败：{0}",
        "log.act.n_visible": "{0} 个可见窗口，直接置前",
        "log.act.n_minimized": "已还原最小化的窗口（{0} 个候选）",
        "log.act.n_nostate": "已置前（状态判不出来）",
        "log.act.n_badstate": "窗口状态无法判定",
        "log.win.scan_empty": "进程扫描一个进程都没扫到：视为探测失败",
        "log.act.n_nowin2": "进程还在但没有窗口",
        "log.size.measure_fail": "实测缩放比例失败：{0}",
        "log.size.apply_fail": "应用尺寸失败：{0}",
        "log.size.remeasured": "实测缩放 {0}（Qt 报告 {1}），已按实测重新换算",
        "log.size.sync": "Recomputed for the current screen: {0}",
        "log.size.sync_fail": "换屏后重新换算大小失败（已忽略）：\n{0}",
        "log.size.level": "桌宠大小 → {0}（档位 {1}）",
        "log.follow_mode": "跟随依据 → {0}",
        "log.follow_resume": "应用重新打开，跟随重新接管（解除手动隐藏）",
        "log.watcher_restore": "待命哨兵不在，正在恢复",
        "log.jump_keep_proc": "召唤：后台还有任务在跑，本次不允许结束进程",
        "log.jump_start": "召唤 MiniMax Code（后台线程，allow_kill={0}）",
        "log.jump_result": "Summon MiniMax Code {0} {1}",
        "log.resume": "手动重新启用：已清除暂停标记（原剩余 {0} 秒）",
        "log.resume_fail": "解除暂停失败：{0}",
        "size.info": "Size info: {0}",
        # ---- v1.1 哨兵：暂停标记 / 状态驱动 / ensure ----
        "watch.lock_broken": "已清除损坏的桌宠锁文件（{0}），原内容={1}",
        "watch.lock_break_fail": "清除桌宠锁文件失败：{0}",
        "watch.watcher_spawned": "已反拉待命哨兵",
        "watch.watcher_spawn_fail": "反拉哨兵失败：{0}",
        "watch.paused": "检测到 MiniMax Code，但处于暂停期（用户手动退出过桌宠），剩余 {0} 分钟",
        "watch.paused_left": "已生效，{0} 分钟后自动恢复",
        "watch.paused_tag": "（已暂停）",
        "watch.heartbeat": "心跳 已运行 {0} 分钟｜{1}",
        "watch.tick_fail": "哨兵这一轮出错了（已忽略）：{0}",
        "watch.ensure_paused": "ensure：处于暂停期（用户手动退出过桌宠），不拉起",
        "watch.ensure_spawn": "ensure：哨兵不在，把哨兵拉起来",
        "watch.ensure_fail": "ensure 失败：{0}",
        "watch.unpaused": "已手动解除暂停（原剩余 {0} 分钟）",
        "watch.unpaused_msg": "已解除暂停，哨兵会在下次检测到 MiniMax Code 时拉起桌宠。",
        "watch.row_paused": "暂停标记",
        # ---- v1.1 计划任务兜底 ----
        "auto.paused": "暂停标记：已生效，{0} 分钟后自动恢复；python pet_watcher.py --unpause 可立即解除",
        "auto.paused_left": "已生效，{0} 分钟后自动恢复",
        "auto.row_keepalive": "计划任务",
        "auto.keepalive_on": "已启用 ✓",
        "auto.keepalive_off": "未启用",
        "auto.keepalive_ok": "OK 已创建计划任务 {0}（每 {1} 分钟一次）",
        "auto.keepalive_removed": "OK 已删除计划任务 {0}",
        "auto.keepalive_none": "计划任务本来就不存在。",
        "auto.keepalive_recreate": "计划任务已存在，先删掉重建以确保指向最新路径。",
        "auto.keepalive_fail": "! 操作失败：{0}",
        "auto.row_keepalive_cmd": "执行",
        "auto.keepalive_note": "作用",
        "auto.keepalive_note_txt": "哨兵和桌宠都被清掉时，把哨兵补回来（不会解除「用户手动退出」的暂停）",
        "auto.keepalive_undo_cmd": "撤销：python autostart.py keepalive off",
        "auto.keepalive_enable_cmd": "开启：python autostart.py keepalive on",
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

        # ---- standby sentinel (pet_watcher.py) ----
        "watch.start": "Standby sentinel started: waiting for MiniMax Code, this process shows nothing",
        "watch.already": "A sentinel is already running; this launch exited",
        "watch.app_seen": "MiniMax Code process detected ✓",
        "watch.app_gone": "MiniMax Code process closed (the pet will exit on its own)",
        "watch.spawned": "Pet spawned",
        "watch.no_pet": "!! minimax_pet.py not found, cannot spawn: {0}",
        "watch.spawn_fail": "!! failed to spawn the pet: {0}",
        "watch.row_watcher": "Sentinel",
        "watch.row_pet": "Pet process",
        "watch.row_app": "MiniMax",
        "watch.row_log": "Log",
        "watch.yes": "running ✓",
        "watch.no": "not running",
        "watch.pet_idle": "not running (waiting for MiniMax Code)",

        # ---- autostart (autostart.py) ----
        "auto.on_ok": "OK Login standby enabled",
        "auto.trigger": "Trigger",
        "auto.interp": "Interpreter",
        "auto.watcher": "Sentinel",
        "auto.pet": "Pet",
        "auto.pet_note": "(spawned by the sentinel when MiniMax Code opens)",
        "auto.undo": "Undo",
        "auto.undo_cmd": "python autostart.py off  (or run remove_autostart.bat)",
        "auto.off_ok": "OK Login standby disabled (deleted {0})",
        "auto.off_none": "Login standby was not enabled in the first place.",
        "auto.warn_ascii": "! Path contains non-ASCII characters; the VBS may not run correctly. Check the file.",
        "auto.row_trig": "Login standby",
        "auto.on": "enabled",
        "auto.off": "disabled",
        "auto.row_watcher": "Sentinel program",
        "auto.row_pet": "Pet program",
        "auto.row_interp": "Interpreter",
        "auto.exists": "present",
        "auto.missing": "!! missing",
        "auto.interp_path": "(relies on PATH, less reliable)",
        "auto.row_running": "Sentinel running",
        "auto.row_pet_running": "Pet running",
        "auto.pet_not_running": "no (waiting for MiniMax Code)",
        "auto.row_vbs": "VBS content",
        "auto.vbs_fail": "read failed {0}",
        "auto.verify_first": "Login standby is off; run python autostart.py on first",
        "auto.v_before": "Before: sentinel",
        "auto.v_after": "After: sentinel",
        "auto.v_yes": "yes ✓",
        "auto.v_no": "no",
        "auto.v_already": "was running",
        "auto.v_not": "not running",
        "auto.v_ok": "spawned ✓",
        "auto.v_fail": "not spawned ✗",
        "auto.v_pet_ok": "running ✓",
        "auto.v_pet_idle": "not running (correct when MiniMax Code is closed)",
        "auto.v_works": "Login standby works. On next sign-in it will silently wait for MiniMax Code.",
        "auto.v_single": "Single-instance lock held; no duplicate sentinel. The trigger works.",
        "auto.v_broken": "! The trigger failed to spawn the sentinel. Check that the interpreter and sentinel exist.",
        "auto.wsh_fail": "! Cannot invoke WSH: {0}",

        "demo.t1": "Demo: refactor utils/date.py and pass its unit tests",
        "demo.t2": "Fix bottom text clipped in the task card",
        "demo.t3": "Investigate lifecycle-follow failing to trigger",
        "demo.t4": "Make the status pill width adaptive",
        "demo.t5": "Wrap up: sync the README",
        # ---- v1.1 runtime fixes ----
        "size.menu": "Pet size",
        "size.level.0.75": "Small",
        "size.level.0.9": "Smaller",
        "size.level.1.0": "Standard",
        "size.level.1.15": "Larger",
        "size.level.1.35": "Large",
        "size.level.custom": "Custom",
        "size.recalibrate": "Re-measure for the current screen",
        "size.show_info": "Show physical size info",
        "follow.mode_menu": "Follow by",
        "follow.mode_process": "By process (stays visible when the window closes)",
        "follow.mode_window": "By window (hides when the window closes)",
        "act.focus": "Jumped to MiniMax Code",
        "act.show": "A task is running - window restored only",
        "act.spawn": "MiniMax Code relaunched",
        "act.relaunch": "Old window was dead - MiniMax Code restarted",
        "act.spawn_failed": "MiniMax Code not found - open it manually",
        "act.relaunch_failed": "Could not clear the old window - open it manually",
        "act.probe_error": "Summon failed - open it manually",
        "toast.hidden": "Hidden",
        "toast.hidden_follow": "Hidden (follow is still on)",
        "toast.shown": "Shown",
        "toast.jump_busy": "Summoning MiniMax Code...",
        "toast.jumping": "Summoning MiniMax Code...",
        "screen.unknown": "unknown",
        "log.win.bind_fail": "Failed to bind {0}: {1}",
        "log.win.probe_exc": "Window liveness probe failed, treating as alive: {0}",
        "log.win.ppid_fail": "Failed to build the process parent map: {0}",
        "log.win.anc_fail": "Failed to resolve the ancestor chain: {0}",
        "log.win.spawned": "Launched MiniMax Code: {0}",
        "log.win.spawn_exe_fail": "Direct exe launch failed ({0}), falling back to the Start Menu shortcut",
        "log.win.spawned_lnk": "Launched MiniMax Code via the Start Menu shortcut",
        "log.win.lnk_fail": "Shortcut launch failed too: {0}",
        "log.act.killed": "Summon: terminated {0} leftover processes ({1} protected roots skipped)",
        "log.act.protected": "{0} leftover windows belong to protected processes - left alone (likely the host the pet runs under)",
        "log.act.exc": "Summon failed with an exception: {0}",
        "log.act.wm_close": "Summon: {0} windows were closed by the user - sent WM_CLOSE and waited {1}s",
        "log.act.cant_kill": "Summon: could not clear leftover processes (likely the host) - trying to launch a new instance anyway",
        "log.act.closed_windows": "Summon: {0} windows were closed but the process lingers - not reviving them, launching a new instance",
        "log.act.n_noexe": "Could not find the MiniMax Code executable",
        "log.act.n_nowin": "{0} - launch was requested but no window appeared",
        "log.act.n_notwin": "Not running on Windows",
        "log.act.n_running": "A task is running - did not terminate any process, restored the window only",
        "log.act.n_restore_failed": "Failed to restore the window",
        "log.act.n_back": "The closed window came back on its own - focused it (no process was terminated)",
        "log.act.n_gone": "Leftover windows exited on their own - launching a new instance",
        "log.act.n_cleared": "Cleared {0} leftover processes, then relaunched",
        "log.act.n_protected": "Could not clear leftover processes - still launching a new instance",
        "log.act.n_enum_fail": "Window enumeration failed: {0}",
        "log.act.n_visible": "{0} visible windows - focused one",
        "log.act.n_minimized": "Restored a minimised window ({0} candidates)",
        "log.act.n_nostate": "Focused (window state could not be determined)",
        "log.act.n_badstate": "Could not determine the window state",
        "log.win.scan_empty": "The process scan found no processes at all - treating it as a probe failure",
        "log.act.n_nowin2": "The process is running but there is no window",
        "log.size.measure_fail": "Failed to measure the scale factor: {0}",
        "log.size.apply_fail": "Failed to apply the size: {0}",
        "log.size.remeasured": "Measured scale {0} (Qt reported {1}) - recomputed from the measurement",
        "log.size.sync": "Recomputed for the current screen: {0}",
        "log.size.sync_fail": "Failed to recompute the size after the screen change (ignored):\n{0}",
        "log.size.level": "Pet size -> {0} (level {1})",
        "log.follow_mode": "Follow by -> {0}",
        "log.follow_resume": "The app reopened - follow takes over again (manual hide cleared)",
        "log.watcher_restore": "The sign-in sentinel is gone - restoring it",
        "log.jump_keep_proc": "Summon: a task is running - no process will be terminated",
        "log.jump_start": "Summon MiniMax Code (worker thread, allow_kill={0})",
        "log.jump_result": "Summon MiniMax Code {0} {1}",
        "log.resume": "Manually re-enabled: the pause flag was cleared ({0} s left)",
        "log.resume_fail": "Could not clear the pause flag: {0}",
        "size.info": "Size info: {0}",
        # ---- v1.1 sentinel: pause flag / state-driven / ensure ----
        "watch.lock_broken": "Cleared the corrupted pet lock file ({0}); original content={1}",
        "watch.lock_break_fail": "Failed to clear the pet lock file: {0}",
        "watch.watcher_spawned": "Respawned the sign-in sentinel",
        "watch.watcher_spawn_fail": "Failed to respawn the sentinel: {0}",
        "watch.paused": "MiniMax Code detected but paused (the pet was quit manually); {0} min left",
        "watch.paused_left": "active, resumes in {0} min",
        "watch.paused_tag": " (paused)",
        "watch.heartbeat": "Heartbeat: up {0} min | {1}",
        "watch.tick_fail": "This sentinel tick failed (ignored): {0}",
        "watch.ensure_paused": "ensure: paused (the pet was quit manually) - not starting anything",
        "watch.ensure_spawn": "ensure: the sentinel is gone - starting it",
        "watch.ensure_fail": "ensure failed: {0}",
        "watch.unpaused": "Manually unpaused ({0} min left)",
        "watch.unpaused_msg": "Unpaused. The sentinel will bring the pet back the next time MiniMax Code is detected.",
        "watch.row_paused": "Pause flag",
        # ---- v1.1 scheduled-task keepalive ----
        "auto.paused": "Pause flag: active, resumes in {0} min; python pet_watcher.py --unpause clears it now",
        "auto.paused_left": "active, resumes in {0} min",
        "auto.row_keepalive": "Scheduled task",
        "auto.keepalive_on": "enabled",
        "auto.keepalive_off": "not enabled",
        "auto.keepalive_ok": "OK created scheduled task {0} (every {1} min)",
        "auto.keepalive_removed": "OK removed scheduled task {0}",
        "auto.keepalive_none": "The scheduled task did not exist.",
        "auto.keepalive_recreate": "The scheduled task exists; recreating it so it points at the current path.",
        "auto.keepalive_fail": "! Operation failed: {0}",
        "auto.row_keepalive_cmd": "Runs",
        "auto.keepalive_note": "What it does",
        "auto.keepalive_note_txt": "brings the sentinel back when both the sentinel and the pet are gone (it does NOT clear a manual quit)",
        "auto.keepalive_undo_cmd": "Undo: python autostart.py keepalive off",
        "auto.keepalive_enable_cmd": "Enable: python autostart.py keepalive on",
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
