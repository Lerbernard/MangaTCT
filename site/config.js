/* ── THE ONE FILE YOU FILL IN ────────────────────────────────────────────────
 *
 * Firebase Console → Project settings → General → Your apps → Web app → Config.
 *
 * These are NOT secrets. A Firebase web config identifies the project; it does
 * not authorise anything. What stops somebody using it is the security rules
 * (`firebase/firestore.rules`) and the Cloud Functions, which are the only
 * things that can move a balance. Your STRIPE key is a secret and is nowhere
 * near this file — it lives in `firebase functions:secrets:set STRIPE_KEY`.
 *
 * Firebase's console hands you a snippet that does `import { initializeApp }
 * from "firebase/app"` and calls it. Don't paste that here. That form is for a
 * project with a bundler, and this site has none — it loads the SDK from
 * Google's CDN in `app.js`, which is also the one place `initializeApp` should
 * ever be called. This file only holds the VALUES.
 */
export const FIREBASE = {
  apiKey: 'AIzaSyDeoXBP0E1h3iQAq3pZ-txdOBYjWekjfHE',
  authDomain: 'mangatctproject.firebaseapp.com',
  projectId: 'mangatctproject',
  storageBucket: 'mangatctproject.firebasestorage.app',
  messagingSenderId: '255534738345',
  appId: '1:255534738345:web:109ba1cbdcbf3578e6b2b8',
};

/* The region your functions are deployed to. `firebase deploy` puts them in
 * us-central1 unless you said otherwise; if the site says "function not found"
 * this is the line that is wrong. */
export const REGION = 'us-central1';

/* Set to true and the site talks to `firebase emulators:start` on this machine
 * instead of the real project — so you can click through sign-up, a fake
 * purchase and the account page without a live Stripe account. */
export const USE_EMULATOR = false;
