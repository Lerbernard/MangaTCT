/* The Cloud Functions. Firestore and Stripe, and nothing else.
 *
 * Every decision about how much money moves lives in `purse.js`, which has no
 * Firebase in it and is tested exhaustively without one. What is here is the
 * talking: transactions, tokens, webhooks. If you find an `if` in this file
 * that decides an AMOUNT, it is in the wrong file.
 *
 * The rule the whole design rests on: **nothing a client holds may write a
 * balance.** The editor runs on the customer's own machine, so everything it
 * can reach they can reach. The Admin SDK used here bypasses the security
 * rules, which is exactly why those rules can forbid client writes outright.
 */
import { initializeApp } from 'firebase-admin/app';
import { FieldValue, getFirestore } from 'firebase-admin/firestore';
import { getAuth } from 'firebase-admin/auth';
import { onCall, HttpsError } from 'firebase-functions/v2/https';
import { onRequest } from 'firebase-functions/v2/https';
import { defineSecret, defineString } from 'firebase-functions/params';
import Stripe from 'stripe';

import { createHash } from 'node:crypto';

import {
  PROVIDERS, relayTarget, tokenOf, forwardHeaders, admit, usageOf, errorBody, withBodyToken,
} from './relay.js';
import {
  PACKS, WELCOME, buy, checkUsername, clawback, pack, refund, refundedShare,
  spend, welcome,
} from './purse.js';

initializeApp();
const db = getFirestore();

/* Set with `firebase functions:secrets:set STRIPE_KEY` — never in a file, and
 * never in the repository. The webhook secret is separate because a webhook
 * nobody verifies is an endpoint that grants coins to anyone who posts to it. */
const STRIPE_KEY = defineSecret('STRIPE_KEY');
const STRIPE_WEBHOOK_SECRET = defineSecret('STRIPE_WEBHOOK_SECRET');
// The provider keys the relay calls with. lee: *"the user shoud not have
// eth keys"* - these are set once with `firebase functions:secrets:set` and
// never leave the function. See relay.js.
const ANTHROPIC_KEY = defineSecret('ANTHROPIC_KEY');
const GEMINI_KEY = defineSecret('GEMINI_KEY');
const OPENROUTER_KEY = defineSecret('OPENROUTER_KEY');
// ...and the cleaner's: its token, and the address of our deploy.
const CLEAN_TOKEN = defineSecret('CLEAN_TOKEN');
const CLEAN_URL = defineSecret('CLEAN_URL');
const PROVIDER_SECRETS = { ANTHROPIC_KEY, GEMINI_KEY, OPENROUTER_KEY, CLEAN_TOKEN };
const SITE = defineString('SITE_URL', { default: 'https://mangatct.com' });

/* `basil` or later, because that is where `managed_payments` exists on a
 * Checkout Session. Pinned rather than left to float: an API version is the
 * shape of every object this file reads, and letting Stripe pick it means the
 * shape can change under a deployment nobody touched. */
const stripe = () => new Stripe(STRIPE_KEY.value(),
                                { apiVersion: '2025-03-31.basil' });

/* Stripe price ids, kept in Firestore at `config/stripe` rather than in code,
 * because they are different in test mode and in live mode and redeploying a
 * function to switch is not a thing anybody should have to do.
 *
 *   config/stripe = { packs: {pack1: "price_...", ...} }
 */
async function priceIds() {
  const snap = await db.doc('config/stripe').get();
  const d = snap.exists ? snap.data() : {};
  return { packs: d.packs || {} };
}

const userRef = (uid) => db.doc(`users/${uid}`);

/* Every movement of money writes a line here. Functions write it, the person
 * reads it, nobody edits it — a ledger you can edit is not a record of
 * anything. */
function ledger(tx, uid, entry) {
  tx.set(userRef(uid).collection('ledger').doc(), {
    at: FieldValue.serverTimestamp(), ...entry,
  });
}

function must(auth) {
  if (!auth || !auth.uid) {
    throw new HttpsError('unauthenticated', 'Sign in first.');
  }
  return auth.uid;
}

