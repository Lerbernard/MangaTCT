#!/usr/bin/env python3
"""Which tests cover what I just changed.

lee: *"can you format the test so that only part of teh software that chnaged
gets tested and then maybe at the end of the day you do a full test"*.

    python tools/affected.py            # list the test files a change touches
    python tools/affected.py --run      # ...and run them
    python tools/affected.py --run --against HEAD~3

The picking is deliberately generous. A test file is taken to cover a changed
source file if it names the file, imports its module, or mentions any function,
class or CSS selector whose definition line the change touched. When in doubt
it is IN — a run that includes a few tests it needn't have costs seconds, and
one that misses the test that would have caught the bug costs the afternoon.

**This is not a substitute for the full run.** It is what to do in the minute
after an edit. The whole suite still goes at the end of the day, and that is
the one that decides whether the day's work was right.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# what a change to one of these can break anywhere
WIDE = {"conftest.py", "browserpool.py"}


def changed(against):
    """Every file that differs from `against`, staged, unstaged or untracked."""
    out = set()
    for cmd in (["git", "diff", "--name-only", against],
                ["git", "diff", "--name-only", "--cached"],
                ["git", "ls-files", "--others", "--exclude-standard"]):
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        out |= {ln.strip() for ln in r.stdout.split("\n") if ln.strip()}
    return sorted(out)


def names(path, text, diff):
    """The words worth searching the tests for: the file, its module, and
    whatever is DEFINED on the lines that changed."""
    p = Path(path)
    got = {p.name}
    if p.suffix == ".py":
        got.add(p.stem)
    for ln in diff:
        for pat in (r"^\s*def\s+(\w+)", r"^\s*class\s+(\w+)",
                    r"^\s*function\s+(\w+)", r"^\s*(?:const|let|var)\s+(\w+)",
                    r"^\s*(\w+)\s*[:(]", r"^([.#][\w-]+)"):
            m = re.match(pat, ln)
            if m and len(m.group(1)) > 3:
                got.add(m.group(1))
    return {g for g in got if len(g) > 3}


def hunks(path, against):
    """The added and removed lines, without the +/-."""
    r = subprocess.run(["git", "diff", "-U0", against, "--", path],
                       cwd=ROOT, capture_output=True, text=True)
    if not r.stdout.strip():                      # untracked: all of it
        f = ROOT / path
        return f.read_text(encoding="utf-8", errors="replace").split("\n") \
            if f.exists() else []
    return [ln[1:] for ln in r.stdout.split("\n")
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]


def pick(against):
    files = changed(against)
    if not files:
        return [], []
    picked, why = set(), []
    tests = {f: f.read_text(encoding="utf-8", errors="replace")
             for f in TESTS.glob("**/test_*.py")}
    for path in files:
        if path.startswith("tests/"):
            f = ROOT / path
            if f.exists() and f.name in WIDE:
                return sorted(tests), [f"{path}: everything uses it"]
            if f.exists() and f.name.startswith("test_"):
                picked.add(f)
                why.append(f"{path}: itself")
            continue
        f = ROOT / path
        if not f.exists() or f.suffix not in (".py", ".js", ".css", ".html"):
            continue
        want = names(path, f.read_text(encoding="utf-8", errors="replace"),
                     hunks(path, against))
        hit = {t for t, src in tests.items() if any(w in src for w in want)}
        picked |= hit
        why.append(f"{path}: {len(hit)} test files "
                   f"({', '.join(sorted(w for w in want)[:6])})")
    return sorted(picked), why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--against", default="HEAD")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("-n", default="2", help="parallel workers")
    a = ap.parse_args()

    picked, why = pick(a.against)
    for line in why:
        print("  " + line, file=sys.stderr)
    if not picked:
        print("nothing changed", file=sys.stderr)
        return 0
    rel = [str(p.relative_to(ROOT)) for p in picked]
    print(f"{len(rel)} test files", file=sys.stderr)
    if not a.run:
        print("\n".join(rel))
        return 0
    return subprocess.run([sys.executable, "-m", "pytest", *rel, "-q",
                           "-p", "no:randomly", "-n", a.n], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
