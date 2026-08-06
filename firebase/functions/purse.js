/* The decisions, with no Firebase in them.

   Everything in this file is a pure function: hand it what the database says
   and what was asked for, and it hands back what should happen. `index.js`
   does the talking to Firestore and Stripe and nothing else.

   That split is not tidiness. The rules and the transactions can only be
   tested against a real emulator, and the emulator is a 60MB download from
   Google's storage — fine on a laptop, not available everywhere. The part
   that decides how much money moves does not need any of that, and it is the
   part that must not be wrong. So it lives here, where it can be tested
   anywhere, exhaustively, in milliseconds.
*/

/* ---------------------------------------------------------------- usernames

   lee: *"allow the user to secelt their usernam that need to be unique"*.

   Unique means unique to a PERSON, not to a byte string. `Lee`, `lee` and
   `LEE` are one name; letting them be three is how you get an impersonation
   problem on day one. So a name has a display form, which is what somebody
   typed, and a key, which is what uniqueness is checked against. */

export const USERNAME_MIN = 3;
export const USERNAME_MAX = 20;

// Names nobody may take. Not a morality list — these are the ones that would
// let somebody be mistaken for the service itself, or that are already a URL
// on the site.
export const RESERVED = new Set([
  'admin', 'administrator', 'root', 'system', 'support', 'help', 'staff',
  'mod', 'moderator', 'official', 'mangatct', 'tct', 'team',
  'billing', 'payment', 'payments', 'account', 'accounts', 'settings',
  'login', 'signin', 'signup', 'register', 'logout', 'api', 'www', 'app',
  'about', 'pricing', 'terms', 'privacy', 'contact', 'null', 'undefined',
  'me', 'you', 'anonymous', 'deleted',
]);

/* Confusable characters folded together before the uniqueness check. `rn` for
   `m` cannot be helped without banning half the dictionary, but a zero for an
   O and the whole `1 / l / i` family are free to catch and are the ones
   actually used — `adm1n` and `admin` are the same claim about who you are. */
const FOLD = {
  '0': 'o', '3': 'e', '4': 'a', '5': 's', '7': 't',
  '1': 'l', 'i': 'l',
};

export function usernameKey(name) {
  const s = String(name == null ? '' : name).trim().toLowerCase()
    .normalize('NFKC')
    // A name is one word. Underscores, hyphens and dots are punctuation
    // somebody put in it, and `lee.m`, `lee_m` and `lee-m` are one person as
    // far as being mistaken for each other goes.
    .replace(/[._-]/g, '');
  return [...s].map((c) => FOLD[c] || c).join('');
}

/* The reserved list is written the way a person reads it, and checked the way
   a name is compared. Storing it pre-folded would mean writing `admln` in the
   list above and hoping nobody ever tidied it back; deriving it here means the
   readable list and the check can never drift apart. */
const RESERVED_KEYS = new Set([...RESERVED].map(usernameKey));

export function checkUsername(name) {
  const raw = String(name == null ? '' : name).trim();
  if (raw.length < USERNAME_MIN) {
    return { ok: false, why: `at least ${USERNAME_MIN} characters` };
  }
  if (raw.length > USERNAME_MAX) {
    return { ok: false, why: `at most ${USERNAME_MAX} characters` };
  }
  if (!/^[A-Za-z0-9._-]+$/.test(raw)) {
    return { ok: false, why: 'letters, numbers, dot, dash and underscore only' };
  }
  if (!/^[A-Za-z0-9]/.test(raw) || !/[A-Za-z0-9]$/.test(raw)) {
    return { ok: false, why: 'start and end with a letter or a number' };
  }
  if (/[._-]{2}/.test(raw)) {
    return { ok: false, why: 'no two punctuation marks in a row' };
  }
  const key = usernameKey(raw);
  // A name that folds away to nothing, or to nothing but punctuation, is not
  // a name — and it would collide with every other one that does.
  if (key.length < USERNAME_MIN) {
    return { ok: false, why: `at least ${USERNAME_MIN} letters or numbers` };
  }
  if (RESERVED_KEYS.has(key)) return { ok: false, why: 'that one is reserved' };
  return { ok: true, name: raw, key };
}

/* ------------------------------------------------------------------ the till

   One balance, and coins that do not expire.

   There is no subscription and so there is no monthly allowance, no ceiling
   over it, no expiry date and no second pocket to keep the perishable half
   in. Every coin on an account was bought outright, on purpose, in one go —
   which makes "your coins never expire" the whole of the rule rather than a
   sentence with a footnote.

   That is worth saying because this file has had three other versions of it.
   One balance with a three-month cap had a bug: the cap counted everything,
   so a big pack plus a subscription meant being charged every month and
   granted nothing. Two pockets fixed it and cost a second number on every
   account, a rule about which pocket a spend comes out of, and an expiry that
   had to be explained on the pricing page. None of that has to exist if
   nothing expires.

   `index.js` runs these inside a Firestore transaction, which is what makes
   them atomic; what makes them RIGHT is here, where it can be argued with. */