/* ------------------------------------------------------------ a new account
 *
 * The user document is made HERE and never by the client. A client that could
 * create its own user document could create it with a million coins in it,
 * which is why the rules forbid `create` outright.
 *
 * It is made on first use rather than by a `beforeUserCreated` blocking
 * trigger, and there are two reasons, one of them boring:
 *
 * A blocking trigger needs Firebase Authentication with Identity Platform
 * turned on — an extra thing to enable, and one that fails at deploy rather
 * than at sign-up if you have not. It also drags in `jwks-rsa`, which
 * `require()`s `jose`, which is now ESM only; that combination stops the
 * whole codebase being analysed and nothing deploys at all.
 *
 * The better reason is that it cannot half-happen. A trigger that fails
 * leaves an auth user with no document behind it, and nothing ever tries
 * again. This runs on the first call that needs the document to exist, so a
 * failure is one retry away rather than permanent.
 *
 * It starts at zero. The hundred free coins are not put here: they are given
 * by `welcomeIfDue` below, to a VERIFIED email, which a document made on the
 * first call usually does not have yet.
 */
async function ensureUser(uid, auth) {
  const ref = userRef(uid);
  const snap = await ref.get();
  if (snap.exists) return snap.data();
  const fresh = {
    coins: 0,
    username: '', usernameKey: '', displayName: '', photo: '',
    email: (auth && auth.token && auth.token.email) || '',
    stripeCustomer: '', granted: {},
    created: FieldValue.serverTimestamp(),
  };
  // `create` and not `set`: two calls arriving together must not have the
  // second one overwrite a balance the first one has already put there.
  await ref.create(fresh).catch(async (e) => {
    if (e && e.code === 6) return;          // ALREADY_EXISTS — somebody won
    throw e;
  });
  return (await ref.get()).data();
}

/* ---------------------------------------------------------- the first coins
 *
 * lee: *"new account shoul get 100 free coins on creation"*. `purse.js` says
 * how many and on what terms; this is the terms being read off the token and
 * the coins being moved, once.
 *
 * Who is verified is the ID token's `email_verified` claim - set by Google
 * for a Google sign-in, and by Firebase Auth for a password account once the
 * link in the verification mail is clicked. It is not a field a client can
 * write, and not something this function is told; it is read off the signed
 * token on every call, so an unverified account calling `me` a thousand
 * times gets nothing a thousand times and a verified one gets it the first
 * time it calls.
 *
 * The email is remembered as a hash, not as an address: `welcomed/<sha256>`
 * is a collection of "this address has had its coins", and there is no need
 * for anyone reading the database to see whose. The account's own document
 * carries `granted.welcome` too, the same way a Stripe event id is carried,
 * so the second gate is the one that survives the account being deleted and
 * made again with the same address.
 */
const emailKey = (email) => createHash('sha256')
  .update(String(email || '').trim().toLowerCase()).digest('hex');

async function welcomeIfDue(uid, auth) {
  const tok = (auth && auth.token) || {};
  const verified = tok.email_verified === true && !!tok.email;
  if (!verified) return { given: false, verified: false };
  const seen = db.doc(`welcomed/${emailKey(tok.email)}`);
  return db.runTransaction(async (tx) => {
    const [me, had] = await tx.getAll(userRef(uid), seen);
    if (!me.exists) return { given: false, verified };
    const d = me.data();
    const got = welcome(d.coins, {
      verified, granted: !!((d.granted || {}).welcome || had.exists),
    });
    if (!got.ok) return { given: false, verified };
    tx.set(userRef(uid), { coins: got.balance, 'granted.welcome': true },
           { merge: true });
    tx.create(seen, { uid, at: FieldValue.serverTimestamp() });
    ledger(tx, uid, { kind: 'credit', what: 'welcome', coins: got.coins });
    return { given: true, verified, coins: got.coins };
  }).catch((e) => {
    // Two calls arriving together both read "not granted"; the second one's
    // `create` of the welcomed document fails and the whole transaction with
    // it - which is the point. Nobody is owed an error for it.
    if (e && e.code === 6) return { given: false, verified };
    throw e;
  });
}

