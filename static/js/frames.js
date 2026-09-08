/* frames.js - showPage() orchestration, region boxes, drag/resize frames with live local re-wrap of text.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* ---------------- page view ---------------- */
/* Every page switch and every save gets a ticket. A reply holding an old
   ticket is thrown away, because applying it would put another page's text on
   this one, or undo an edit you have already made. */
let pageTicket=0;

/* The cache keys the server hands out, remembered per page so anything that
   builds an image URL outside showPage - the reference pane, the prefetcher -
   asks for the copy the browser already has instead of a fresh download. */
var scanKey={}, vKey={};
/* ...and the key for the FINISHED page. A different picture from the
   clean plate, so a different key - see `editor._render_key`, which is
   asked with the mode for this one and without one for `vKey`. */
var tKey={};

/* ---- picture cache -------------------------------------------------------
   Switching pages used to show the page you were LEAVING for a moment: the
   browser keeps the old picture painted until the new file has downloaded and
   DECODED, and both of those were happening after the click. So every picture
   now goes through here. `preloadImage` starts the download and holds the
   Image object alive, which is what keeps the decoded bitmap in memory - a
   bare `new Image()` that goes out of scope leaves only the compressed bytes
   in the HTTP cache and the decode has to happen again. `readyImage` waits
   for the decode to finish, off screen, so that the assignment which follows
   has nothing left to do and the swap lands in a single frame. */
var imgCache={}, imgOrder=[];
const IMG_CACHE_MAX=14;      // ~6 pages either side, both panes
function preloadImage(url){
  let p=imgCache[url];
  if(!p){
    p=new Image();
    try{ p.decoding='async'; }catch(e){}
    p.src=url;
    imgCache[url]=p; imgOrder.push(url);
    while(imgOrder.length>IMG_CACHE_MAX){
      const old=imgOrder.shift();
      if(old!==url) delete imgCache[old];
    }
  }
  return p;
}
/* Resolves when the picture is decoded and ready to paint - or after the
   guard, because a slow or missing file must never leave you looking at the
   previous page with nothing happening. */
function readyImage(url, guard){
  const p=preloadImage(url);
  const wait=new Promise(res=>{
    if(p.complete && p.naturalWidth){
      if(p.decode){ p.decode().then(res, ()=>res()); } else res();
      return;
    }
    p.addEventListener('load', ()=>{
      if(p.decode){ p.decode().then(res, ()=>res()); } else res();
    }, {once:true});
    p.addEventListener('error', ()=>res(), {once:true});
  });
  return Promise.race([wait,
    new Promise(res=>setTimeout(res, guard||4000))]);
}
/* The URL of a page in the view currently on screen. One definition, used by
   showPage, the prefetcher and the reference pane alike - they were three
   copies of the same string-building and they drifted, so a prefetch warmed a
   URL the swap then did not ask for. */
function pageUrl(i, mode){
  if((mode||view)==='original')
    return apiUrl(`/img/${i}?v=`+encodeURIComponent(scanKey[i]||vKey[i]||'x'));
  const m = (mode||view)==='typeset' ? 'clean' : (mode||view);
  const bare = (mode||view)==='typeset' ? '&paint=0' : '';
  return apiUrl(`/render/${i}?mode=${m}${bare}&v=`
    +encodeURIComponent(vKey[i]||'x'));
}

/* While a page's picture is still on its way, switching is HELD - mashing
   Next used to queue half-loaded pages behind each other, each one paying
   its round trips just to lose the ticket race. The screen (`#pageLoading`,
   the app icon with a ring round it) appears only after a short grace, so a
   cached page - the common case, the prefetcher fills the cache - never
   shows it at all. lee: *"add a loading screen that prevents teh user to
   switch page while a page is loading"*. */
let pageHold=false;
let pageHoldTimer=null;
let pageHoldNext=null;      // the LAST page asked for during the hold
function holdPages(){
  pageHold=true;
  clearTimeout(pageHoldTimer);
  pageHoldTimer=setTimeout(()=>{
    const el=$('pageLoading');
    if(el && pageHold) el.classList.add('on');
  }, 160);
}
function releasePages(){
  pageHold=false;
  clearTimeout(pageHoldTimer);
  // A click made during the hold was a decision, not noise - the LAST one
  // is honoured the moment the page in flight lands. Dropping them outright
  // read as a dead button, and quietly broke anything that turns pages
  // programmatically.
  const next=pageHoldNext;
  pageHoldNext=null;
  if(next!=null && next!==cur) showPage(next);
}
function hideLoadScreen(){
  const el=$('pageLoading');
  if(el) el.classList.remove('on');
}