/* A coin is a whole coin. Truncating a fraction instead of refusing it looks
   harmless and is how 0.5 becomes free: a caller that can send fractions can
   send a million of them. */
function whole(n) {
  return Number.isInteger(n) && Number.isFinite(n) ? n : null;
}

export function spend(balance, coins) {
  const n = whole(coins);
  if (n === null || n <= 0) {
    return { ok: false, why: 'that is not an amount', balance };
  }
  const have = Math.trunc(Number(balance) || 0);
  if (have < n) {
    // Never into the red on a spend. The whole price is taken before a run
    // starts, so this is asked BEFORE anything is bought.
    return { ok: false, why: 'not enough coins', short: n - have, balance: have };
  }
  return { ok: true, balance: have - n, coins: n };
}

export function refund(balance, coins, spentEarlier) {
  const n = whole(coins);
  if (n === null || n <= 0) {
    return { ok: false, why: 'that is not an amount', balance };
  }
  // A refund can never be bigger than what that run took. Without this, a
  // client that can call `refund` can call it with any number it likes and the
  // balance is decoration again — the function is authenticated, but being
  // signed in as yourself is exactly the position an attacker is in.
  const cap = Math.trunc(Number(spentEarlier) || 0);
  if (n > cap) {
    return { ok: false, why: 'more than that run cost', balance };
  }
  return { ok: true, balance: Math.trunc(Number(balance) || 0) + n, coins: n };
}

/* ----------------------------------------------------------------- the packs

   lee: *"fuck teh subcription, it too omplicated jus have teh pacjks"*.

   Four sizes, bought outright, no plan behind any of them. A hundred coins is
   a dollar of face value — see `coins.py`, where every price is a real
   provider cost, doubled — so the smallest is exactly face value and it is the
   only thing here sold at it. Buying more at once is the only concession a
   one-off purchase can make, so the bonus climbs: nothing, 5%, 7.6%, 8%.

   The tests below hold that ladder in place. A price cannot be edited into an
   order nobody should buy. */
export const PACKS = [
  { id: 'pack1', coins: 500, usd: 4.99 },
  { id: 'pack2', coins: 1050, usd: 9.99 },
  { id: 'pack3', coins: 2150, usd: 19.99 },
  { id: 'pack4', coins: 5400, usd: 49.99 },
];

export function pack(id) {
  return PACKS.find((q) => q.id === id) || null;
}

/* Coins in. Not capped and they do not expire: bought outright, this minute,
   on purpose. Refusing part of a purchase somebody just made is not a policy,
   it is a bug with a reason. */
export function buy(balance, coins) {
  const have = Math.trunc(Number(balance) || 0);
  const add = whole(coins);
  if (add === null || add <= 0) {
    return { ok: false, why: 'that is not an amount', balance: have };
  }
  return { ok: true, balance: have + add, coins: add };
}

/* --------------------------------------------------------------- refunds in

   Money going back the other way, which is a different question from the
   `refund` above. That one gives coins back for work that was paid for and
   never done. This one takes coins away because the PURCHASE was undone.

   It matters more under Managed Payments than it would otherwise. Stripe is
   the merchant of record there, customers ask Link for refunds rather than
   asking us, and Stripe's own terms say that if we do not answer a support
   escalation within 48 hours they may refund without our approval. So a
   refund is no longer a thing we decide to do; it is a thing we are told
   about. Without this, "buy three thousand coins, translate a series, ask
   Link for your money back" is a complete and repeatable way to get the work
   for nothing. */

export function refundedShare(coins, refunded, total) {
  const all = Math.trunc(Number(total) || 0);
  const back = Math.trunc(Number(refunded) || 0);
  const had = Math.trunc(Number(coins) || 0);
  if (had <= 0 || all <= 0 || back <= 0) return 0;
  // Anything at or over the whole charge is the whole purchase. This is not
  // only the tidy case: tax is withheld and returned with a Managed Payments
  // refund, so the money back can genuinely exceed the money in, and without
  // this line the arithmetic below would claw back more coins than the
  // purchase ever gave.
  if (back >= all) return had;
  // Rounded DOWN, so a part refund never claws back more of the coins than it
  // did of the money. Every other rounding in this system is up, and every
  // one of them is up because it favours the customer; this one is down for
  // the same reason.
  return Math.floor((had * back) / all);
}

export function clawback(balance, coins) {
  const n = whole(coins);
  if (n === null || n <= 0) {
    return { ok: false, why: 'that is not an amount', balance };
  }
  // Allowed to go NEGATIVE, and that is the point. Somebody who bought 3,000
  // coins, spent 500 and then took all their money back is at minus 500 — not
  // at zero, which would mean the 500 coins of work were free and the trick
  // works again tomorrow. Nothing collects that debt; `spend` refuses until
  // the balance is positive again, which is the right amount of consequence.
  return { ok: true, balance: Math.trunc(Number(balance) || 0) - n, coins: n };
}
