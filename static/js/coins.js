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
  // account, so no account = no coins"*. The pill says what to do instead
  // of showing a number that is nobody's.
  if(wallet && wallet.needs_signin){
    n.textContent = 'Sign in';
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

/* Settings > Account. lee: *"there isn't a place to sign in in the app"* -
   there was, inside the coin's panel, and a panel behind a coin is not a
   place anybody looks for it. This is the same form and the same two
   buttons on a page with a name. */
async function renderAccount(){
  const box = $('acctBox'); if(!box) return;
  if(!wallet){ try{ await refreshCoins(); }catch(e){} }
  const w = wallet || {};
  if(!w.configured){
    box.innerHTML = '<div class="wnote">This copy has no account service configured.</div>';
    return;
  }
  if(!w.signed_in){ walletSignIn(false, box); return; }
  box.innerHTML =
    `<div class="acctwho"><b>${coinEsc(w.username || w.email || 'signed in')}</b>` +
    (w.username && w.email ? `<span class="muted">${coinEsc(w.email)}</span>` : '') + `</div>` +
    `<div class="acctcoins"><svg class="coinface" width="15" height="15" aria-hidden="true">` +
    `<use href="#tctcoin"/></svg><b>${w.balance}</b><span>TCT Coins</span></div>` +
    `<div class="row" style="gap:10px;margin-top:14px">` +
    `<button class="pri" onclick="buyCoins()">Buy coins</button>` +
    `<button onclick="walletSignOut()">Sign out</button></div>` +
    (typeof welcomeRow === 'function' ? welcomeRow(w) : '');
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
