/* coins.js - TCT Coins: the count in the top bar and the purse behind it.

   lee: *"i wan you to impiment a credit syste using coins $1 is 100 coins ...
   also add a coin count in the ui at the top"*, then *"remove teh real money
   comarasion, it shoud oporate on whoel numbers, always round up, remove teh
   recnetly part and the top up just have a buy coin button that will link to a
   page on the website"*.

   So: whole coins and nothing else. No dollars anywhere on the screen - a coin
   is the unit the app is priced in, and putting a currency beside it invites
   the question of which currency, in which country, at today's rate. Where
   coins come from is a link, not an exchange rate.

   Everything here READS. The balance and the prices come from /api/coins in
   one answer, because they are shown together and a price quoted from a
   different moment than the balance is how a screen comes to say you can
   afford something you cannot. */

let wallet = null;

/* Prices are worked out on the SERVER, for whichever pages you ask about:
   /api/coins?pages=… is the run's price and ?page=n is that one page on its
   own. Never assembled here out of per-page numbers added together - a price
   is whole coins rounded up once over the whole run, and twenty-three pages
   rounded up one at a time would be twenty-three coins whatever was on them,
   which is the flat rate lee explicitly did not want. */
function coinsFor(step){
  return ((wallet && wallet.prices) || {})[step] || 0;
}

function coinsForAll(){
  return Object.values((wallet && wallet.prices) || {})
               .reduce((a,b)=>a+b, 0);
}

async function refreshCoins(){
  try{ paintCoins(await api('/api/coins')); }catch(e){}
}

/* The same prices for a SUBSET of the chapter, without disturbing the ones
   the panel and the low-balance mark are reading. The two are different
   questions asked of the same endpoint - "what would this chapter cost" and
   "what would this run cost" - and one answer cannot be both. */
async function quoteCoins(query){
  try{ return await api('/api/coins' + (query||'')); }catch(e){ return null; }
}

/* Draw one balance. Takes the number rather than reading `wallet`, because a
   run that is spending draws a number the purse has not been re-read for.

   `low` is under what one more chapter would cost at today's models rather
   than a fixed number - a hundred coins is plenty for Gemini and nothing at
   all for Opus. */
function paintCount(coins){
  const n = $('coinN'); if(!n) return;
  const btn = $('coinBtn');
  // No account, no coins. lee: *"the coins should only be linked to an
  // account, so no account = no coins"*, and then *"if the user is not
  // signed in it should show 0 coins"*. So: 0, not red (nothing is wrong,
  // nobody is in), and the click opens the sign-in form.
  if(wallet && wallet.needs_signin){
    n.textContent = '0';
    if(btn){ btn.classList.remove('broke','low'); btn.title = 'Sign in to use TCT Coins'; }
    return;
  }
  n.textContent = String(coins);
  const chapter = coinsForAll();
  if(btn){
    btn.classList.toggle('broke', coins <= 0);
    btn.classList.toggle('low', coins > 0 && chapter > 0 && coins < chapter);
    btn.title = coins + ' TCT Coins';
  }
}

function paintCoins(w){
  if(!w) return;
  wallet = w;
  paintCount(w.balance);
  if($('walletPop') && $('walletPop').classList.contains('open')) drawWallet();
}

/* While a run is spending. `spent` is what THIS run has taken so far and
   `wallet.balance` is what the last read of the purse saw, so the difference
   is the live figure - and it is drawn, not stored. Storing it would make the
   next poll subtract the same spend from the already-reduced number, and the
   count would fall twice as fast as the money. */
function coinsSpending(spent){
  if(!wallet) return;
  paintCount(wallet.balance - (spent||0));
}

function toggleWallet(ev){
  if(ev) ev.stopPropagation();
  const pop = $('walletPop'); if(!pop) return;
  const opening = !pop.classList.contains('open');
  pop.classList.toggle('open', opening);
  if(opening){ drawWallet(); refreshCoins(); }
}

document.addEventListener('click', e=>{
  const pop = $('walletPop');
  if(pop && pop.classList.contains('open') && !e.target.closest('.coinwrap'))
    pop.classList.remove('open');
});

