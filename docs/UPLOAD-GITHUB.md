# Uploading to a public GitHub repository

> Publish `C:\Users\23154\Desktop\MiniMax-pet` as a **public** GitHub repository.
> Every command below is meant for **Git Bash**.
>
> 中文版完整指南见 [UPLOAD-GITHUB.zh-CN.md](UPLOAD-GITHUB.zh-CN.md)。

---

## Contents

- [Step 0 — Pre-publish checks](#step-0--pre-publish-checks)
- [Step 1 — Create the repository (what to put in the form)](#step-1--create-the-repository-what-to-put-in-the-form)
- [Step 2 — Configure your Git identity](#step-2--configure-your-git-identity)
- [Step 3 — Initialise the local repo](#step-3--initialise-the-local-repo)
- [Step 4 — Commit](#step-4--commit)
- [Step 5 — Link the remote and push](#step-5--link-the-remote-and-push)
- [Step 6 — Finish the repository settings](#step-6--finish-the-repository-settings)
- [Authentication: PAT vs SSH](#authentication-pat-vs-ssh)
- [FAQ](#faq)

---

## Step 0 — Pre-publish checks

```bash
cd /c/Users/23154/Desktop/MiniMax-pet

python tools/check_repo.py     # required files / sizes / secrets / README image links / syntax / i18n parity
python tests/run_tests.py      # 25 tests: syntax, key parity, plurals, state machine, offscreen render
```

Do not proceed until both pass.

---

## Step 1 — Create the repository (what to put in the form)

Open <https://github.com/new>.

### ① Owner and repository name

```
Owner:      Hai-mian-33
Repository: MiniMax-pet
```

### ② Description (350 characters max)

Copy this line:

```
Bilingual desktop pet for MiniMax Code — live task cards, permission nudges and zh/en UI. 一个实时显示 MiniMax Code 任务进度的中英双语桌宠。
```

### ③ Configuration

| Field | Choose | Why |
|---|---|---|
| **Choose visibility** | **Public** | You asked for a public repository |
| **Add README** | **Off** | A README already exists locally; turning this on creates a conflict |
| **Add .gitignore** | **No .gitignore** | Same — a commented Chinese `.gitignore` is already in the repo |
| **Add license** | **No license** | Same — an MIT `LICENSE` is already present |
| **Jumpstart with Copilot** | **leave empty** | Leave the Prompt box completely blank |

> **Rule of thumb:** keep README / .gitignore / license on *Off / No*.
> Everything is already prepared locally, and GitHub's generated versions will
> collide with yours and get the push rejected.

### ④ Everything else: defaults

The `Settings` checkboxes (Issues, Projects, Wiki, Sponsors, Discussions) are
fine at their defaults. Hit the green **Create repository** button once you
have confirmed **Visibility = Public**.

Do **not** click the big green button under "uploading an existing file" — go
straight to Step 2 and push from the command line instead.

---

## Step 2 — Configure your Git identity

Run once in Git Bash:

```bash
git config --global user.name  "Sun Haiming"
git config --global user.email "haiming.sun33@gmail.com"
```

Verify:

```bash
git config --global --list | grep user
```

> To scope a different identity to just this repository:

```bash
cd /c/Users/23154/Desktop/MiniMax-pet
git config user.name  "Sun Haiming"
git config user.email "your-github-verified-email"
```

---

## Step 3 — Initialise the local repo

```bash
cd /c/Users/23154/Desktop/MiniMax-pet
git status
```

If it reports **not a git repository**:

```bash
git init -b main
```

If it is already a repository:

```bash
git branch -M main
```

Confirm `.gitignore` is working — these must **not** appear:

```bash
git status --short
```

`pet_state.json`, `pet.log` and `__pycache__` should be absent.

---

## Step 4 — Commit

```bash
cd /c/Users/23154/Desktop/MiniMax-pet

git add -A
git status --short          # read this before committing
```

Then:

```bash
git commit -m "MiniMax Pet v1.0: bilingual (zh/en) task-progress desktop pet for MiniMax Code

- Read-only tailing of ~/.minimax/v2/sessions/**/messages.jsonl
- Six live states: idle / thinking / running / needs-you / done / failed
- Full zh + en UI with runtime switching from the tray menu
- Multi-session task cards; click to jump into the right session
- Local HTTP event bridge on 127.0.0.1:8766
- Self-testing offscreen renderer that generates docs/images/*-zh|en.png"
```

---

## Step 5 — Link the remote and push

```bash
cd /c/Users/23154/Desktop/MiniMax-pet

git remote add origin https://github.com/Hai-mian-33/MiniMax-pet.git
git remote -v
git push -u origin main
```

You will be prompted:

```
Username: Hai-mian-33
Password: <paste your PAT here — NOT your account password>
```

> ⚠️ The password prompt wants a **Personal Access Token**. GitHub removed
> password authentication for git operations in 2021.

---

## Authentication: PAT vs SSH

### Option A — Personal Access Token (recommended)

1. Go to <https://github.com/settings/tokens?type=classic>
2. **Generate new token (classic)**
3. **Note**: `MiniMax-pet upload`
   **Expiration**: 90 days
   **Scopes**: check `repo` (or `public_repo`)
4. **Generate token**, then **copy it immediately** — it is shown exactly once
5. Paste it at the `Password:` prompt
6. If Git Credential Manager pops up, paste it there and tick "Save"

Store it once so you are never asked again:

```bash
git config --global credential.helper manager
```

### Option B — SSH (set up once, then passwordless)

```bash
ls -al ~/.ssh/id_ed25519.pub || ls -al ~/.ssh/id_rsa.pub   # have a key?
ssh-keygen -t ed25519 -C "haiming.sun33@gmail.com"          # or make one
cat ~/.ssh/id_ed25519.pub                                    # copy the line
```

Paste it into <https://github.com/settings/keys> → **New SSH key** → **Add SSH key**.

```bash
ssh -T git@github.com
git remote set-url origin git@github.com:Hai-mian-33/MiniMax-pet.git
git push -u origin main
```

---

## Step 6 — Finish the repository settings

### About sidebar

| Field | Value |
|---|---|
| Description | Same as Step 1 |
| Website | leave blank, or your homepage |
| Topics | see below |

**Recommended topics (20 max — these genuinely help discovery):**

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

---

## FAQ

<details>
<summary><b>Q1. <code>remote: Permission to … denied</code></summary>

Almost always an auth problem:

1. Did you paste a PAT, or your account password? (PAT required)
2. Does the PAT have the `repo` scope?
3. Has it expired?
4. Is the repo name right? `Hai-mian-33/MiniMax-pet` — hyphen, not underscore.
</details>

<details>
<summary><b>Q2. <code>Updates were rejected</code></summary>

The remote already has content (usually because "Add README" was left on).

```bash
git pull origin main --allow-unrelated-histories
# resolve any conflicts, then
git push -u origin main
```

Or, if the remote is just an empty scaffold and you want to replace it:

```bash
git push -u origin main --force
```

Safe for a first publish. Prefer `--force-with-lease` afterwards.
</details>

<details>
<summary><b>Q3. <code>fatal: not a git repository</code></summary>

```bash
cd /c/Users/23154/Desktop/MiniMax-pet
git init -b main
```
</details>

<details>
<summary><b>Q4. Mojibake in Git Bash</summary>

```bash
export LANG=zh_CN.UTF-8
export LC_ALL=zh_CN.UTF-8
git config --global i18n.commitencoding utf-8
git config --global i18n.logoutputencoding utf-8
```

Every filename in this repo is pure ASCII, so this should not actually bite.
</details>

<details>
<summary><b>Q5. <code>warning: LF will be replaced by CRLF</code></summary>

Normal on Windows. To silence it, add a `.gitattributes` at the repo root:

```
* text=auto eol=lf
*.bat text eol=crlf
*.png binary
```

Keep CRLF for `.bat` or the Windows wrappers will break.
</details>

<details>
<summary><b>Q6. Does the source leak anything private?</summary>

`tools/check_repo.py` scans for common credential formats. In addition:

- `pet_state.json` (window position) and `pet.log` are gitignored
- no session content is ever written into the project directory — the pet only reads
</details>

<details>
<summary><b>Q7. Updating later</summary>

```bash
cd /c/Users/23154/Desktop/MiniMax-pet
python tools/check_repo.py && python tests/run_tests.py
git add -A
git commit -m "what changed"
git push
```
</details>

<details>
<summary><b>Q8. Cutting a release</summary>

```bash
git tag -a v1.0.0 -m "MiniMax Pet v1.0.0"
git push origin v1.0.0
```

Then **Releases → Draft a new release** on the repo page.
</details>

<details>
<summary><b>Q9. README images not rendering</summary>

```bash
ls docs/images/
python tools/gen_screenshots.py     # if empty
```
</details>

<details>
<summary><b>Q10. Everything in one go</summary>

```bash
cd /c/Users/23154/Desktop/MiniMax-pet && \
python tools/check_repo.py && \
python tests/run_tests.py && \
{ git init -b main 2>/dev/null || true; } && \
git branch -M main && \
git add -A && \
git commit -m "MiniMax Pet v1.0: bilingual (zh/en) task-progress desktop pet for MiniMax Code" && \
{ git remote remove origin 2>/dev/null || true; } && \
git remote add origin https://github.com/Hai-mian-33/MiniMax-pet.git && \
git push -u origin main
```
</details>

---

## Checklist

- [ ] `python tools/check_repo.py` passes
- [ ] `python tests/run_tests.py` — 25/25
- [ ] `git status --short` shows no `pet_state.json` / `pet.log` / `__pycache__`
- [ ] Repository visibility is **Public**
- [ ] README / .gitignore / license all left at **Off / No** when creating the repo
- [ ] `git config user.name` / `user.email` are set
- [ ] `git push` succeeded
- [ ] Description and Topics filled in on the repo page
