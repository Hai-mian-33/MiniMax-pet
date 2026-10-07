# Contributing to MiniMax Pet

[English](CONTRIBUTING.md) · [简体中文](CONTRIBUTING.zh-CN.md)

Thanks for taking the time. This is a small, single-file Python project, so the
bar for a patch is low — but a few ground rules keep it healthy.

---

## Ground rules

1. **The pet is read-only.** It may never write into `~/.minimax/` or anywhere
   else owned by MiniMax Code. Its own state stays inside the project folder.
   If your change needs to persist something, put it in `pet_state.json`.
2. **No hardcoded user-facing strings.** Every visible word goes through
   `i18n.t()`. If you add a string, add it to *both* `zh` and `en` in
   [`i18n.py`](i18n.py). A missing key falls back to Chinese, which is fine in
   development but should not ship.
3. **Don't name a local variable `t`.** The module-level i18n translation
   function is `t()`, and a local assignment shadows it for the entire
   function body — you will get `UnboundLocalError` at runtime, not at import
   time. Use `tk`, `ctype`, `flat`, or just a better name.
4. **Position parameters only.** Use `{0} {1}`, never f-strings or named
   placeholders. `str.format` raises `KeyError` on `{0,3}` on Python 3.12.

---

## Dev setup

```bash
git clone https://github.com/Hai-mian-33/MiniMax-pet.git
cd MiniMax-pet
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
pip install PyQt5
```

## Run the tests

```bash
python tests/run_tests.py
```

The suite is plain `unittest` — no pytest required. It covers:

- syntax of every module
- `i18n` key parity between `zh` and `en` (a missing translation fails the build)
- plural forms and argument-count safety
- `normalize()` / `system_lang()` behaviour
- an offscreen render of every widget state

## Try your change without disturbing your running pet

```bash
python minimax_pet.py --demo              # synthetic task, no real sessions
python minimax_pet.py --selftest          # render PNGs, exit
python minimax_pet.py --selftest-live     # render against real sessions
```

The pet takes a `QLockFile` in the temp directory, so a second instance exits
cleanly instead of fighting over the tray icon.

---

## Adding a translation

This is the single most valuable contribution, and the easiest.

1. Fork and create a branch: `git checkout -b add-japanese`
2. In [`i18n.py`](i18n.py):
   - add the code to `LANGS = (...)`
   - add a `STRINGS["ja"]` block — copy `STRINGS["zh"]` and translate every value
   - teach `normalize()` your locale (e.g. `"ja"` / `ja-JP`)
3. Run `python tests/run_tests.py` — the parity check will tell you exactly
   which keys you missed.
4. Generate screenshots so the README can show them:
   ```bash
   python minimax_pet.py --lang ja --selftest
   ```
5. Open a PR.

The tray menu and the `--lang` flag both derive from `LANGS`, so there is
nothing else to wire up.

---

## Regenerating the mascot assets

`assets/` ships pre-generated. Only regenerate if you have MiniMax Code
installed and want to pick up a new official icon:

```bash
python build_assets.py
```

It reads the official `icon.icns`, extracts `mascot.png` pixel-for-pixel, and
writes the derived `mascot_glow.png` / `mascot_shadow.png` / `mascot_tray.png`.
Note that the artwork stays the property of its owner — do not rebrand it.

---

## Regenerating screenshots

```bash
python minimax_pet.py --lang zh --selftest
python minimax_pet.py --lang en --selftest
```

Both land in `docs/images/`, paired by language. Keep them in sync with UI
changes — a stale screenshot in a README is worse than none.

---

## Style

- Python 3.9-compatible syntax. No `match`, no `X | Y` type unions in runtime
  code.
- Comments explain *why*, not *what*. The codebase is Chinese-commented by
  convention — match the file you're editing.
- Keep `minimax_pet.py` self-contained. It is deliberately a single file so the
  project can be downloaded and run without packaging.

---

## Reporting bugs

Please include:

- your OS and Python version
- the full command line you used
- the tail of `pet.log` (it lives next to the script)
- a screenshot if it's visual

A `pet.log` excerpt usually identifies the problem immediately.

---

## Security notes

The HTTP bridge binds to `127.0.0.1` only and accepts unauthenticated JSON.
That is intentional for a local desktop pet, but it does mean anything running
on your machine can push a card. If you expose it, you are on your own — put a
proxy in front of it or pass `--no-server`.

---

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
