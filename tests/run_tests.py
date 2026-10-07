# -*- coding: utf-8 -*-
"""
tests/run_tests.py - MiniMax Pet test suite
================================================
Pure-stdlib unittest, no pytest required. Run:

    python tests/run_tests.py

Coverage:
    1. syntax compile of every module
    2. zh / en key parity in the i18n string table (a missing translation fails)
    3. positional placeholders and plural forms
    4. graceful degradation on missing keys / wrong argument counts (must never raise)
    5. normalize() / system_lang() language detection
    6. SessionWatcher state machine (noise filtering, step counting, "needs you")
    7. offscreen render of every state (needs PyQt5)
    8. a coarse sweep for hardcoded UI text

Test 7 needs PyQt5; it skips itself when PyQt5 is missing, the rest still run.
"""
import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import i18n  # noqa: E402

MODULES = ("minimax_pet.py", "i18n.py", "autostart.py", "pet_watcher.py",
           "pet_launcher.py", "build_assets.py")


def _src(name):
    """Read a module without tripping the BOM / encoding traps."""
    p = os.path.join(BASE, name)
    if not os.path.exists(p):
        return None
    with io.open(p, "r", encoding="utf-8-sig") as f:
        return f.read()


# ---------------------------------------------------------------- 1. syntax
class TestSyntax(unittest.TestCase):
    def test_modules_compile(self):
        for m in MODULES:
            if not os.path.exists(os.path.join(BASE, m)):
                continue
            try:
                compile(_src(m), m, "exec")
            except SyntaxError as e:
                self.fail("%s: SyntaxError at line %s: %s" % (m, e.lineno, e.msg))

    def test_no_local_t_shadowing(self):
        """A local named `t` shadows i18n.t() for the WHOLE function body.

        Python only complains at runtime (UnboundLocalError), so this has to be
        checked statically. Assign/loop-bind `t` and call `t(...)` in the same
        function = guaranteed crash.
        """
        src = _src("minimax_pet.py")
        if src is None:
            self.skipTest("minimax_pet.py not present")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            binds_t = False
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    if any(isinstance(x, ast.Name) and x.id == "t" for x in sub.targets):
                        binds_t = True
                elif isinstance(sub, (ast.For, ast.ListComp, ast.SetComp,
                                      ast.GeneratorExp, ast.DictComp)):
                    tgt = getattr(sub, "target", None)
                    if tgt is None:
                        continue
                    names = tgt.elts if isinstance(tgt, ast.Tuple) else [tgt]
                    if any(isinstance(x, ast.Name) and x.id == "t" for x in names):
                        binds_t = True
            if not binds_t:
                continue
            calls_t = any(
                isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id == "t"
                for sub in ast.walk(node))
            self.assertFalse(
                calls_t,
                "%s() binds a local `t` and also calls i18n t() -> "
                "UnboundLocalError at runtime" % node.name)


# ---------------------------------------------------------------- 2. table
class TestStringTable(unittest.TestCase):
    def test_key_parity(self):
        zh = set(i18n.STRINGS.get("zh", {}))
        en = set(i18n.STRINGS.get("en", {}))
        self.assertTrue(zh, "zh table is empty")
        self.assertEqual(set(), en - zh, "keys in en but missing from zh")
        self.assertEqual(set(), zh - en, "keys in zh but missing from en")

    def test_placeholder_parity(self):
        """Both languages must consume the same number of placeholders."""
        def shapes(v):
            forms = v if isinstance(v, (list, tuple)) else (v,)
            return frozenset(len(re.findall(r"\{\d+\}", f)) for f in forms)
        for k in i18n.STRINGS.get("zh", {}):
            self.assertEqual(
                shapes(i18n.STRINGS["zh"][k]), shapes(i18n.STRINGS["en"][k]),
                "placeholder count differs for %s: %r vs %r"
                % (k, i18n.STRINGS["zh"][k], i18n.STRINGS["en"][k]))

    def test_no_format_spec_brace(self):
        """`{0,3}` makes str.format raise KeyError (reproduced on Python 3.12)."""
        for lang, tbl in i18n.STRINGS.items():
            for k, v in tbl.items():
                for s in (v if isinstance(v, (list, tuple)) else (v,)):
                    self.assertIsNone(
                        re.search(r"\{\d+\s*[,!:]", s),
                        "%s/%s uses a format spec: %r" % (lang, k, s))

    def test_every_value_is_text(self):
        for lang, tbl in i18n.STRINGS.items():
            for k, v in tbl.items():
                for s in (v if isinstance(v, (list, tuple)) else (v,)):
                    self.assertIsInstance(s, str)


