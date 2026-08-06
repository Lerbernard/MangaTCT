# Path to a hosted, multi-user mangatl

The editor today is one Python process serving one project to one browser.
This note maps the road from that to "hosted somewhere, several people each
working on their own project in their own browser at the same time" — in
small steps that each leave the app working. Nothing here needs a build
step or a framework switch; the client stays vanilla JS.

## What this refactor already did for you

The client is now split into modules under `static/js/`, and every server
URL the client builds goes through one function: `apiUrl()` in
`js/core.js`, with an `API_BASE` prefix that is currently `''`. That means
project-scoped URLs later are a one-line client change. The server's
`_static()` handler already serves nested paths safely, so no server change
was needed for the split.

## Step 1 — several projects in one server (still one user)

The server keeps one global `PROJECT`. Replace it with a dict of open
projects keyed by a short id, and scope routes with a prefix:

- `GET /p/<id>/...` → look up the project, then dispatch to the existing
  handlers unchanged. A tiny router shim in `Handler.do_GET/do_POST` that
  peels `/p/<id>` off `self.path` and sets `self.project` is enough — the
  ~40 existing route branches don't have to change if they read
  `self.project` instead of the global.
- Client: set `API_BASE='/p/'+projectId` (read the id from
  `location.pathname` at boot). That is the one-line change `apiUrl()`
  was added for.
- A bare `GET /` becomes a project chooser (list of open/known project
  dirs, "new chapter" creates one).

## Step 2 — hosting it

- Put the process behind a real front door (Caddy/nginx for TLS, or a
  small VPS with the port firewalled + basic auth to start).
- `ThreadingHTTPServer` is fine longer than people expect for a handful of
  users; the CPU-heavy work (detect/OCR/inpaint) already runs as
  background jobs polled via `/api/job`. If those jobs start starving the
  request threads, move them to a worker process (queue keyed by project
  id) before reaching for a framework.
- Storage: each project is already a folder on disk. Hosted, that becomes
  a folder per project id under one data root — no schema migration.
- Auth, simplest that works: a signed session cookie mapping user → list
  of project ids. One user per project sidesteps conflict handling
  entirely and covers "each person on their own project", which is the
  stated goal.

## Step 3 — only if two people must share ONE project

Skip this until it's actually needed. The pieces that would matter:

- The client already syncs paint layers with a debounced
  `queueSync()`/`syncPaint()` (js/sync.js) and saves typesetting per region;
  writes are already small and region-scoped, which is the right shape.
- Last-write-wins per region is acceptable for a two-person team; add a
  `rev` counter per region so the server can reject a stale write and the
  client can re-fetch and re-apply (the code paths for re-fetch already
  exist: every mutation response returns fresh region state).
- Live presence (seeing the other person's cursor/selection) would need
  server-sent events or a websocket — that is the first feature on this
  road that the stdlib server genuinely can't do well, and the sensible
  moment to consider moving `editor.py`'s routes onto something like
  aiohttp. Moving them then will be far easier because they are already
  thin handlers over `Project` methods.

## Rules of thumb the modules should keep obeying

- All server URLs go through `apiUrl()`. Never build one inline.
- New client code goes in the module that owns the concern (see each
  file's banner); new cross-cutting state goes at the top of `core.js`.
- Scripts are classic, load-order-dependent, and share one global scope —
  editor.html's script list is the load order. Keep boot.js last.
- Keep server routes thin: parse → call a `Project` method → JSON. That's
  what makes Step 1's router shim and Step 3's framework move cheap.