async function showPage(i){
  // A page is still loading: the click waits its turn rather than joining a
  // race it would lose - the LAST page asked for is shown when the hold
  // lifts. Same-page reloads (saves, view switches) go through - they are
  // not a switch, and holding them would deadlock a save.
  if(pageHold && showPage._last!==i){ pageHoldNext=i; return; }
  // Any pending stroke changes belong to the page being left - save them
  // before switching. Nothing painted is ever thrown away by moving around.
  await syncPaint();
  const ticket=++pageTicket;
  const stamp=(typeof editStamp!=='undefined') ? editStamp : 0;
  closeCanvasEdit(true);
  layers=[]; layerSel=null; renderLayers();
  // Selections are per PAGE - but plenty of things reload the SAME page in
  // place (saving typesetting, view switches, style tweaks), and clearing the
  // selection on those made it "vanish" moments after being drawn.
  if(showPage._last!==i && typeof selClear==='function') selClear();
  syncBoxesForView(view);        // also covers loading straight into a view
  cur=i; sel=null;
  // Start the picture downloading BEFORE the page's data comes back. The URL
  // needs only the cache key, and the prefetcher has already learned it for
  // every neighbour - so the round trip for regions and the round trip for
  // the image now happen at the same time instead of one after the other.
  if(vKey[i]!==undefined||scanKey[i]!==undefined){
    preloadImage(pageUrl(i));
    if(typeof sideBySide!=='undefined' && sideBySide && view!=='original')
      preloadImage(pageUrl(i,'original'));
  }
  const d=await api('/api/page/'+i);
  if(ticket!==pageTicket) return;      // a later page won the race
  scanKey[i]=d.ikey||'';               // so the reference pane can cache too
  vKey[i]=d.vkey||'';
  tKey[i]=d.tkey||'';
  // Is this the same page coming back, or a different one? Needed before the
  // regions land (see below) as well as by the scroll-keeping further down.
  const samePage = (showPage._last===i);
  // the new page may be typeset where the last one was not (or the reverse)
  pageNote=d.note||'';           // the proofreader's remark about this page
  pageNoteIds=d.note_ids||[];    // ...and which boxes it is about
  kindsHere=d.kinds||[]; hiddenKinds=d.hidden||[];
  hiddenIds=d.hidden_ids||[]; hiddenRows=d.hidden_rows||[];
  // Reloading the SAME page - a save, a tab switch, a view switch - draws the
  // boxes straight away, because their old numbers are on screen right now and
  // this reply may have renumbered them. A different page waits for its own
  // picture to arrive: `applyZoom` redraws them at the new scale on load, and
  // drawing them here first would flash them at the last page's zoom.
  // An edit made while this was in the air means the answer describes the page
  // as it was BEFORE it, so the boxes it carries are stale - see editStamp in
  // core.js. Everything else in the reply (the picture key, the kinds, the
  // note) is still good and is applied above and below.
  if(typeof editStamp === 'undefined' || stamp === editStamp)
    setRegions(d.regions, {boxes: samePage, overlay: false, list: false});
  if(typeof syncTextToggle==='function') syncTextToggle();
  if(proj&&proj.pages&&proj.pages[i]) proj.pages[i].custom_clean=!!d.custom_clean;
  loadLayers(d.paint_layers);
  const img=$('img');
  pageW=d.width; pageH=d.height;
  // Go through the zoom code rather than setting scale directly, or the page
  // and the boxes drawn over it end up at different sizes.
  const wrapEl=$('canvasWrap');
  // Same page reloading (tab switch, save, boot's first poll) keeps the view
  // you had - UNLESS the initial centring is still pending, in which case
  // "the view you had" is just an uncentred scroll of 0,0 captured too
  // early. Boot used to lose the centring to exactly that race.
  const settled = typeof centerPending==='undefined' || !centerPending;
  const keep = (samePage && settled)
    ? {l:wrapEl.scrollLeft, t:wrapEl.scrollTop} : null;
  // Declare the intent NOW, not in the load callback: a second showPage can
  // replace img.onload before the first image ever loads, and then nothing
  // would have marked the centring as wanted.
  if(!keep && typeof centerPending!=='undefined') centerPending=true;
  showPage._last=i;
  const fit=()=>{
    fitZoom=fitScale();
    // A page opens FITTED to the window. It opened at actual size for one
    // round - lee asked for that when "100%" in the readout still meant the
    // fit, and asked for it back the moment the readout started telling the
    // truth: *"ok make the defaut zoom fit the page"*. The whole page in front
    // of you is the right thing to start from; 100% is a keypress away.
    if(!keep) zoom = 1;
    applyZoom(); drawOverlay();
    // a NEW page opens centred in the pan slack; reloading the same page
    // (tab switch, save) keeps exactly the view you had
    if(keep){ wrapEl.scrollLeft=keep.l; wrapEl.scrollTop=keep.t; }
    else centerPageSoon();     // keeps trying until the centre actually sticks
  };
  img.onload=fit;
  // ...and when the picture never arrives. `fit` is where the page is centred,
  // and hanging it on `onload` alone meant that a page whose image 404s - one
  // deleted underneath us, one from a chapter that has been put down - left
  // the view exactly where it was booted: scrolled to 0,0, which is deep
  // inside the stage's 46vmax margin and therefore a screen of nothing but
  // background. It reads as a broken editor. It is a missing page, and it is
  // supposed to look like an empty middle with the page list still beside it.
  img.onerror=()=>{ pageW=pageW||1; pageH=pageH||1; fit(); };
  // Build the query properly: the original view has no other parameters, so
  // it needs "?" not "&". Getting that wrong 404s silently and leaves a blank
  // page with the boxes still drawn over it.
  // The URL used to end in the clock, so every visit to a page re-fetched and
  // re-decoded the whole image even when it was byte for byte the one already
  // in the browser. The server hands back a key that changes exactly when the
  // page's appearance can have - so going back to a page you have seen is now
  // free, and a page that really did change still reloads.
  // The URL used to end in the clock, so every visit to a page re-fetched and
  // re-decoded the whole image even when it was byte for byte the one already
  // in the browser. The server hands back a key that changes exactly when the
  // page's appearance can have - so going back to a page you have seen is now
  // free, and a page that really did change still reloads. The scan gets a key
  // of its own: it cannot change when a page is cleaned or typeset, so
  // hanging the render key on it only threw a good copy out of the cache.
  const url = pageUrl(i);
  const refUrl = pageUrl(i, 'original');
  img.onerror=()=>{
    toast('Could not load the '+view+' view of this page.');
    console.error('image failed:', img.src);
  };
  const setMain=()=>{
    img.src=url;
    if(img.complete && img.naturalWidth) fit(); // cached image fires no onload
  };
  const ri=$('refImg');
  const bothPanes = typeof sideBySide!=='undefined' && sideBySide
    && (typeof tab==='undefined' || tab==='edit')
    && ri && ri.dataset.page!==String(i);
  // Nothing goes on screen until it is DECODED. Both panes wait on both
  // pictures, so they swap in the same frame - one pane flipping half a
  // second before the other reads as a glitch - and the single-pane case
  // waits on its one picture for the same reason: an undecoded assignment is
  // exactly the flash of the previous page's cleaning. `readyImage` has its
  // own guard, so a slow or missing file can only delay this, never stop it.
  const want = bothPanes ? [url, refUrl] : [url];
  // Already decoded and in the cache? Then there is nothing to hold for -
  // assigning a cached src reports complete immediately. SAME-PAGE reloads
  // hold too: after Clean or Typeset the picture on this very page is being
  // rebuilt, which is exactly the wait the screen is for. lee: *"the oading
  // screen should also happen when the pages is etting ready after clenning
  // or typesetting"*. The grace in holdPages keeps it off the small saves
  // whose rebuild lands faster than a blink.
  const probe=new Image(); probe.src=url;
  const cached = probe.complete && probe.naturalWidth;
  if(!cached) holdPages();
  Promise.all(want.map(u=>readyImage(u, 2500))).then(()=>{
    // THE HOLD AND THE SCREEN COME DOWN SEPARATELY. The hold is about input
    // and stays short - 2.5s at most, then clicks work again whatever
    // happens, which is the behaviour every switching test pins. The SCREEN
    // is about honesty and stays up until the picture actually lands: a
    // page being BUILT during "Preparing pages" is seconds of real work,
    // and dropping the ring at 2.5s left lee looking at a blank stage with
    // the page still in the oven (his ask: the Image tab, mid-warm-up,
    // should show the loading screen until the page is ready).
    releasePages();
    if(ticket!==pageTicket) return;            // a later page won the race
    if(bothPanes){ ri.dataset.page=String(i); ri.src=refUrl; }
    setMain();
    if(typeof refSync==='function') refSync();  // side-by-side follows along
    const im=$('img');
    if(im && !(im.complete && im.naturalWidth)){
      const done=()=>hideLoadScreen();
      im.addEventListener('load', done, {once:true});
      im.addEventListener('error', done, {once:true});
    } else {
      hideLoadScreen();
    }
  });
  renderPages(); renderList();
  warmFrom(i);
}