/* --------------------------------------------------------------- usernames
 *
 * lee: *"allow the user to secelt their usernam that need to be unique"*.
 *
 * The uniqueness index is a collection keyed by the FOLDED name, so "is it
 * taken" is a document read and "take it" is a create that fails if the
 * document exists. Two people claiming the same name at the same moment are
 * two creates of one document id, and exactly one of them loses. Checking a
 * field on the user document and then writing it is a race whose window is
 * exactly as long as a round trip.
 */
export const claimUsername = onCall(async (req) => {
  const uid = must(req.auth);
  await ensureUser(uid, req.auth);
  const want = checkUsername(req.data && req.data.username);
  if (!want.ok) throw new HttpsError('invalid-argument', want.why);

  const index = db.doc(`usernames/${want.key}`);
  try {
    await db.runTransaction(async (tx) => {
      const [taken, me] = await tx.getAll(index, userRef(uid));
      if (taken.exists && taken.data().uid !== uid) {
        throw new HttpsError('already-exists', 'That name is taken.');
      }
      const old = me.exists ? me.data().usernameKey : '';
      // The old name is given back in the SAME transaction that takes the new
      // one. Released first and claimed second, a failure in between loses the
      // name for everybody; claimed first and released second, a crash leaves
      // two names pointing at one person for ever.
      if (old && old !== want.key) tx.delete(db.doc(`usernames/${old}`));
      tx.set(index, { uid, at: FieldValue.serverTimestamp() });
      tx.set(userRef(uid), { username: want.name, usernameKey: want.key },
             { merge: true });
    });
  } catch (e) {
    if (e instanceof HttpsError) throw e;
    throw new HttpsError('aborted', 'Could not take that name — try again.');
  }
  await getAuth().updateUser(uid, { displayName: want.name }).catch(() => {});
  return { ok: true, username: want.name };
});

/* Availability, for a sign-up form that wants to say "gone" before the button
 * is pressed. Deliberately says nothing about WHO has it. */
export const usernameFree = onCall(async (req) => {
  const want = checkUsername(req.data && req.data.username);
  if (!want.ok) return { free: false, why: want.why };
  const snap = await db.doc(`usernames/${want.key}`).get();
  const mine = snap.exists && req.auth && snap.data().uid === req.auth.uid;
  return { free: !snap.exists || !!mine, why: snap.exists && !mine
    ? 'that name is taken' : '' };
});

/* ------------------------------------------------------------ the downloads
 *
 * lee: *"there should be no link to github on the website"*. The files live
 * on GitHub Releases - that is where the release workflow puts them and where
 * every installed launcher fetches updates from - but the website never says
 * so. Every download on the site is `/get/<version>/<what>`, served by this:
 * a 302 to the real file, worked out from the version alone, because the
 * release names are fixed (`MangaTCT-Setup-<v>.exe`, `mangatct-app-<v>.zip`,
 * `SHA256SUMS`). `latest` is read off the same manifest the launcher reads,
 * cached for five minutes, so the button on the download page works with
 * JavaScript off and needs no version typed into any page.
 *
 * A plain HTTP function and not a Hosting redirect rule, because a redirect
 * rule cannot know what "latest" is, and cannot splice a version into the
 * middle of a file name.
 */
const REPO = 'Lerbernard/MangaTCT';
const MANIFEST = `https://raw.githubusercontent.com/${REPO}/main/manifest.json`;
const NAMES = {
  installer: (v) => `MangaTCT-Setup-${v}.exe`,
  app: (v) => `mangatct-app-${v}.zip`,
  checksums: () => 'SHA256SUMS',
};
let latestCache = { at: 0, version: '' };

async function latestVersion() {
  if (Date.now() - latestCache.at < 5 * 60 * 1000 && latestCache.version) {
    return latestCache.version;
  }
  const r = await fetch(MANIFEST, { headers: { 'cache-control': 'no-cache' } });
  if (!r.ok) throw new Error(`manifest ${r.status}`);
  const m = await r.json();
  const v = m && m.app && String(m.app.version || '');
  if (!/^\d+\.\d+\.\d+$/.test(v)) throw new Error('manifest has no version');
  latestCache = { at: Date.now(), version: v };
  return v;
}

