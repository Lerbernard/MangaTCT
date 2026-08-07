/* The money decisions, argued with.

   These run anywhere — no emulator, no network, no Firebase. That is the
   point of `purse.js` being pure: the part that decides how much money moves
   is the part that must not be wrong, and it should not need a 60MB download
   to find out whether it is.

   Run:  npx vitest run tests/functions
*/
import { describe, expect, it } from 'vitest';
import {
  PACKS, RESERVED, USERNAME_MAX, USERNAME_MIN, buy, checkUsername, clawback,
  looksLikePriceId, pack, refund, refundedShare, spend, usernameKey,
} from '../../firebase/functions/purse.js';

describe('a username is unique to a person, not to a byte string', () => {
  it('folds case', () => {
    expect(usernameKey('Lee')).toBe(usernameKey('LEE'));
    expect(usernameKey('lee')).toBe('lee');
  });

  it('folds the punctuation somebody put in it', () => {
    // lee.m, lee_m, lee-m and leem are one person as far as being mistaken
    // for each other goes.
    const one = usernameKey('lee.m');
    expect(usernameKey('lee_m')).toBe(one);
    expect(usernameKey('lee-m')).toBe(one);
    expect(usernameKey('leem')).toBe(one);
  });

  it('folds the digits people use as letters', () => {
    expect(usernameKey('l33t')).toBe(usernameKey('leet'));
    // 1, l and i are the classic confusable set — all three fold together.
    expect(usernameKey('1ee')).toBe(usernameKey('lee'));
    expect(usernameKey('adm1n')).toBe(usernameKey('admin'));
    expect(usernameKey('lil')).toBe(usernameKey('l1l'));
    expect(usernameKey('b0b')).toBe(usernameKey('bob'));
    expect(usernameKey('m1ke')).toBe(usernameKey('mlke'));
  });

  it('folds the unicode that looks like ASCII', () => {
    // Full-width Latin is a different code point and the same picture.
    expect(usernameKey('ｌｅｅ')).toBe('lee');
  });

  it('keeps two genuinely different names apart', () => {
    expect(usernameKey('lee')).not.toBe(usernameKey('leo'));
    expect(usernameKey('anna')).not.toBe(usernameKey('anne'));
  });
});

