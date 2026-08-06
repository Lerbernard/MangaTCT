/* Everything the three pages share: one Firebase app, one set of helpers.
 *
 * ES modules from the CDN, no build step — the same choice the editor makes,
 * for the same reason: a site you can open by double-clicking a file is a site
 * that still works in two years.
 */
import { initializeApp } from 'https://www.gstatic.com/firebasejs/11.0.2/firebase-app.js';
import {
  getAuth, connectAuthEmulator, createUserWithEmailAndPassword,
  signInWithEmailAndPassword, signOut, onAuthStateChanged,
  sendPasswordResetEmail, GoogleAuthProvider, signInWithPopup,
} from 'https://www.gstatic.com/firebasejs/11.0.2/firebase-auth.js';
import {
  getFunctions, connectFunctionsEmulator, httpsCallable,
} from 'https://www.gstatic.com/firebasejs/11.0.2/firebase-functions.js';
import {
  getFirestore, connectFirestoreEmulator, doc, onSnapshot, setDoc,
  collection, query, orderBy, limit, getDocs,
} from 'https://www.gstatic.com/firebasejs/11.0.2/firebase-firestore.js';
import { FIREBASE, REGION, USE_EMULATOR } from './config.js';

const app = initializeApp(FIREBASE);
export const auth = getAuth(app);
const fns = getFunctions(app, REGION);
export const db = getFirestore(app);
if (USE_EMULATOR) {
  connectAuthEmulator(auth, 'http://127.0.0.1:9099', { disableWarnings: true });
  connectFunctionsEmulator(fns, '127.0.0.1', 5001);
  connectFirestoreEmulator(db, '127.0.0.1', 8080);
}

export const call = (name) => httpsCallable(fns, name);
export {
  createUserWithEmailAndPassword, signInWithEmailAndPassword, signOut,
  onAuthStateChanged, sendPasswordResetEmail, GoogleAuthProvider,
  signInWithPopup, doc, onSnapshot, setDoc, collection, query, orderBy,
  limit, getDocs,
};

/* The account document, watched rather than fetched.
 *
 * This is what makes coming back from Stripe work. The payment succeeds on
 * Stripe's side and the coins arrive when the WEBHOOK lands, which is a second
 * or two later and is not something the browser is part of. A page that read
 * the balance once on load would show the old number to somebody who has just
 * paid, and "I paid and nothing happened" is the worst minute in the product.
 * Watching it means the number simply changes when the money does. */
export function watchMe(uid, then) {
  return onSnapshot(doc(db, 'users', uid), (s) => then(s.exists() ? s.data() : null));
}

/* Firebase's error codes as sentences. A form that says
 * "auth/invalid-credential" has told the person nothing they can act on. */
const SAYS = {
  'auth/invalid-credential': 'That email and password do not match an account.',
  'auth/invalid-email': 'That does not look like an email address.',
  'auth/missing-password': 'Enter a password.',
  'auth/weak-password': 'Six characters at least.',
  'auth/email-already-in-use': 'There is already an account with that email.',
  'auth/too-many-requests': 'Too many tries. Wait a minute and go again.',
  'auth/network-request-failed': 'No connection.',
  'auth/popup-closed-by-user': '',
  'functions/unauthenticated': 'Sign in first.',
  'functions/already-exists': 'That name is taken.',
};
export function saysWhat(e) {
  const code = (e && e.code) || '';
  if (code in SAYS) return SAYS[code];
  return (e && e.message) || 'Something went wrong.';
}

export const $ = (id) => document.getElementById(id);

export function toast(msg, bad) {
  const t = $('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'toast on' + (bad ? ' bad' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = 'toast'; }, 5000);
}

/* The coin, drawn once and used wherever a coin belongs — the same mark as the
 * app icon and the same one the editor draws in its top bar. */
export const COIN = `<svg class="coin" viewBox="0 0 64 64" aria-hidden="true">
  <defs>
    <linearGradient id="cf" x1="0" y1="0" x2=".25" y2="1">
      <stop offset="0" stop-color="#ffd75e"/><stop offset=".5" stop-color="#ffc400"/>
      <stop offset="1" stop-color="#e08900"/></linearGradient>
    <linearGradient id="cr" x1="0" y1="0" x2=".3" y2="1">
      <stop offset="0" stop-color="#fff0b0"/><stop offset="1" stop-color="#c87b00"/></linearGradient>
  </defs>
  <circle cx="32" cy="32" r="31" fill="url(#cr)"/>
  <circle cx="32" cy="32" r="27" fill="url(#cf)"/>
  <circle cx="32" cy="32" r="27" fill="none" stroke="#a86400" stroke-opacity=".55" stroke-width="1.4"/>
  <g transform="translate(12.16 10.3) scale(.62)">
    <path d="M7 10 L18 10 L32 30 L46 10 L57 10 L57 46 L46.5 46 L46.5 26.5 L35.5 42 L28.5 42 L17.5 26.5 L17.5 47 L11.5 60 L7 47 Z" fill="#fff3c4" fill-opacity=".55" transform="translate(0 1.1)"/>
    <path d="M7 10 L18 10 L32 30 L46 10 L57 10 L57 46 L46.5 46 L46.5 26.5 L35.5 42 L28.5 42 L17.5 26.5 L17.5 47 L11.5 60 L7 47 Z" fill="#7a4a00"/>
  </g></svg>`;

/* A name is somebody else's string. It goes on the page as TEXT, never as
 * markup — a username is exactly the field an attacker controls. */
export function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* Waits for Firebase to say who you are before deciding you are nobody.
 * `auth.currentUser` is null for a moment after every page load, and a page
 * that reads it too early bounces a signed-in person to the sign-in form. */
export function whoAmI() {
  return new Promise((done) => {
    const stop = onAuthStateChanged(auth, (u) => { stop(); done(u); });
  });
}

export function needSignIn(u) {
  if (u) return false;
  location.href = 'signin.html?next=' +
    encodeURIComponent(location.pathname.split('/').pop() || 'account.html');
  return true;
}

/* The pictures somebody may choose. Presets and not an upload: an upload is a
 * storage bucket, a size limit, a content check and a moderation problem, and
 * none of that is what lee asked for — *"basic account custmization like
 * cnging username or picture icon etc"*. */
export const ICONS = ['fox', 'cat', 'moon', 'star', 'bolt', 'leaf',
                      'wave', 'ink', 'panel', 'brush'];

export function iconSvg(id, size) {
  const n = Math.max(0, ICONS.indexOf(id));
  const hue = (n * 36 + 20) % 360;
  const ch = String.fromCodePoint(0x2726 + (n % 4));
  return `<svg class="pic" width="${size}" height="${size}" viewBox="0 0 40 40"
     aria-hidden="true"><circle cx="20" cy="20" r="20"
     fill="hsl(${hue} 70% 42%)"/><text x="20" y="27" text-anchor="middle"
     font-size="19" fill="#fff">${ch}</text></svg>`;
}