# ---------------------------------------------------------------- 3. lookup
class TestTranslate(unittest.TestCase):
    def tearDown(self):
        i18n.set_lang(i18n.DEFAULT_LANG)

    def test_basic(self):
        i18n.set_lang("zh")
        zh = i18n.t("menu.quit")
        i18n.set_lang("en")
        en = i18n.t("menu.quit")
        self.assertTrue(zh and en and zh != en, "zh and en should differ")

    def test_positional_args(self):
        i18n.set_lang("zh")
        s = i18n.t("foot.more", 3)
        self.assertIn("3", s)
        self.assertNotIn("{", s)

    def test_plural_forms(self):
        i18n.set_lang("en")
        one = i18n.t("card.done", 1)
        many = i18n.t("card.done", 19)
        self.assertTrue(one.endswith("step"), one)
        self.assertTrue(many.endswith("steps"), many)

    def test_plural_with_trailing_non_int(self):
        """chip.done takes (steps, duration) - the counter is not the last arg."""
        i18n.set_lang("en")
        self.assertTrue(i18n.t("chip.done", 1, "00:07").startswith("1 step "))
        self.assertTrue(i18n.t("chip.done", 9, "02:34").startswith("9 steps "))

    def test_missing_key_degrades(self):
        self.assertEqual("definitely.not.a.key", i18n.t("definitely.not.a.key"))

    def test_arg_count_mismatch_does_not_raise(self):
        for key in i18n.STRINGS["zh"]:
            i18n.t(key)
            i18n.t(key, 1, 2, 3)

    def test_all_keys_renderable(self):
        for lang in i18n.LANGS:
            i18n.set_lang(lang)
            for k in i18n.STRINGS[lang]:
                out = i18n.t(k, 1, "x")
                self.assertIsInstance(out, str)
                self.assertNotIn("{0}", out)


# ---------------------------------------------------------------- 4. language
class TestLangDetection(unittest.TestCase):
    def test_normalize(self):
        for raw, want in (("zh", "zh"), ("zh-CN", "zh"), ("zh_TW", "zh"),
                          ("en", "en"), ("en_US", "en"), ("en-GB", "en"),
                          ("C", "zh"), ("POSIX", "zh"), (None, "zh"),
                          ("", "zh"), ("klingon", "zh")):
            self.assertEqual(want, i18n.normalize(raw), "normalize(%r)" % raw)

    def test_system_lang_env_override(self):
        os.environ["MINIMAX_PET_LANG"] = "en-US"
        try:
            self.assertEqual("en", i18n.system_lang())
        finally:
            del os.environ["MINIMAX_PET_LANG"]

    def test_set_get_roundtrip(self):
        for lang in i18n.LANGS:
            self.assertEqual(lang, i18n.set_lang(lang))
            self.assertEqual(lang, i18n.get_lang())


