"""A release is a tag, and what the tag makes is checked before it ships.

`tools/release.py` builds the app zip and the manifest; `.github/workflows/
release.yml` runs it on a `v*` tag and publishes to the public releases
repository the launcher reads. These tests hold the zip to what it must and
must not contain, and the workflow to the order that keeps an installed
copy safe: files up first, manifest last.
"""
import io
import json
import os
import re
import subprocess
import sys
import zipfile

import pytest

from where import PKG

sys.path.insert(0, str(PKG / "tools"))
import release as R  # noqa: E402


def test_the_tag_must_be_the_version(capsys):
    R.check_tag("v" + R.version())
    with pytest.raises(SystemExit):
        R.check_tag("v9.9.9")
    assert "refusing" in capsys.readouterr().err


def test_the_zip_is_the_package_and_nothing_private(tmp_path):
    dest = R.build_zip(str(tmp_path))
    assert dest.endswith("mangatct-app-%s.zip" % R.version())
    with zipfile.ZipFile(dest) as z:
        names = z.namelist()
    top = {n.split("/")[0] for n in names}
    assert top == {"mangatl", "requirements.txt", "models.json"}
    must = ["mangatl/editor.py", "mangatl/version.py", "mangatl/__init__.py",
            "mangatl/static/editor.html", "mangatl/static/js/vendor/prosemirror.js",
            "mangatl/detect/webtoon.py", "mangatl/paintread/trba/LICENSE",
            "mangatl/hyph_en_US.dic", "mangatl/LICENSE", "mangatl/NOTICE",
            "mangatl/fonts/LICENSES.md"]
    for m in must:
        assert m in names, m
    never = re.compile(r"(_clean_modal\.py$|/\.env$|^mangatl/tests/|^mangatl/site/|"
                       r"^mangatl/docs/|^mangatl/tools/|^mangatl/launcher/|"
                       r"\.(onnx|pt|pth|ckpt|dat)$|__pycache__|^mangatl/_sb\.py$|"
                       r"node_modules|^mangatl/firebase)")
    bad = [n for n in names if never.search(n)]
    assert not bad, bad
    # Anime Ace and Wild Words may not be bundled (fonts/LICENSES.md)
    fonts = [n.lower() for n in names if n.startswith("mangatl/fonts/")]
    assert not any("anime" in f or "wild" in f for f in fonts)


def test_the_zip_refuses_to_carry_a_key(tmp_path, monkeypatch):
    leaky = tmp_path / "leaky.py"
    leaky.write_text('CLEAN_TOKEN = "yq3tdiuwdgugqewyhduygwqdgduggeqywygyw"\n')
    pairs = [(str(leaky), "mangatl/leaky.py")]
    assert R.scan_for_leaks(pairs) == ["mangatl/leaky.py holds the cleaner's token"]
    leaky.write_text('key = "sk-ant-api03-' + "a" * 40 + '"\n')
    assert "Anthropic" in R.scan_for_leaks(pairs)[0]
    leaky.write_text("CLEAN_TOKEN = settings.get('clean_token')\n")
    assert R.scan_for_leaks(pairs) == [], "reading the setting is not baking the value"
    monkeypatch.setattr(R, "files_for_zip", lambda: [(str(leaky), "mangatl/x.py")])
    leaky.write_text('CLEAN_TOKEN = "yq3tdiuwdgugqewyhduygwqdgduggeqywygyw"\n')
    with pytest.raises(SystemExit):
        R.build_zip(str(tmp_path / "out"))
    assert not os.path.exists(tmp_path / "out" / ("mangatct-app-%s.zip" % R.version()))


