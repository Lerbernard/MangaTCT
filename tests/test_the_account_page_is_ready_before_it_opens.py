"""Settings > Account is ready before anybody opens it.

lee: *"the account page takes a while to load, make it load as teh app is
scting so there no delay"*.

The page asked `/api/account` every time it opened and showed nothing until
the answer came - and signed in, that answer is the account service's balance,
name and every coin that moved, which takes seconds. So the question is asked
once while the app starts (`acctPrefetch`, from boot.js, once the first page is
up so it does not race the page's own requests), the answer is kept, and
opening the page draws it at once and asks again behind it.

The account service is stood in for INSIDE THE PAGE: its own `fetch` answers
`/api/account` after a second and a half, with a signed-in account. Not with a
Playwright route that sleeps - a sleeping route handler holds up Playwright
itself, so the test's clock ran on while the page had long since drawn, and
"at once" measured as the stand-in's delay.
"""
import json
import time

import pytest

import browserpool
from test_centred_pages import _serve

cv2 = pytest.importorskip("cv2")

SLOW_MS = 1500

FAKE = {"account": {"configured": True, "signed_in": True, "balance": 4181,
                    "email": "reader@example.com", "username": "max",
                    "buy_url": "https://mangatct.com/pricing"},
        "ledger": [{"at": 1757800000000, "kind": "spend", "what": "translate",
                    "page": "001.jpg", "coins": 5}],
        "packs": {}}

# A slow account service, in the page. Only the plain GET of /api/account -
# `/api/account/hand?...` and every POST go through untouched.
_SLOW_SERVICE = """(() => {
  const real = window.fetch;
  const fake = %s;
  window.__acctAsked = 0;
  window.fetch = function(u, o) {
    const url = String((u && u.url) || u);
    const method = ((o && o.method) || 'GET').toUpperCase();
    if (method === 'GET' && /\\/api\\/account(\\?|$)/.test(url)) {
      window.__acctAsked++;
      return new Promise(done => setTimeout(() => done(new Response(
        JSON.stringify(fake),
        {status: 200, headers: {'Content-Type': 'application/json'}})), %d));
    }
    return real.apply(this, arguments);
  };
})();""" % (json.dumps(FAKE), SLOW_MS)


def _open_with_a_slow_service(pg):
    pg.add_init_script(_SLOW_SERVICE)
    pg.reload(wait_until="load")
    browserpool.ready(pg)
    # The prefetch waits for an idle moment after the first page; give it that
    # and the service's second and a half.
    pg.wait_for_function("typeof _acctView!=='undefined' && _acctView!==null",
                         timeout=15000)


def test_the_answer_is_fetched_while_the_app_starts_not_when_the_page_opens():
    def check(pg, p):
        _open_with_a_slow_service(pg)
        asked = pg.evaluate("window.__acctAsked")
        assert asked == 1, "the account was asked %d times at start" % asked
    _serve(check)


def test_opening_the_page_draws_the_kept_answer_at_once():
    def check(pg, p):
        _open_with_a_slow_service(pg)
        t0 = time.time()
        pg.evaluate("setTab('settings'); setSettingsTab('account')")
        pg.wait_for_function("!!document.querySelector('#acctBox .acctpurse')",
                             timeout=10000)
        took = time.time() - t0
        assert took < SLOW_MS / 2000.0, (
            "the page waited %.2fs for the account service instead of drawing "
            "what it already had" % took)
        assert "4181" in pg.evaluate(
            "document.querySelector('#acctBox .acctpurse').textContent")
        # ...and it still asks again behind it, so a change made on the
        # website shows up.
        assert pg.evaluate("window.__acctAsked") == 2
    _serve(check)