const COIN_STEP_NAMES = {ocr:'Read text', translate:'Translate',
                         proofread:'Proofread', clean:'Clean'};

/* panels.js defines `esc` too, and these are classic scripts sharing one
   global scope - a second `function esc` here silently replaces whichever
   loaded first, for everybody. Own name, own file. */
function coinEsc(s){ return String(s==null?'':s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function drawWallet(){
  const pop = $('walletPop'); if(!pop) return;
  if(!wallet){ pop.innerHTML = '<div class="wnote">Counting…</div>'; return; }
  const w = wallet;
  // Signed out on an installed copy: the purse IS the sign-in form.
  if(w.needs_signin){ walletSignIn(false); return; }
  const steps = Object.keys(w.prices||{});
  const odd = new Set(w.unpriced || []);
  const rows = steps.map(k =>
    `<div class="wrow${odd.has(k)?' unpriced':''}">` +
    `<span class="wlbl">${coinEsc(COIN_STEP_NAMES[k]||k)}` +
    (odd.has(k) ? `<b class="wflag" title="${coinEsc((w.models||{})[k]||'')
      } is not in the price list, so it is charged at the highest rate">?</b>`
                : '') +
    `</span><span class="wamt">${coinsFor(k)}</span></div>`).join('');
  // Said out loud, with the model named. An unpriced model is charged at the
  // dearest rate on the list - the right way round, since charging an unknown
  // model as free is a bill this app eats - but it is an eightfold difference
  // and nobody would guess it from the number.
  const warn = odd.size ? `<div class="wnote warn">` +
    [...odd].map(k => coinEsc((w.models||{})[k] || COIN_STEP_NAMES[k])).join(', ') +
    ` ${odd.size === 1 ? 'is' : 'are'} not in the price list, so ` +
    `${odd.size === 1 ? 'that step is' : 'those steps are'} charged at the ` +
    `highest rate. Pick a listed model, or the price is a guess in our ` +
    `favour.</div>` : '';
  pop.innerHTML =
    `<div class="wtot"><b class="big">${w.balance}</b>` +
    `<span>TCT Coins</span></div>` +
    accountRow(w) +
    `<h4>This chapter, all ${w.pages||0} pages</h4>${rows}` +
    `<div class="wrow"><span class="wlbl"><b>Everything</b></span>` +
    `<span class="wamt"><b>${coinsForAll()}</b></span></div>` +
    `<div class="wnote">${w.boxes||0} text box${w.boxes===1?'':'es'} in the ` +
    `chapter. The three AI steps are priced per box, so a page with two ` +
    `costs less than a page with six; cleaning is a flat fee a page.</div>` +
    warn +
    `<div class="wtop"><button class="pri" onclick="buyCoins()">` +
    `Buy coins</button>` + topUpRow(w) + `</div>`;
}

/* Putting coins in from here, which is only ever a TESTING purse.

   lee: *"i ran out of coins to test stuff"* and *"just add coins to the editor
   not teh website"*. So there is a button, and it is behind
   `MANGATL_TEST_PURSE` on the machine the editor runs on - see
   `coins.can_top_up`, which is also the only thing that decides whether this
   draws at all. On an account it never appears, because on an account the
   client cannot write a balance and a button that always failed would be
   worse than none. */
function topUpRow(w){
  if(!w.can_top_up) return '';
  return `<div class="wtest"><span class="wnote">Test purse on this ` +
         `computer.</span>` +
         [100, 1000, 5000].map(n =>
           `<button onclick="topUp(${n})">+${n}</button>`).join('') +
         `</div>`;
}

async function topUp(n){
  try{
    const r = await fetch('/api/coins', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({coins:n, what:'test purse'})});
    const j = await r.json();
    if(j.error){ toast(j.error); return; }
    paintCoins(j);            // sets `wallet` and redraws
    toast('+' + n + ' coins');
  }catch(e){ toast('Could not add coins.'); }
}

/* Who the coins belong to.

   Nothing at all when there is no Firebase project configured: a checkout with
   no billing behind it keeps the local purse, and a "Sign in" button that
   cannot sign in to anything is worse than no button. */
function accountRow(w){
  if(!w.configured) return '';
  if(!w.signed_in)
    return `<div class="wacct"><span class="wnote">Your coins are on this ` +
           `computer. Sign in to keep them on your account.</span>` +
           `<button onclick="walletSignIn()">Sign in</button></div>`;
  return `<div class="wacct"><span class="wwho">${
    coinEsc(w.username || w.email || 'signed in')}</span>` +
    `<button onclick="walletSignOut()">Sign out</button></div>` +
    welcomeRow(w);
}

/* The hundred free coins, while they are still to be had.

   A new account is given them once its email is verified - the server does
   that on its own the first time it sees a verified token, see `welcomeIfDue`
   in the functions. What this row does is say so, offer the mail again, and
   take "I clicked it": the editor's token is turned over and the server asked,
   so the coins do not wait on the hour the old token had left in it.

   Drawn only while there is something to do. Verified and still owed is an
   address that had its coins on an earlier account; asking it to verify for
   coins that will not come would be a lie with a button on it. */
let welcomeToasted = false;
function welcomeRow(w){
  if(w.welcome_given && !welcomeToasted){
    welcomeToasted = true;
    toast('Your ' + (w.welcome_coins || 100) + ' free coins have landed.');
  }
  if(!w.welcome_due || w.verified) return '';
  return `<div class="wacct wwelcome"><span class="wnote">` +
    `<b>${w.welcome_coins || 100} free coins are waiting.</b> Click the link ` +
    `we emailed to ${coinEsc(w.email || 'your address')} and they land here.` +
    `</span>` +
    `<button class="pri" onclick="walletClaim(this)">I clicked it</button>` +
    `<button onclick="walletVerifyMail(this)">Send it again</button></div>`;
}

async function walletClaim(btn){
  if(btn) btn.disabled = true;
  const got = await acPost({do: 'claim'});
  if(got.error){ toast(got.error); if(btn) btn.disabled = false; return; }
  await refreshCoins();
  drawWallet();
  if(wallet && wallet.welcome_due && !wallet.verified)
    toast('Not verified yet. Open the mail and click the link first.');
}

async function walletVerifyMail(btn){
  if(btn) btn.disabled = true;
  const got = await acPost({do: 'verify'});
  toast(got.error || 'Sent. Look for a mail from MangaTCT - the spam folder too.');
  // Thirty seconds before it can be pressed again: Google rate-limits these,
  // and a button that answers "too many" is worse than one that waits.
  setTimeout(() => { if(btn) btn.disabled = false; }, 30000);
}

/* The sign-in form, drawn inside the purse rather than as a dialog of its own.
   It is three fields and it belongs beside the number it changes.

   The password is posted to the editor's own server, which passes it to Google
   and keeps nothing. What comes back and is kept is a refresh token, in the
   person's own folder - see `account.py`. */
function walletSignIn(making, host){
  // Drawn into the purse, or into Settings > Account (`renderAccount`) -
  // one at a time, since the form's fields are found by id.
  const pop = host || $('walletPop'); if(!pop) return;
  if(host && $('walletPop')) $('walletPop').innerHTML = '';
  pop.innerHTML =
    `<h4>${making ? 'Make an account' : 'Sign in'}</h4>` +
    `<div class="wform">` +
    // Google first, as on the website: one press against three fields.
    `<button class="gbtn" onclick="walletGoogle(${making ? 'true' : 'false'})">` +
    `${GOOGLE_MARK}<span>${making ? 'Sign up with Google' : 'Continue with Google'}</span></button>` +
    `<div class="wor">or with an email</div>` +
    `<input id="acEmail" type="email" placeholder="you@example.com" ` +
    `autocomplete="username">` +
    `<input id="acPass" type="password" placeholder="password" ` +
    `autocomplete="${making ? 'new-' : 'current-'}password">` +
    (making ? `<input id="acName" placeholder="username (optional)" ` +
              `autocomplete="off">` : '') +
    `<div class="wnote" id="acSay"></div>` +
    `<div class="wtop">` +
    `<button class="pri" onclick="walletDoSignIn(${making ? 'true' : 'false'})">` +
    `${making ? 'Make it' : 'Sign in'}</button>` +
    `<button onclick="walletSignIn(${making ? 'false' : 'true'}, this.closest('#acctBox'))">` +
    `${making ? 'I have one' : 'Make one'}</button>` +
    `</div>` +
    (making ? '' : `<button class="wlink" onclick="walletReset()">` +
                   `Forgot the password</button>`) +
    `</div>`;
  const box = $('acEmail');
  if(box){
    box.focus();
    // Enter is what somebody presses in a two-field form, and a form that
    // ignores it reads as broken rather than as strict.
    for(const id of ['acEmail','acPass','acName']){
      const f = $(id);
      if(f) f.onkeydown = e => { if(e.key === 'Enter') walletDoSignIn(making); };
    }
  }
}

/* Google's mark, the four colours, as the website draws it. */
const GOOGLE_MARK = '<svg viewBox="0 0 48 48" aria-hidden="true">' +
  '<path fill="#4285F4" d="M45.1 24.5c0-1.6-.1-2.8-.4-4H24v7.3h12.1c-.2 2-1.6 5-4.5 7l-.1.3 6.5 5 .5.1c4.2-3.8 6.6-9.5 6.6-15.7Z"/>' +
  '<path fill="#34A853" d="M24 46c5.9 0 10.9-2 14.5-5.3l-6.9-5.4c-1.8 1.3-4.3 2.2-7.6 2.2-5.8 0-10.7-3.8-12.5-9l-.3.1-6.8 5.2-.1.3C7.9 41 15.4 46 24 46Z"/>' +
  '<path fill="#FBBC05" d="M11.5 28.5c-.5-1.4-.8-2.9-.8-4.5s.3-3.1.7-4.5v-.3l-6.9-5.4-.2.1A22 22 0 0 0 2 24c0 3.5.9 6.9 2.3 9.9l7.2-5.4Z"/>' +
  '<path fill="#EA4335" d="M24 9.5c4.1 0 6.9 1.8 8.5 3.3l6.2-6C34.9 3.3 29.9 1 24 1 15.4 1 7.9 6 4.3 13.2l7.2 5.6c1.8-5.3 6.7-9.3 12.5-9.3Z"/></svg>';

/* lee: *"sign in / sign up and login with google like in the website"*.
   Google's sign-in happens in the system browser, on the website's own
   sign-in page, opened by the server with a one-time nonce in its address
   (`account.begin_handoff`). This waits: it asks `/api/account/hand?state=`
   every couple of seconds until the page has handed the sign-in over, then
   paints the purse, the Account page and Home as signed in. Ten minutes and
   it stops asking - the nonce is dead by then anyway. */
let _hand = null;                        // the nonce being waited on

async function walletGoogle(making){
  const say = $('acSay');
  const tell = (msg, warn) => { if(say){ say.className = 'wnote' + (warn ? ' warn' : '');
                                          say.innerHTML = msg; } };
  tell('Opening the browser…');
  const got = await acPost({do:'google', making: !!making});
  if(got.error){ tell(got.error, true); return; }
  _hand = got.state;
  const link = got.url ? ` If it did not open, <a href="${got.url}" target="_blank" rel="noopener">go there</a>.` : '';
  tell('Finish signing in in the browser that just opened; this fills in by itself.' + link);
  const until = Date.now() + 10*60*1000;
  while(_hand === got.state && Date.now() < until){
    await new Promise(r => setTimeout(r, 2000));
    let st;
    try{
      const r = await fetch(apiUrl('/api/account/hand?state=' + encodeURIComponent(got.state)));
      st = await r.json();
    }catch(e){ continue; }
    if(st && st.done){
      _hand = null;
      await refreshCoins();
      drawWallet();
      if(typeof renderAccount === 'function') renderAccount();
      if(typeof renderHome === 'function') renderHome();
      if(typeof winFocus === 'function') winFocus();     // back to the app
      toast('Signed in' + (st.who ? ' as ' + st.who : '') + '.');
      return;
    }
    if(st && st.known === false){ _hand = null; tell('That sign-in ran out. Press the button again.', true); return; }
  }
  if(_hand === got.state){ _hand = null; tell('Nobody came back from the browser. Press the button to try again.', true); }
}

/* Its own fetch and not `api`, for one reason: `api` toasts whatever the
   server says went wrong. A wrong password is not a system message across the
   bottom of the screen, it is a line under the password box. */
async function acPost(body){
  const r = await fetch(apiUrl('/api/account'), {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)});
  return await r.json().catch(() => ({error: 'The server did not answer.'}));
}