def test_what_ships_actually_imports_as_a_package(tmp_path):
    """Unpack the zip somewhere with nothing else on the path and import the
    editor from it - the launcher's runtime does exactly this."""
    dest = R.build_zip(str(tmp_path))
    where = tmp_path / "unpacked"
    with zipfile.ZipFile(dest) as z:
        z.extractall(where)
    r = subprocess.run([sys.executable, "-c",
                        "import mangatl.editor, mangatl.version, mangatl.pickdir; "
                        "print(mangatl.version.__version__)"],
                       cwd=str(where), capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(where), "PYTHONNOUSERSITE": "1"},
                       timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip() == R.version()


def test_the_manifest_names_the_zip_by_sum_and_carries_the_models(tmp_path):
    R.build_zip(str(tmp_path))
    R.build_manifest("https://github.com/x/MangaTCT/releases/download/v1.0.0/", str(tmp_path))
    man = json.load(open(tmp_path / "manifest.json"))
    zp = tmp_path / ("mangatct-app-%s.zip" % R.version())
    assert man["app"]["version"] == R.version()
    assert man["app"]["url"].endswith("/v1.0.0/" + zp.name)
    assert man["app"]["sha256"] == R.sha256_of(str(zp))
    assert man["app"]["size"] == zp.stat().st_size
    assert man["app"]["notes"] == "https://github.com/x/MangaTCT/releases/tag/v1.0.0"
    assert man["models"] == json.load(open(PKG / "tools" / "models.json"))["models"]
    assert "installer" not in man, "none built here"
    sums = (tmp_path / "SHA256SUMS").read_text()
    assert zp.name in sums and "manifest.json" in sums
    # ...and the launcher accepts what this wrote
    sys.path.insert(0, str(PKG / "launcher"))
    import mangatct_launcher as L
    assert L.is_version(man["app"]["version"])


def test_the_exe_carries_the_version_in_its_properties(tmp_path):
    fp = R.write_version_info(str(tmp_path / "vi.txt"))
    text = open(fp).read()
    assert "FileVersion', '%s'" % R.version() in text
    nums = ", ".join((R.version().split(".") + ["0"])[:4])
    assert "filevers=(%s)" % nums in text
    assert "MangaTCT" in text


# ------------------------------------------------------------- the workflow

