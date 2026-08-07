/* Write the two config documents Firestore needs, once.
 *
 *   node seed.js price_starter=price_123 price_regular=... price_pack1=...
 *
 * `config/prices` is the public price list — the pricing page reads it when
 * nobody is signed in, which is most of the people who look at it.
 *
 * There are no tiers. lee: *"fuck teh subcription, it too omplicated jus have
 * teh pacjks"* — so four one-off prices and nothing recurring.
 *
 * `config/stripe` is the map from a tier or pack id to a Stripe price id. It
 * lives in the database and not in the code because those ids are different in
 * test mode and in live mode, and redeploying a function to switch between
 * them is not a thing anybody should have to do.
 *
 * Run it with application-default credentials:
 *
 *   gcloud auth application-default login       (once)
 *   cd firebase/functions && npm install         (once)
 *   node seed.js price_starter=price_1A... price_regular=price_1B... ...
 *
 * Anything you leave out keeps whatever is already there, so this is safe to
 * run again after adding one pack.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { initializeApp, applicationDefault } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';
import { PACKS, looksLikePriceId } from './purse.js';

/* Which project, said out loud rather than inferred.
 *
 * `applicationDefault()` on its own will guess, from the credential or from
 * whatever `GCLOUD_PROJECT` happens to be set to, and a wrong guess here does
 * not fail cleanly — it writes the price list into somebody else's project, or
 * fails with an error naming a project you have never heard of. Ours is in
 * `.firebaserc`, two directories up, which is the same file every `firebase`
 * command reads. One source of truth.
 */
const HERE = dirname(fileURLToPath(import.meta.url));
function projectId() {
  if (process.env.GOOGLE_CLOUD_PROJECT) return process.env.GOOGLE_CLOUD_PROJECT;
  try {
    const rc = JSON.parse(readFileSync(join(HERE, '..', '..', '.firebaserc'),
                                       'utf8'));
    const id = rc && rc.projects && rc.projects.default;
    if (id) return id;
  } catch (e) {
    // fall through to the error below, which says something useful
  }
  console.error('No project id. Put one in .firebaserc at the repository '
                + 'root, or set GOOGLE_CLOUD_PROJECT.');
  process.exit(1);
  return '';
}

const PROJECT = projectId();
console.log('project:', PROJECT);
initializeApp({ credential: applicationDefault(), projectId: PROJECT });
const db = getFirestore();

const args = Object.fromEntries(process.argv.slice(2)
  .map((a) => a.split('=')).filter((p) => p.length === 2));

/* Before anything is written, and before the network is touched: is what came
   in on the command line actually a Stripe price id?
 *
 * An argument that is present but wrong is worse than one that is missing. A
 * missing one is reported at the bottom of this file; a wrong one is written,
 * reported as success, and surfaces as a 500 from the buy button on a live
 * site. That happened here with a pasted `…`. */
const junk = Object.entries(args)
  .filter(([k, v]) => k.startsWith('price_') && !looksLikePriceId(v));
if (junk.length) {
  for (const [k, v] of junk) console.error(`not a Stripe price id: ${k}=${v}`);
  console.error('');
  console.error('They look like price_1U1fCAPRGT41DjkSNiPmuk4f — about thirty');
  console.error('characters. Copy each one from the price row of its product');
  console.error('in the Stripe dashboard, in the mode you are seeding.');
  console.error('Nothing was written.');
  process.exit(1);
}

const ids = { packs: {} };

for (const q of PACKS) if (args['price_' + q.id]) ids.packs[q.id] = args['price_' + q.id];

// The public list carries no Stripe ids. It is world-readable by the rules,
// and what the world needs is the names and the numbers.
const public_ = {
  packs: PACKS.map(({ id, coins, usd }) => ({ id, coins, usd })),
};

await db.doc('config/prices').set(public_);
if (Object.keys(ids.packs).length) {
  await db.doc('config/stripe').set(ids, { merge: true });
}

const missing = PACKS.map((t) => t.id)
  .filter((id) => !args['price_' + id]);
console.log('config/prices written —', PACKS.length, 'packs');
if (missing.length) {
  console.log('no Stripe price id yet for:', missing.join(', '));
  console.log('make them in the Stripe dashboard, then run this again with');
  console.log('  ' + missing.map((id) => `price_${id}=price_XXXX`).join(' '));
}
process.exit(0);
