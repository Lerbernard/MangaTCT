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
signed-out copies have no purse at all). It also keeps the checkout's own
`.env` out of the run — lee keeps his real one in the repository folder, and
both `import mangatl` and `userdata.env_paths` would otherwise read it. Keep
every new test inside that. Some tests need Playwright's Chromium
(`playwright install chromium` once); a handful of launcher tests are
Linux-only and skip or fail on Windows — fix the test, not the machine. A
`_to_delete/` folder is not collected (`pytest.ini`).

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
  the person's Firebase ID token. `tools/release.py zip` (it refuses to write
  a zip that fails its leak scan) and
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
`git status --short` empty, `python tools/release.py check-tag vX.Y.Z` (there
is no plain `check`), suite green. A tag that is already published is not
moved: an installed copy only updates to a HIGHER number, so a fix ships as
the next one. Site changes need `firebase deploy --only hosting`; function
changes need `firebase deploy --only functions` (if it times out on "Cannot
determine backend specification", set `$env:FUNCTIONS_DISCOVERY_TIMEOUT="90"`
— the OneDrive folder makes the first load slow). Deploy *before* tagging
when the app version depends on the site or the functions.

Files that change together and are easy to forget: `site/costs.js` is
generated (`python tools/site_costs.py`) and a test pins it to `coins.py`;
`site/index.html` is generated (`python site/build.py`) and a test pins it
to `site/build.py`; `site/tutorial.html` names the current version in words
and a test pins that to `version.py`; `docs/every-feature.md` describes every
control and is kept current in the same commit as the control.

## Where things live on a machine

* `%LOCALAPPDATA%\MangaTCT` — the launcher, its Python, `app\<version>\`,
  downloaded models, `state.json`, `update.json`. Replaceable.
* `~\.mangatl` — the person's: `account.json` (refresh token, 0600), fonts,
  prefs, `wallet.json` (developer purse only). Untouched by updates.
* The launcher's log is beside it; the editor logs to the console it runs in.

## State as of 2026-09-13 (1.0.8)

1.0.6 was tagged and published on 2026-09-11 from `ac7d874`, before the fix
for the window crashing on open (`Api._win`), so installed 1.0.6 copies crash
when the window opens (lee's `launcher.log` shows it). 1.0.7 is that fix plus
what checking the frameless window on a real Windows 11 machine turned up (one
3456x2160 monitor at 150%, the taskbar set to hide itself):

* resizing at the edges did nothing and nothing ever snapped. `FormBorderStyle
  None` drops `WS_THICKFRAME`; the frame hook in `window.py` puts the styles
  back and hides the frame (WM_NCCALCSIZE), and `_begin_native_drag` now sends
  the cursor position in lParam (sent as 0, a resize never started and the
  window stopped answering);
* a double click on the bar did nothing. The page never sees one; `Api.hit`
  counts it;
* maximized covered a self-hiding taskbar for good. WM_GETMINMAXINFO now stops
  two pixels short of it, also when the window opens maximized; WinForms'
  MaximizedBounds (wrong on a second monitor) is gone.

Checked by driving the real window with real mouse input: dragging by every
empty part of the bar, double click, the three buttons, all eight edges, snap
to the top and to the left half, dragging a maximized window down, the taskbar
sliding up over a maximized window, opening maximized. NOT checked on a real
screen: a second monitor, a taskbar that stays shown, Windows 10.

Deployed 2026-09-13: functions (`get` at 256 MiB — its log said "Memory limit
of 128 MiB exceeded" on every start; `ledgerLines`) and hosting (the sign-in
hand-off). `mangatct.com/get/latest/installer` answers 302 to the GitHub
release again.

Fixed in the suite on the way: the order-dependent `running_qid` failure (a
dispatcher that had been replaced wrote over the one that replaced it;
`editor._dispatch` now checks it still owns the line); test files that read
UTF-8 sources without saying so (cp1252 on Windows); and the checkout's own
`.env` reaching the tests (see Tests above).

Still to watch. The full suite on lee's machine, the night 1.0.7 was tagged
(51 minutes; no pytest-xdist; no Playwright, so the browser tests skip), ends
8 failed, 4555 passed, 632 skipped. Seven of the eight fail the same way on
the 1.0.6 commit, before any of that night's changes:

* `test_breaking_at_the_authors_dashes.py::test_the_warning_only_says_shrunk_when_it_shrank`
* `test_every_core_for_find_text.py::test_importing_the_package_first_keeps_ultralytics_from_throttling_torch`
* `test_no_account_no_coins.py::test_the_quote_is_not_slow_and_says_how_long_it_took`
* `test_out_of_the_box.py::test_it_really_is_wider_than_the_box_it_belongs_to`
* `test_sfx.py::test_an_effect_that_turns_a_corner_is_not_rotated`
* `test_the_purse_the_suite_spends.py::test_the_suite_is_not_spending_the_real_purse`
* `test_who_reads_the_text.py::test_the_ten_per_cent_result_is_stated_as_a_wash_not_as_a_win`

The eighth, `test_pipeline.py::test_snap_recovers_bubble_from_sloppy_drag`
(15 of 21), reads sample pages that exist only in lee's checkout, so a clean
checkout skips it and it could not be compared. Separately,
`test_clean_routing.py::test_a_finished_clean_reports_itself_through_the_job`
fails when `test_clean_says_when_it_fails.py` runs before it; the suite's own
order passes. Skipped on Windows on purpose, each with its reason: the
launcher tests whose fake runtime is a shell script, and the end card, whose
DejaVu fonts `tools/adcard.py` names by their Debian path.

1.0.8, the same night. Sign-in from the app no longer sends the browser to
127.0.0.1: the app keeps a secret, opens `mangatct.com/signin?hand=<sha256 of
it>`, the page files the sign-in with the `handToApp` function and says "You
are signed in" on the website, and the app collects it with `takeHand` (see
the comment in `account.py`). The route a browser used to post to is gone.
Account pictures are gone from the app and the site; the username is the one
thing to customize. The app's Account page asks the account service afresh
when it opens and whenever the window comes back to the front. The top bar
has room and a short rule before the window buttons.

`authDomain` in `site/config.js` is `mangatct.com`, so Google's sign-in popup
and its "you shared data with" email name the website. That rests on
`https://mangatct.com/__/auth/handler` being an authorized redirect URI (and
`https://mangatct.com` a JavaScript origin) on the OAuth web client in Google
Cloud, and on `mangatct.com` being an authorized domain in Firebase
Authentication - lee added them on 2026-09-13. Take either away and Google
sign-in on the website stops working.

After 1.0.8: `hidden` always hides on the website now (`[hidden]{display:none
!important}` in `site/style.css`) - `.forapp` and `.forapp-row` set `display`
and beat the attribute, so the sign-in page offered "Use this account" to
somebody signed out. The app opens the website through its own window
(`Api.open_url`, which calls `AllowSetForegroundWindow` first), so the browser
comes to the front. Deleting an account happens only on the website's account
page: a warning that it is permanent, DELETE typed, a second "Are you sure?",
then the `deleteAccount` function; the app's Account page links there. A
refresh token Google says is dead (`account.SIGN_IN_GONE`) signs the app out.

The launcher is 1.0.3 and does not need rebuilding for an app-only release.

## Driving the app window from a Claude Code session

* WebView2 would not start (0x80080005) from the session's own shell with a
  profile under the session's temp folder. Started through `explorer.exe`,
  with `MANGATL_HOME` in plain `%TEMP%`, it did.
* Screenshots of the app window's own rectangle only, never the monitor: a
  whole-screen capture takes in whatever else lee has open.
