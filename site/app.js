/* Everything the three pages share: one Firebase app, one set of helpers.
 *
 * ES modules from the CDN, no build step - the same choice the editor makes,
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

/* The coin, drawn once and used wherever a coin belongs - the same mark as the
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
 * markup - a username is exactly the field an attacker controls. */
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
 * none of that is what lee asked for - *"basic account custmization like
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

/* ------------------------------------------------------------------ theme

   Three states, and only two of them are stored. "Follow the system" is the
   absence of a stored value, not a third string - so a browser that has never
   pressed the control tracks the OS for ever, and one that has pressed it
   keeps that choice until it is pressed back round to Auto.

   The value is read and applied by a two-line script in the <head> of every
   page, before the stylesheet paints. It has to be there and not here: this
   file is a module, modules are deferred, and a theme applied after first
   paint is a white flash on a dark page every time you load it. */
export const THEMES = ['auto', 'light', 'dark'];

export function theme() {
  try { return localStorage.getItem('tct-theme') || 'auto'; } catch { return 'auto'; }
}

export function setTheme(t) {
  const want = THEMES.includes(t) ? t : 'auto';
  try {
    if (want === 'auto') localStorage.removeItem('tct-theme');
    else localStorage.setItem('tct-theme', want);
  } catch { /* private browsing. The page still changes, it just forgets. */ }
  if (want === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = want;
  return want;
}

const SUN = `<svg viewBox="0 0 24 24" width="17" height="17" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle
  cx="12" cy="12" r="4.2"/><path d="M12 2.6v2M12 19.4v2M2.6 12h2M19.4 12h2
  M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"/></svg>`;
const MOON = `<svg viewBox="0 0 24 24" width="17" height="17" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round"
  stroke-linejoin="round"><path d="M20 13.5A8.2 8.2 0 0 1 10.5 4a8.2 8.2 0 1 0
  9.5 9.5Z"/></svg>`;
const AUTO = `<svg viewBox="0 0 24 24" width="17" height="17" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linejoin="round"><circle
  cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8A8.4 8.4 0 0 0 12 3.6Z"
  fill="currentColor"/></svg>`;
const FACE = { auto: AUTO, light: SUN, dark: MOON };
const CALLED = { auto: 'Theme: follows your system', light: 'Theme: light',
                 dark: 'Theme: dark' };

/* -------------------------------------------------------------- the chrome

   One call, on every page: marks the document as scripted, wires the theme
   control, and starts the reveal. Everything in it is optional - a page with
   no theme button and no `.reveal` gets a no-op, which is what lets the same
   line sit at the top of all four pages. */
export function initChrome() {
  document.documentElement.classList.add('js');
  // Tells the two-line script in the <head> that its dead-man timer can stand
  // down: something is here to do the revealing.
  document.documentElement.dataset.chrome = '1';

  const b = $('theme');
  if (b) {
    const paint = (t) => {
      b.innerHTML = FACE[t] || AUTO;
      b.title = CALLED[t] || '';
      b.setAttribute('aria-label', CALLED[t] || 'Theme');
    };
    paint(theme());
    b.onclick = () => paint(setTheme(
      THEMES[(THEMES.indexOf(theme()) + 1) % THEMES.length]));
  }

  reveal();
}

/* Sections arrive as you reach them. `IntersectionObserver` and not a scroll
   handler: a scroll handler runs on every pixel and this runs when the answer
   changes. Once in, they stay in - a section that fades back out when you
   scroll up is a section fighting the reader. */
export function reveal(root) {
  const bits = (root || document).querySelectorAll('.reveal:not(.in)');
  if (!bits.length) return;
  if (!('IntersectionObserver' in window)) {
    for (const el of bits) el.classList.add('in');
    return;
  }
  const eye = new IntersectionObserver((rows) => {
    for (const r of rows) {
      if (!r.isIntersecting) continue;
      r.target.classList.add('in');
      eye.unobserve(r.target);
    }
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
  for (const el of bits) eye.observe(el);
}

/* Google's mark, drawn rather than fetched. Their brand rules ask for the
   four colours and the shape, and an <img> to a CDN is a request that can
   fail and a button that then says nothing. */
export const GOOGLE = `<svg viewBox="0 0 48 48" aria-hidden="true">
  <path fill="#4285F4" d="M45.1 24.5c0-1.6-.1-2.8-.4-4H24v7.3h12.1c-.2 2-1.6 5-4.5 7l-.1.3 6.5 5 .5.1c4.2-3.8 6.6-9.5 6.6-15.7Z"/>
  <path fill="#34A853" d="M24 46c5.9 0 10.9-2 14.5-5.3l-6.9-5.4c-1.8 1.3-4.3 2.2-7.6 2.2-5.8 0-10.7-3.8-12.5-9l-.3.1-6.8 5.2-.1.3C7.9 41 15.4 46 24 46Z"/>
  <path fill="#FBBC05" d="M11.5 28.5c-.5-1.4-.8-2.9-.8-4.5s.3-3.1.7-4.5v-.3l-6.9-5.4-.2.1A22 22 0 0 0 2 24c0 3.5.9 6.9 2.3 9.9l7.2-5.4Z"/>
  <path fill="#EA4335" d="M24 9.5c4.1 0 6.9 1.8 8.5 3.3l6.2-6C34.9 3.3 29.9 1 24 1 15.4 1 7.9 6 4.3 13.2l7.2 5.6c1.8-5.3 6.7-9.3 12.5-9.3Z"/></svg>`;

/* The two-line script that has to run before the stylesheet paints. Kept
   here, as a string, so the four pages and the generated landing page all
   carry the same one and it cannot drift between them. */
export const THEME_BOOT =
  "try{var t=localStorage.getItem('tct-theme');"
  + "if(t)document.documentElement.dataset.theme=t;"
  + "document.documentElement.classList.add('js')}catch(e){}";
