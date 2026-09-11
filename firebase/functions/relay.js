/* The relay: the app's AI calls, made with OUR keys.
 *
 * lee: *"the user shoud not have eth keys"*. Until this existed the editor
 * called Claude, Gemini and OpenRouter directly, with a key the person had
 * put in a file - and a person with coins and no key was refused with "has
 * no API key". Now a signed-in editor with no key of its own sends the same
 * request here, with its Firebase ID token where the provider's key would
 * go, and this forwards it to the provider with the key from the project's
 * secrets. The request and the reply pass through unchanged, so everything
 * the editor already does - Anthropic's cache marks, Gemini's safety
 * settings, OpenRouter's usage accounting - keeps working, and no provider
 * key ever leaves this function.
 *
 * What is checked before a call is forwarded: the token is a real one, the
 * account exists and has coins. The PRICE is not taken here - the editor
 * holds it when a run starts (`spendCoins`) and settles it after, as it
 * always did - so this is a gate, not a till. The provider's usage is logged
 * on every call for the day a till is wanted.
 *
 * Only the pure decisions live in this file, so they can be run under node
 * without Firebase; `index.js` wires them to the request.
 */

/* Where each provider is, and how its key is handed over. The editor's own
 * clients speak the OpenAI shape to Gemini and OpenRouter and Anthropic's
 * own shape to Claude, so those are the shapes forwarded. */
export const PROVIDERS = {
  anthropic: {
    base: 'https://api.anthropic.com/v1/',
    secret: 'ANTHROPIC_KEY',
    auth: (key) => ({ 'x-api-key': key }),
    paths: ['messages', 'models'],
  },
  gemini: {
    base: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    secret: 'GEMINI_KEY',
    auth: (key) => ({ Authorization: `Bearer ${key}` }),
    paths: ['chat/completions', 'models'],
  },
  openrouter: {
    base: 'https://openrouter.ai/api/v1/',
    secret: 'OPENROUTER_KEY',
    auth: (key) => ({ Authorization: `Bearer ${key}`,
      'HTTP-Referer': 'https://mangatct.com', 'X-Title': 'MangaTCT' }),
    paths: ['chat/completions', 'models'],
  },
  // The fourth key lee named: the page cleaner's. lee: *"ther 4 key one for
  // teh clner do tha too"*. Its endpoint is ours (a Modal deploy) and its
  // token travels IN THE BODY - `{token, model, image, mask}` - not in a
  // header, so `base` is a secret too (CLEAN_URL) and `bodyToken` says where
  // the key goes. The reply is a PNG, not JSON.
  clean: {
    base: null,                       // CLEAN_URL, read at call time
    secret: 'CLEAN_TOKEN',
    auth: () => ({}),
    paths: [''],
    bodyToken: 'token',
  },
};

/* Headers the editor sets that the provider needs to see. Everything else
 * - host, content-length, the token itself - is ours, not the provider's. */
export const PASS_HEADERS = ['content-type', 'accept', 'anthropic-version', 'anthropic-beta'];

/* `/relay/anthropic/v1/messages` -> { backend: 'anthropic', path: 'messages' }.
 * The function's own name may or may not lead the path, depending on how it
 * was reached; a `v1/` the SDK adds is dropped; anything not on the
 * provider's short list is null, which is a 404. */
export function relayTarget(pathname) {
  const parts = String(pathname || '').split('/').filter(Boolean);
  if (parts[0] === 'relay') parts.shift();
  const backend = parts.shift() || '';
  const p = PROVIDERS[backend];
  if (!p) return null;
  if (parts[0] === 'v1') parts.shift();
  const path = parts.join('/');
  if (!p.paths.includes(path)) return null;
  return { backend, path, url: p.base == null ? null : p.base + path };
}

/* The cleaner's body with OUR token in it, whatever the editor put there
 * (its ID token, which is how it signed the request). Anything that is not
 * a JSON object is left alone and the endpoint answers as it likes. */
export function withBodyToken(raw, backend, key) {
  const p = PROVIDERS[backend];
  if (!p || !p.bodyToken) return raw;
  let obj;
  try { obj = JSON.parse(String(raw || '{}')); } catch (e) { return raw; }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return raw;
  obj[p.bodyToken] = key;
  return JSON.stringify(obj);
}

/* The ID token, from wherever the editor's client put it: the OpenAI
 * clients send `Authorization: Bearer`, Anthropic's SDK sends `x-api-key`. */
export function tokenOf(headers) {
  const h = (n) => String((headers && (headers[n] || headers[n.toLowerCase()])) || '');
  const auth = h('authorization');
  if (/^bearer\s+/i.test(auth)) return auth.replace(/^bearer\s+/i, '').trim();
  return h('x-api-key').trim();
}

/* Which of the caller's headers go on to the provider, plus the key. */
export function forwardHeaders(headers, backend, key) {
  const out = {};
  for (const n of PASS_HEADERS) {
    const v = headers && (headers[n] || headers[n.toLowerCase()]);
    if (v) out[n] = String(v);
  }
  if (!out['content-type']) out['content-type'] = 'application/json';
  return { ...out, ...PROVIDERS[backend].auth(key) };
}

/* May this account make a call? The gate, in one place. `user` is the
 * account document or null. */
export function admit(user) {
  if (!user) return { ok: false, status: 402, why: 'No account yet - open MangaTCT\'s Coins panel once, signed in.' };
  const coins = Number(user.coins || 0);
  if (!(coins > 0)) return { ok: false, status: 402, why: 'No TCT Coins left. Buy more to keep going.' };
  return { ok: true, status: 200, why: '' };
}

/* The provider's usage numbers out of a reply, whichever shape it is in.
 * Logged, not billed - see the file's opening. */
export function usageOf(body) {
  const u = body && body.usage;
  if (!u || typeof u !== 'object') return null;
  const n = (x) => (Number.isFinite(Number(x)) ? Number(x) : 0);
  return {
    input: n(u.input_tokens ?? u.prompt_tokens),
    output: n(u.output_tokens ?? u.completion_tokens),
    cached: n(u.cache_read_input_tokens ?? (u.prompt_tokens_details || {}).cached_tokens),
    cost: u.cost == null ? null : n(u.cost),
  };
}

/* An error in the shape the editor's clients already read - `{error:
 * {message}}` is what every one of the three providers sends - so a refusal
 * here reads on screen like any other. */
export function errorBody(message, type = 'relay') {
  return { error: { message, type } };
}