@pytest.fixture
def wf():
    return (PKG / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def test_it_runs_on_a_version_tag_and_checks_it_first(wf):
    assert "tags: ['v*']" in wf
    assert "check-tag" in wf
    assert wf.index("check-tag") < wf.index("release.py zip")


def test_the_windows_side_is_built_on_windows(wf):
    assert "runs-on: windows-latest" in wf
    for step in ("build_runtime.ps1", "pyinstaller", "installer.iss", "release.py manifest"):
        assert step in wf, step
    assert "MangaTCT.exe --version" in wf, "the exe is started once before it ships"


def test_it_publishes_here_with_no_second_repo_and_no_second_token(wf):
    """lee: *"we alredy have a github repo, we dont need a newone"*. So the
    Release goes on this repository with the token every run already has,
    and there is nothing to create or rotate by hand."""
    assert "RELEASES_REPO" not in wf and "RELEASES_TOKEN" not in wf
    assert "repository: ${{ env" not in wf, "no cross-repo Release"
    assert "contents: write" in wf, "this run writes the Release and the manifest"
    assert "github.repository" in wf, "the manifest's base url is this repo"


def test_the_files_go_up_before_the_manifest_points_at_them(wf):
    assert wf.index("action-gh-release") < wf.index("cp ../dist/manifest.json"), \
        "a manifest that points at files not yet uploaded is a broken update for everyone"
    assert "fail_on_unmatched_files: true" in wf
    assert "[skip ci]" in wf, "a one-line json commit does not need the suite"


def test_the_launcher_reads_where_the_workflow_writes(wf):
    sys.path.insert(0, str(PKG / "launcher"))
    import mangatct_launcher as L
    assert "/Lerbernard/MangaTCT/" in L.MANIFEST_URL
    assert L.MANIFEST_URL.endswith("/main/manifest.json")
    assert L.MANIFEST_URL.startswith("https://raw.githubusercontent.com/")
    # ...which is exactly the branch and filename the workflow commits to
    assert "ref: main" in wf and "manifest.json" in wf


def test_the_installer_installs_per_user_and_leaves_the_persons_things(tmp_path):
    iss = (PKG / "launcher" / "installer.iss").read_text(encoding="utf-8")
    assert "DefaultDirName={localappdata}\\MangaTCT" in iss
    assert "PrivilegesRequired=lowest" in iss
    assert "state.json" in iss and "runtime\\*" in iss and "app\\*" in iss
    assert "models" not in iss.split("[Files]")[1].split("[Dirs]")[0], \
        "the weights are not redistributed - NOTICE"
    assert ".mangatl" not in iss.split("[UninstallDelete]")[1]
    assert "MinVersion=10.0" in iss


def test_a_recommended_weight_stops_a_start_from_nothing_and_a_release_from_nothing():
    """Severity follows `tier`. A publisher moving a file on Hugging Face is
    not a reason to hold a version of THIS app: the editor already grays out
    a route whose weights are absent, so the release goes out and says which
    one to fix. Only the detector every route cleans with is `required`."""
    src = (PKG / "tools" / "release.py").read_text(encoding="utf-8")
    body = src[src.index("def check_models("):src.index("\n# ---", src.index("def check_models("))]
    assert 'm.get("tier") == "required"' in body
    assert "WARNING" in body and "refusing the release" in body
    d = json.loads((PKG / "tools" / "models.json").read_text(encoding="utf-8"))
    assert [m["name"] for m in d["models"] if m["tier"] == "required"] \
        == ["comictextdetector.pt.onnx"]
    # ...and a url nobody could fetch from here says so in the data
    unverified = [m["name"] for m in d["models"] if not m.get("verified")]
    assert all("huggingface.co" in m["url"]
               for m in d["models"] if m["name"] in unverified)
    assert all(m.get("tier") == "recommended"
               for m in d["models"] if m["name"] in unverified), \
        "nothing required may rest on a url that has never been fetched"


def test_the_installer_lands_where_the_release_looks_for_it(tmp_path):
    """Release #5: the Windows job went green, the artifact was 5 MB, and
    publish failed with "Pattern 'dist/MangaTCT-Setup-*.exe' does not match
    any files". Inno Setup's `OutputDir` is relative to the SCRIPT, so
    `OutputDir=dist` wrote to `launcher\\dist` while everything else read
    `dist`. Two things now hold: the script says `..\\dist`, and the manifest
    step - the last one that runs on the installer's folder - refuses to write
    a release manifest when the installer is not in it."""
    iss = (PKG / "launcher" / "installer.iss").read_text(encoding="utf-8")
    m = re.search(r"^OutputDir=(.+)$", iss, re.M)
    assert m and m.group(1).strip() == "..\\dist", \
        "relative to launcher\\, so ..\\dist is the repository's dist"
    wf = (PKG / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "mangatl/dist/MangaTCT-Setup-*.exe" in wf, \
        "the upload pattern is the folder the .iss now writes to"
    # the command line the workflow runs refuses without the installer...
    R.build_zip(str(tmp_path))
    r = subprocess.run([sys.executable, str(PKG / "tools" / "release.py"), "manifest",
                        "--out", str(tmp_path), "--base", "https://x/v1.0.0/"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "MangaTCT-Setup-" in r.stderr, r.stderr
    assert not (tmp_path / "manifest.json").exists()
    # ...and writes the installer's entry once it is there
    (tmp_path / ("MangaTCT-Setup-%s.exe" % R.version())).write_bytes(b"MZ" + b"\0" * 100)
    r = subprocess.run([sys.executable, str(PKG / "tools" / "release.py"), "manifest",
                        "--out", str(tmp_path), "--base", "https://x/v1.0.0/"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["installer"]["url"] == "https://x/v1.0.0/MangaTCT-Setup-%s.exe" % R.version()
    assert man["installer"]["size"] == 102


def test_the_runtime_script_proves_the_import_before_it_is_done():
    ps = (PKG / "launcher" / "build_runtime.ps1").read_text(encoding="utf-8")
    assert "import mangatl.editor" in ps
    assert "import sys, tkinter" in ps, "the folder picker needs tk"
    assert "tkinter.Tcl().eval" in ps, \
        "an import proves the .pyd loads; a Tcl interpreter proves tcl\\ was found"
    assert "requirements_sha256" in ps, "so the first start does not pip for nothing"


def test_the_runtime_is_a_python_that_has_tkinter_pinned_by_hash():
    """Release #4: the parse error fixed, the script ran - and the NuGet
    `python` package it fetched has no tkinter, so the proof at line 43
    threw. The runtime now comes from python-build-standalone, whose Windows
    `install_only` tarballs carry `DLLs\\_tkinter.pyd` and `tcl\\` (listed
    from the 3.12.7+20241016 asset itself). It is pinned three ways, and a
    download whose sha256 is not the pinned one is refused."""
    ps = (PKG / "launcher" / "build_runtime.ps1").read_text(encoding="utf-8")
    assert "nuget install" not in ps, "the header may say why not; the script may not run it"
    assert "astral-sh/python-build-standalone/releases/download" in ps
    assert "install_only_stripped.tar.gz" in ps
    m = re.search(r'\$PythonSha256\s*=\s*"([0-9a-f]{64})"', ps)
    assert m, "the sha256 is pinned in the script, not looked up at build time"
    assert "Get-FileHash" in ps and "-ne $PythonSha256" in ps
    assert "Include_tcltk" not in ps, "no installer is run - a tarball is unpacked"


def test_the_runtime_script_parses_as_powershell():
    """Three releases failed to parse. Two traps are held by regex - a
    backslash is not an escape, and `"$name: ..."` reads `name:` as a drive
    (`$env:` is the one that is meant) - and where `pwsh` is on the path,
    which it is on the Tests workflow's runner, the real parser gets the
    last word."""
    path = PKG / "launcher" / "build_runtime.ps1"
    ps = path.read_text(encoding="utf-8")
    assert not re.findall(r'\$(?!env:)[A-Za-z_]\w*:', ps), \
        "`$name:` inside a string is a scope qualifier - write `${name}:`"
    import shutil
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("no pwsh here; the regexes above are what holds")
    script = ("$t=$null;$e=$null;"
              "[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e)|Out-Null;"
              "if($e){$e|%%{$_.Message};exit 1}" % str(path).replace("'", "''"))
    r = subprocess.run([pwsh, "-NoProfile", "-Command", script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_version_comes_out_of_the_zip_by_a_subcommand_not_a_one_liner(tmp_path):
    """Release #1, #2 and #3 all died in nineteen seconds on a PowerShell
    ParserError: an inline Python one-liner in `build_runtime.ps1` needed a
    literal double quote, escaped it the C way, and the backslash ended the
    PowerShell string instead. The whole script failed to parse before a
    line of it ran. Nothing here can execute PowerShell, so two things are
    held instead: the script asks `release.py` for the number, and no
    PowerShell file in the launcher carries backslash-quote at all."""
    ps = (PKG / "launcher" / "build_runtime.ps1").read_text(encoding="utf-8")
    assert "release.py" in ps and "zip-version" in ps
    for f in (PKG / "launcher").glob("*.ps1"):
        assert '\\"' not in f.read_text(encoding="utf-8"), \
            "%s: backslash-quote is not an escape in PowerShell" % f.name
    wf = (PKG / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert '\\"' not in wf
    # ...and the subcommand answers with the zip's own number
    dest = R.build_zip(str(tmp_path))
    assert R.zip_version(dest) == R.version()