/* Tell the server which page is on screen, so the background page-builder
   works outwards from here - the pages you are about to click are the ones it
   makes next. It ignores the nudge while it is already busy, so this is free
   to call on every page change. */
function warmFrom(i){
  // Deliberately not api(): a nudge that fails is not worth a message on
  // screen, and nothing waits on the answer.
  try{
    fetch(apiUrl('/api/warm'),{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({from:i})}).catch(()=>{});
  }catch(e){}
  prefetchAround(i);
}

/* Pull the neighbouring pages into the browser's own cache.

   Assigning a new src leaves the PREVIOUS page on screen until the new one has
   downloaded and decoded - which is the half-second of the old page's cleaning
   you see after clicking Next. Nothing can swap an image that has not arrived
   yet, so the answer is for it to have arrived already: by the time the click
   happens the file is in the cache and the swap is immediate. */
function prefetchAround(i){
  const n=(proj&&proj.pages)?proj.pages.length:0;
  // Forwards first - Next is the click that actually happens - and two ahead,
  // because reading a chapter is a run of Nexts, not a single step.
  [i+1,i+2,i-1,i+3].forEach(async k=>{
    if(k<0||k>=n) return;
    // The keys come from the page payload, so a page never visited has none.
    // Asking for it is cheap and it is exactly the page about to be needed.
    if(scanKey[k]===undefined){
      try{
        const d=await api('/api/page/'+k);
        scanKey[k]=d.ikey||''; vKey[k]=d.vkey||'';
      }catch(e){ return; }
    }
    // Decode it now too, not just download it: a decode of a 960×1365 page is
    // the rest of the pause, and doing it here means the swap is a paint.
    readyImage(pageUrl(k), 30000);
    if(typeof sideBySide!=='undefined' && sideBySide && view!=='original')
      readyImage(pageUrl(k,'original'), 30000);
  });
}
function drawBoxes(){
  if(typeof syncMulti==='function') syncMulti();
  document.querySelectorAll('.box,.tagf,.bhint').forEach(e=>e.remove());
  const st=$('stage');
  // Hide boxes hides everything overlaid on the page - the link connectors too.
  if(boxesHidden()){
    st.querySelectorAll('.linksvg').forEach(e=>e.remove());
    drawText(); return;
  }
  // One balloon, one box. Regions carrying the same box_group are SECTIONS of
  // one balloon - the sentence up the right of it and the small あっ！ below.
  // Both are still separate regions with their own reading, their own
  // translation and their own typesetting; what the grouping changes is only
  // how the page LOOKS, which was lee's complaint: "the boxes shoud be around
  // the bubbles no 2 of them split randomly".
  //
  // It used to draw a solid frame round the pair as well. lee, finding one on
  // a burst holding two speeches and not knowing what it was - *"there a big
  // box with no label or anything"*, then *"hide teh big box afterware it
  // dosnt need to be visibel"*. It was the only thing on the page with no
  // number chip and nothing to click, and what it says is already said by the
  // sections' own dashed outlines. So the GROUPING stays and the frame goes,
  // in the editor and in the exported sheet alike - the sheet shows what the
  // screen shows. This is the same end the balloon hint came to below.
  const bg={};
  regions.forEach(r=>{ const g=+(r.box_group||0);
    if(g>0){ (bg[g]=bg[g]||[]).push(r); } });
  const sectioned=r=>{ const g=+(r.box_group||0); return g>0 && bg[g] && bg[g].length>1; };
  // The balloon behind each box used to be drawn here as a faint dashed
  // rectangle - a label saying "this is the room the English may use". lee, on
  // finding it around a box on a page he was cleaning: *"there a thin dahed red
  // box around the box around the text what does it do and remove it"*. It
  // answered a question nobody was asking and looked like a second box, so it
  // is gone. `bubble_bbox` still does its job; it just does not draw itself.
  regions.forEach(r=>{
    // A text box you drew yourself, while it is the selected one and the
    // typesetting frame is therefore on screen: the frame IS its box. Drawing
    // both put two outlines and two sets of handles around one rectangle -
    // lee, with a picture of exactly that: *"the etxt box still crated a new
    // box"*. Unselected it keeps its box, or there would be nothing to see
    // and nothing to click.
    if(r.own_text && r.id===sel && inText() && !handMode
       && r.layout && r.layout.lines) return;
    // ...and outside the Edit view it has no box at all. The Translation
    // view is about the Japanese and what it will say; a rectangle holding
    // words of lee's own was never part of that conversation.
    // lee: *"ITS SHSOUD BE [not] LINK TO ANYTJING ITS SHOUD BE AN
    // IDENPENDNT TEXT BOX"*.
    if(r.own_text && !inText()) return;
    const [x,y,w,h]=r.bbox||r.bubble_bbox;
    const d=document.createElement('div');
    d.className='box'+(r.id===sel?' sel':'')
      +(selMulti.has(r.id)?' msel':'')+(r.manual?' manual':'')
      +((r.confidence<0.55&&!r.manual)?' weak':'')
      +(inText()?' textmode':'')
      +(r.link?' linked':'')
      +(sectioned(r)?' section':'')
      +(r.id===linkPick?' linkpick':'');
    d.style.cssText=`left:${x*scale}px;top:${y*scale}px;width:${w*scale}px;height:${h*scale}px`;
    // A box that has been turned leans on screen too. CSS turns about the
    // element's centre by default, which is the same centre `turned_box` on
    // the server turns the rectangle about - so the outline drawn here and the
    // outline the cleaner erases inside are the same four corners.
    const deg=turnOf(r);
    if(deg) d.style.transform=`rotate(${deg}deg)`;
    // Border + faint fill come from the text TYPE. Link grouping is shown by
    // the connector lines (drawLinks), so it no longer recolours the box.
    const kc=kindColor(r.kind);
    d.style.borderColor=kc;
    d.style.background=kc+'22';          // ~13% alpha
    d.dataset.id=r.id;
    st.appendChild(d);
    if(r.id===sel) addHandles(d);
  });
  drawLinks();
  // The order numbers live in their OWN layer above every box - a numbered
  // corner must never disappear under an overlapping neighbour's fill.
  regions.forEach(r=>{
    // No reading-order number on a box you drew yourself: the order is the
    // order the page is READ in, and your own box is not in it.
    if(r.own_text && !inText()) return;
    const [x,y]=r.bbox||r.bubble_bbox;
    const t=document.createElement('span');
    t.className='tagf'+(r.id===sel?' sel':'')
      +(selMulti.has(r.id)?' msel':'')+(r.manual?' manual':'');
    t.dataset.id=r.id;
    t.textContent=(r.order??0)+1;
    // The number badge matches its box's text-type colour.
    const tkc=kindColor(r.kind);
    t.style.cssText=`left:${x*scale-9}px;top:${y*scale-9}px;`+
      `background:${tkc};color:${contrastText(tkc)}`;
    st.appendChild(t);
  });
  drawText();
}
/* Linked bubbles: one continuous line split across balloons. Same colour +
   a dashed connector between their centres so the pairing is obvious. */