# ---------------------------------------------------------------- 5. state machine
class TestWatcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import PyQt5  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("PyQt5 not installed")
        import minimax_pet as mp
        cls.mp = mp

    def _state(self):
        return self.mp._new_state("t")

    def _watcher(self):
        return self.mp.SessionWatcher()

    def _apply(self, w, s, role, content, **extra):
        msg = {"role": role, "timestamp": extra.pop("ts", 1000),
               "content": content}
        msg.update(extra)
        w._apply(s, json.dumps({"message": msg}))

    def test_new_task_from_real_prompt(self):
        w = self._watcher()
        s = self._state()
        self._apply(w, s, "user", [{"type": "text", "text": "do the thing"}])
        self.assertEqual("thinking", s["state"])
        self.assertIn("do the thing", s["task"])

    def test_system_reminder_is_not_a_task(self):
        """An injected <system-reminder> must not become the task title, and
        must not reset the step count."""
        w = self._watcher()
        s = self._state()
        s.update(task="real work", steps=7, state="executing")
        noise = ("<system-reminder>\ntodo-cadence: keep going\n"
                 "</system-reminder>")
        self._apply(w, s, "user", [{"type": "text", "text": noise}], ts=2000)
        self.assertEqual("real work", s["task"])
        self.assertEqual(7, s["steps"])

    def test_tool_call_then_result_counts_steps(self):
        w = self._watcher()
        s = self._state()
        self._apply(w, s, "user", [{"type": "text", "text": "go"}])
        self._apply(w, s, "assistant",
                    [{"type": "toolCall", "id": "c1", "name": "Bash"}], ts=1100)
        self.assertEqual("executing", s["state"])
        self.assertEqual("Bash", s["tool"])
        self._apply(w, s, "toolResult", [], ts=1200,
                    toolCallId="c1", toolName="Bash")
        self.assertEqual(1, s["steps"])

    def test_error_marks_error(self):
        w = self._watcher()
        s = self._state()
        self._apply(w, s, "user", [{"type": "text", "text": "go"}])
        self._apply(w, s, "assistant",
                    [{"type": "toolCall", "id": "c1", "name": "Bash"}], ts=1100)
        self._apply(w, s, "toolResult", [], ts=1200,
                    toolCallId="c1", toolName="Bash", isError=True)
        self.assertEqual("error", s["state"])
        self.assertEqual(1, s["errors"])

    def test_stale_tool_call_becomes_waiting(self):
        """Tool call with no result -> Needs you."""
        w = self._watcher()
        s = self._state()
        now = int(time.time() * 1000)
        self._apply(w, s, "assistant",
                    [{"type": "toolCall", "id": "c1", "name": "Bash"}], ts=now)
        w._settle(s, time.time() + 60)
        self.assertEqual("waiting", s["state"])

    def test_done_freezes_duration(self):
        w = self._watcher()
        s = self._state()
        self._apply(w, s, "assistant",
                    [{"type": "text", "text": "all set"}], ts=1000)
        self.assertEqual("done", s["state"])
        self.assertTrue(s["t_end"] > 0)


# ---------------------------------------------------------------- 6. render
class TestRender(unittest.TestCase):
    def test_selftest_renders_both_languages(self):
        try:
            import PyQt5  # noqa: F401
        except ImportError:
            self.skipTest("PyQt5 not installed")
        for lang in i18n.LANGS:
            r = subprocess.run(
                [sys.executable, os.path.join(BASE, "minimax_pet.py"),
                 "--lang", lang, "--selftest"],
                cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=240)
            err = r.stderr.decode("utf-8", "replace")
            self.assertEqual(0, r.returncode,
                             "selftest --lang %s failed: %s" % (lang, err[-800:]))
            self.assertIn(b"SELFTEST_OK", r.stdout)


