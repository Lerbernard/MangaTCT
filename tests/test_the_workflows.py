"""What GitHub runs when lee pushes.

Two workflows, and the same failure would sink either: a list that rots. A
workflow naming the tests it runs stops covering the file you add tomorrow; a
workflow naming a secret nobody set fails on the day you need it. Both are
checked here against the repository itself rather than against a memory of it.
"""
import re

import pytest

from where import PKG

WF = PKG / ".github" / "workflows"


@pytest.fixture(scope="module")
def site():
    return (WF / "site.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tests_wf():
    return (WF / "tests.yml").read_text(encoding="utf-8")


def test_both_workflows_are_there():
    assert (WF / "site.yml").exists()
    assert (WF / "tests.yml").exists()


# ------------------------------------------------------------------ the site

def test_the_site_is_rebuilt_rather_than_shipped_as_committed(site):
    """`index.html` is generated. Deploying the committed copy ships whatever
    was last built by hand, which on the day somebody forgets is a stale
    page — and a stale page looks exactly like a current one."""
    assert "python site/build.py" in site
    assert "channelId: live" in site


def test_the_deploy_goes_where_firebase_json_points(site):
    """A workflow that names a different project than `firebase.json` is a
    deploy to somewhere nobody is looking."""
    import json
    rc = json.loads((PKG / ".firebaserc").read_text(encoding="utf-8"))
    project = rc["projects"]["default"]
    assert f"projectId: {project}" in site
    fb = json.loads((PKG / "firebase.json").read_text(encoding="utf-8"))
    assert fb["hosting"]["public"] == "site"


def test_the_deploy_needs_a_secret_and_the_setup_note_says_which(site):
    """Firebase's own `init hosting:github` names the secret after the
    project; this workflow does not. Whichever way that is settled, the note
    has to say so, because it fails at the one moment nobody is watching."""
    m = re.search(r"firebaseServiceAccount: \$\{\{ secrets\.([A-Z_]+) \}\}",
                  site)
    assert m, "the deploy must read a service account from a secret"
    doc = (PKG / "docs" / "github-and-deploys.md").read_text(encoding="utf-8")
    assert m.group(1) in doc, "the setup note must name the secret it needs"


def test_two_deploys_cannot_race(site):
    """They land in either order, and the one that lands second is the one you
    see."""
    assert "concurrency:" in site
    assert "cancel-in-progress: true" in site


def test_a_broken_picture_cannot_reach_the_live_site():
    """The guard is `build.py`'s exit code, so the workflow needs nothing of
    its own — but something has to hold that it still exits non-zero."""
    src = (PKG / "site" / "build.py").read_text(encoding="utf-8")
    assert "raise SystemExit(1 if broken else 0)" in src


# ----------------------------------------------------------------- the tests

def test_the_test_workflow_names_no_tests(tests_wf):
    """The whole point. A list of test files in a YAML file is a list that
    rots — you add a file, and CI silently stops covering it."""
    body = tests_wf.split("jobs:", 1)[1]
    named = re.findall(r"tests/test_\w+\.py", body)
    assert not named, named


def test_it_runs_the_whole_suite_and_lets_the_browser_tests_skip(tests_wf):
    """`tests/browserpool.py` skips when Chromium is not there — it has since
    it was written, because a machine without one was always a case it had to
    survive. So CI installs everything EXCEPT Playwright and gets the
    non-browser tests for free, with the rest reported as skipped rather than
    quietly missing."""
    assert "python -m pytest tests" in tests_wf
    # Asked of what is INSTALLED, not of the file — the comment above the step
    # has to be able to say the word it is explaining.
    installed = " ".join(re.findall(r"pip install ([^\n]*(?:\n\s+[^\n-][^\n]*)*)",
                                    tests_wf))
    assert "playwright" not in installed.lower(), \
        "installing it would make CI fifteen minutes and need Chromium"
    assert "pytest" in installed and "numpy" in installed
    pool = (PKG / "tests" / "browserpool.py").read_text(encoding="utf-8")
    assert 'importorskip("playwright.sync_api")' in pool


def test_the_package_can_be_imported_where_ci_puts_it(tests_wf):
    """The repo root IS the package, so `import mangatl` needs its PARENT on
    the path. Checking out into a folder named `mangatl` with the workspace
    above it means this does not depend on what the repository is called."""
    assert "path: mangatl" in tests_wf
    assert "PYTHONPATH: ${{ github.workspace }}" in tests_wf
    assert "working-directory: mangatl" in tests_wf


def test_the_money_tests_run_too(tests_wf):
    """`tests/functions` is the arithmetic that decides what a pack is worth
    and what a refund gives back, and it needs nothing but node."""
    assert "npx vitest run tests/functions" in tests_wf
    # ...and `tests/rules` is NOT in CI, because it needs the emulator.
    assert "tests/rules" not in tests_wf.split("npx vitest", 1)[1][:200]


# --------------------------------------------------------- nothing secret ships

def test_nothing_that_ships_looks_like_a_key():
    """Run against the files git would actually carry. The repository is
    private, but "private" is a setting somebody can change in two clicks and
    a key in the history outlives the decision."""
    import subprocess
    ign = {"node_modules", "__pycache__", ".pytest_cache", ".firebase", "out",
           "models", "_to_delete", ".git", "fonts"}
    skip = (".pt", ".onnx", ".tgz", ".zip", ".png", ".jpg", ".jpeg", ".gif",
            ".ttf", ".ico", ".webp", ".b64")
    pats = [
        ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        ("an Anthropic key", re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}")),
        ("an OpenAI/OpenRouter key", re.compile(r"sk-(?:or-)?[A-Za-z0-9]{32,}")),
        ("a Stripe secret", re.compile(r"sk_(?:live|test)_[0-9A-Za-z]{20,}")),
        ("a Stripe webhook secret", re.compile(r"whsec_[0-9A-Za-z]{20,}")),
        ("a service account", re.compile(r'"type"\s*:\s*"service_account"')),
    ]
    bad = []
    for p in PKG.rglob("*"):
        if not p.is_file() or p.suffix in skip:
            continue
        if any(part in ign for part in p.relative_to(PKG).parts):
            continue
        if p.name == ".env" or p.name == "test_the_workflows.py":
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        for what, rx in pats:
            if rx.search(t):
                bad.append(f"{p.relative_to(PKG)}: {what}")
    assert not bad, bad


def test_the_firebase_web_config_is_allowed_to_be_there():
    """It looks like a key and is not one: it identifies the project and
    authorises nothing. What stops somebody using it is `firestore.rules` and
    the Cloud Functions, which are the only things that can move a balance.

    Written down because the next person to run a secret scanner over this
    will find it and have to decide, and this is that decision.
    """
    cfg = (PKG / "site" / "config.js").read_text(encoding="utf-8")
    assert "apiKey:" in cfg
    assert "NOT secrets" in cfg, \
        "the file has to say why it is allowed to hold that"
    assert "STRIPE_KEY" not in cfg.replace("STRIPE_KEY`", "")


def test_the_generated_page_is_not_carried_in_the_history():
    """Three megabytes of base64, rewritten on every build. `index.html` IS
    tracked — it is what Firebase serves and it is small."""
    ign = (PKG / ".gitignore").read_text(encoding="utf-8")
    assert "site/mangatct-site-standalone.html" in ign
    assert "\nsite/index.html" not in ign


# ------------------------------------------- and the suite writes where it may

def test_no_test_builds_a_project_outside_its_own_temp_directory():
    """`Project.__init__` calls `os.makedirs` on the path it is given. A test
    that hands it an absolute path writes there — and the one that did wore a
    name saying it would not: `/nonexistent-so-nothing-is-written`.

    A name is not a permission. Running as root it created that directory at
    the root of the filesystem, every run, for as long as it existed; running
    as anybody else — which is what CI is — it was a PermissionError and a red
    build. The two look nothing alike and are the same mistake.
    """
    import re
    bad = []
    for p in sorted((PKG / "tests").glob("test_*.py")):
        for n, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
            m = re.search(r"Project\(\s*[^,]+,\s*['\"](/[^'\"]*)", line)
            if m:
                bad.append(f"{p.name}:{n}: {m.group(1)}")
    assert not bad, bad


def test_the_suite_leaves_nothing_at_the_root_of_the_filesystem():
    """The other half, asked of the machine rather than of the source: a run
    that has just finished should not have added anything to `/`.

    Cheap, and it is the check that would have caught the one above on the
    machine it was passing on."""
    import os
    strays = [n for n in os.listdir("/")
              if "nonexistent" in n or "mangatl" in n.lower()]
    assert not strays, strays