export function downloadTarget(path, latest) {
  const m = /^\/get\/(latest|\d+\.\d+\.\d+)\/(installer|app|checksums)\/?$/.exec(path || '');
  if (!m) return null;
  const v = m[1] === 'latest' ? latest : m[1];
  if (!v) return null;
  return `https://github.com/${REPO}/releases/download/v${v}/${NAMES[m[2]](v)}`;
}

export const get = onRequest({ memory: '128MiB', maxInstances: 5 }, async (req, res) => {
  let latest = '';
  if (req.path.startsWith('/get/latest/')) {
    try { latest = await latestVersion(); } catch (e) {
      console.error('latestVersion', e);
      res.status(503).set('Retry-After', '60')
        .send('The download is not reachable just now. Try again in a minute.');
      return;
    }
  }
  const to = downloadTarget(req.path, latest);
  if (!to) { res.status(404).send('No such download.'); return; }
  // Cached at Hosting's edge for five minutes: a burst of clicks is one
  // function call, and a new release is visible within the same five.
  res.set('Cache-Control', 'public, max-age=300, s-maxage=300');
  res.redirect(302, to);
});

/* ------------------------------------------------------------------ the relay
 *
 * `POST /relay/<backend>/<path>`: the editor's own request to Claude, Gemini
 * or OpenRouter, forwarded with our key. The editor puts its Firebase ID
 * token where the provider's key would go; that is the whole of the
 * handshake. relay.js says what is checked and why the price is not taken
 * here. Long, because a page of translation on a thinking model can take a
 * couple of minutes; not streamed, because the editor does not stream.
 */
export const relay = onRequest({
  memory: '512MiB', timeoutSeconds: 540, maxInstances: 20,
  secrets: [ANTHROPIC_KEY, GEMINI_KEY, OPENROUTER_KEY, CLEAN_TOKEN, CLEAN_URL],
}, async (req, res) => {
  const to = relayTarget(req.path);
  if (!to) { res.status(404).json(errorBody('No such relay.')); return; }
  if (req.method !== 'POST' && req.method !== 'GET') {
    res.status(405).json(errorBody('POST or GET.')); return;
  }
  const token = tokenOf(req.headers);
  if (!token) { res.status(401).json(errorBody('Sign in to MangaTCT to use TCT Coins.')); return; }
  let uid = '';
  try { uid = (await getAuth().verifyIdToken(token)).uid; } catch (e) {
    res.status(401).json(errorBody('Your sign-in has expired - sign in again.')); return;
  }
  const snap = await userRef(uid).get();
  const gate = admit(snap.exists ? snap.data() : null);
  if (!gate.ok) { res.status(gate.status).json(errorBody(gate.why, 'coins')); return; }

  const key = PROVIDER_SECRETS[PROVIDERS[to.backend].secret].value();
  if (!key) { res.status(503).json(errorBody(`The ${to.backend} key is not set on the server.`)); return; }
  // The cleaner's address is ours and set beside its token.
  const url = to.url || (to.backend === 'clean' ? CLEAN_URL.value() : '');
  if (!url) { res.status(503).json(errorBody('The cleaner address is not set on the server.')); return; }
  let body = req.method === 'POST' ? (req.rawBody || JSON.stringify(req.body || {})) : undefined;
  if (body !== undefined) body = withBodyToken(body, to.backend, key);
  let up;
  try {
    up = await fetch(url, { method: req.method, body,
      headers: forwardHeaders(req.headers, to.backend, key) });
  } catch (e) {
    console.error('relay upstream', to.backend, String(e));
    res.status(502).json(errorBody(`${to.backend} did not answer: ${String(e).slice(0, 200)}`)); return;
  }
  // Bytes, not text: the cleaner answers with a PNG.
  const buf = Buffer.from(await up.arrayBuffer());
  const ctype = up.headers.get('content-type') || 'application/json';
  let usage = null;
  if (/json/i.test(ctype)) {
    try { usage = usageOf(JSON.parse(buf.toString('utf8'))); } catch (e) { /* not usage */ }
  }
  console.log(JSON.stringify({ relay: to.backend, path: to.path, uid, status: up.status,
    bytes: buf.length, usage }));
  res.status(up.status).set('content-type', ctype).send(buf);
});

