# -*- coding: utf-8 -*-
"""
tools/check_repo.py - pre-publish sanity check
===============================================
Run this before every `git push` to a public repository:

    python tools/check_repo.py

It verifies:
    * every tracked-looking file exists and is not accidentally empty
    * no runtime artefacts (pet_state.json / pet.log / __pycache__) would ship
    * no file exceeds GitHub's friendly size limits
    * no leftover PROXY / SECRET-looking strings in the sources
    * both READMEs link to screenshots that actually exist
    * LICENSE is present and non-trivial
    * the modules still compile
    * zh / en key parity holds

Exit code 0 = safe to publish, 1 = fix the listed problems first.
"""
import ast
import io
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

REQUIRED = [
    "README.md", "README.zh-CN.md", "CONTRIBUTING.md", "CONTRIBUTING.zh-CN.md",
    "LICENSE", ".gitignore",
    "minimax_pet.py", "i18n.py", "autostart.py", "pet_launcher.py",
    "assets/mascot.png", "assets/mascot_glow.png",
    "tests/run_tests.py", "docs/UPLOAD-GITHUB.md", "docs/UPLOAD-GITHUB.zh-CN.md",
]

# must NOT be committed
FORBIDDEN = [
    "pet_state.json", "pet.log", ".env", "id_rsa", "id_ed25519",
]

SUSPICIOUS = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")

SCAN_EXT = (".py", ".md", ".txt", ".bat", ".cmd", ".json", ".yml", ".yaml", ".cfg")


def rel(*p):
    return os.path.join(BASE, *p)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


errors, warnings = [], []


def check_required():
    for f in REQUIRED:
        p = rel(*f.split("/"))
        if not os.path.exists(p):
            errors.append("missing: %s" % f)
        elif os.path.getsize(p) == 0:
            errors.append("empty:   %s" % f)
    lic = rel("LICENSE")
    if os.path.exists(lic) and os.path.getsize(lic) < 300:
        errors.append("LICENSE looks truncated")


def _load_gitignore():
    """Read .gitignore into a list of (pattern, negated, dir_only)."""
    p = rel(".gitignore")
    if not os.path.exists(p):
        return []
    rules = []
    with io.open(p, "r", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            if neg:
                line = line[1:]
            dir_only = line.endswith("/")
            rules.append((line.rstrip("/"), neg, dir_only))
    return rules


def _ignored(rel_path, rules, is_dir=False):
    """A deliberately small gitignore matcher: enough for this repo's rules.

    Supports  leading '*'  ,  '*'  ,  'name/'  and exact paths.  Anything more
    exotic is not used by this project, and if it ever is, the tool errs on the
    side of *reporting* the file rather than silently hiding it.
    """
    import fnmatch
    parts = rel_path.replace("\\", "/").split("/")
    for pat, neg, dir_only in rules:
        if dir_only and not is_dir:
            continue
        hit = False
        if "/" in pat:
            hit = fnmatch.fnmatch(rel_path.replace("\\", "/"), pat)
            hit = hit or fnmatch.fnmatch("/".join(parts), pat.lstrip("/"))
        else:
            hit = any(fnmatch.fnmatch(part, pat) for part in parts)
        if hit:
            return not neg
    return False


def check_forbidden():
    rules = _load_gitignore()
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in
                   (".git", "__pycache__", ".venv", "venv", "node_modules")]
        for f in files:
            if f not in FORBIDDEN and not f.endswith((".pyc", ".pyo")):
                continue
            rel_p = os.path.relpath(os.path.join(root, f), BASE).replace("\\", "/")
            if ".git/" in rel_p:
                continue
            if _ignored(rel_p, rules):
                warnings.append("runtime artefact present but gitignored: %s" % rel_p)
                continue
            errors.append("would be committed: %s" % rel_p)


def check_sizes():
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".venv")]
        for f in files:
            p = os.path.join(root, f)
            n = os.path.getsize(p)
            rel_p = os.path.relpath(p, BASE)
            if n > 10 * 1024 * 1024:
                errors.append("too big (>10 MB): %s  %s" % (rel_p, human(n)))
            elif n > 1024 * 1024:
                warnings.append("large (>1 MB): %s  %s" % (rel_p, human(n)))


def check_secrets():
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".venv")]
        for f in files:
            if not f.endswith(SCAN_EXT):
                continue
            p = os.path.join(root, f)
            try:
                with io.open(p, "r", encoding="utf-8-sig", errors="ignore") as fh:
                    txt = fh.read()
            except OSError:
                continue
            for m in SUSPICIOUS.finditer(txt):
                errors.append("possible secret in %s: %s..."
                              % (os.path.relpath(p, BASE), m.group(0)[:12]))


def check_readme_images():
    for md in ("README.md", "README.zh-CN.md", "CONTRIBUTING.md"):
        p = rel(md)
        if not os.path.exists(p):
            continue
        with io.open(p, "r", encoding="utf-8-sig") as fh:
            txt = fh.read()
        for m in re.finditer(r'<img[^>]*src="([^"]+)"', txt):
            src = m.group(1)
            if src.startswith("http"):
                continue
            if not os.path.exists(rel(*src.split("/"))):
                errors.append("%s references a missing image: %s" % (md, src))


def check_syntax():
    for m in ("minimax_pet.py", "i18n.py", "autostart.py",
              "pet_launcher.py", "build_assets.py"):
        p = rel(m)
        if not os.path.exists(p):
            continue
        with io.open(p, "r", encoding="utf-8-sig") as fh:
            try:
                ast.parse(fh.read(), m)
            except SyntaxError as e:
                errors.append("%s: SyntaxError line %s: %s" % (m, e.lineno, e.msg))


def check_i18n():
    try:
        import i18n as _i
    except Exception as e:
        errors.append("cannot import i18n: %s" % e)
        return
    zh = set(_i.STRINGS.get("zh", {}))
    en = set(_i.STRINGS.get("en", {}))
    for k in sorted(en - zh):
        errors.append("i18n key in en but not zh: %s" % k)
    for k in sorted(zh - en):
        errors.append("i18n key in zh but not en: %s" % k)
    if not zh:
        errors.append("i18n zh table is empty")


def main():
    for fn in (check_required, check_forbidden, check_sizes, check_secrets,
               check_readme_images, check_syntax, check_i18n):
        try:
            fn()
        except Exception as e:                      # never crash the checker
            errors.append("%s raised %s: %s" % (fn.__name__, type(e).__name__, e))

    for w in warnings:
        print("[warn ] %s" % w)
    for e in errors:
        print("[ERROR] %s" % e)

    if errors:
        print("\n%d problem(s). Do NOT publish yet." % len(errors))
        return 1
    print("\nAll checks passed - safe to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