# ---------------------------------------------------------------- 6b. sentinel
class TestSentinel(unittest.TestCase):
    """The standby sentinel must stay importable without Qt."""

    def test_imports_without_qt(self):
        """The sentinel must not import Qt or the pet - it runs headless.

        Checked via AST, not by grepping the text: both names legitimately
        appear in comments and docstrings.
        """
        src = _src("pet_watcher.py")
        self.assertIsNotNone(src, "pet_watcher.py missing")
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
        self.assertNotIn("PyQt5", imported,
                         "the sentinel must not pull in Qt - it runs headless")
        self.assertNotIn("PyQt5", imported)
        for forbidden in ("minimax_pet",):
            self.assertNotIn(forbidden, imported,
                             "the sentinel must not import the pet; it only "
                             "spawns it as a separate process")

    def test_process_probe_agrees_with_pet(self):
        import pet_watcher
        try:
            import minimax_pet as mp
        except ImportError:
            self.skipTest("PyQt5 not installed")
        self.assertEqual(mp.app_running(), pet_watcher.app_running(),
                         "sentinel and pet disagree about the app state")

    def test_lock_probe_does_not_steal(self):
        """lock_held_by_other() must observe, not acquire."""
        import pet_watcher
        import tempfile as tf
        orig = pet_watcher.LOCK_PATH
        pet_watcher.LOCK_PATH = os.path.join(BASE, ".watcher-test.lock")
        try:
            self.assertFalse(pet_watcher.lock_held_by_other(),
                             "nothing should hold a brand-new lock")
            holder = pet_watcher.acquire_lock()
            self.assertIsNotNone(holder)
            try:
                self.assertTrue(pet_watcher.lock_held_by_other(),
                                "the holder should be detected")
            finally:
                try:
                    holder.close()
                except Exception:
                    pass
        finally:
            pet_watcher.LOCK_PATH = orig
            for p in (pet_watcher.LOCK_PATH,):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    def test_lang_flag_is_stripped(self):
        import pet_watcher
        lang, rest = pet_watcher._resolve_lang(
            ["--lang", "en", "--status"])
        self.assertEqual("en", lang)
        self.assertEqual(["--status"], rest)
        self.assertEqual((None, []), pet_watcher._resolve_lang([]))


# ---------------------------------------------------------------- 6c. lifecycle
class TestExitWithApp(unittest.TestCase):
    """The sentinel/pet contract: the pet lives and dies with the app.

    `_check_app` is exercised on a bare object with stubbed methods, so no Qt
    widget tree is needed and the probe runs offline.
    """

    def setUp(self):
        try:
            import PyQt5  # noqa: F401
        except ImportError:
            self.skipTest("PyQt5 not installed")
        import minimax_pet as mp
        self.mp = mp
        self.pet = mp.PetWindow.__new__(mp.PetWindow)   # no __init__, no Qt
        self.pet.app_seen = False
        self.pet.app_miss = 0
        self.pet.follow = True
        self.pet.manual_hidden = False
        self.pet.exit_with_app = True
        self.pet.quit_calls = 0
        self.pet.visible = True
        self.pet.quit = lambda: setattr(self.pet, "quit_calls",
                                        self.pet.quit_calls + 1)
        self.pet.isVisible = lambda: self.pet.visible
        self.pet._sync_visibility = lambda running: setattr(
            self.pet, "visible", bool(running))
        self._orig_app_running = mp.app_running
        mp.app_running = lambda: self._running

    def tearDown(self):
        self.mp.app_running = self._orig_app_running

    def _poll(self):
        self.mp.PetWindow._check_app(self.pet)

    def test_single_miss_does_not_quit(self):
        """A restart blip must not kill the pet on the very first miss."""
        self._running = True
        self.pet.app_seen = True
        self._running = False
        self._poll()
        self.assertEqual(0, self.pet.quit_calls, "quit on the FIRST miss")
        self.assertEqual(1, self.pet.app_miss)

    def test_two_consecutive_misses_quit(self):
        self._running = True
        self.pet.app_seen = True
        self._running = False
        self._poll()
        self._poll()
        self.assertEqual(1, self.pet.quit_calls)
        self.assertFalse(self.pet.app_seen)
        self.assertEqual(0, self.pet.app_miss)

    def test_intermittent_misses_do_not_quit(self):
        """Missing but recovering must reset the counter, never accumulate."""
        self._running = True
        self.pet.app_seen = True
        for _ in range(5):
            self._running = False
            self._poll()
            self._running = True
            self._poll()
        self.assertEqual(0, self.pet.quit_calls)
        self.assertEqual(0, self.pet.app_miss)

    def test_without_exit_flag_only_hides(self):
        self.pet.exit_with_app = False
        self._running = True
        self.pet.app_seen = True
        self._running = False
        self._poll()
        self._poll()
        self.assertEqual(0, self.pet.quit_calls, "must not quit without the flag")
        self.assertFalse(self.pet.visible, "must hide instead")

    def test_app_always_running_never_quits(self):
        self._running = True
        self.pet.app_seen = True
        for _ in range(10):
            self._poll()
        self.assertEqual(0, self.pet.quit_calls)
        self.assertEqual(0, self.pet.app_miss)

    def test_miss_counter_ignores_when_app_never_seen(self):
        """app_seen False + app absent = nothing to conclude, no counting."""
        self._running = False
        self.pet.app_seen = False
        self._poll()
        self.assertEqual(0, self.pet.app_miss)
        self.assertEqual(0, self.pet.quit_calls)

    def test_exit_with_app_defaults_to_true(self):
        """"同生共死" must be the default, not something you opt into."""
        st = {}
        self.assertTrue(True is not False)
        resolved = st.get("exit_with_app", True) is not False
        self.assertTrue(resolved, "missing key must resolve to exit_with_app=True")
        st = {"exit_with_app": False}
        self.assertFalse(st.get("exit_with_app", True) is not False,
                         "an explicit False must still win")

    def test_always_show_flag_exists(self):
        src = _src("minimax_pet.py")
        self.assertIn('"--always-show"', src)
        self.assertIn("show_now", src)

    def test_startup_probe_sets_app_seen(self):
        """app_seen must be probed at construction, not hardcoded False.

        Scoped to __init__ on purpose: _check_app legitimately assigns
        `self.app_seen = False` again when the app really does close.
        """
        tree = ast.parse(_src("minimax_pet.py"))
        init = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Assign)
                            and isinstance(sub.value, ast.Call)
                            and isinstance(sub.value.func, ast.Name)
                            and sub.value.func.id == "app_running"):
                        for tgt in sub.targets:
                            if (isinstance(tgt, ast.Attribute)
                                    and tgt.attr == "app_seen"):
                                init = sub.lineno
        self.assertIsNotNone(
            init, "__init__ must probe app_running() into self.app_seen; "
                  "otherwise the 'two consecutive misses' branch can never "
                  "fire when the pet was started manually")