async function walletPost(body, saying){
  const say = $('acSay');
  if(say){ say.className = 'wnote'; say.textContent = saying || 'One moment…'; }
  const got = await acPost(body);
  if(got.error){
    if(say){ say.className = 'wnote warn'; say.textContent = got.error; }
    return false;
  }
  // The full purse, not the answer to this call. `/api/account` replies with
  // the account's state and no prices in it, and painting that over `wallet`
  // would leave the panel with a balance and no rows.
  await refreshCoins();
  drawWallet();
  if(typeof renderAccount === 'function') renderAccount();
  return true;
}

function walletDoSignIn(making){
  const email = ($('acEmail')||{}).value || '';
  const pass = ($('acPass')||{}).value || '';
  const name = ($('acName')||{}).value || '';
  walletPost(making ? {do:'signup', email, password:pass, username:name}
                    : {do:'signin', email, password:pass});
}

async function walletReset(){
  const email = ($('acEmail')||{}).value || '';
  const say = $('acSay');
  if(!email){
    if(say){ say.className = 'wnote warn';
             say.textContent = 'Put the email address in first.'; }
    return;
  }
  const got = await acPost({do:'reset', email});
  if(say){
    say.className = got.error ? 'wnote warn' : 'wnote';
    say.textContent = got.error || 'Sent. Check that inbox.';
  }
}

