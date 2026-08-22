/* What the customer's own machine is allowed to touch.

   The editor runs on their computer, so everything it can reach they can
   reach: with a browser console and their own ID token they can send whatever
   request the rules permit. These tests are that boundary, asked of a real
   Firestore - the emulator runs the same rules engine production does, so a
   rule that passes here is a rule that holds there.

   Run:  npx firebase emulators:exec --only firestore --project mangatctproject \
           "npx vitest run tests/rules"
*/
import { readFileSync } from 'node:fs';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import {
  assertFails, assertSucceeds, initializeTestEnvironment,
} from '@firebase/rules-unit-testing';
import {
  collection, doc, getDoc, getDocs, setDoc, updateDoc, deleteDoc,
} from 'firebase/firestore';

let env;

beforeAll(async () => {
  env = await initializeTestEnvironment({
    projectId: 'mangatctproject',
    firestore: {
      rules: readFileSync('firebase/firestore.rules', 'utf8'),
      host: '127.0.0.1',
      port: 8080,
    },
  });
});

afterAll(async () => { await env.cleanup(); });

/* The state a signed-up person is really in: a user document made by the auth
   trigger, with a balance the functions own. Written past the rules, the way
   the Admin SDK writes it. */
beforeEach(async () => {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await setDoc(doc(db, 'users/lee'), {
      username: 'lee', displayName: 'lee', photo: '', coins: 500,
      plan: { tier: 'none', status: 'none' }, stripeCustomer: 'cus_1',
    });
    await setDoc(doc(db, 'users/lee/ledger/e1'), { coins: 20, what: 'translate' });
    await setDoc(doc(db, 'usernames/lee'), { uid: 'lee' });
    await setDoc(doc(db, 'config/prices'), { tiers: [] });
  });
});

const me = () => env.authenticatedContext('lee').firestore();
const someoneElse = () => env.authenticatedContext('mallory').firestore();
const nobody = () => env.unauthenticatedContext().firestore();

describe('the balance', () => {
  it('can be read by the person it belongs to', async () => {
    const snap = await assertSucceeds(getDoc(doc(me(), 'users/lee')));
    expect(snap.data().coins).toBe(500);
  });

  it('cannot be written by them', async () => {
    // The whole point. Anything that can reach Firestore with lee's token can
    // send this, so it has to be the database that says no.
    await assertFails(updateDoc(doc(me(), 'users/lee'), { coins: 1000000 }));
  });

  it('cannot be written by them alongside something that is allowed', async () => {
    // The one that gets past a rule written as "must include displayName".
    await assertFails(updateDoc(doc(me(), 'users/lee'),
      { displayName: 'lee', coins: 1000000 }));
  });

  it('cannot be granted by making the document again', async () => {
    await assertFails(setDoc(doc(me(), 'users/lee'), { coins: 999, photo: '' }));
  });

  it('cannot be created from nothing', async () => {
    // A brand new uid with no document. Allowing create means allowing
    // create-with-a-million.
    const fresh = env.authenticatedContext('brand-new').firestore();
    await assertFails(setDoc(doc(fresh, 'users/brand-new'), { coins: 999 }));
  });

  it('cannot be reset by deleting the document', async () => {
    await assertFails(deleteDoc(doc(me(), 'users/lee')));
  });
});

describe('somebody else', () => {
  it('cannot read your account', async () => {
    await assertFails(getDoc(doc(someoneElse(), 'users/lee')));
  });

  it('cannot write your account', async () => {
    await assertFails(updateDoc(doc(someoneElse(), 'users/lee'),
      { displayName: 'not lee' }));
  });

  it('cannot read your receipts', async () => {
    await assertFails(getDoc(doc(someoneElse(), 'users/lee/ledger/e1')));
  });

  it('is not signed in at all, and still cannot', async () => {
    await assertFails(getDoc(doc(nobody(), 'users/lee')));
  });
});

describe('what you may change about yourself', () => {
  it('a display name and a picture', async () => {
    await assertSucceeds(updateDoc(doc(me(), 'users/lee'),
      { displayName: 'Lee M', photo: 'preset:fox' }));
  });

  it('but not your plan', async () => {
    await assertFails(updateDoc(doc(me(), 'users/lee'),
      { plan: { tier: 'pro', status: 'active' } }));
  });

  it('and not the Stripe customer you are', async () => {
    // Pointing your account at somebody else's Stripe customer is how you
    // spend their subscription.
    await assertFails(updateDoc(doc(me(), 'users/lee'),
      { stripeCustomer: 'cus_someone_else' }));
  });

  it('and not your username, which has to stay unique', async () => {
    await assertFails(updateDoc(doc(me(), 'users/lee'), { username: 'taken' }));
  });

  it('and a name has to be a name, not a novel', async () => {
    await assertFails(updateDoc(doc(me(), 'users/lee'),
      { displayName: 'x'.repeat(41) }));
    await assertFails(updateDoc(doc(me(), 'users/lee'), { displayName: 42 }));
    await assertFails(updateDoc(doc(me(), 'users/lee'),
      { photo: 'x'.repeat(301) }));
  });
});

describe('the receipt', () => {
  it('is yours to read', async () => {
    await assertSucceeds(getDoc(doc(me(), 'users/lee/ledger/e1')));
  });

  it('is not yours to write', async () => {
    // A ledger you can edit is not a record of anything.
    await assertFails(setDoc(doc(me(), 'users/lee/ledger/e2'),
      { coins: -1000, what: 'a present to myself' }));
    await assertFails(deleteDoc(doc(me(), 'users/lee/ledger/e1')));
  });
});

describe('usernames', () => {
  it('can be checked one at a time, by anybody', async () => {
    // A sign-up form has to be able to say "that one is gone" before the
    // button is pressed, and a name in use is public the moment it is used.
    const snap = await assertSucceeds(getDoc(doc(nobody(), 'usernames/lee')));
    expect(snap.exists()).toBe(true);
    await assertSucceeds(getDoc(doc(nobody(), 'usernames/free-one')));
  });

  it('cannot be listed', async () => {
    // Availability is a question about ONE name, not a licence to download
    // every name there is.
    await assertFails(getDocs(collection(nobody(), 'usernames')));
  });

  it('cannot be claimed by writing the index', async () => {
    // This is what `claimUsername` is for. A client that can write here can
    // take every good name in an afternoon, and can point an existing name at
    // its own uid.
    await assertFails(setDoc(doc(me(), 'usernames/brand-new'), { uid: 'lee' }));
    await assertFails(setDoc(doc(me(), 'usernames/lee'), { uid: 'mallory' }));
    await assertFails(deleteDoc(doc(me(), 'usernames/lee')));
  });
});

describe('the price list', () => {
  it('is readable without an account', async () => {
    await assertSucceeds(getDoc(doc(nobody(), 'config/prices')));
  });

  it('is not writable with one', async () => {
    await assertFails(setDoc(doc(me(), 'config/prices'), { tiers: ['free'] }));
  });
});

describe('anything nobody thought of', () => {
  it('is closed', async () => {
    // The catch-all at the bottom of the rules. Without it, one forgotten
    // `match` is an open database.
    await assertFails(setDoc(doc(me(), 'whatever/x'), { a: 1 }));
    await assertFails(getDoc(doc(me(), 'whatever/x')));
    await assertFails(setDoc(doc(me(), 'users/lee/secrets/x'), { a: 1 }));
  });
});