/* ---- colour system: three families, and shades within each ----

   Three main box types - balloon, outside text, sound effect - each with an
   undeletable default sub-type that carries the family's colour, and up to
   five more whose colours can only be SHADES of it. So the colour of a box
   says which family it is in before it says which sub-type, which is the way
   round that matters when you are looking at a page rather than a menu.

   These tables are the same ones in `mangatl/kinds.py`, which is where the
   reasoning lives; a test parses this file and fails if the two drift apart.
   Yellow is the selected box and blue is a link, so no family may drift into
   either - none of them does. */
const KIND_FAMILIES=['bubble','freefloat','sfx'];
const FAMILY_LABELS={bubble:'Bubble text', freefloat:'Freefloat text', sfx:'Sound effect'};
const DEFAULT_LABELS={bubble:'Regular speech', freefloat:'Freefloat text', sfx:'Sound effect'};
const KIND_COLORS={bubble:'#ed4545', freefloat:'#2cdd60', sfx:'#a550e2'};
const FAMILY_SHADES={
  bubble:['#ffaebe','#ff8f72','#ff5c7e','#c26046','#c29184','#a16e78','#a12f46','#805f57','#5f1c1c','#5f4147'],
  freefloat:['#9bf3c7','#5bf3a7','#5bf369','#30f391','#74b594','#5bb563','#1e9639','#4c7762','#125818','#39583b'],
  sfx:['#e9b0f9','#da68f9','#ab7bf9','#b29ad9','#c26cd9','#8b6fb9','#8f42b9','#6a4c9a','#592b7a','#36205a'],
};
const SUBS_PER_FAMILY=10;
/* One colour for every linked pair. lee: *"make the lunks just one color so
   all the link shoud be one color"*. Which link is which was never the
   question - the question is only ever whether two boxes are joined. */
/* A deeper blue. The old one was a pale cyan that read as a highlight
   rather than as a relationship, and at chip size on a dark panel it
   was almost white. lee: *"make the link a deapper blue"*. Nothing a
   box can be is blue - the three families are red, green and purple -
   so a blue row is always a linked row and never anything else. */
const LINK_COLOR='#2a63d8';
function linkColor(g){ return LINK_COLOR; }
/* Every sub-type the open project has. */
function subTypes(){
  return ((typeof proj!=='undefined'&&proj.settings&&proj.settings.custom_kinds)
          ||[]).filter(k=>k&&k.key);
}
/* Which family a kind belongs to. An unknown one is a balloon - a box whose
   sub-type has been deleted still has to draw, still has to be cleaned, and
   still has to obey the switch that puts its family away. */
function familyOf(kind){
  if(KIND_COLORS[kind]) return kind;
  const s=subTypes().find(k=>k.key===kind);
  return (s && KIND_COLORS[s.family]) ? s.family : 'bubble';
}
function subsOf(family){ return subTypes().filter(k=>familyOf(k.key)===family); }
/* Border colour for a box. A family's default carries the family colour;
   anything else carries a shade of it - and a sub-type whose colour is not one
   its own family issues is drawn in the family's first shade rather than in a
   colour that lies about which family it is in. */
function kindColor(kind){
  if(KIND_COLORS[kind]) return KIND_COLORS[kind];
  const s=subTypes().find(k=>k.key===kind);
  const shades=FAMILY_SHADES[familyOf(kind)]||FAMILY_SHADES.bubble;
  const c=(s&&s.color||'').toLowerCase();
  return shades.includes(c) ? c : shades[0];
}
/* Black or white text, whichever reads better on a given colour. */
function contrastText(hex){
  const h=(hex||'#888').replace('#','');
  const r=parseInt(h.slice(0,2),16), g=parseInt(h.slice(2,4),16),
        b=parseInt(h.slice(4,6),16);
  return (0.299*r+0.587*g+0.114*b) > 150 ? '#161616' : '#ffffff';
}
/* Where a link connector starts and ends: the middle of the WRITING, which is
   the box now on screen. Off the balloon it drew to thin air whenever the
   balloon was much bigger than the text in it. */
function boxCentre(r){ const [x,y,w,h]=r.bbox||r.bubble_bbox;
  return {x:(x+w/2)*scale, y:(y+h/2)*scale}; }
