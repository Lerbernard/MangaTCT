# MangaTCT — working notes for Claude Code

This repository is the app: a Python server (`editor.py`) plus a vanilla-JS
editor (`static/`), a pywebview window (`window.py`), a launcher
(`launcher/`), the website (`site/`), and the Firebase functions the coins
run on (`firebase/functions/`). GPL-3.0. One person (lee) owns it and ships
it; you are the second pair of hands. The full history of why things are the
way they are lives in the code comments and in `docs/every-feature.md` — read
the relevant section of that before changing a feature.

## Layout — the folder IS the package

The repository root is the `mangatl` package (`__init__.py` is here), so its
parent has to be importable. `pytest.ini` handles that for the suite; to run
anything else, run it from the parent folder as a module:

```powershell
cd $HOME\OneDrive\Documents            # the folder ABOVE the repo
python -m mangatl.editor --input chapter\ --output out\     # a checkout, in the browser
python -m mangatl.window                                     # the app window
```

Tests, from the repository folder:

```powershell
cd $HOME\OneDrive\Documents\mangatl
python -m pytest tests -q                # the whole suite (slow: ~50 min; use -x or name files)
python -m pytest tests\test_x.py -q      # one file
npx vitest run tests\functions           # the Cloud Functions' pure logic (purse.js, relay.js)
```

The suite never touches the real `~/.mangatl`: `tests/conftest.py` points
`MANGATL_HOME` and `MANGATL_ENV` at a throwaway folder and sets
`MANGATL_TEST_PURSE=1` (a local wallet for the developer's machine; installed,
signed-out copies have no purse at all). Keep every new test inside that.
Some tests need Playwright's Chromium (`playwright install chromium` once);
a handful of launcher tests are Linux-only and skip or fail on Windows — fix
the test, not the machine.

## Rules lee has set (each has a test; the tests are the law)

* **American spelling** in everything the person reads. (Code comments from
  before the rule still carry British spellings; do not churn them.)
* **lee's words are kept verbatim in comments**, in the form
  `lee: *"what he said"*`, typos and all. It is how a change explains itself.
  Add the quote when you implement something he asked for.
* **The word for putting text on a page is "typesetting."** The other word
  — the one `tests/test_the_word_is_typesetting.py` forbids, as noun and as
  verb — must not appear in any `.py .js .html .css .md` file, including this
  one. The glyph sense (a letter of the alphabet) is fine.
* **One-line descriptions on the File and Settings screens**, never
  paragraphs. Screen copy is plain: what the control does, in one sentence.
* Comments explain *why*, at length, in prose. That is the house style and
  lee wants it kept.

## Things that must never ship

* **No secrets in the repository or the zip.** `CLEAN_TOKEN`, the provider
  keys (Anthropic, Gemini, OpenRouter) and Stripe live only in Firebase
  Secret Manager, set by lee with `firebase functions:secrets:set`. The app
  never holds a provider key: AI calls go through the `relay` function with
  the person's Firebase ID token. `tools/release.py check` and
  `tests/test_the_workflows.py::test_nothing_that_ships_looks_like_a_key`
  scan for leaks; `site/config.js` (the Firebase *web* config) is the one
  allowed exception. Never ask lee for a key; never read his `.env`.
* **Fonts only where redistribution is allowed** — `fonts/LICENSES.md` is the
  list; `tests/test_only_what_we_may_ship.py` names the forbidden files
  (Anime Ace, Wild Words). Do not add a font without a licence line.
* **Model weights are not in the repo.** `tools/models.json` says where each
  comes from (a mirror on the `models` GitHub release first, the publisher
  second, checksummed). The webtoon detectors have no written licence and are
  *not* mirrored. `NOTICE` must stay true when this list changes.
* **`static/js/vendor/prosemirror.js` is committed, never fetched.**
* `.github/workflows/*.yml` are edited by lee only; put a proposed change in
  `tools/pending/` and say so.
* Never add code that scrapes or lists piracy sites, or that pulls pages out
  of DRM'd readers. The app opens files the person already has.

## How a release works (`docs/releasing.md` has the long form)

`version.py` is the single version. Bump it, commit, push, tag `vX.Y.Z`,
push the tag; CI builds the app zip, the installer and `manifest.json`, and
the launcher on every installed copy picks it up. Before tagging:
`git status --short` empty, `python tools/release.py check`, suite green.
Site changes need `firebase deploy --only hosting`; function changes need
`firebase deploy --only functions` (if it times out on "Cannot determine
backend specification", set `$env:FUNCTIONS_DISCOVERY_TIMEOUT="90"` — the
OneDrive folder makes the first load slow). Deploy *before* tagging when the
app version depends on the site or the functions.

Files that change together and are easy to forget: `site/costs.js` is
generated (`python tools/site_costs.py`) and a test pins it to `coins.py`;
`site/index.html` is generated (`python site/build.py`) and a test pins it
to `site/build.py`; `docs/every-feature.md` describes every control and is
kept current in the same commit as the control.

## Where things live on a machine

* `%LOCALAPPDATA%\MangaTCT` — the launcher, its Python, `app\<version>\`,
  downloaded models, `state.json`, `update.json`. Replaceable.
* `~\.mangatl` — the person's: `account.json` (refresh token, 0600), fonts,
  prefs, `wallet.json` (developer purse only). Untouched by updates.
* The launcher's log is beside it; the editor logs to the console it runs in.

## State as of 2026-09-13 (1.0.6, not yet tagged)

The 1.0.6 changes are in the working tree (Home screen, frameless window with
the page as title bar, Settings › Account like the website's page, Google
sign-in via a browser hand-off to `/api/account/hand`, 4-piece reading and
export-preview-off as defaults, `site/config.js` shipped in the zip,
`pytest.ini`). Two things were being fixed when this file was written:

1. **The download link.** `mangatct.com/get/latest/installer` showed Google's
   generic "Server Error"; the `get` function was the only one at 128 MiB and
   the file now loads too much at start for that. It is 256 MiB in
   `firebase/functions/index.js`; confirm with `firebase functions:log --only
   get`, then `firebase deploy --only functions,hosting`.
2. **The frameless window on real Windows.** The crash on open (pywebview
   walking `api.win.native…` forever) is fixed by keeping the window on the
   `Api` object as `_win`; the drag, snap, resize edges, rounded corners and
   the maximize-that-respects-the-taskbar have only been checked by reading.
   `--frame` or `MANGATCT_FRAME=1` brings the system frame back if needed.

Also pending: functions deploy for `ledgerLines` (the Account page's
receipt); hosting deploy for the sign-in hand-off (until then the Google
button opens the site and nothing comes back). Known: an order-dependent
flake around `running_qid` in the queue tests (pre-existing, not fixed);
lee's own project has ComicNeue-Italic saved as its font and needs one reset
to "Shipped default".

The launcher is 1.0.3 and does not need rebuilding for an app-only release.
