# 上传到 GitHub 公开仓库 · 完整操作指南

> 目标：把 `C:\Users\23154\Desktop\MiniMax-pet` 发布为一个**公开**的 GitHub 仓库。
> 全部命令都在 **Git Bash** 里执行。

---

## 目录

- [第 0 步：发布前自检](#第-0-步发布前自检)
- [第 1 步：创建仓库（网页表单填什么）](#第-1-步创建仓库网页表单填什么)
- [第 2 步：配置 Git 身份](#第-2-步配置-git-身份)
- [第 3 步：初始化本地仓库](#第-3-步初始化本地仓库)
- [第 4 步：提交](#第-4-步提交)
- [第 5 步：关联远程并推送](#第-5-步关联远程并推送)
- [第 6 步：补齐仓库设置](#第-6-步补齐仓库设置)
- [认证方式：PAT vs SSH](#认证方式pat-vs-ssh)
- [常见问题 FAQ](#常见问题-faq)

---

## 第 0 步：发布前自检

在动手之前，先跑一遍检查，确保没有把运行时产物或密钥带上去。

```bash
cd /c/Users/23154/Desktop/MiniMax-pet

python tools/check_repo.py     # 必需文件 / 体积 / 密钥 / README 图片链接 / 语法 / 双语 key
python tests/run_tests.py      # 25 项测试：语法、双语对齐、复数、状态机、离屏渲染
```

两个都显示通过再往下走。

> 目录里现在有 `pet_state.json` / `pet.log` 是正常的 —— 它们已在 `.gitignore` 里，
> 不会被提交。

---

## 第 1 步：创建仓库（网页表单填什么）

打开 <https://github.com/new>。

### ① Owner / 仓库名

```
Owner:      Hai-mian-33
Repository: MiniMax-pet
```

> 仓库名建议用 `MiniMax-pet`。如果这个名字已被占用，GitHub 会自动提示，
> 改成 `minimax-pet` 即可，**大小写无所谓**。

### ② Description（350 字符以内）

直接复制这一行：

```
Bilingual desktop pet for MiniMax Code — live task cards, permission nudges and zh/en UI. 一个实时显示 MiniMax Code 任务进度的中英双语桌宠。
```

**如果嫌长，用这个精简版：**

```
Bilingual desktop pet for MiniMax Code — live task cards, zh/en UI. 实时显示 MiniMax Code 任务进度的中英双语桌宠。
```

### ③ Configuration 区域（你截图里那三块）

| 项目 | 选什么 | 为什么 |
|---|---|---|
| **Choose visibility** | **Public** | 你要的就是公开仓库 |
| **Add README** | **Off** | README 已经写好了，本地 `git push` 会带上去；开 On 会产生冲突 |
| **Add .gitignore** | **No .gitignore** | 同上，本地已有中文注释版 `.gitignore` |
| **Add license** | **No license** | 同上，本地已有 MIT `LICENSE`；开这个会多生成一份冲突文件 |
| **Jumpstart with Copilot** | **留空，不填** | 完全不用，Prompt 框里什么都不写 |

> **关键原则**：这三项（README / .gitignore / license）一律选 "Off / No"，
> 因为本地已经全部准备好了。GitHub 生成的和本地的会打架，导致 push 被拒绝。

### ④ 其余保持默认

- 下方 `Settings`（Issues / Projects / Wiki / Sponsors / Discussions）默认全开，无所谓。
- 底部绿色 **Create repository** 按钮 —— 点之前确认上面 **Visibility = Public**。

### 创建完成后

GitHub 会显示一个空仓库页面。**先不要点 "uploading an existing file" 里的绿色按钮**，
直接切到第 2 步用命令行推。

---

## 第 2 步：配置 Git 身份

Git Bash 里执行（只需一次）：

```bash
git config --global user.name  "Sun Haiming"
git config --global user.email "haiming.sun33@gmail.com"
```

确认一下：

```bash
git config --global --list | grep user
# user.name=Sun Haiming
# user.email=haiming.sun33@gmail.com
```

> 如果你希望这个仓库用别的身份（工作邮箱更保险，避免和私人邮箱关联）：

```bash
cd /c/Users/23154/Desktop/MiniMax-pet
git config user.name  "Sun Haiming"
git config user.email "你的GitHub验证邮箱"
```

---

## 第 3 步：初始化本地仓库

```bash
cd /c/Users/23154/Desktop/MiniMax-pet

# 如果这个目录已经是 git 仓库，先看一眼状态
git status
```

**如果报 `not a git repository`**，执行初始化：

```bash
git init -b main
```

**如果它已经是仓库**（比如之前初始化过），只改分支名即可：

```bash
git branch -M main
```

顺便确认一下 `.gitignore` 生效了 —— 应该看不到这些运行时文件：

```bash
git status --short
```

输出里**不应该**出现 `pet_state.json`、`pet.log`、`__pycache__`。
如果出现了，`.gitignore` 没生效，先处理掉再继续。

---

## 第 4 步：提交

```bash
cd /c/Users/23154/Desktop/MiniMax-pet

git add -A
git status --short          # 先看清楚要提交什么，确认没有垃圾文件
```

确认无误后提交：

```bash
git commit -m "MiniMax Pet v1.0: bilingual (zh/en) task-progress desktop pet for MiniMax Code

- Read-only tailing of ~/.minimax/v2/sessions/**/messages.jsonl
- Six live states: idle / thinking / running / needs-you / done / failed
- Full zh + en UI with runtime switching from the tray menu
- Multi-session task cards; click to jump into the right session
- Local HTTP event bridge on 127.0.0.1:8766
- Self-testing offscreen renderer that generates docs/images/*-zh|en.png"
```

> 如果提示 `Please tell me who you are`，说明第 2 步没做，回到那里执行。

---

## 第 5 步：关联远程并推送

```bash
cd /c/Users/23154/Desktop/MiniMax-pet

git remote add origin https://github.com/Hai-mian-33/MiniMax-pet.git
git remote -v                  # 确认地址对
git push -u origin main
```

推送时会提示输入：

```
Username: Hai-mian-33
Password: <在这里粘贴你的 PAT，不是账号密码>
```

> ⚠️ **密码框要填 Personal Access Token，不能填 GitHub 登录密码。**
> GitHub 早就不再接受账号密码用于 git 操作了。见下一节。

---

## 认证方式：PAT vs SSH

### 方案 A：Personal Access Token（推荐，最省事）

1. 打开 <https://github.com/settings/tokens?type=classic>
2. 右上角 **Generate new token (classic)**
3. 填写：
   - **Note**：`MiniMax-pet upload`
   - **Expiration**：90 days（或 30 days）
   - **勾选权限**：只勾 `repo` 一项就够（勾 `public_repo` 也行）
4. 滑到底点 **Generate token**
5. **立刻复制那串 token**，关掉页面后就再也看不到了
6. 回到 `git push`，粘贴到 Password 位置
7. 如果 Git 抱怨要凭据，Windows 上会弹 **Git Credential Manager** 窗口，粘贴 token 并勾选 "Save"

> 也可以先存好，省掉以后每次输入：

```bash
git config --global credential.helper manager
```

之后第一次推送填一次，就长期记住了。

### 方案 B：SSH（配一次，长期免密）

```bash
# 1. 看有没有现成的公钥
ls -al ~/.ssh/id_ed25519.pub || ls -al ~/.ssh/id_rsa.pub

# 2. 没有就生成
ssh-keygen -t ed25519 -C "haiming.sun33@gmail.com"
# 一路回车即可（passphrase 可留空）

# 3. 复制公钥内容
cat ~/.ssh/id_ed25519.pub
```

把输出的整行（以 `ssh-ed25519` 开头）粘贴到 GitHub：
<https://github.com/settings/keys> → **New SSH key** → Title 随便起 → **Add SSH key**

然后测试并改用 SSH 推送：

```bash
ssh -T git@github.com
# Hi Hai-mian-33! You've successfully authenticated...  ← 成功

git remote set-url origin git@github.com:Hai-mian-33/MiniMax-pet.git
git push -u origin main
```

---

## 第 6 步：补齐仓库设置

推送成功后，回到仓库网页：

### About 区域（页面右侧栏）

| 字段 | 填什么 |
|---|---|
| Description | 与第 1 步相同的描述 |
| Website | 留空，或填你的个人主页 |
| Topics | 见下方列表（**最多 20 个，一定要加**，能显著提升曝光） |

**推荐 Topics（直接复制）：**

```
desktop-pet
minimax
minimax-code
pyqt5
python
bilingual
i18n
zh-cn
english
task-tracker
status-bar
tray-icon
always-on-top
open-source
mit-license
```

### 置顶 README

README 已在仓库首页。确保勾选 **Options → Show README…** 相关项正常显示。

---

## 常见问题 FAQ

<details>
<summary><b>Q1. 提示 <code>remote: Permission to … denied</code></summary>

几乎都是认证问题。按顺序排查：

1. 密码位置填的是 PAT 还是 GitHub 密码？（必须是 PAT）
2. PAT 有没有勾 `repo` 权限？
3. PAT 是否已过期？
4. 仓库名拼对了吗？注意 `Hai-mian-33/MiniMax-pet`，中间是**短横线**不是下划线。
</details>

<details>
<summary><b>Q2. 提示 <code>Updates were rejected</code> / <code>fetch first</code></summary>

远程已经有了内容（通常是你在网页上误开了 Add README）。二选一：

**方案一（推荐，保住远程内容）：**

```bash
git pull origin main --allow-unrelated-histories
# 解决冲突后
git push -u origin main
```

**方案二（远程只是空壳模板，直接覆盖）：**

```bash
git push -u origin main --force
```

> `--force` 会覆盖远程历史。本项目是首次发布、没有任何别人参与的提交，用它是安全的。
> 但以后**不要**随便用，要用也优先用 `--force-with-lease`。
</details>

<details>
<summary><b>Q3. 提示 <code>fatal: not a git repository</code></summary>

没进到目录，或没初始化：

```bash
cd /c/Users/23154/Desktop/MiniMax-pet
git init -b main
```
</details>

<details>
<summary><b>Q4. Git Bash 里中文文件名/路径乱码</summary>

Git Bash 用的是 UTF-8，Windows 终端可能是 GBK。执行前设置：

```bash
export LANG=zh_CN.UTF-8
export LC_ALL=zh_CN.UTF-8
git config --global i18n.commitencoding utf-8
git config --global i18n.logoutputencoding utf-8
```

本项目所有文件名都是纯 ASCII，其实不受影响，但设了没坏处。
</details>

<details>
<summary><b>Q5. <code>warning: LF will be replaced by CRLF</code></summary>

Windows 的正常现象，忽略即可。如果嫌吵，在仓库根加一个 `.gitattributes`：

```
* text=auto eol=lf
*.bat text eol=crlf
*.png binary
```

（`.bat` 必须保留 CRLF，否则 Windows 下批处理会挂。）
</details>

<details>
<summary><b>Q6. 桌宠源码泄露了隐私吗</summary>

`tools/check_repo.py` 会扫一遍常见密钥格式。另外：

- `pet_state.json` 存的是窗口位置，**已在 .gitignore 里**
- `pet.log` 同上，已忽略
- 源码里**不含**任何会话内容 —— 它只读不写，运行数据从不写进项目目录
</details>

<details>
<summary><b>Q7. 以后改了代码怎么再更新</summary>

```bash
cd /c/Users/23154/Desktop/MiniMax-pet

# 改完代码后，先自检
python tools/check_repo.py && python tests/run_tests.py

git add -A
git commit -m "描述这次改了什么"
git push
```
</details>

<details>
<summary><b>Q8. 想发 Release / 打 tag</summary>

```bash
git tag -a v1.0.0 -m "MiniMax Pet v1.0.0 — bilingual task-progress desktop pet"
git push origin v1.0.0
```

再到 GitHub 仓库 → **Releases** → **Draft a new release** → 选这个 tag，写点说明发布。
</details>

<details>
<summary><b>Q9. README 里的截图没显示</b></summary>

截图用的是相对路径 `docs/images/xxx.png`。确认：

```bash
ls docs/images/
```

如果为空，重新生成：

```bash
python tools/gen_screenshots.py
git add docs/images && git commit -m "docs: regenerate bilingual screenshots" && git push
```
</details>

<details>
<summary><b>Q10. 一次跑完全部命令</b></summary>

```bash
cd /c/Users/23154/Desktop/MiniMax-pet && \
python tools/check_repo.py && \
python tests/run_tests.py && \
git init -b main 2>/dev/null; \
git branch -M main && \
git add -A && \
git commit -m "MiniMax Pet v1.0: bilingual (zh/en) task-progress desktop pet for MiniMax Code" && \
git remote remove origin 2>/dev/null; \
git remote add origin https://github.com/Hai-mian-33/MiniMax-pet.git && \
git push -u origin main
```

> 中途要输 Username / PAT，正常。
</details>

---

## 检查清单

发布前确认打勾：

- [ ] `python tools/check_repo.py` 通过
- [ ] `python tests/run_tests.py` 25 项全绿
- [ ] `git status --short` 里没有 `pet_state.json` / `pet.log` / `__pycache__`
- [ ] 仓库 Visibility = **Public**
- [ ] 创建仓库时 README / .gitignore / license 都选了 **Off / No**
- [ ] `git config user.name` / `user.email` 已设
- [ ] `git push` 成功
- [ ] 仓库 About 里填了 Description 和 Topics

---

祝发布顺利 🎉