function drawLinks(){
  const st=$('stage');
  st.querySelectorAll('.linksvg').forEach(e=>e.remove());
  const groups={};
  regions.forEach(r=>{ if(r.link){ (groups[r.link]=groups[r.link]||[]).push(r); } });
  const keys=Object.keys(groups).filter(g=>groups[g].length>1);
  if(!keys.length) return;
  const NS='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(NS,'svg');
  svg.setAttribute('class','linksvg');
  svg.style.cssText='position:absolute;left:0;top:0;width:100%;height:100%;'
    +'pointer-events:none;overflow:visible;z-index:6';
  keys.forEach(g=>{
    const mem=groups[g].slice().sort((a,b)=>(a.order??0)-(b.order??0));
    const col=linkColor(+g);
    for(let i=0;i<mem.length-1;i++){
      // SECTIONS OF ONE BALLOON GET THE LINE TOO, and they used to be the
      // one case that did not: "already shown as one framed group", said the
      // reason. That frame is gone - lee asked for it twice, *"hide teh big
      // box afterware it dosnt need to be visibel"* - and nothing took over
      // saying it. `.box.section` forces the dashes back on, deliberately, so
      // it beats `.box.linked`'s solid border as well; between the two, a
      // linked pair of sections was drawn exactly like two unrelated boxes
      // and lee said so: *"the link is not showing"*.
      //
      // The line is the only thing left that can say it, so it says it.
      const a=boxCentre(mem[i]), b=boxCentre(mem[i+1]);
      const ln=document.createElementNS(NS,'line');
      ln.setAttribute('x1',a.x);ln.setAttribute('y1',a.y);
      ln.setAttribute('x2',b.x);ln.setAttribute('y2',b.y);
      ln.setAttribute('stroke',col);ln.setAttribute('stroke-width','2.5');
      ln.setAttribute('stroke-dasharray','6 4');ln.setAttribute('opacity','0.9');
      svg.appendChild(ln);
    }
    // No markers ON the boxes - linking only draws the connecting line, so a
    // box keeps its text-type colour completely unchanged.
  });
  st.appendChild(svg);
}
/* The four corners, as (right?, bottom?) pairs. A turn ZONE sits just
   outside each one - the same bargain the typeset frame already makes: press
   the corner and you resize, step past it and you turn. lee: *"make the rotat
   the same way as the text box with the corners allowiing me to rotate it"*.

   It replaced a single handle on a stalk above the box, which was both a
   second thing to learn and only ever offered on a box somebody drew. */
const ROTZ=[[0,0],[1,0],[0,1],[1,1]];

function addHandles(box){
  // BOTH classes, or every re-select stacks another four zones on the box.
  box.querySelectorAll('.hd,.rotz').forEach(h=>h.remove());
  ['nw','ne','sw','se'].forEach(c=>{
    const h=document.createElement('div');
    h.className='hd '+c; h.dataset.c=c; box.appendChild(h);
  });
  // ...and a turn zone outside each corner, on EVERY box. It used to be
  // conditional on the box being hand-drawn, because a detected outline came
  // off the artwork and turning it read as turning the drawing. lee asked for
  // the other thing - *"alowm me to be able to rotate every box"* - and a
  // detector is as able to be wrong about the angle as about the edges.
  ROTZ.forEach(([rt,bt])=>{
    const z=document.createElement('div');
    z.className='rotz'+(rt?' r':'')+(bt?' b':'');
    z.dataset.c='rot'; box.appendChild(z);
  });
}
function turnOf(r){
  return r ? (+(r.turn||0)||0) : 0;
}
/* The translated view is the CLEANED page plus typesetting drawn here in the
   browser. Editing then costs nothing - no round trip, no re-render - and the
   server stays the authority for the exported file. */
function layoutOrigins(r, L){
  // A sound effect is the one thing not laid out in a box: it runs along its
  // own measured axis, letter by letter, with the gap between lines taken
  // from the ink rather than from a leading. Nothing here reproduces that, so
  // its origins ARE its layout and are used as they came.
  // A speech divided between the two lobes of a double balloon is the same
  // kind of exception for the same reason: it is TWO blocks, one per lobe,
  // and no single box spaced evenly reproduces them. Filling one is what put
  // the second half back across the waist.
  if((r.kind==='sfx' || L.fixed) && L.origins
     && L.origins.length===L.lines.length && !L.dirty) return L.origins;
  // Everything else is a text box, and this is the one piece of arithmetic
  // that fills one: lines centred on the box, evenly spaced down it. The
  // server places the box and then places its lines from the box with exactly
  // this sum, and so does the editor you type into - three engines that used
  // to disagree, which is why clicking a block made the words jump.
  //
  // No dx/dy here: a frame already has them baked in (both the server's and
  // the one dragging writes), and adding them again is how a block crept by
  // one nudge on every click.
  const [fx,fy,fw,fh]=frameOf(r);
  const lh=L.font_size*(L.leading||1.12);
  const top=fy+(fh-L.lines.length*lh)/2;
  // Which edge the lines hang from. Centred unless asked otherwise - and the
  // preview has to agree with the page, so this is the same sum the server
  // does in `apply_align`: every line is DRAWN centred on its origin, so
  // ranging it left or right is a matter of moving each origin by half the
  // difference between that line and the widest one.
  const how=(r.style&&r.style.align)||(r.layout_override&&r.layout_override.align)
            ||'center';
  const ws=(how==='left'||how==='right')
    ? L.lines.map(ln=>measureLine(ln, L, r)) : null;
  const widest=ws?Math.max(...ws,0):0;
  return L.lines.map((ln,k)=>{
    let x=fx+fw/2;
    if(ws){ const d=(widest-ws[k])/2; x += (how==='left'?-d:d); }
    return [x, Math.round(top+(k+0.5)*lh)];
  });
}
/* How wide one line is in the face this block uses - measured in a canvas,
   because that is what the browser will actually draw with. */
let _measCtx=null;
function measureLine(text, L, r){
  if(!_measCtx) _measCtx=document.createElement('canvas').getContext('2d');
  const ov=(r&&r.layout_override)||{}, st=(r&&r.style)||{};
  const fam=(typeof fontFam==='function')
    ? fontFam(ov.font||st.font||L.font, r&&r.kind) : 'sans-serif';
  // The size ASKED FOR, not the size stored: a point is not a size, and the
  // server draws this line through `typeset.px_for`. Measuring at the nominal
  // size in a face with small capitals put every line short of where the page
  // actually puts it. See `project.emPx`.
  _measCtx.font=`${emPx(L.font_size, fam)}px ${fam}`;
  return _measCtx.measureText(text||'').width;
}

/* ---------------- the text frame (move / resize / rotate) ---------------- */
const TH=[['nw',0,0],['n',.5,0],['ne',1,0],['e',1,.5],
          ['se',1,1],['s',.5,1],['sw',0,1],['w',0,.5]];
const CORNERS=TH.filter(h=>h[0].length===2);

/* Which way each handle points, in the box's own frame, as a screen angle:
   0 is right, 90 is down (screen y grows downward). */
