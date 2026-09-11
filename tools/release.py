"""Make a release: the app zip, the manifest, and the checks in between.

    python tools/release.py check-tag v1.0.0        the tag is the version
    python tools/release.py zip [--out dist]        dist/mangatct-app-1.0.0.zip
    python tools/release.py models                  every weight url answers and
                                                    its sum matches models.json
    python tools/release.py manifest --base URL --out dist
                                                    dist/manifest.json from what
                                                    is in dist/

The release workflow (`.github/workflows/release.yml`) runs these in that
order on a pushed `v*` tag; a person can run them by hand to see what a
release would contain. Standard library only, like everything the launcher
side touches.

WHAT THE APP ZIP IS. The `mangatl` package as the launcher's runtime imports
it - source, the static client, the bundled fonts, the hyphenation
dictionary - beside a `requirements.txt` (the runtime is checked against it)
and a `models.json` (the weights the launcher fetches). Nothing else: no
tests, no site, no weights, no deploy scripts. The zip is source and it is
GPL-3.0 source, so shipping it IS the "corresponding source" the license
asks for; LICENSE and NOTICE go in it.

WHAT MUST NOT BE IN IT, and is checked rather than hoped: the `.env` with
API keys, the Modal deploy scripts with the cleaner's token baked in, and
anything that looks like a key. `zip` refuses to write a zip that fails the
scan, which is the release refusing to happen.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # the mangatl package folder
sys.path.insert(0, os.path.dirname(ROOT))


def version() -> str:
    ns: dict = {}
    with open(os.path.join(ROOT, "version.py"), encoding="utf-8") as f:
        exec(compile(f.read(), "version.py", "exec"), ns)
    return ns["__version__"]


# ------------------------------------------------------------------ the zip

#: Top-level names that go in. Everything else at the root is left out, so a
#: new folder is out until somebody says it is in - the safe default for a
#: thing that is published.
INCLUDE_DIRS = ("detect", "static", "fonts", "paintread")
INCLUDE_FILES = ("LICENSE", "NOTICE", "hyph_en_US.dic")
#: Python files at the root that are NOT the app.
EXCLUDE_PY = {"_sb.py", "diag.py", "demo_offline.py"}
EXCLUDE_PY_SUFFIX = ("_clean_modal.py",)          # bake in the cleaner's token
EXCLUDE_ANYWHERE = ("__pycache__", ".pyc", ".pyo", ".DS_Store", "Thumbs.db")

LEAKS = [
    ("the cleaner's token", re.compile(r"CLEAN_TOKEN\s*=\s*[\"'][A-Za-z0-9]{16,}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an Anthropic key", re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}")),
    ("an OpenAI/OpenRouter key", re.compile(r"sk-(?:or-)?[A-Za-z0-9]{32,}")),
    ("a Google key", re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("a Stripe secret", re.compile(r"sk_(?:live|test)_[0-9A-Za-z]{20,}")),
    ("a service account", re.compile(r'"type"\s*:\s*"service_account"')),
]


def _skip(rel: str) -> bool:
    return any(part in rel for part in EXCLUDE_ANYWHERE) or rel.endswith(".env")


def files_for_zip() -> list[tuple[str, str]]:
    """(path on disk, path in zip) for everything that ships."""
    out = []
    for name in sorted(os.listdir(ROOT)):
        full = os.path.join(ROOT, name)
        if os.path.isfile(full):
            if name.endswith(".py") and name not in EXCLUDE_PY \
                    and not name.endswith(EXCLUDE_PY_SUFFIX):
                out.append((full, "mangatl/" + name))
            elif name in INCLUDE_FILES:
                out.append((full, "mangatl/" + name))
        elif name in INCLUDE_DIRS:
            for dp, dns, fns in os.walk(full):
                dns[:] = sorted(d for d in dns if not _skip(d))
                for fn in sorted(fns):
                    fp = os.path.join(dp, fn)
                    rel = os.path.relpath(fp, ROOT).replace(os.sep, "/")
                    if not _skip(rel):
                        out.append((fp, "mangatl/" + rel))
    # The launcher's own module rides along, as `mangatl/launcher/`: the
    # editor's Settings > Updates runs its check/download code from here,
    # which is always the current copy even when the exe on disk is old.
    out.append((os.path.join(ROOT, "launcher", "mangatct_launcher.py"),
                "mangatl/launcher/mangatct_launcher.py"))
    out.append((os.path.join(ROOT, "requirements.txt"), "requirements.txt"))
    out.append((os.path.join(HERE, "models.json"), "models.json"))
    return out


def launcher_version() -> str:
    """`LAUNCHER_VERSION` out of the launcher file, without importing it."""
    src = open(os.path.join(ROOT, "launcher", "mangatct_launcher.py"), encoding="utf-8").read()
    m = re.search(r'^LAUNCHER_VERSION\s*=\s*"([^"]+)"', src, re.M)
    return m.group(1) if m else "0.0.0"


def scan_for_leaks(pairs) -> list[str]:
    bad = []
    for fp, arc in pairs:
        if not arc.endswith((".py", ".js", ".json", ".txt", ".md", ".html", ".css")):
            continue
        try:
            text = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for what, rx in LEAKS:
            if rx.search(text):
                bad.append("%s holds %s" % (arc, what))
    return bad


def build_zip(out_dir: str) -> str:
    v = version()
    pairs = files_for_zip()
    leaks = scan_for_leaks(pairs)
    if leaks:
        for b in leaks:
            print("REFUSED:", b, file=sys.stderr)
        raise SystemExit(2)
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, "mangatct-app-%s.zip" % v)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for fp, arc in pairs:
            z.write(fp, arc)
    print("%s  %d files  %.1f MB" % (dest, len(pairs), os.path.getsize(dest) / 1e6))
    return dest


# --------------------------------------------------------------- the checks

def zip_version(zip_path: str) -> str:
    """The version written inside an app zip - read from ITS `version.py`, not
    this checkout's, so the runtime is staged against the zip it will run.

    This used to be a Python one-liner inside `build_runtime.ps1`, and the
    one-liner needed a literal double quote, and PowerShell escapes those
    with a backtick, not a backslash. The backslash ended the string early,
    the stray quote after it opened another, and every release run died on
    a ParserError before a single line of the script executed. Three runs,
    same nineteen seconds. A subcommand here has no quoting to get wrong.
    """
    with zipfile.ZipFile(zip_path) as z:
        text = z.read("mangatl/version.py").decode("utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not m:
        sys.exit("%s: no __version__ in mangatl/version.py" % zip_path)
    return m.group(1)


def check_tag(tag: str) -> None:
    v = version()
    if tag.lstrip("v") != v:
        print("tag %s is not version %s (version.py) - refusing" % (tag, v), file=sys.stderr)
        raise SystemExit(2)
    print("tag %s matches version.py" % tag)


def sha256_of(fp: str) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_models() -> None:
    """Every weight the launcher will fetch: does the url answer, and is the
    file it serves the one models.json promises? Downloads them, which is the
    only honest check - a HEAD says nothing about the bytes.

    SEVERITY FOLLOWS `tier`, and the difference matters on the day it bites.
    A `required` model that cannot be had is a release that would install and
    then refuse to find text, so it stops the release. A `recommended` one is
    a route the editor already knows how to gray out - the launcher logs it,
    says which, and starts anyway - so a publisher moving a file on Hugging
    Face must not block a release of THIS app, which has nothing to do with
    it. It is reported loudly and the exit code stays zero.
    """
    d = json.load(open(os.path.join(HERE, "models.json"), encoding="utf-8"))
    stop, warn = [], []
    for m in d["models"]:
        why = ""
        try:
            req = urllib.request.Request(m["url"], headers={"User-Agent": "MangaTCT-release"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if m.get("inside"):
                data = zipfile.ZipFile(io.BytesIO(data)).read(m["inside"])
            got = hashlib.sha256(data).hexdigest()
            if got != m["sha256"] or len(data) != m["size"]:
                why = ("serves sha %s size %d; models.json says %s %d"
                       % (got[:12], len(data), m["sha256"][:12], m["size"]))
        except Exception as e:
            why = str(e)
        if not why:
            print("ok       %-28s %6.1f MB  %s" % (m["name"], len(data) / 1e6, m["tier"]))
        elif m.get("tier") == "required":
            print("FAIL     %-28s %s" % (m["name"], why)); stop.append(m["name"])
        else:
            print("WARNING  %-28s %s" % (m["name"], why)); warn.append(m["name"])
    if warn:
        print("\n%d recommended weight(s) could not be verified: %s"
              % (len(warn), ", ".join(warn)))
        print("The app installs and runs without them; the routes that want "
              "them stay off until the url in tools/models.json is fixed.")
    if stop:
        print("\n%d REQUIRED weight(s) unavailable: %s - refusing the release."
              % (len(stop), ", ".join(stop)))
        raise SystemExit(2)


# ------------------------------------------------------------- the manifest

def build_manifest(base: str, out_dir: str, need_installer: bool = False) -> str:
    """What the launcher reads. `base` is where the release assets will be
    served from, with a trailing slash.

    `need_installer`: refuse to write a manifest when `MangaTCT-Setup-<v>.exe`
    is not beside the zip. Release #5 built everything, uploaded a 5 MB
    artifact and failed at publish with "Pattern 'dist/MangaTCT-Setup-*.exe'
    does not match any files": Inno Setup had written the installer under
    `launcher\dist\` (a relative `OutputDir` is relative to the SCRIPT), and
    this step, which ran after it and looked in the right folder, said
    nothing. The command line the workflow runs now asks for it."""
    v = version()
    app = os.path.join(out_dir, "mangatct-app-%s.zip" % v)
    if not os.path.isfile(app):
        print("no %s - run `zip` first" % app, file=sys.stderr)
        raise SystemExit(2)
    base = base if base.endswith("/") else base + "/"
    man = {
        "app": {
            "version": v,
            "url": base + os.path.basename(app),
            "sha256": sha256_of(app),
            "size": os.path.getsize(app),
            "notes": base.replace("/download/", "/tag/").rstrip("/"),
        },
        "models": json.load(open(os.path.join(HERE, "models.json"), encoding="utf-8"))["models"],
        # The oldest launcher that can run this app zip at all...
        "minimum_launcher": "1.0.0",
        # ...and the launcher this release's installer carries. An installed
        # copy running an older one is offered the installer in
        # Settings > Updates; below the minimum it is told it has to.
        "launcher": {"version": launcher_version()},
    }
    setup = os.path.join(out_dir, "MangaTCT-Setup-%s.exe" % v)
    if need_installer and not os.path.isfile(setup):
        print("no %s - the installer is not where the release expects it; "
              "installer.iss writes to ..\\dist relative to launcher\\, check "
              "OutputDir and the ISCC log" % setup, file=sys.stderr)
        raise SystemExit(2)
    if os.path.isfile(setup):
        man["installer"] = {"version": v, "url": base + os.path.basename(setup),
                            "sha256": sha256_of(setup), "size": os.path.getsize(setup)}
    dest = os.path.join(out_dir, "manifest.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    sums = os.path.join(out_dir, "SHA256SUMS")
    with open(sums, "w", encoding="utf-8") as f:
        for name in sorted(os.listdir(out_dir)):
            fp = os.path.join(out_dir, name)
            if os.path.isfile(fp) and name not in ("SHA256SUMS",):
                f.write("%s  %s\n" % (sha256_of(fp), name))
    print(dest)
    return dest


# ---------------------------------------------------------- the exe's label

def write_version_info(dest: str) -> str:
    """PyInstaller's version resource, so the exe's Properties dialog and
    Windows' own dialogs say MangaTCT 1.0.0 rather than nothing."""
    v = version()
    nums = ", ".join((v.split(".") + ["0"])[:4])
    text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'LMB Technology'),
      StringStruct('FileDescription', 'MangaTCT'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'MangaTCT'),
      StringStruct('LegalCopyright', 'GPL-3.0 - see LICENSE'),
      StringStruct('OriginalFilename', 'MangaTCT.exe'),
      StringStruct('ProductName', 'MangaTCT'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    print(dest)
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="release.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check-tag"); s.add_argument("tag")
    s = sub.add_parser("zip"); s.add_argument("--out", default="dist")
    sub.add_parser("models")
    s = sub.add_parser("manifest"); s.add_argument("--base", required=True); s.add_argument("--out", default="dist")
    # From the command line the installer is REQUIRED unless said otherwise:
    # the command line is what the release workflow runs, and a release with
    # no installer in it is the thing that must not go quietly.
    s.add_argument("--no-installer", action="store_true",
                   help="write a manifest with no installer entry (not a release)")
    sub.add_parser("version")
    s = sub.add_parser("zip-version"); s.add_argument("zip")
    s = sub.add_parser("version-info"); s.add_argument("--out", default=os.path.join(ROOT, "launcher", "version_info.txt"))
    a = ap.parse_args(argv)
    if a.cmd == "check-tag":
        check_tag(a.tag)
    elif a.cmd == "zip":
        build_zip(a.out)
    elif a.cmd == "models":
        check_models()
    elif a.cmd == "manifest":
        build_manifest(a.base, a.out, need_installer=not a.no_installer)
    elif a.cmd == "version":
        print(version())
    elif a.cmd == "zip-version":
        print(zip_version(a.zip))
    elif a.cmd == "version-info":
        write_version_info(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