/* ------------------------------------------------------------------ the till
 *
 * The two calls the editor makes. Both are one Firestore transaction around
 * one pure function, and neither of them decides an amount — `purse.js` does.
 */
export const spendCoins = onCall(async (req) => {
  const uid = must(req.auth);
  const coins = Number(req.data && req.data.coins);
  const what = String((req.data && req.data.what) || 'ai').slice(0, 40);
  const where = String((req.data && req.data.page) || '').slice(0, 120);
  const runId = String((req.data && req.data.run) || '').slice(0, 64);
  if (!runId) throw new HttpsError('invalid-argument', 'no run id');
  await ensureUser(uid, req.auth);

  return db.runTransaction(async (tx) => {
    const me = await tx.get(userRef(uid));
    if (!me.exists) throw new HttpsError('failed-precondition', 'no account');
    // The same run charged twice is a double charge, and a client that
    // retries on a timeout will send the same run twice as a matter of
    // course. The run id makes it once.
    const runRef = userRef(uid).collection('runs').doc(runId);
    const run = await tx.get(runRef);
    if (run.exists) {
      return { ok: true, balance: me.data().coins, coins: run.data().coins,
               repeat: true };
    }
    const got = spend(me.data().coins, coins);
    if (!got.ok) {
      throw new HttpsError('failed-precondition', got.why, {
        short: got.short || 0, balance: got.balance });
    }
    tx.set(userRef(uid), { coins: got.balance }, { merge: true });
    tx.set(runRef, { coins: got.coins, what, refunded: 0,
                     at: FieldValue.serverTimestamp() });
    ledger(tx, uid, { kind: 'spend', what, page: where, coins: got.coins,
                      run: runId });
    return { ok: true, balance: got.balance, coins: got.coins };
  });
});

export const refundCoins = onCall(async (req) => {
  const uid = must(req.auth);
  const coins = Number(req.data && req.data.coins);
  const runId = String((req.data && req.data.run) || '').slice(0, 64);
  if (!runId) throw new HttpsError('invalid-argument', 'no run id');

  return db.runTransaction(async (tx) => {
    const runRef = userRef(uid).collection('runs').doc(runId);
    const [me, run] = await tx.getAll(userRef(uid), runRef);
    if (!me.exists || !run.exists) {
      throw new HttpsError('failed-precondition', 'no such run');
    }
    // The cap is what that run took, LESS anything already given back. Without
    // the second half, calling refund twice for the same run refunds it twice.
    const left = (run.data().coins || 0) - (run.data().refunded || 0);
    const got = refund(me.data().coins, coins, left);
    if (!got.ok) throw new HttpsError('invalid-argument', got.why);
    tx.set(userRef(uid), { coins: got.balance }, { merge: true });
    tx.set(runRef, { refunded: (run.data().refunded || 0) + got.coins },
           { merge: true });
    ledger(tx, uid, { kind: 'refund', what: run.data().what || 'ai',
                      coins: got.coins, run: runId });
    return { ok: true, balance: got.balance, coins: got.coins };
  });
});

/* What the editor reads to draw the count. One call, so the balance and the
 * plan are from the same moment. */
export const me = onCall(async (req) => {
  const uid = must(req.auth);
  // The first thing a signed-in page calls, so this is where the document
  // usually comes into existence - and, once the email is verified, where
  // the hundred coins land.
  await ensureUser(uid, req.auth);
  const w = await welcomeIfDue(uid, req.auth);
  const d = (await userRef(uid).get()).data() || {};
  return {
    coins: d.coins || 0, username: d.username || '',
    photo: d.photo || '', packs: PACKS,
    verified: w.verified,
    // What the screens say about the free coins: `due` while they are still
    // to be had (verify the email and they come), `given` on the one call
    // that put them there (so the page can say so), the amount either way.
    welcome: {
      coins: WELCOME, given: !!w.given,
      due: !((d.granted || {}).welcome) && !w.given,
    },
  };
});

/* A verified email is a claim on the token, and a token lasts an hour. The
 * page that just came back from the link in the mail refreshes its token and
 * calls `me`; the editor does the same. Nothing else is needed - there is no
 * "claim my coins" call, because a call a client makes on purpose is a call a
 * client can make for someone else's uid if there is ever a bug in it. */