const TH_DEG={e:0, se:45, s:90, sw:135, w:180, nw:225, n:270, ne:315};
/* ...and the cursor for a direction, to the nearest eighth of a turn. Only
   four names exist for eight directions, because a resize arrow is a line and
   a line has no head: ns, ew, nwse, nesw. */
const DIR_CUR=['ew','nwse','ns','nesw','ew','nwse','ns','nesw'];
function dirCursor(deg){
  const d=((deg%360)+360)%360;
  return DIR_CUR[Math.round(d/45)%8]+'-resize';
}
/* The handle's direction on screen. The frame is drawn with
   `transform: rotate(-rotate)`, so the box's own angles arrive on screen
   turned by exactly that much. */
function handleCursor(name, rot){
  return dirCursor((TH_DEG[name]||0) - (+rot||0));
}
/* A curved arrow, as a cursor. Two colours with a dark rim so it reads on
   white paper and on black ink alike. */
const ROT_CURSOR="url(\"data:image/svg+xml;utf8,"+encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">'+
  '<g fill="none" stroke="#000" stroke-width="3.4" stroke-linecap="round">'+
  '<path d="M5 13a6 6 0 1 1 3 5"/></g>'+
  '<g fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round">'+
  '<path d="M5 13a6 6 0 1 1 3 5"/></g>'+
  '<path fill="#000" d="M1.6 12.4 8.4 12.4 5 7.2Z"/>'+
  '<path fill="#fff" d="M3.1 11.4 6.9 11.4 5 8.6Z"/></svg>')+
  "\") 11 11, crosshair";

function drawFrame(){
  const old=$('tframe'); if(old) old.remove();
  if(!inText()||sel===null||handMode) return;
  const r=regions.find(x=>x.id===sel);
  // An emptied block keeps its frame, so the handles are still there to
  // resize it and there is somewhere to click to type into it again.
  if(!r||!r.layout||!r.layout.lines) return;

  const [fx,fy,fw,fh]=frameOf(r);
  const rot=+(r.layout.rotate||0);
  const el=document.createElement('div');
  el.id='tframe';
  if(editing===r.id) el.classList.add('editing');
  el.style.cssText=`left:${fx*scale}px;top:${fy*scale}px;`+
    `width:${fw*scale}px;height:${fh*scale}px;`+
    (rot?`transform:rotate(${-rot}deg);`:'');

  if(editing!==r.id){
    const body=document.createElement('div');
    body.className='tbody';
    body.addEventListener('mousedown',e=>startFrame(e,r.id,'move'));
    el.appendChild(body);
  } else {
    // While typing, the middle belongs to the caret - so the border is what
    // you grab to move it, as in Word.
    ['t','r','b','l'].forEach(side=>{
      const g=document.createElement('div');
      g.className='tedge '+side;
      g.addEventListener('mousedown',e=>startFrame(e,r.id,'move'));
      el.appendChild(g);
    });
  }

  // Just outside each corner, a zone that rotates. This is where every
  // drawing program puts it, and it is where the hand already is after
  // resizing. lee: *"remove teh rotate thing the the top of teh text bot and
  // make it so that if i go to the edgec corner and out out a little a rotate
  // thing come up ... and tht hsoud happen to all 4 corners"*.
  //
  // Added BEFORE the handles so a press exactly on a corner resizes: the
  // handle is painted over the zone and takes the click.
  CORNERS.forEach(([name,ax,ay])=>{
    const z=document.createElement('div');
    z.className='trotz';
    z.style.left=(ax*100)+'%'; z.style.top=(ay*100)+'%';
    // centred on the corner and nudged OUTWARDS, so most of it lies outside
    // the box: press the corner itself and you resize, step a little past it
    // and you turn
    // 16px clear of the corner: the resize handle's own hit area reaches
    // about ten, and a zone centred inside that is a zone you can never
    // press. The two overlap only where the handle wins.
    z.style.transform=`translate(calc(-50% + ${ax?16:-16}px),`+
                      ` calc(-50% + ${ay?16:-16}px))`;
    z.style.cursor=ROT_CURSOR;
    z.title='Drag to turn the box · Shift snaps to 15°';
    z.addEventListener('mousedown',e=>startFrame(e,r.id,'rot'));
    el.appendChild(z);
  });

  TH.forEach(([name,ax,ay])=>{
    const h=document.createElement('div');
    h.className='th';
    h.style.left=(ax*100)+'%'; h.style.top=(ay*100)+'%';
    // The cursor has to mean what the handle DOES on screen. A box turned
    // 90° has its top-left corner pointing up-and-right, and an arrow saying
    // otherwise is worse than no arrow. lee: *"make sure when the txext box
    // is rotated it the coner show acurate mouse icons"*.
    h.style.cursor=handleCursor(name, rot);
    h.addEventListener('mousedown',e=>startFrame(e,r.id,'size',name));
    el.appendChild(h);
  });

  // Photoshop and InDesign both mark a box whose text no longer fits with a
  // small badge on the frame rather than by hiding or shrinking anything -
  // you are told, and you decide. Same here: the words are all still drawn.
  if(overset(r)){
    const b=document.createElement('div');
    b.className='tover'; b.textContent='+';
    b.title='The text is bigger than its box - drag a corner to fit it';
    el.appendChild(b);
  }

  $('stage').appendChild(el);
}

let fdrag=null;
function startFrame(e,id,mode,corner){
  e.preventDefault(); e.stopPropagation();
  // Grabbing a handle doesn't blur the inline editor in every browser, and a
  // stuck-open editor drew a ghost copy of the text. Close it cleanly first.
  if(editing!==null) closeCanvasEdit(true);
  const r=regions.find(x=>x.id===id); if(!r) return;
  if(r.locked){ toast('That text box is locked.'); return; }   // …nor moved
  fdrag={id, mode, corner, p0:pt(e), fr:frameOf(r).slice(),
         rot0:+(r.layout.rotate||0), moved:false,
         words:(r.layout&&r.layout.lines
                ? r.layout.lines.join(' ').split(/\s+/).filter(Boolean) : [])};
}

