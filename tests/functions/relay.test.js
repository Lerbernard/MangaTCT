/* The relay's decisions, argued with. Pure, like purse.js: no Firebase.

   Run:  npx vitest run tests/functions
*/
import { describe, expect, it } from 'vitest';
import {
  PASS_HEADERS, PROVIDERS, admit, errorBody, forwardHeaders, relayTarget, tokenOf, usageOf, withBodyToken,
} from '../../firebase/functions/relay.js';

describe('a request is forwarded only to a provider and path we know', () => {
  it('names the three providers and the cleaner', () => {
    expect(Object.keys(PROVIDERS).sort()).toEqual(['anthropic', 'clean', 'gemini', 'openrouter']);
  });
  it('reads the path with or without the function name, and drops the v1 an SDK adds', () => {
    expect(relayTarget('/relay/anthropic/v1/messages').url).toBe('https://api.anthropic.com/v1/messages');
    expect(relayTarget('/anthropic/messages').url).toBe('https://api.anthropic.com/v1/messages');
    expect(relayTarget('/relay/gemini/chat/completions').path).toBe('chat/completions');
  });
  it('refuses everything else', () => {
    for (const p of ['/relay/openai/chat/completions', '/relay/gemini/embeddings', '/relay/gemini',
      '', '/relay/anthropic/v1/complete']) expect(relayTarget(p)).toBeNull();
  });
});

describe('the token travels where the key would', () => {
  it('Bearer for the OpenAI-shaped clients, x-api-key for Anthropic\'s SDK', () => {
    expect(tokenOf({ authorization: 'Bearer t1' })).toBe('t1');
    expect(tokenOf({ 'x-api-key': 't2' })).toBe('t2');
    expect(tokenOf({})).toBe('');
  });
  it('the provider sees our key and the few headers it needs, never the token', () => {
    const h = forwardHeaders({ 'x-api-key': 'tok', 'anthropic-version': '2023-06-01', host: 'h' }, 'anthropic', 'K');
    expect(h['x-api-key']).toBe('K');
    expect(h['anthropic-version']).toBe('2023-06-01');
    expect(h.host).toBeUndefined();
    expect(forwardHeaders({}, 'openrouter', 'K').Authorization).toBe('Bearer K');
    expect(PASS_HEADERS).toContain('content-type');
  });
});

describe('the gate', () => {
  it('is an account with coins, and says why not in the provider error shape', () => {
    expect(admit(null).status).toBe(402);
    expect(admit({ coins: 0 }).ok).toBe(false);
    expect(admit({ coins: 2 }).ok).toBe(true);
    expect(errorBody('x', 'coins')).toEqual({ error: { message: 'x', type: 'coins' } });
  });
  it('reads usage in either shape', () => {
    expect(usageOf({ usage: { input_tokens: 1, output_tokens: 2 } })).toEqual({ input: 1, output: 2, cached: 0, cost: null });
    expect(usageOf({ usage: { prompt_tokens: 1, completion_tokens: 2, cost: 0.5 } }).cost).toBe(0.5);
    expect(usageOf({})).toBeNull();
  });
});

describe('the cleaner, the fourth key', () => {
  it('has a secret address and carries its token in the body', () => {
    expect(relayTarget('/relay/clean')).toEqual({ backend: 'clean', path: '', url: null });
    expect(relayTarget('/relay/clean/x')).toBeNull();
    expect(JSON.parse(withBodyToken('{"token":"ID","model":"m"}', 'clean', 'S'))).toEqual({ token: 'S', model: 'm' });
    expect(withBodyToken('{"a":1}', 'gemini', 'S')).toBe('{"a":1}');
    expect(withBodyToken('nope', 'clean', 'S')).toBe('nope');
  });
});