/* --------------------------------------------------------------- paying
 *
 * Stripe Checkout, which is one integration for cards, Apple Pay, Google Pay,
 * Link and the local methods enabled on the account. lee: *"for payment allow
 * many difrent ways to pay"* — that is a switch in the Stripe dashboard, not
 * code here, which is the whole reason to use Checkout rather than build a
 * card form.
 */
export const checkout = onCall({ secrets: [STRIPE_KEY] }, async (req) => {
  const uid = must(req.auth);
  const what = String((req.data && req.data.buy) || '');
  await ensureUser(uid, req.auth);
  const q = pack(what);
  const ids = await priceIds();
  const price = ids.packs[what];
  if (!q || !price) {
    throw new HttpsError('invalid-argument', 'no such pack');
  }

  const snap = await userRef(uid).get();
  let customer = snap.exists ? snap.data().stripeCustomer : '';
  if (customer) {
    // The id we hold can stop existing without us doing anything. A customer
    // who asks Stripe to delete their data has their Customer object deleted
    // in OUR account too, and a Checkout Session naming a deleted customer
    // fails — which would read to them as "the buy button is broken" for ever.
    const had = await stripe().customers.retrieve(customer).catch(() => null);
    if (!had || had.deleted) customer = '';
  }
  if (!customer) {
    const made = await stripe().customers.create({
      metadata: { uid },
      email: (req.auth.token && req.auth.token.email) || undefined,
    });
    customer = made.id;
    await userRef(uid).set({ stripeCustomer: customer }, { merge: true });
  }

  const session = await stripe().checkout.sessions.create({
    mode: 'payment',
    customer,
    line_items: [{ price, quantity: 1 }],
    // The uid travels with the payment, on the OBJECT the webhook will read.
    // A webhook that had to look the customer up by email would be a webhook
    // that credits the wrong account the day somebody changes theirs.
    client_reference_id: uid,
    metadata: { uid, buy: what },
    payment_intent_data: { metadata: { uid, buy: what } },
    allow_promotion_codes: true,
    // Stripe is the merchant of record: they calculate, collect, file and
    // remit sales tax, VAT and GST in 80+ countries, and carry the fraud and
    // dispute load. The customer's statement reads `LINK.COM* MANGATCT` and
    // their receipts come from Link, which is the visible cost of it.
    managed_payments: { enabled: true },
    success_url: `${SITE.value()}/account.html?paid=1`,
    cancel_url: `${SITE.value()}/pricing.html`,
  });
  return { url: session.url };
});

/* ---------------------------------------------------------------- the webhook
 *
 * The only thing that puts coins in. It is a plain HTTP function because
 * Stripe posts to it, and the FIRST thing it does is verify the signature: a
 * webhook nobody verifies is an endpoint that grants coins to anyone who
 * posts to it, and the body is attacker-controlled until that check passes.
 *
 * `rawBody` and not the parsed body — the signature is over the bytes.
 */
export const stripeWebhook = onRequest(
  { secrets: [STRIPE_KEY, STRIPE_WEBHOOK_SECRET] },
  async (rq, rs) => {
    let event;
    try {
      event = stripe().webhooks.constructEvent(
        rq.rawBody, rq.headers['stripe-signature'],
        STRIPE_WEBHOOK_SECRET.value());
    } catch (e) {
      // Logged, not just answered. A rejected signature used to return 400
      // and write nothing, so the function's own log showed two blank warning
      // lines and the only way to find out what had happened was Stripe's
      // dashboard. The most likely cause is a secret that does not match, and
      // the second most likely is that it matches but was stored with
      // something extra on the end — so the LENGTH goes in the line. Never
      // the secret itself.
      console.error('webhook signature rejected:', e.message,
                    '| secret length:',
                    (STRIPE_WEBHOOK_SECRET.value() || '').length,
                    '| body bytes:', (rq.rawBody || '').length,
                    '| header present:', !!rq.headers['stripe-signature']);
      rs.status(400).send(`bad signature: ${e.message}`);
      return;
    }

    try {
      await handle(event);
    } catch (e) {
      // 500 so Stripe retries. Everything that moves coins is keyed on an id
      // it will send again, so a retry is safe — see `granted` below.
      console.error('webhook', event.type, e);
      rs.status(500).send('retry');
      return;
    }
    rs.json({ received: true });
  });