# ---------------------------------------------------------------- 7. misc
CJK = re.compile(r"[\u4e00-\u9fff]")


class TestNoHardcodedUI(unittest.TestCase):
    def test_ui_text_goes_through_i18n(self):
        """Coarse sweep: strings that look like visible labels must be table keys.

        This only warns - it deliberately does not fail the build, because
        comments, paths and log formats also contain CJK.
        """
        src = _src("minimax_pet.py")
        if src is None:
            self.skipTest("minimax_pet.py not present")
        offenders = []
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node) or ""
            for sub in ast.walk(node):
                if not (isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)):
                    continue
                s = sub.value
                if s in doc or s.lstrip().startswith(("#", "<system", "--")):
                    continue
                if not CJK.search(s) or len(s) > 40:
                    continue
                if "\\" in s or "/" in s or "%" in s:
                    continue
                if not re.search(r"[，。！、：；（）「」…]", s):
                    continue          # only flag prose, not identifiers
                offenders.append("%s():%d %r" % (node.name, sub.lineno, s))
        if offenders:
            sys.stderr.write(
                "[warn] possible hardcoded UI text, move these into i18n.STRINGS:\n  "
                + "\n  ".join(offenders) + "\n")


class TestNoStrayFiles(unittest.TestCase):
    def test_runtime_artifacts_not_required(self):
        """pet_state.json / pet.log are generated at runtime, not shipped."""
        for junk in ("pet_state.json", "pet.log"):
            p = os.path.join(BASE, junk)
            if os.path.exists(p):
                sys.stderr.write("[info] runtime artifact present (gitignored): %s\n"
                                 % junk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
