/* chrome.js - The window's own frame, drawn by the page.

   lee: *"instead of having a separate top bar like this, integrate it with
   the app"*. In its own window the app has no system frame (`window.py`,
   frameless): the top bar IS the title bar. This file is what makes that
   true - the three window buttons at the far right, the empty stretch of the
   bar you drag the window by, and eight thin strips round the edge you
   resize it by. In a browser tab none of it appears: the tab has a frame of
   its own and there is no window to drive.

   HOW A DRAG WORKS. Nothing here moves the window a pixel at a time. On
   mousedown the page tells the window process WHICH PART OF A FRAME the
   mouse went down on (a WM_NCHITTEST code: 2 the caption, 10-17 the edges
   and corners) and Windows runs its own move or resize loop from there - so
   dragging is as smooth as any other window, Aero snap works, and a double
   click on the bar maximises like a title bar does.

   Classic script; needs `$` from core.js. Wired once `pywebviewready` fires,
   which is how the page learns it is in the window at all. */

const HIT = { caption: 2, left: 10, right: 11, top: 12, topleft: 13,
              topright: 14, bottom: 15, bottomleft: 16, bottomright: 17 };
let framed = false;                 // true once the window says it is frameless

function winApi(){ return (window.pywebview && window.pywebview.api) || null; }

async function winCtl(what){
  const api = winApi(); if(!api) return;
  try{
    if(what === 'min') await api.minimize();
    else if(what === 'close') await api.close();
    else if(what === 'max'){ const on = await api.toggle_maximize(); paintMaxGlyph(!!on); }
  }catch(e){ /* the window is gone or never was; nothing to do */ }
}

/* Back to the front - after a sign-in that happened in the browser (see
   `walletGoogle`). In a browser tab there is no window to raise; nothing
   happens, and the tab is where the person already is. */
async function winFocus(){
  const api = winApi(); if(!api || !api.focus) return;
  try{ await api.focus(); }catch(e){}
}

/* The middle button reads as "maximise" or "restore", like the real one. */
function paintMaxGlyph(maximized){
  const b = $('wbMax'); if(!b) return;
  b.title = maximized ? 'Restore' : 'Maximize';
  b.innerHTML = maximized
    ? '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M2.5 2.5V.5h7v7h-2" fill="none" stroke="currentColor" stroke-width="1"/><rect x=".5" y="2.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1"/></svg>'
    : '<svg width="10" height="10" viewBox="0 0 10 10"><rect x=".5" y=".5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1"/></svg>';
  document.documentElement.classList.toggle('maximized', !!maximized);
}

async function syncMaxGlyph(){
  const api = winApi(); if(!api) return;
  try{ const st = await api.state(); paintMaxGlyph(!!st.maximized); }catch(e){}
}

/* A mousedown that hands the drag to Windows. Left button only, and never
   from a control - the buttons on the bar are theirs to click. */
function hitDown(code){
  return ev => {
    if(ev.button !== 0) return;
    if(ev.target.closest && ev.target.closest('button,input,select,a,textarea,label')) return;
    const api = winApi(); if(!api) return;
    ev.preventDefault();
    try{ api.hit(code); }catch(e){}
  };
}

function buildEdges(){
  if($('winEdges')) return;
  const box = document.createElement('div');
  box.id = 'winEdges';
  for(const [name, code] of Object.entries(HIT)){
    if(name === 'caption') continue;
    const e = document.createElement('div');
    e.className = 'wedge ' + name;
    e.addEventListener('mousedown', hitDown(code));
    box.appendChild(e);
  }
  document.body.appendChild(box);
}

function wireChrome(){
  framed = true;
  document.documentElement.classList.add('framed');
  const ctl = $('winctl'); if(ctl) ctl.hidden = false;
  const drag = $('tbDrag');
  if(drag){
    drag.addEventListener('mousedown', hitDown(HIT.caption));
    drag.addEventListener('dblclick', () => winCtl('max'));
  }
  // The bar's own empty parts drag too: the top bar minus its controls.
  const top = $('top');
  if(top){
    top.addEventListener('mousedown', ev => {
      if(ev.target !== top && !ev.target.classList.contains('side')) return;
      hitDown(HIT.caption)(ev);
    });
    top.addEventListener('dblclick', ev => {
      if(ev.target === top || ev.target.classList.contains('side')) winCtl('max');
    });
  }
  buildEdges();
  syncMaxGlyph();
  window.addEventListener('resize', () => { clearTimeout(wireChrome._t);
    wireChrome._t = setTimeout(syncMaxGlyph, 150); });
}

/* Only when the window says so: a browser tab, and a window started with
   `--frame`, keep the system's frame and none of this. */
window.addEventListener('pywebviewready', async () => {
  const api = winApi(); if(!api) return;
  try{
    const st = await api.state();
    if(st && st.frameless) wireChrome();
  }catch(e){ /* an older window.py with no api: the system frame is there */ }
});