async function handle(event) {
  const o = event.data.object;

  // A one-off pack. Credited on the SESSION, not on the payment intent: the
  // session is the only object that carries `client_reference_id`.
  if (event.type === 'checkout.session.completed' && o.mode === 'payment') {
    const uid = o.client_reference_id || (o.metadata && o.metadata.uid);
    const q = pack(o.metadata && o.metadata.buy);
    if (uid && q) await credit(uid, q.coins, `pack ${q.id}`, o.id);
    return;
  }

  /* Money going back. Under Managed Payments this is not always our decision:
   * customers ask Link, and Stripe may refund without our approval if a
   * support escalation goes unanswered for 48 hours. So the coins have to come
   * back off the account when it happens, or "buy coins, translate a series,
   * ask for your money back" is free work, repeatable.
   *
   * Keyed on the charge id, so the several events a refund can produce — and
   * Stripe's retries of each — take the coins off exactly once. A SECOND,
   * larger refund on the same charge is a different amount, and the key
   * carries it, so a partial refund followed by the rest is handled too. */
  if (event.type === 'charge.refunded') {
    const back = Number(o.amount_refunded) || 0;
    const all = Number(o.amount) || 0;
    if (!back) return;
    const [uid, coins, what] = await whatItBought(o);
    if (!uid || !coins) return;
    const take = refundedShare(coins, back, all);
    if (!take) return;
    await db.runTransaction(async (tx) => {
      const me = await tx.get(userRef(uid));
      if (!me.exists) return;
      const d = me.data();
      const once = `refund_${o.id}_${back}`;
      if ((d.granted || {})[once]) return;
      // Anything already taken off for an earlier, smaller refund of this
      // same charge is not taken off twice.
      const already = Number((d.clawed || {})[o.id] || 0);
      const owed = take - already;
      if (owed <= 0) {
        tx.set(userRef(uid), { [`granted.${once}`]: true }, { merge: true });
        return;
      }
      const got = clawback(d.coins, owed);
      if (!got.ok) return;
      tx.set(userRef(uid), {
        coins: got.balance, [`granted.${once}`]: true,
        [`clawed.${o.id}`]: take,
      }, { merge: true });
      ledger(tx, uid, { kind: 'clawback', what: `${what} — refunded`,
                        coins: got.coins, charge: o.id });
    });
    return;
  }

}

/* Which account a charge belongs to and how many coins it put there.
 *
 * A charge does not say. It points at the payment intent, which carries the
 * metadata we put on it when the Checkout Session was made. Asked of Stripe
 * rather than remembered here, so it is right even for a charge from before
 * this account existed.
 */
async function whatItBought(charge) {
  try {
    if (!charge.payment_intent) return [];
    const pi = await stripe().paymentIntents.retrieve(
      String(charge.payment_intent));
    const q = pack(pi.metadata && pi.metadata.buy);
    const uid = pi.metadata && pi.metadata.uid;
    return q && uid ? [uid, q.coins, `pack ${q.id}`] : [];
  } catch (e) {
    // Throwing would 500 and make Stripe retry, which is right: a lookup that
    // failed on a timeout should be tried again rather than quietly letting
    // the coins stay.
    console.error('whatItBought', charge.id, e);
    throw e;
  }
}

async function credit(uid, coins, what, once) {
  await db.runTransaction(async (tx) => {
    const me = await tx.get(userRef(uid));
    if (!me.exists) return;
    const d = me.data();
    // Stripe retries a webhook that did not answer 200, and a function that
    // timed out after doing its work has done its work. The event's own id
    // makes it once.
    if ((d.granted || {})[once]) return;
    const got = buy(d.coins, coins);
    if (!got.ok) return;
    tx.set(userRef(uid), { coins: got.balance, [`granted.${once}`]: true },
           { merge: true });
    ledger(tx, uid, { kind: 'credit', what, coins: got.coins });
  });
}