describe('what a username may be', () => {
  it('a plain one is fine', () => {
    const got = checkUsername('lee');
    expect(got.ok).toBe(true);
    expect(got.name).toBe('lee');       // what they typed is what is shown
    expect(got.key).toBe('lee');        // what uniqueness is checked against
  });

  it('keeps the capitals somebody chose', () => {
    expect(checkUsername('LeeM').name).toBe('LeeM');
    expect(checkUsername('LeeM').key).toBe('leem');
  });

  it('is long enough to be a name and short enough to fit', () => {
    expect(checkUsername('x'.repeat(USERNAME_MIN - 1)).ok).toBe(false);
    expect(checkUsername('x'.repeat(USERNAME_MIN)).ok).toBe(true);
    expect(checkUsername('x'.repeat(USERNAME_MAX)).ok).toBe(true);
    expect(checkUsername('x'.repeat(USERNAME_MAX + 1)).ok).toBe(false);
  });

  it('is letters, numbers and a little punctuation', () => {
    expect(checkUsername('lee m').ok).toBe(false);      // no spaces
    expect(checkUsername('lee@m').ok).toBe(false);
    expect(checkUsername('lee/m').ok).toBe(false);      // would be a URL
    expect(checkUsername('<script>').ok).toBe(false);
    expect(checkUsername('lee.m_1-x').ok).toBe(true);
  });

  it('does not start or end with punctuation', () => {
    // A leading dot hides a name in a file listing and a trailing one reads
    // as a typo in every sentence it appears in.
    expect(checkUsername('.lee').ok).toBe(false);
    expect(checkUsername('lee.').ok).toBe(false);
    expect(checkUsername('-lee').ok).toBe(false);
  });

  it('does not run punctuation together', () => {
    // `lee..m` and `lee.m` fold to the same key, so allowing both means one
    // of them can never be claimed and nobody can tell which.
    expect(checkUsername('lee..m').ok).toBe(false);
    expect(checkUsername('lee_-m').ok).toBe(false);
  });

  it('is not a name that would be mistaken for us', () => {
    for (const bad of ['admin', 'Admin', 'ADMIN', 'support', 'billing',
                       'mangatct', 'a.d.m.i.n', 'manga-tct']) {
      expect(checkUsername(bad).ok, bad).toBe(false);
    }
    expect(RESERVED.has('admin')).toBe(true);
  });

  it('is not a reserved name with a digit standing in for a letter', () => {
    // `adm1n` is the same claim about who you are as `admin`, and it is the
    // one an impersonator actually types.
    for (const bad of ['adm1n', 'supp0rt', '5upport', 'b1lling', 'te4m',
                       'mangat<t'.replace('<', 'c'), '0fficial']) {
      expect(checkUsername(bad).ok, bad).toBe(false);
    }
  });

  it('catches every name on the reserved list', () => {
    // The list is written to be read; the check runs on folded keys. If those
    // two ever came apart, a name on the list would quietly be free.
    for (const r of RESERVED) {
      expect(checkUsername(r).ok, r).toBe(false);
      expect(checkUsername(r.toUpperCase()).ok, r).toBe(false);
    }
  });

  it('has no reserved entry that another one already covers', () => {
    const keys = [...RESERVED].map(usernameKey);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('is not something that folds away to nothing', () => {
    // `1.0.1` is three characters of punctuation and three digits that fold
    // to letters; `..-..` folds to the empty string, and an empty key would
    // collide with every other empty key.
    expect(checkUsername('...').ok).toBe(false);
    expect(checkUsername('a.b').ok).toBe(false);   // key is "ab", too short
  });

  it('says WHY, every time it says no', () => {
    for (const bad of ['', 'x', 'x'.repeat(99), 'lee m', '.lee', 'admin']) {
      const got = checkUsername(bad);
      expect(got.ok).toBe(false);
      expect(typeof got.why).toBe('string');
      expect(got.why.length).toBeGreaterThan(0);
    }
  });

  it('does not fall over on things that are not strings', () => {
    for (const junk of [null, undefined, 42, {}, []]) {
      expect(checkUsername(junk).ok).toBe(false);
    }
  });
});

describe('spending', () => {
  it('takes the coins', () => {
    expect(spend(100, 30)).toEqual({ ok: true, balance: 70, coins: 30 });
  });

  it('allows spending the last coin', () => {
    expect(spend(30, 30)).toEqual({ ok: true, balance: 0, coins: 30 });
  });

  it('refuses one coin more than there is, and says how short', () => {
    const got = spend(29, 30);
    expect(got.ok).toBe(false);
    expect(got.short).toBe(1);
    expect(got.balance).toBe(29);
  });

  it('never goes into the red', () => {
    for (const [have, want] of [[0, 1], [5, 6], [1, 1000]]) {
      expect(spend(have, want).ok).toBe(false);
    }
  });

  it('cannot be spent out of a debt', () => {
    // After a refunded purchase the balance can be negative. Nothing collects
    // that debt; refusing to spend is the whole consequence of it.
    expect(spend(-500, 1).ok).toBe(false);
    expect(spend(-500, 1).short).toBe(501);
  });

  it('refuses a fraction rather than truncating it', () => {
    // Truncating looks harmless and is how 0.5 becomes free: a caller that
    // can send fractions can send a million of them.
    expect(spend(100, 0.5).ok).toBe(false);
    expect(spend(100, 30.5).ok).toBe(false);
  });

  it('refuses nothing, and negatives', () => {
    expect(spend(100, 0).ok).toBe(false);
    expect(spend(100, -30).ok).toBe(false);
    expect(spend(100, -30).balance).toBe(100);   // a negative spend is a mint
  });

  it('refuses the numbers that are not numbers', () => {
    for (const bad of [NaN, Infinity, -Infinity, '30', null, undefined, {}]) {
      expect(spend(100, bad).ok, String(bad)).toBe(false);
    }
  });

  it('reads a rubbish balance as nothing rather than as free money', () => {
    for (const bad of [undefined, null, NaN, 'lots']) {
      expect(spend(bad, 1).ok, String(bad)).toBe(false);
    }
  });
});

describe('refunding a run that did not happen', () => {
  it('gives the coins back', () => {
    expect(refund(70, 30, 30)).toEqual({ ok: true, balance: 100, coins: 30 });
  });

  it('allows exactly what the run took', () => {
    expect(refund(0, 30, 30).ok).toBe(true);
  });

  it('refuses one coin more than the run took', () => {
    // Without this, anybody signed in as themselves can print money — and
    // being signed in as yourself is exactly the position an attacker is in.
    expect(refund(0, 31, 30).ok).toBe(false);
  });

  it('refuses when the run took nothing', () => {
    expect(refund(100, 1, 0).ok).toBe(false);
  });

  it('refuses a fraction, nothing, and a negative', () => {
    expect(refund(0, 0.5, 30).ok).toBe(false);
    expect(refund(0, 0, 30).ok).toBe(false);
    expect(refund(0, -5, 30).ok).toBe(false);
  });

  it('leaves the balance alone when it says no', () => {
    expect(refund(70, 999, 30).balance).toBe(70);
  });
});

describe('the packs', () => {
  it('are the only thing sold — there is no subscription', () => {
    // lee: *"fuck teh subcription, it too omplicated jus have teh pacjks"*.
    // Which takes with it the monthly allowance, the ceiling over it, the
    // expiry date, and the second pocket that existed to hold the perishable
    // half. Nothing here may quietly grow a plan back.
    const words = JSON.stringify(PACKS).toLowerCase();
    for (const w of ['month', 'tier', 'plan', 'subscription', 'recurring']) {
      expect(words, w).not.toContain(w);
    }
  });

  it('are priced in whole coins, at prices with cents in them', () => {
    for (const q of PACKS) {
      // There is no fraction of a coin anywhere in this system. There are
      // fractions of a DOLLAR, because $4.99 is what a price looks like.
      expect(Number.isInteger(q.coins), q.id).toBe(true);
      expect(q.coins, q.id).toBeGreaterThan(0);
      // Compared with a tolerance, because `19.99 * 100` is 1998.9999999999998
      // in binary floating point — which is exactly why no BALANCE here is
      // ever a float.
      expect(Math.abs(q.usd * 100 - Math.round(q.usd * 100)), q.id)
        .toBeLessThan(1e-6);
    }
  });

  it('give every id once', () => {
    const ids = PACKS.map((q) => q.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('never sell a coin for more than a cent', () => {
    // Face value is the ceiling on price. A hundred coins is a dollar — see
    // `coins.py`, where every figure is a real provider cost, doubled — so no
    // arrangement of these numbers can charge more than that.
    for (const q of PACKS) {
      expect(q.coins / q.usd, q.id).toBeGreaterThanOrEqual(100);
    }
  });

  it('sell the smallest at face value, the only thing sold at it', () => {
    const [small] = [...PACKS].sort((a, b) => a.usd - b.usd);
    expect(small.coins / (small.usd * 100)).toBeCloseTo(1.00, 2);
  });

  it('make a bigger pack better value than a smaller one', () => {
    // Buying more at once is the only concession a one-off purchase can make,
    // so here it has to be real. A bigger pack that was worse value is a
    // pack nobody should buy, and somebody would.
    const sorted = [...PACKS].sort((a, b) => a.usd - b.usd);
    for (let i = 1; i < sorted.length; i += 1) {
      expect(sorted[i].coins / sorted[i].usd, sorted[i].id)
        .toBeGreaterThan(sorted[i - 1].coins / sorted[i - 1].usd);
    }
  });

  it('are looked up by id, and an unknown id is nothing', () => {
    expect(pack('pack1').coins).toBe(500);
    for (const bad of ['', null, undefined, 'nope', '__proto__', 'toString']) {
      expect(pack(bad), String(bad)).toBe(null);
    }
  });
});

describe('coins in', () => {
  it('are added', () => {
    expect(buy(0, 5400)).toEqual({ ok: true, balance: 5400, coins: 5400 });
  });

  it('are not capped and do not expire', () => {
    // Bought outright, this minute, on purpose. Refusing part of a purchase
    // somebody just made is not a policy, it is a bug with a reason — and
    // there is no longer any rule anywhere that takes a coin back.
    const huge = 999999;
    expect(buy(huge, 5400).balance).toBe(huge + 5400);
  });

  it('refuse a fraction, nothing, and a negative', () => {
    for (const bad of [0.5, 0, -100, NaN, '100', null, undefined]) {
      expect(buy(1000, bad).ok, String(bad)).toBe(false);
      expect(buy(1000, bad).balance, String(bad)).toBe(1000);
    }
  });
});

describe('refundedShare', () => {
  it('takes all the coins back on a full refund', () => {
    expect(refundedShare(3000, 2600, 2600)).toBe(3000);
  });

  it('takes all of them when the refund somehow exceeds the charge', () => {
    // Tax withheld and returned can make the numbers not line up. More money
    // back than went in is still, unambiguously, all of it.
    expect(refundedShare(3000, 3000, 2600)).toBe(3000);
  });

  it('takes half back on half a refund', () => {
    expect(refundedShare(3000, 1300, 2600)).toBe(1500);
  });

  it('rounds a part refund DOWN', () => {
    // Every other rounding in this system is up, and every one of them is up
    // because it favours the customer. This one is down for the same reason:
    // rounding up would claw back more of the coins than it did of the money.
    expect(refundedShare(10, 1, 3)).toBe(3);      // 3.33… → 3
    expect(refundedShare(100, 1, 7)).toBe(14);    // 14.28… → 14
  });

  it('never takes back more coins than the purchase gave', () => {
    for (const [c, r, t] of [[500, 999, 500], [500, 500, 1], [1, 99, 1]]) {
      expect(refundedShare(c, r, t)).toBeLessThanOrEqual(c);
    }
  });

  it('takes nothing back for nothing refunded', () => {
    expect(refundedShare(3000, 0, 2600)).toBe(0);
    expect(refundedShare(3000, -100, 2600)).toBe(0);
  });

  it('survives a charge of nothing rather than dividing by it', () => {
    expect(refundedShare(3000, 100, 0)).toBe(0);
    expect(Number.isFinite(refundedShare(3000, 100, 0))).toBe(true);
  });

  it('survives the numbers that are not numbers', () => {
    for (const bad of [null, undefined, NaN, 'lots', {}]) {
      expect(refundedShare(bad, 100, 100), String(bad)).toBe(0);
      expect(refundedShare(100, bad, 100), String(bad)).toBe(0);
      expect(refundedShare(100, 100, bad), String(bad)).toBe(0);
    }
  });

  it('always returns a whole number', () => {
    for (let r = 1; r <= 20; r += 1) {
      expect(Number.isInteger(refundedShare(37, r, 21)), String(r)).toBe(true);
    }
  });
});

describe('clawback — a purchase undone', () => {
  it('takes the coins off', () => {
    expect(clawback(3000, 3000)).toEqual({ ok: true, balance: 0, coins: 3000 });
  });

  it('goes NEGATIVE when they have already been spent', () => {
    // The whole point. Somebody who bought 3,000, spent 500 and then took all
    // their money back is at minus 500 — not at zero, which would mean the 500
    // coins of work were free and the trick works again tomorrow.
    expect(clawback(2500, 3000).balance).toBe(-500);
  });

  it('leaves an account that cannot pay unable to start a run', () => {
    const after = clawback(2500, 3000).balance;
    expect(spend(after, 1).ok).toBe(false);
    expect(spend(after, 1).short).toBe(501);
  });

  it('lets a top-up clear the debt and nothing more', () => {
    const owing = clawback(0, 500).balance;        // −500
    expect(buy(owing, 500).balance).toBe(0);
    expect(buy(owing, 700).balance).toBe(200);
  });

  it('refuses a fraction, nothing, and a negative', () => {
    for (const bad of [0.5, 0, -100, NaN, '100', null, undefined]) {
      expect(clawback(1000, bad).ok, String(bad)).toBe(false);
    }
  });

  it('leaves the balance alone when it says no', () => {
    expect(clawback(1000, 0).balance).toBe(1000);
    expect(clawback(1000, -5).balance).toBe(1000);
  });
});

describe('a price id is checked for being one before it is written', () => {
  /* The bug this came from: a placeholder ellipsis was pasted in place of all
     four ids, `seed.js` wrote them without complaint, and the live buy button
     answered 500 with `No such price: '…'` in a log nobody was watching. */

  it('takes a real one', () => {
    expect(looksLikePriceId('price_1U1fCAPRGT41DjkSNiPmuk4f')).toBe(true);
  });

  it('refuses the placeholder that caused this', () => {
    expect(looksLikePriceId('…')).toBe(false);
    expect(looksLikePriceId('price_…')).toBe(false);
    expect(looksLikePriceId('...')).toBe(false);
    expect(looksLikePriceId('price_XXXX')).toBe(false);   // too short
  });

  it('refuses the other id on the product page', () => {
    // `prod_...` is the one right next to it, and it is the wrong one — a
    // Checkout Session takes a price, not a product.
    expect(looksLikePriceId('prod_V1JWOROYDWUVHX')).toBe(false);
  });

  it('refuses nothing at all', () => {
    for (const bad of ['', ' ', null, undefined, 0, {}, [], 'price_']) {
      expect(looksLikePriceId(bad), String(bad)).toBe(false);
    }
  });

  it('refuses one with whitespace or quotes still attached', () => {
    // What a paste out of a terminal or a document brings with it.
    expect(looksLikePriceId(' price_1U1fCAPRGT41DjkSNiPmuk4f')).toBe(false);
    expect(looksLikePriceId('price_1U1fCAPRGT41DjkSNiPmuk4f\n')).toBe(false);
    expect(looksLikePriceId('"price_1U1fCAPRGT41DjkSNiPmuk4f"')).toBe(false);
  });

  it('does not claim to know whether the id exists', () => {
    // Shape only. A well-formed sandbox id passes here and fails at Stripe,
    // and that is the division of labour on purpose — this check must never
    // grow into something that pretends to have asked.
    expect(looksLikePriceId('price_1AAAAAAAAAAAAAAAAAAAAAAA')).toBe(true);
  });
});
