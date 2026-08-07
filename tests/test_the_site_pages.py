"""The three signed-in pages, in a browser, with Firebase replaced.

These pages are ES modules that import the Firebase SDK from Google's CDN, so
two things have to be arranged before any of them can be asked a question:

* they must be **served over HTTP**. A module loaded from `file://` is refused
  by the browser as a cross-origin request from a null origin, and the page
  comes up blank with a CORS message. That is not a bug in the page, but it
  does mean a test that opens the file directly tests nothing.
* the **CDN must be answered locally**. `STUB` below is a Firebase-shaped
  module that returns a fixed account: a name, a balance and four ledger rows,
  one of each kind. No network, and the same answers every run.

What is being tested is the PAGE - the arithmetic on the pricing page, the
sign of a row in the ledger, the popup, the theme. Firebase itself is not.
"""
import http.server
import socketserver
import threading

import pytest

import browserpool as pool
from where import PKG

SITE = str(PKG / "site")

# A Firebase-shaped module. Every symbol `app.js` imports, and nothing else.
STUB = """
export const initializeApp = () => ({});
export const getAuth = () => ({ currentUser: null });
export const connectAuthEmulator = () => {};
export const createUserWithEmailAndPassword = async () => ({});
export const signInWithEmailAndPassword = async () => ({});
export const signOut = async () => {};
export const onAuthStateChanged = (a, cb) => {
  setTimeout(() => cb(window.__USER || null), 0); return () => {}; };
export const sendPasswordResetEmail = async () => {};
export function GoogleAuthProvider() {}
export const signInWithPopup = async () => ({});
export const getFunctions = () => ({});
export const connectFunctionsEmulator = () => {};
export const httpsCallable = (f, name) => async () => {
  if (name === 'me') return { data: { coins: 4300, username: 'max',
    photo: 'fox', packs: [
      {id:'pack1',coins:500,usd:4.99}, {id:'pack2',coins:1050,usd:9.99},
      {id:'pack3',coins:2150,usd:19.99}, {id:'pack4',coins:5400,usd:49.99}] } };
  if (name === 'usernameFree') return { data: { free: true } };
  return { data: {} };
};
export const getFirestore = () => ({});
export const connectFirestoreEmulator = () => {};
export const doc = () => ({});
export const onSnapshot = (d, cb) => {
  setTimeout(() => cb({ exists: () => true,
    data: () => ({ coins: 4300, username: 'max', photo: 'fox' }) }), 0);
  return () => {}; };
export const setDoc = async () => {};
export const collection = () => ({});
export const query = () => ({});
export const orderBy = () => ({});
export const limit = () => ({});
const AT = { toDate: () => new Date(2026, 7, 7, 1, 8) };
export const getDocs = async () => ({ docs: [
  { data: () => ({ kind:'clawback', what:'pack pack1 \\u2014 refunded',
                   coins:500, at:AT }) },
  { data: () => ({ kind:'credit', what:'pack pack1', coins:500, at:AT }) },
  { data: () => ({ kind:'spend', what:'translate', page:'004.jpg',
                   coins:37, at:AT }) },
  { data: () => ({ kind:'refund', what:'translate', coins:12, at:AT }) },
]});
"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SITE, **kw)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def served():
    """`site/` on a port, for the length of this file.

    Port 0, so several test processes can run this at once - `-n auto` is the
    normal way this suite is run and a hard-coded port makes that a race.
    """
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Quiet)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def _site_costs():
    """`tools/site_costs.py`, which is a script rather than a module of the
    package. Loaded by path so the test does not depend on how the caller set
    PYTHONPATH, and so `tools/` does not have to become importable."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "site_costs", str(PKG / "tools" / "site_costs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def open_page(br, base, name, signed_in=True, scheme="dark"):
    ctx = br.new_context(color_scheme=scheme, viewport={"width": 1280,
                                                        "height": 900})
    ctx.route("https://www.gstatic.com/**",
              lambda r: r.fulfill(status=200, content_type="text/javascript",
                                  body=STUB))
    pg = ctx.new_page()
    if signed_in:
        pg.add_init_script("window.__USER={uid:'u1',email:'lee@example.com'}")
    pg.goto(f"{base}/{name}", wait_until="load")
    pg.wait_for_function("() => document.documentElement.dataset.chrome === '1'",
                         timeout=15000)
    return pg


# ------------------------------------------------------------ the calculator