function moveFrame(e){
  if(!fdrag) return;
  const r=regions.find(x=>x.id===fdrag.id); if(!r) return;
  const p=pt(e);
  let dx=(p.x-fdrag.p0.x)/scale, dy=(p.y-fdrag.p0.y)/scale;
  if(Math.abs(p.x-fdrag.p0.x)>1||Math.abs(p.y-fdrag.p0.y)>1) fdrag.moved=true;
  let [fx,fy,fw,fh]=fdrag.fr;

  if(fdrag.mode==='rot'){
    // RELATIVE to where the grab started, not absolute. The old handle stuck
    // out of the top of the box at a fixed angle, so setting the rotation to
    // "wherever the pointer is, plus ninety" happened to mean "no change" on
    // the press. From a corner it means a 45° jolt the instant you touch it.
    // Turn by how far the pointer has travelled round the centre instead, and
    // grabbing anything anywhere moves nothing until you do.
    const cx=(fx+fw/2)*scale, cy=(fy+fh/2)*scale;
    const a1=Math.atan2(p.y-cy, p.x-cx)*180/Math.PI;
    // seeded from where the button went DOWN, not from the first move -
    // otherwise the first stretch of the drag is silently thrown away
    if(fdrag.aPrev==null){
      fdrag.aPrev=Math.atan2(fdrag.p0.y-cy, fdrag.p0.x-cx)*180/Math.PI;
      fdrag.acc=0;
    }
    // The angle jumps 360 as it crosses the far side, so each step is wrapped
    // into half a turn and ADDED UP. Comparing against the start instead
    // meant a drag round the bottom-left corner came out three quarters the
    // wrong way - and past a full turn it would have flipped every time.
    let step=a1-fdrag.aPrev;
    while(step>180) step-=360;
    while(step<-180) step+=360;
    fdrag.acc+=step; fdrag.aPrev=a1;
    let deg=fdrag.rot0-fdrag.acc;
    if(e.shiftKey) deg=Math.round(deg/15)*15;   // snap to 15° with Shift
    r.layout.rotate=deg;
    r.layout_override=Object.assign({},r.layout_override,
                                    {rotate:deg,locked:true});
    const f=$('lyRot'); if(f) f.value=Math.round(deg);
  } else if(fdrag.mode==='move'){
    fx+=dx; fy+=dy;
    setFrame(r,[fx,fy,fw,fh]);
  } else {
    // resizing happens in the frame's own space, so a rotated box still
    // grows the way the handle you grabbed suggests
    const th=-(+(r.layout.rotate||0))*Math.PI/180;
    const lx= dx*Math.cos(th)+dy*Math.sin(th);
    const ly=-dx*Math.sin(th)+dy*Math.cos(th);
    const c=fdrag.corner;
    if(c.includes('w')){fx+=lx; fw-=lx;}
    if(c.includes('e')){fw+=lx;}
    if(c.includes('n')){fy+=ly; fh-=ly;}
    if(c.includes('s')){fh+=ly;}
    if(fw<16||fh<16) return;
    setFrame(r,[fx,fy,fw,fh]);
    // All local, no round trip: corners scale the text with the box, sides
    // re-wrap at the same size (left/right also hug the height). The server
    // confirms once, on release.
    fdrag.invert=!!(e.ctrlKey||e.metaKey);   // read again on release
    const flags=resizeFlags(c, fdrag.invert, r);
    if(flags.fit) localFit(r); else localWrap(r, flags.snug);
  }
  if(editing!==null){
    const er=regions.find(x=>x.id===editing);
    if(er) placeEditor($('canvasEdit'), er);
  }
  drawText();          // drawText redraws the frame itself
}

/* How much of a block has to stay on the paper. The same number as
   typeset.ON_PAGE_PX, which does this again on the server for anything that
   arrives another way. */
const ON_PAGE_PX = 24;
function onPage(fr){
  const W=pageW||0, H=(typeof pageH!=='undefined'?pageH:0)||0;
  if(!W||!H) return fr;
  const k=ON_PAGE_PX;
  return [Math.max(Math.min(fr[0], W-k), k-fr[2]),
          Math.max(Math.min(fr[1], H-k), k-fr[3]), fr[2], fr[3]];
}

function setFrame(r,f){
  // A box may hang over the edge - a sound effect running off the side of a
  // panel does exactly that. What it may not do is leave: a block whose whole
  // box is past the edge is not drawn, not clickable and not reachable at
  // all, and the only thing left to do with it is delete it and start again.
  // lee: *"the etxt box shifted out of the page and is now stuck and
  // unclicable"*.
  const fr=onPage([Math.round(f[0]),Math.round(f[1]),
            Math.round(Math.max(16,f[2])),Math.round(Math.max(16,f[3]))]);
  const L=r.layout, old=L.frame;
  // A divided speech has no even spacing to recompute, so moving its box
  // CARRIES the words instead: the same shift is applied to every line, and
  // the two halves stay in their own lobes exactly as they were laid out.
  if(L.fixed && L.origins && old && old.length===4){
    const ddx=fr[0]-old[0], ddy=fr[1]-old[1];
    if(ddx||ddy) L.origins=L.origins.map(o=>[o[0]+ddx, o[1]+ddy]);
  }
  L.frame=fr;
  if(!L.fixed) L.dirty=true;  // recompute positions from the frame, not cache
  const extra=L.fixed
    ? {fixed:true, origins:L.origins.map(o=>[Math.round(o[0]),
                                             Math.round(o[1])])}
    : {};
  r.layout_override=Object.assign({},r.layout_override,
                                  {frame:fr,locked:true},extra);
}

/* Resizing or re-wrapping turns a divided speech back into an ordinary block
   in an ordinary box: the person has taken it over, and from here the box is
   the layout again - which is what they are expecting while they drag it. */
function unfix(r){
  const L=r.layout; if(!L||!L.fixed) return;
  L.fixed=false;
  if(r.layout_override) delete r.layout_override.fixed;
  if(r.layout_override) delete r.layout_override.origins;
}

/* Which resize behaviour a handle gets: corners (two letters) scale the
   text with the box; sides re-wrap at the same size, and dragging the left
   or right side lets the height follow the text.

   Holding Ctrl (⌘ on a Mac) swaps the two, which is how Photoshop works
   round the other way: there a handle reflows by default and Ctrl scales.
   Either way the point is that both behaviours are on every handle, so you
   are never forced to let go and grab a different one. */
