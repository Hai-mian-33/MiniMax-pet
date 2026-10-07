# 参与 MiniMax Pet 开发

[English](CONTRIBUTING.md) · [简体中文](CONTRIBUTING.zh-CN.md)

感谢你有兴趣。这是个单文件 Python 小项目，参与门槛很低，
但有几条约定能保证它长期健康。

---

## 铁律

1. **桌宠只读。** 绝不允许写入 `~/.minimax/` 或 MiniMax Code 的任何目录。
   自身状态只落在项目目录内（`pet_state.json`）。
2. **界面文案不许硬编码。** 所有看得见的字都走 `i18n.t()`。
   加文案时 `zh` 和 `en` 两张表**都要加**。缺 key 会回退中文，调试可以，上线不行。
3. **局部变量别叫 `t`。** 模块级的翻译函数就是 `t()`，
   局部赋值会让整个函数体把它遮蔽掉 —— 报错是运行时的 `UnboundLocalError`，
   不是导入时。这类坑已经踩过一次了。用 `tk` / `ctype` / `flat`，或者换个更贴切的名字。
4. **只用位置参数。** 写 `{0} {1}`，不要用 f-string 或具名占位符。
   `str.format` 遇到 `{0,3}` 在 Python 3.12 上会抛 `KeyError`。

---

## 开发环境

```bash
git clone https://github.com/Hai-mian-33/MiniMax-pet.git
cd MiniMax-pet
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
pip install PyQt5
```

## 跑测试

```bash
python tests/run_tests.py
```

纯 `unittest`，不依赖 pytest。覆盖：

- 所有模块的语法
- `zh` / `en` 两张表的 key 对齐（有漏翻直接失败）
- 单复数与参数个数的安全性
- `normalize()` / `system_lang()` 的行为
- 全部控件状态的离屏渲染

## 不打扰你正在跑的桌宠地调试

```bash
python minimax_pet.py --demo              # 合成任务，不碰真实会话
python minimax_pet.py --selftest          # 渲染 PNG 后退出
python minimax_pet.py --selftest-live     # 用真实会话渲染
```

桌宠在临时目录持有一把 `QLockFile`，所以第二个实例会干净退出，
不会和你已经开着的那个抢托盘图标。

---

## 加一种语言翻译

这是最有价值、也最容易的贡献方式。

1. Fork 后切分支：`git checkout -b add-japanese`
2. 在 [`i18n.py`](i18n.py) 里：
   - 把语言代码加进 `LANGS = (...)`
   - 加一个 `STRINGS["ja"]` 块 —— 复制 `STRINGS["zh"]` 然后逐条翻译
   - 在 `normalize()` 里让它认得你的地区写法（比如 `"ja"` / `ja-JP`）
3. 跑 `python tests/run_tests.py` —— 对齐检查会直接告诉你漏了哪些 key。
4. 生成截图，好让 README 能展示：
   ```bash
   python minimax_pet.py --lang ja --selftest
   ```
5. 提 PR。

托盘菜单和 `--lang` 选项都从 `LANGS` 派生，不用再改别的地方。

---

## 重新生成吉祥物素材

`assets/` 已经随仓库提供。只有当你本机装了 MiniMax Code、
且想跟上新版官方图标时，才需要重新生成：

```bash
python build_assets.py
```

它会读取官方 `icon.icns`，像素级还原地提取 `mascot.png`，
再派生 `mascot_glow.png` / `mascot_shadow.png` / `mascot_tray.png`。
注意素材著作权归原权利人所有，**不要**改成别的品牌。

---

## 重新生成截图

```bash
python minimax_pet.py --lang zh --selftest
python minimax_pet.py --lang en --selftest
```

两种语言都会落到 `docs/images/`，按语言成对。改了界面就要一起更新 ——
README 里挂一张过期的截图比不挂更糟。

---

## 代码风格

- 兼容 Python 3.9 的语法。运行时代码里不要用 `match`，不要用 `X | Y` 类型联合。
- 注释写「为什么」，不是「是什么」。本仓库注释惯例用中文 —— 跟着你改的那个文件走。
- 保持 `minimax_pet.py` 自包含。刻意做成单文件，
  是为了让人下载下来就能跑，不需要打包。

---

## 报告 Bug

请附上：

- 你的系统与 Python 版本
- 完整的启动命令行
- `pet.log` 的尾部（就在脚本旁边）
- 界面问题请附截图

`pet.log` 的几行日志通常就能直接定位问题。

---

## 安全说明

HTTP 入口只绑定 `127.0.0.1`，且接受不带鉴权的 JSON。
对一个本地桌宠来说这是有意为之，但也意味着**本机任何程序都能往桌宠推卡片**。
要暴露出去的话请自负风险：套一层代理，或者干脆加 `--no-server`。

---

## 许可

你的贡献将以 [MIT 许可](LICENSE) 发布。
