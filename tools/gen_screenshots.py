# -*- coding: utf-8 -*-
"""
tools/gen_screenshots.py - regenerate the bilingual screenshot set
===============================================================
Usage / 用法:

    python tools/gen_screenshots.py            # both languages
    python tools/gen_screenshots.py --lang en  # one language

Every screenshot lands in docs/images/ with a -zh / -en suffix so the two
READMEs can show the same UI in both languages side by side.

This is a thin wrapper around `minimax_pet.py --selftest`; the renderer lives
in the main program so the images can never drift from the widgets.
"""
import argparse
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PET = os.path.join(BASE, "minimax_pet.py")
OUT = os.path.join(BASE, "docs", "images")


def render(lang):
    print("[%s] rendering ..." % lang)
    r = subprocess.run(
        [sys.executable, PET, "--lang", lang, "--selftest"],
        cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace"))
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description="Generate bilingual screenshots")
    ap.add_argument("--lang", choices=("zh", "en", "both"), default="both")
    a = ap.parse_args()
    langs = ("zh", "en") if a.lang == "both" else (a.lang,)

    os.makedirs(OUT, exist_ok=True)
    ok = all(render(l) for l in langs)
    if not ok:
        return 1

    files = sorted(f for f in os.listdir(OUT) if f.endswith(".png"))
    print("\n%d file(s) in %s" % (len(files), OUT))
    for f in files:
        print("  docs/images/%s" % f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