function resizeFlags(corner, invert, r){
  let scaling=(corner&&corner.length===2) ? !invert : !!invert;
  // A BLOCK WITH MIXED SIZES IS NEVER RESCALED BY ITS BOX.
  //
  // Scaling means one new size for the whole block, and a block where part
  // of the text was deliberately made bigger has no one size to give it -
  // dragging a corner would flatten the very difference somebody set. lee:
  // *"if all the text in a box is the same, then keep the text box as is
  // but if some of the text is not the same make chnaging the text box
  // size not change the text size like it does now to keep it simple"*.
  // So a corner on such a block re-wraps at the sizes it already has,
  // which is what every side drag does anyway.
  if(scaling && typeof hasMetricSpans==='function' && hasMetricSpans(r))
    scaling=false;
  return scaling
    ? {fit:true}
    : {wrap:true, snug:(corner==='e'||corner==='w')};
}

/* Does any range in this block carry a face or a size of its own? The one
   question that decides whether the block still has a single size to scale.
   `render.has_metric_spans` asks it on the other side. */
function hasMetricSpans(r){
  const raw=(r&&r.layout_override||{}).spans;
  if(!Array.isArray(raw)) return false;
  return raw.some(sp=>sp && sp.st
    && (sp.st.font!==undefined || sp.st.font_size!==undefined));
}

/* Does the text run past its box? Measured the way the box is measured -
   widest line against the width, line count against the height. */
function overset(r){
  const L=r&&r.layout;
  if(!L||!L.lines||!L.lines.length) return false;
  const [,,fw,fh]=frameOf(r);
  const ov=r.layout_override||{};
  const fam=fontFam(ov.font||L.font||'', r.kind);
  const lh=L.font_size*(L.leading||1.12);
  if(L.lines.length*lh > fh+1) return true;
  for(const t of L.lines)
    if(textW(fam, L.font_size, t) > fw-2*PADL+1) return true;
  return false;
}

/* ---- local layout while dragging ----
   The browser measures and wraps the text itself on every mouse move, so
   resizing is smooth; the server's word-for-word layout replaces it once
   on release. Same greedy wrap, same padding as the server. */
const PADL=4;
let _measure=null;
function textW(fam,size,t){
  if(!_measure) _measure=document.createElement('canvas').getContext('2d');
  // `size` is the NOMINAL size everything stores; `emPx` is the pixel size the
  // face is actually asked for, here and on the server. One conversion, in the
  // one place every caller measures through - wrapping, fitting, the overset
  // check and the curved-line places all come here.
  _measure.font=`${emPx(size, fam)}px ${fam},sans-serif`;
  return _measure.measureText(t).width;
}
function wrapLocal(words,fam,size,maxw){
  const out=[]; let line='';
  for(const w of words){
    const cand=line?line+' '+w:w;
    if(line && textW(fam,size,cand)>maxw){ out.push(line); line=w; }
    else line=cand;
  }
  if(line) out.push(line);
  return out;
}
function dragWords(r){
  return (fdrag&&fdrag.words&&fdrag.words.length) ? fdrag.words
    : r.layout.lines.join(' ').split(/\s+/).filter(Boolean);
}
/* The panel says what the page says.

   Dragging a corner re-fits the text locally and writes the answer onto the
   LAYOUT. The size box and the line box in the Typesetting panel were left
   holding what they held before the drag - and `currentPatch` builds every
   save out of those two fields. So the next save that is not itself a fit -
   a nudge, a colour, a click on another control - posted the stale size back
   over the one that had just been dragged, and the text sprang back to what
   it was.

   lee: *"wheni move it a little bit it reverts to the bigger size and teh
   after cliking off it revest back t teh samler text"*. Both halves of that
   are this: big is the layout, small is the panel, and whichever spoke last
   won.

   `livePreview` already does exactly this from the SERVER's answer when a fit
   or a wrap comes back. This is the same sync for the local one, which is the
   copy that exists while the mouse is still down.

   Never while somebody is typing in the field: a value replaced under the
   caret is a value they were halfway through changing. */
function panelSaysWhatTheLayoutSays(r){
  if(typeof sel!=='undefined' && sel!==null && sel!==r.id) return;
  const L=r.layout; if(!L) return;
  const sz=$('lySize');
  if(sz && document.activeElement!==sz && L.font_size) sz.value=L.font_size;
  const la=$('lyLines');
  if(la && document.activeElement!==la && L.lines) la.value=L.lines.join('\n');
}

function localWrap(r, snug){
  const L=r.layout; if(!L||!L.lines) return;
  unfix(r);
  const ov=r.layout_override||{};
  const fam=fontFam(ov.font||((r.style||{}).font)||L.font, r.kind);
  const [fx,fy,fw]=frameOf(r);
  const size=L.font_size, lead=L.leading||1.12;
  const lines=wrapLocal(dragWords(r),fam,size,Math.max(8,fw-2*PADL));
  if(lines.length){ L.lines=lines; L.dirty=true; panelSaysWhatTheLayoutSays(r); }
  if(snug){
    const nh=Math.round(L.lines.length*size*lead+2*PADL);
    L.frame=[fx,fy,fw,nh];
    r.layout_override=Object.assign({},r.layout_override,
                                    {frame:[fx,fy,fw,nh],locked:true});
  }
}
function localFit(r){
  const L=r.layout; if(!L||!L.lines) return;
  unfix(r);
  const ov=r.layout_override||{};
  const fam=fontFam(ov.font||((r.style||{}).font)||L.font, r.kind);
  const [,,fw,fh]=frameOf(r);
  const lead=L.leading||1.12, words=dragWords(r);
  const aw=Math.max(8,fw-2*PADL), ah=Math.max(8,fh-2*PADL);
  let lo=7, hi=200, best=null;
  while(lo<=hi){
    const mid=(lo+hi)>>1;
    const ls=wrapLocal(words,fam,mid,aw);
    const ok=ls.length
      && ls.length*mid*lead<=ah
      && Math.max(...ls.map(t=>textW(fam,mid,t)))<=aw;
    if(ok){ best=[mid,ls]; lo=mid+1; } else hi=mid-1;
  }
  if(best){
    L.font_size=best[0]; L.lines=best[1]; L.dirty=true;
    panelSaysWhatTheLayoutSays(r);
  }
}

function endFrame(){
  if(!fdrag) return;
  const {id, moved, mode, corner, invert}=fdrag; fdrag=null;
  if(!moved) return;                 // a plain click just selects
  const r=regions.find(x=>x.id===id);
  if(!r) return;
  // One request, not two: the save's reply carries the fresh layout, and a
  // second concurrent preview was the other half of the springing-text race.
  saveTypesetting(id, true,
                  mode==='size' ? resizeFlags(corner, invert, r) : null);
}

window.addEventListener('mousemove',moveFrame);
window.addEventListener('mouseup',endFrame);