async function walletSignOut(){
  const got = await acPost({do: 'signout'});
  if(got.error){ toast(got.error); return; }
  await refreshCoins();
  drawWallet();
  if(typeof renderAccount === 'function') renderAccount();
}

/* Settings > Account, the website's page in the app. lee: *"there isn't a
   place to sign in in the app"*, then *"have an account view like on the
   website"*. The purse, the free coins if owed, the receipt, and the
   profile - the same picture set and the same username rules the site has.
   Drawn from /api/account; the receipt comes through the `ledgerLines`
   function, the picture is written the way the website writes it. */
const ACCT_ICONS = ['fox','cat','moon','star','bolt','leaf','wave','ink','panel','brush'];
function acctIconSvg(id, size){
  const n = Math.max(0, ACCT_ICONS.indexOf(id));
  const hue = (n * 36 + 20) % 360;
  const ch = String.fromCodePoint(0x2726 + (n % 4));
  return `<svg class="pic" width="${size}" height="${size}" viewBox="0 0 40 40" aria-hidden="true">` +
    `<circle cx="20" cy="20" r="20" fill="hsl(${hue} 70% 42%)"/>` +
    `<text x="20" y="27" text-anchor="middle" font-size="19" fill="#fff">${ch}</text></svg>`;
}
const ACCT_IN = new Set(['credit','refund']);
const ACCT_WORDS = {spend:'Spent on', refund:'Given back', credit:'Bought', clawback:'Taken back'};
function acctSays(r, packs){
  let what = String(r.what || '');
  what = what.replace(/\bpack (pack\d+)\b/g, (m,id)=> (packs && packs[id]) ? 'the ' + packs[id] + ' pack' : m);
  what = what.replace(/\s*[-|\u2013\u2014]\s*refunded\s*$/i, '');
  if(r.kind === 'credit' && what === 'welcome') return 'Free coins for signing up';
  return `${ACCT_WORDS[r.kind] || r.kind} ${what}`.trim();
}
function acctWhen(ms){
  if(!ms) return '';
  try{ return new Date(ms).toLocaleString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}); }
  catch(e){ return ''; }
}

