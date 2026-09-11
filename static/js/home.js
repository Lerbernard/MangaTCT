/* home.js - The Home screen: the first thing up, and where the mark at the
   top left always leads.

   lee: *"have a landing page, a home page that I can log in to the app and
   view projects to load, like Photoshop has, and make clicking the logo go
   to the home page"*. Left, the account and the two ways to start; right,
   the chapter that is open and the chapters opened before. Drawn from
   /api/home. Classic script; needs `$`, `api`, `toast`, `setTab`,
   `walletSignIn`, `adoptProject` from the files before it. */

function goHome(ev){
  if(ev) ev.preventDefault();
  if(typeof setTab === 'function') setTab('home', 1);
}

function _homeAgo(t){
  if(!t) return '';
  const s = Math.max(0, Date.now()/1000 - t);
  if(s < 3600) return 'just now';
  if(s < 86400) return Math.round(s/3600) + ' h ago';
  if(s < 86400*30) return Math.round(s/86400) + ' days ago';
  return new Date(t*1000).toLocaleDateString();
}
const _hesc = s => String(s==null?'':s).replace(/[<>&"]/g,
  c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));

async function renderHome(){
  const box = $('home'); if(!box) return;
  let h;
  try{ h = await api('/api/home'); }catch(e){ return; }
  $('homeVer').textContent = (h.channel ? h.channel + ' ' : '') + h.version;
  // the account, left
  const a = h.account || {};
  const acct = $('homeAcct');
  if(!a.configured){
    acct.innerHTML = '';
  } else if(!a.signed_in){
    acct.innerHTML = '';
    const host = document.createElement('div'); acct.appendChild(host);
    if(typeof walletSignIn === 'function') walletSignIn(false, host);   // its own "Sign in" heading
  } else {
    acct.innerHTML =
      `<div class="homeacct-title">Signed in</div>` +
      `<div class="acctwho"><b>${_hesc(a.username || a.email || '')}</b></div>` +
      `<div class="acctcoins"><svg class="coinface" width="15" height="15" aria-hidden="true">` +
      `<use href="#tctcoin"/></svg><b>${Number(a.balance||0)}</b><span>TCT Coins</span></div>` +
      `<div class="row" style="gap:10px;margin-top:12px">` +
      `<button onclick="openSettingsDlg(); setSettingsTab('account')">Account</button>` +
      `<button onclick="buyCoins()">Buy coins</button></div>`;
  }
  // what is open
  const c = h.current || {};
  const cont = $('homeContinue');
  if(c.pages > 0){
    cont.hidden = false;
    cont.innerHTML =
      `<h2 class="set-h">Continue</h2>` +
      `<button class="homecard-proj now" onclick="setTab('edit',1)">` +
      `<b>${_hesc(c.name || 'Current project')}</b>` +
      `<span>${c.pages} page${c.pages===1?'':'s'}${c.medium ? ' · ' + _hesc(c.medium) : ''}</span>` +
      `<em>Open in the Workspace</em></button>`;
  } else { cont.hidden = true; cont.innerHTML = ''; }
  // opened before
  const grid = $('homeRecent');
  const rec = h.recent || [];
  if(!rec.length){
    grid.innerHTML = '<div class="homeempty">Nothing yet. A chapter saved as a .tctp file, ' +
      'or opened from one, shows up here.</div>';
    return;
  }
  grid.innerHTML = rec.map(r =>
    `<div class="homecard-proj${r.exists ? '' : ' gone'}" ` +
    `${r.exists ? `onclick="homeOpenPath(${JSON.stringify(r.path).replace(/"/g,'&quot;')})"` : ''}>` +
    `<b>${_hesc(r.name)}</b>` +
    `<span>${r.pages ? r.pages + ' page' + (r.pages===1?'':'s') : ''}${r.medium ? ' · ' + _hesc(r.medium) : ''}` +
    `${r.at ? ' · ' + _hesc(_homeAgo(r.at)) : ''}</span>` +
    `<em title="${_hesc(r.path)}">${r.exists ? _hesc(r.path) : 'Not found - the file has moved or gone'}</em>` +
    `<button class="x" title="Take off this list" onclick="event.stopPropagation(); homeForget(${JSON.stringify(r.path).replace(/"/g,'&quot;')})">×</button>` +
    `</div>`).join('');
}

function homeNew(){
  if(typeof setTab === 'function') setTab('new', 1);
  if(typeof setFileTab === 'function') setFileTab('new');
}
async function homeOpen(){
  // The File screen's own Open, which also knows what to do when this
  // machine cannot show a file dialog.
  if(typeof openProject === 'function'){ await openProject(); return; }
  const pick = await api('/api/pick_project','POST',{});
  if(!pick || !pick.path) return;
  await homeOpenPath(pick.path);
}
async function homeOpenPath(path){
  try{
    const r = api('/api/project_open','POST',{path});
    if(typeof adoptProject === 'function') await adoptProject(r);
    else await r;
    if(typeof setTab === 'function') setTab('edit', 1);
  }catch(e){ toast('Could not open it.'); }
}
async function homeForget(path){
  try{ await api('/api/home','POST',{do:'forget', path}); renderHome(); }catch(e){}
}
