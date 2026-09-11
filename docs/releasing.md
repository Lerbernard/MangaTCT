# Releasing MangaTCT for Windows

How a version gets from this repository onto people's computers, and stays
current there. Written for the day you ship 1.0.0 and for every day after.

## The shape of it

```
you:   change version.py -> commit -> push -> git tag v1.0.1 -> push the tag
CI:    check the tag = version.py → fast tests → every weight url still answers
       (Windows) app zip → Python runtime with every package → launcher exe
                 → installer → manifest.json + SHA256SUMS
       publish, on THIS repository:
                 a Release with the installer, the app zip, the sums
                 manifest.json on main  ← this is the one url every install reads
users: next time they start MangaTCT, the launcher reads manifest.json,
       fetches the new app zip (a few MB), checks its sha256, unpacks it beside
       the old version, starts it. No reinstall, ever, for an app change.
```

One repository, no second token: the Release is created with the
`GITHUB_TOKEN` every Actions run already has. lee: *"we alredy have a github
repo, we dont need a newone"*.

Three artifacts, three jobs:

| file | what | who downloads it |
|---|---|---|
| `MangaTCT-Setup-1.0.1.exe` | launcher + Python runtime with every package + the app | a new user, once |
| `mangatct-app-1.0.1.zip` | the `mangatl` package as source, `requirements.txt`, `models.json` | every installed launcher, on update |
| `manifest.json` | version, url, sha256, size of the zip; the model list | every launcher, every start |

The **model weights are not in the installer**. NOTICE says why: they are
not ours to redistribute. The launcher fetches them on the first start from
each publisher (`tools/models.json` — url, sha256, size, tier) into
`%LOCALAPPDATA%\MangaTCT\models`, and keeps them across app updates.

## One-time setup (before the first tag)

**1. This repository has to be public.** Settings → General → scroll to
Danger Zone → *Change repository visibility* → Public.

That is the whole of the setup, and it is not really an extra ask. A private
repository's Release assets need a token to download, and the entire point of
a self-updating app is that it fetches without one — there is no arrangement
where the app updates itself from a private repo. And the licence already
settled the question: MangaTCT is GPL-3.0 (it has to be — comic-text-detector
is, and every detection route uses its mask), so every copy you hand out
already comes with the offer of its corresponding source. Publishing the
source is a commitment that has been in force since that licence was chosen;
this just makes it a link instead of a request you would have to answer by
hand.

Two things to look at once before flipping it, both already checked here and
both fine:

* `tests/test_the_workflows.py::test_nothing_that_ships_looks_like_a_key`
  scans every tracked file on every push. It passes.
* `site/config.js` holds the Firebase **web** config. That is not a secret —
  it identifies the project and authorizes nothing; the rules and the Cloud
  Functions are what stop anyone using it. Your Stripe key is in
  `firebase functions:secrets:set` and `.env` is git-ignored.

If you would rather keep the code private, the alternative is a separate
public repo holding only the Releases — which is what this was before you
said *"we alredy have a github repo, we dont need a newone"*. Say the word
and it goes back; it costs one repo and one fine-grained token.

**Two things that are not setup, but are worth knowing:**

* **The weights list.** `tools/models.json` names five files with the sha256
  of the copies on your machine. The `check` job fetches every one. A
  `required` one failing stops the release; a `recommended` one failing is
  reported as a WARNING and the release goes out — the route that wanted it
  simply stays gray in the editor until the url is fixed. Two urls
  (AnimeText, the Manga109 segmenter) are marked `"verified": false`:
  Hugging Face is blocked from both the build sandbox and your machine, so
  they are written from the publishers' naming convention and **the first
  release is what proves them**. If one is wrong the log names it; fix the
  url, commit, re-tag.
* **Windows SmartScreen.** The exe is not signed. Windows shows "Windows
  protected your PC" on first run; *More info → Run anyway*. The download
  page says so and says what to click. A code-signing certificate (Azure
  Trusted Signing is about $10/month; a traditional OV cert $200–400/year)
  makes that go away after enough installs. Not needed for the beta, and
  worth doing before you tell strangers to install it.

## The `models` release (once, and whenever a weight file changes)

The launcher fetches each model from the first address in its `urls` in
`tools/models.json` — the project's own mirror first, the publisher after.
The mirror is a GitHub release on this repository tagged `models`, holding
the exact files their publishers put out (the checksums in models.json are
of those files). It exists because an installed copy could reach GitHub but
not Hugging Face, and because the COO sound-effect weights have no fetchable
publisher address at all. Upload the four by hand: comictextdetector.pt.onnx,
animetext.pt, m109seg.pt, dbpp_coo.dat (GitHub → Releases → Draft a new
release → tag `models`, drag the files in — or `gh release create models
<files>`). Not the webtoon models: no licence is written down for them
(NOTICE). Adding a model: put the file on the `models` release, add an entry
with its sha256 and size, mirror first in `urls`, publisher (if any) last and
also as `url` for launchers before 1.0.3.