async function renderAccount(){
  const box = $('acctBox'); if(!box) return;
  let v;
  try{ v = await api('/api/account'); }catch(e){ return; }
  const w = v.account || {};
  wallet = Object.assign(wallet || {}, w);
  if(!w.configured){
    box.innerHTML = '<div class="wnote">This copy has no account service configured.</div>';
    return;
  }
  if(!w.signed_in){ walletSignIn(false, box); return; }
  const rows = v.ledger || [];
  const ledger = !rows.length
    ? '<p class="muted" style="margin:0">Nothing yet. Every coin in and every coin out shows up here.</p>'
    : `<table class="acctledger"><tr><th>When</th><th>What</th><th class="n">Coins</th></tr>` +
      rows.map(r => { const plus = ACCT_IN.has(r.kind);
        return `<tr><td class="muted">${coinEsc(acctWhen(r.at))}</td>` +
          `<td>${coinEsc(acctSays(r, v.packs))}${r.page ? ` <span class="muted">${coinEsc(r.page)}</span>` : ''}</td>` +
          `<td class="n ${plus ? 'plus' : 'minus'}">${plus ? '+' : '−'}${Number(r.coins||0)}</td></tr>`; }).join('') +
      `</table>`;
  const icons = (v.icons && v.icons.length) ? v.icons : ACCT_ICONS;
  box.innerHTML =
    `<div class="acctpurse">` +
    `<div class="acctcoins"><svg class="coinface" width="18" height="18" aria-hidden="true"><use href="#tctcoin"/></svg>` +
    `<b>${Number(w.balance||0)}</b><span>TCT Coins</span></div>` +
    `<button class="pri" onclick="buyCoins()">Buy coins</button></div>` +
    (typeof welcomeRow === 'function' ? welcomeRow(w) : '') +
    `<h3 class="accth">Everything that moved</h3>` +
    (v.ledger_problem ? `<p class="muted">${coinEsc(v.ledger_problem)}</p>` : ledger) +
    `<h3 class="accth">How people see you</h3>` +
    `<div class="acctprofile">` +
    `<div id="acctPicNow">${acctIconSvg(w.photo || icons[0], 72)}</div>` +
    `<div class="acctname"><label>Username</label>` +
    `<div class="row"><input id="acctName" maxlength="20" spellcheck="false" autocomplete="off" ` +
    `value="${coinEsc(w.username||'')}" placeholder="pick a name">` +
    `<button class="pri" onclick="acctSaveName()">Save name</button></div>` +
    `<div class="muted" id="acctNameHint">Letters, numbers, dot, dash and underscore. Everyone's is different.</div></div></div>` +
    `<label style="margin-top:14px">Picture</label>` +
    `<div class="acctpicks">` + icons.map(id =>
      `<button type="button" class="${id === w.photo ? 'on' : ''}" data-p="${id}" onclick="acctSetPic('${id}')">${acctIconSvg(id, 40)}</button>`).join('') +
    `</div>` +
    `<div class="acctfoot"><span class="muted">Signed in as ${coinEsc(w.email||'')}</span>` +
    `<button onclick="walletSignOut()">Sign out</button></div>`;
}

async function acctSaveName(){
  const want = (($('acctName')||{}).value || '').trim();
  const hint = $('acctNameHint');
  if(!want) return;
  const got = await acPost({do:'name', username: want});
  if(got.error){ if(hint){ hint.textContent = got.error; hint.className = 'muted warnbad'; } return; }
  if(hint){ hint.textContent = 'Saved.'; hint.className = 'muted good'; }
  await refreshCoins();
  if(typeof renderHome === 'function') renderHome();
}

async function acctSetPic(id){
  const got = await acPost({do:'photo', photo: id});
  if(got.error){ toast(got.error); return; }
  const now = $('acctPicNow'); if(now) now.innerHTML = acctIconSvg(id, 72);
  document.querySelectorAll('.acctpicks button').forEach(b => b.classList.toggle('on', b.dataset.p === id));
}

/* lee: *"just have a buy coin button that will link to oa page on the
   website"*. A new tab, and the address comes from the server so there is one
   place it is written down - the editor is a thing somebody runs on their own
   machine and a card number has no business inside it. */
function buyCoins(){
  const url = (wallet && wallet.buy_url) || '';
  if(!url){ toast('Nowhere to buy coins yet.'); return; }
  window.open(url, '_blank', 'noopener');
}