def test_the_calculator_quotes_exactly_what_the_app_would_charge(served):
    """Not "about right". The same number.

    The pricing page used to carry a hand-typed table, and by the time anybody
    looked at it again every figure in it was wrong - `coins.py` had gained
    thinking tokens, prompt caching and the drift correction, and a sales page
    cannot notice that. So the numbers are generated now, and this is the test
    that makes generated mean equal: for each model and several chapter
    shapes, what the browser shows and what `coins.quote` would take.
    """
    from mangatl import coins
    site_costs = _site_costs()

    with pool.session() as br:
        pg = open_page(br, served, "pricing.html")
        try:
            for mid, _name, backend, _blurb in site_costs.SHOW:
                for pages, boxes in [(23, 217), (1, 6), (60, 900), (5, 5)]:
                    # One box count per page, the boxes spread over them the
                    # way `quote` is really called.
                    per = [boxes // pages] * pages
                    for i in range(boxes - sum(per)):
                        per[i] += 1
                    want = sum(coins.quote(s, per, mid, backend)
                               for s in ("ocr", "translate", "proofread"))
                    got = pg.evaluate(
                        """([id, p, b]) => import('./costs.js').then((m) => {
                             const q = m.MODELS.find((x) => x.id === id);
                             return m.quote(q, p, b,
                               {ocr:1, translate:1, proofread:1});
                           })""", [mid, pages, boxes])
                    assert got == want, (mid, pages, boxes, got, want)
        finally:
            pg.context.close()


def test_the_calculator_moves_when_you_drag_it(served):
    """A slider that does not change the number is a picture of a slider."""
    with pool.session() as br:
        pg = open_page(br, served, "pricing.html")
        try:
            read = lambda: int(pg.inner_text("#sum").replace(",", ""))
            first = read()
            assert first > 0
            pg.eval_on_selector(
                "#pages",
                "el => { el.value = 60; el.dispatchEvent(new Event('input')); }")
            assert read() > first, "more pages has to cost more"

            # ...and proofreading is a CHOICE, which means turning it on is
            # visible in the price rather than being priced in all along.
            before = read()
            pg.click('[data-step="proofread"]')
            assert read() > before
            pg.click('[data-step="proofread"]')
            assert read() == before
        finally:
            pg.context.close()


# ----------------------------------------------------------------- the ledger

def test_a_clawback_is_money_out_and_says_so(served):
    """The bug this file was started for.

    lee refunded a live $4.99 purchase and the account page told him he had
    been GIVEN 500 coins for it: a green `+500`, because the row's sign was
    `kind !== 'spend'` and a clawback is not a spend. His balance was correct
    the whole time, which is what made it a lie rather than a bug - nothing
    was broken, the page just said the opposite of what had happened.
    """
    with pool.session() as br:
        pg = open_page(br, served, "account.html")
        try:
            pg.wait_for_selector("#ledger table tr:nth-child(2)")
            rows = pg.evaluate("""() =>
              [...document.querySelectorAll('#ledger tr')].slice(1).map((r) => ({
                what: r.cells[1].innerText,
                coins: r.cells[2].innerText,
                cls: r.cells[2].className,
              }))""")
            assert len(rows) == 4, rows
            claw, credit, spend, refund = rows

            assert claw["coins"].startswith("−"), claw
            assert "minus" in claw["cls"], claw
            assert "plus" not in claw["cls"], claw

            assert credit["coins"].startswith("+"), credit
            assert "plus" in credit["cls"], credit
            assert spend["coins"].startswith("−"), spend
            assert refund["coins"].startswith("+"), refund
        finally:
            pg.context.close()


def test_the_ledger_says_what_a_pack_was_rather_than_its_id(served):
    """`Added - pack pack1` was on a customer's account page. `pack1` is a key
    in `purse.js`; the size is the thing the person bought."""
    with pool.session() as br:
        pg = open_page(br, served, "account.html")
        try:
            pg.wait_for_selector("#ledger table tr:nth-child(2)")
            text = pg.inner_text("#ledger")
            assert "pack pack1" not in text, text
            assert "500 coins pack" in text
            # ...and "Taken back the 500 coins pack, refunded" says it twice.
            assert "refunded" not in text.lower()
        finally:
            pg.context.close()


# ------------------------------------------------------------------ the popup

def test_creating_an_account_asks_for_a_username_in_a_popup(served):
    """lee: *"theer shoud be a create username popup"*. Signing IN does not
    ask; creating an account does, and it does it without leaving the page -
    somebody who signed up halfway through buying something is still halfway
    through buying something."""
    with pool.session() as br:
        pg = open_page(br, served, "signin.html", signed_in=False)
        try:
            assert not pg.is_visible("#veil.on")
            pg.fill("#email", "lee@example.com")
            pg.fill("#pass", "hunter22")
            pg.click("#tabUp")
            pg.click("#go")
            pg.wait_for_selector("#veil.on", timeout=8000)
            assert pg.is_visible("#user")
            assert "signin.html" in pg.url, "the popup is not a redirect"
        finally:
            pg.context.close()


def test_signing_in_does_not_ask_for_a_username(served):
    with pool.session() as br:
        pg = open_page(br, served, "signin.html", signed_in=False)
        try:
            pg.fill("#email", "lee@example.com")
            pg.fill("#pass", "hunter22")
            pg.click("#go")
            pg.wait_for_timeout(600)
            assert not pg.is_visible("#veil.on")
        finally:
            pg.context.close()


# ------------------------------------------------------------------ the theme

@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_theme_follows_the_system_when_nobody_has_chosen(served, scheme):
    with pool.session() as br:
        pg = open_page(br, served, "pricing.html", scheme=scheme)
        try:
            assert pg.evaluate("() => document.documentElement.dataset.theme")\
                is None
            lit = pg.evaluate(
                "() => getComputedStyle(document.body).backgroundColor")
            # The light ground is bright and the dark one is not. Read off the
            # painted colour rather than off a class name, because a token
            # that is defined and not applied looks exactly like this test
            # passing.
            rgb = [int(x) for x in lit[lit.index("(") + 1:lit.index(")")]
                   .split(",")[:3]]
            assert (sum(rgb) > 500) == (scheme == "light"), (scheme, lit)
        finally:
            pg.context.close()


def test_the_button_overrides_the_system_and_is_remembered(served):
    """Three states, and only two of them are stored: Auto is the ABSENCE of a
    stored value, so a browser that has never pressed this tracks the system
    for ever and one that has keeps what it chose."""
    with pool.session() as br:
        pg = open_page(br, served, "pricing.html", scheme="dark")
        try:
            pg.click("#theme")                       # auto -> light
            assert pg.evaluate(
                "() => document.documentElement.dataset.theme") == "light"
            pg.reload(wait_until="load")
            pg.wait_for_function(
                "() => document.documentElement.dataset.chrome === '1'")
            assert pg.evaluate(
                "() => document.documentElement.dataset.theme") == "light", \
                "a theme that forgets on reload is a theme nobody sets twice"
            pg.click("#theme")                       # light -> dark
            assert pg.evaluate(
                "() => document.documentElement.dataset.theme") == "dark"
            pg.click("#theme")                       # dark -> auto
            assert pg.evaluate(
                "() => document.documentElement.dataset.theme") is None
            assert pg.evaluate(
                "() => localStorage.getItem('tct-theme')") is None, \
                "Auto is the absence of a value, not a third string"
        finally:
            pg.context.close()


# ------------------------------------------------------------ the dead man

def test_a_script_that_never_arrives_does_not_leave_an_invisible_page(served):
    """The sections start hidden so they can be revealed on scroll, and the
    thing that reveals them is a module fetched from a CDN. Block the CDN and
    that page was, for ever, a header and three invisible boxes.

    It is not a hypothetical: the CDN is not reachable from the machine this
    was written on, and the first screenshot of the new pricing page was a
    title and a footer with a thousand pixels of nothing between them.
    """
    with pool.session() as br:
        ctx = br.new_context(viewport={"width": 1280, "height": 900})
        ctx.route("https://www.gstatic.com/**", lambda r: r.abort())
        pg = ctx.new_page()
        try:
            pg.goto(f"{served}/pricing.html", wait_until="load")
            pg.wait_for_timeout(3200)          # the timer is 2500ms
            assert pg.evaluate(
                "() => document.documentElement.classList.contains('js')") \
                is False
            seen = pg.evaluate("""() => [...document.querySelectorAll('.sect')]
              .every((s) => getComputedStyle(s).opacity === '1')""")
            assert seen, "a page nobody can read is worse than a page with no JS"
        finally:
            ctx.close()


# --------------------------------------------------------------- the chrome

def test_nothing_on_any_page_is_an_underlined_link(served):
    """lee: *"avoid having underlines in links"*. Asked of the painted style
    and not of the stylesheet, because a rule can be written and overridden."""
    with pool.session() as br:
        for name in ("pricing.html", "account.html", "signin.html"):
            pg = open_page(br, served, name)
            try:
                bad = pg.evaluate("""() => [...document.querySelectorAll('a')]
                  .filter((a) => getComputedStyle(a).textDecorationLine
                                   .includes('underline'))
                  .map((a) => a.textContent.trim().slice(0, 30))""")
                assert not bad, (name, bad)
            finally:
                pg.context.close()


def test_the_google_button_carries_the_google_mark(served):
    """lee: *"add teh google logo the the sign in a nd sign up with google"*.
    Drawn into the page rather than fetched: a mark that comes from a CDN is a
    button that says nothing on the day the CDN is slow."""
    with pool.session() as br:
        pg = open_page(br, served, "signin.html", signed_in=False)
        try:
            paths = pg.evaluate(
                """() => [...document.querySelectorAll('#gbtn svg path')]
                     .map((p) => p.getAttribute('fill'))""")
            # Google's four, which is what their brand rules ask for.
            assert set(paths) == {"#4285F4", "#34A853", "#FBBC05", "#EA4335"}
            box = pg.eval_on_selector("#gbtn svg",
                                      "el => el.getBoundingClientRect().width")
            assert box > 10, "drawn, and big enough to be a logo"
        finally:
            pg.context.close()