## Every release

**In PowerShell, one command per line.** Windows PowerShell 5.1 - the one that
opens by default - does not accept `&&` between commands and answers
*"The token '&&' is not a valid statement separator in this version"*. Use `;`
if you want them on one line, or just press Enter between them.

```powershell
# 1. the number
#    edit version.py:  __version__ = "1.0.1"

# 2. commit and push EVERYTHING first.
#    A tag points at a commit. Tagging with work still uncommitted tags the
#    OLD code - the workflow reads `version.py` out of the tag, so it either
#    refuses ("tag v1.0.1 is not version 1.0.0") or, worse, builds a release
#    out of last week.
git add -A
git commit -m "1.0.1: what changed"
git push

# 3. the tag
git tag v1.0.1
git push origin v1.0.1

# 4. watch Actions -> Release. About 15 minutes; the Windows job is most of it.
```

To check before you tag that the tag will be accepted:

```powershell
git status --short          # should be empty
python tools/release.py version
```

The first of those two is the one that bites. `git status --short` empty means
the commit you are about to tag is the code you have been testing.

When it is green: the Release is at
`https://github.com/Lerbernard/MangaTCT/releases/tag/v1.0.1`, the
download page's button (`/get/latest/installer`, answered by the `get`
function from the manifest) hands out the new file, and every
installed copy picks the new version up on its next start (or within six
hours if it is left running — the pill in the header gets a dot, and the
switch happens at the next start).

**A release that must not be used** (a bad bug found after publishing):
publish the next number. Every launcher keeps the previous version on disk
and falls back to it only if the new one cannot be *prepared*, not if it is
merely wrong, so the fix is always "ship the fix". Do not delete a Release
that installs are already on — their launchers re-verify nothing after the
first checksum, but a person reinstalling would find the button dead.

## Where things are on a user's machine

```
%LOCALAPPDATA%\MangaTCT\
  MangaTCT.exe           the launcher
  runtime\python\        Python 3.12 + every package (~1.5 GB with torch)
  app\1.0.0\  app\1.0.1\ one folder per version; .complete inside = verified
  models\                the weights, fetched once
  logs\launcher.log      what the launcher did
  logs\editor-<date>.log the editor's console, one file a day
  logs\window-<date>.log the app window's, usually empty; says why the
                         browser opened instead when it did
  state.json             installed version, last check, requirements hash,
                         auto_update (Settings > Updates switch)
  update.json            what the pill and Settings > Updates read (only
                         while one is offered, downloading or ready)
~\.mangatl\              THEIRS: fonts, prefs, API keys - untouched by all of this
  window.json            where the app's window was last (size, place, maximised)
  webview\               the window's own storage (localStorage, cache)
~\Documents\MangaTCT\out exported pages, unless they chose a folder
```

A support message should start with the version (the pill) and attach
`logs\editor-<date>.log`; *Open logs folder* is on the launcher window.

## Updates from inside the app

Settings > Updates (1.0.3+) is the launcher's updating made visible: the
app zip carries `launcher/mangatct_launcher.py` as `mangatl.launcher`, and
`mangatl/updates.py` runs its `check_for_update` from the editor — same
manifest, same checksum rule, same folders. *Check now* checks (and, with
*Download updates automatically* on, fetches); *Restart now* ends the editor
with exit code 75 (`EDITOR_RESTART`) and a 1.0.3+ launcher makes another
pass, which is when the fetched version is switched to. The manifest also
carries `launcher.version`, the launcher the release's installer shipped;
when it is newer than the one running, the page offers *Get the new setup*,
which downloads the installer to `%TEMP%` (checksum checked), runs it
`/SILENT /relaunch=1`, and leaves — the installer's `PrepareToInstall` stops
whatever still runs out of `%LOCALAPPDATA%\MangaTCT`, and `/relaunch=1`
starts MangaTCT again at the end. **Bump `LAUNCHER_VERSION` whenever the
launcher file changes**; that is the whole signal.

## What the launcher will not do

* switch versions while the editor is running — a mid-session download is
  used on the next start, or when the person presses Restart now;
* use a zip whose sha256 is not the manifest's;
* delete the version that is running, or the one before it;
* wait on the network to start: four seconds, then it starts what it has.

## Testing a release without publishing it

`MANGATCT_MANIFEST=<url>` on the launcher points it at any manifest - a file
on a local web server, a `manifest.json` on a branch of this repo - so
an update can be rehearsed on one machine before the channel moves.

The workflow itself has no rehearsal mode: a tag must equal `version.py`
exactly, and a green run publishes. To try the Windows build without
publishing, push the tag, watch the `build` job, download its artifact from
the run page (the installer is in it), and cancel the run before `publish`
starts - or let it publish and follow it with the real number, since every
launcher simply takes the highest version it is offered.
