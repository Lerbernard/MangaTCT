/* view.js — Zoom, pan, hand tool, view switching (original/clean/typeset), tabs, results list.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* ---------------- tabs / results ---------------- */
let tab='edit';
/* ---------------- zoom & pan ---------------- */
function fitScale(){
  const wrap=$('canvasWrap');
  // Layout may not have settled on the very first paint; retry rather than
  // computing a fit from a zero-sized container.
  if(!pageW||!wrap.clientWidth||!wrap.clientHeight){
    soon(()=>{ if($('img').naturalWidth){fitZoom=fitScale();applyZoom();} });
    return fitZoom||1;
  }
  const avail=wrap.clientWidth-28, availH=wrap.clientHeight-28;
  // pageW/pageH are what the SERVER said about the page that is open now.
  // The <img> is a rendering of it and lags: while the next page's picture is
  // still on the wire the element still reports the LAST page's size, and a
  // fit measured from that is a fit for the wrong page. lee: *"wheni swith to
  // the next page its still keeping the old pages size, meanin that if the
  // next page is smaller it gts stuck on top"*. The element is the fallback
  // now, not the authority.
  const d=$('img');
  const pw=pageW||d.naturalWidth||1, ph=pageH||d.naturalHeight||1;
  return Math.min(avail/pw, availH/ph, 1);
}

function applyZoom(){
  const img=$('img');
  // Same authority as fitScale, and for a sharper reason here: the width was
  // taken from the ELEMENT while `scale` divided it by pageW, so between
  // pages those two were describing different pictures — and `scale` is what
  // every box is drawn with. A stale width did not just size the page wrong,
  // it put the boxes somewhere the writing is not.
  const nw=pageW||img.naturalWidth;
  if(!nw) return;
  const pc=$('paint');
  if(pc){
    // The paint canvas is sized from BOTH dimensions, not width plus
    // `height:auto`.
    //
    // `auto` takes its height from the canvas's own BITMAP aspect, and the
    // bitmap is only resized when someone paints — so on the page after a tall
    // one it is still 690 by 3000, and 629 CSS pixels wide at that aspect is
    // 2735 tall. The canvas lives inside the stage, so the stage became 2735
    // tall for an 821-tall picture, and `centerPage` — which centres the
    // STAGE — put the middle of that empty column in front of you with the
    // page scrolled 613 pixels off the top of the pane.
    //
    // lee, on the framing for the fourth time: *"try to fi the issue of teh
    // image not being centered"*. Measured in a real browser, turning from the
    // tall page to the short one left the picture at top −599 in an 849-tall
    // pane. Every other state measured — first paint, turning back, the Find
    // text dialog open, Fit page, 2x, hiding the side panel, a page wider than
    // the pane — was centred to the pixel, which is why this one lasted.
    const nh=pageH||img.naturalHeight||0;
    pc.style.width=(nw*fitZoom*zoom)+'px';
    pc.style.height=nh ? (nh*fitZoom*zoom)+'px' : 'auto';
  }
  const w=nw*fitZoom*zoom;
  img.style.width=w+'px'; img.style.height='auto';
  const ri=$('refImg');
  if(ri && sideBySide) ri.style.width=w+'px';   // reference keeps the zoom
  scale=w/nw;
  // The percentage is the REAL one: how big a page pixel is on screen.
  // It used to be `zoom`, which is measured from the fit — so a page shrunk
  // to a third to get it in the window read "100%", and there was no number
  // anywhere that meant actual size. lee: *"double clciking teh hadns dosnt
  // change teh zoom it jyst centers it"* — it did exactly what the readout
  // said, which was the problem.
  $('zlabel').textContent=Math.round(scale*100)+'%';
  drawBoxes();
}

/* ---- side by side ----
   The untouched original page in a second pane, at the same zoom, scrolling
   in step with the pane being edited. Identical border geometry on both
   stages makes the scroll positions map one to one. */
let sideBySide=false;
function toggleSideBySide(on){
  sideBySide = (on===undefined) ? !sideBySide : !!on;
  const ck=$('sbs'); if(ck) ck.checked=sideBySide;
  syncViewChrome();
  refSync();
  // the editing pane just changed width — refit and recentre both panes
  fitZoom=fitScale(); applyZoom(); centerPageSoon();
}
/* The reference pane is the page you are working on beside the page you
   started from, so it says something only in the Edit view of the Edit tab —
   on the Original view it is the same picture twice, and on Results or
   Settings there is no page in front of you at all. The switch goes where the
   pane can go, next to the other switch that follows the same rule. */
function sbsUsable(){ return tab === 'edit' && view === 'typeset'; }

function syncViewChrome(){
  const ok = sbsUsable();
  const sw = $('sbsWrap');
  if (sw) sw.style.display = ok ? 'inline-flex' : 'none';
  const stw = $('showTextWrap');
  if (stw) stw.style.display = (view === 'typeset') ? 'inline-flex' : 'none';
  const rw = $('refWrap');
  if (rw) rw.style.display = (ok && sideBySide) ? 'block' : 'none';
  // Cut / join belongs to the Translation view — the artwork as it came. In
  // the Image view the boxes are placed against the page and the server
  // refuses to cut it, so a button there would only ever offer a refusal.
  //
  // ...and to a webtoon. lee: *"cut and join shoud only be a thing for manhwa
  // and manhua"*. A manga chapter arrives as pages somebody already decided
  // the boundaries of; a webtoon arrives as a strip somebody's slicer cut by
  // counting, and putting those boundaries right is the whole reason any of
  // this exists.
  const cb = $('cutBtn');
  const strip = (typeof stripMedium === 'function') ? stripMedium() : true;
  if (cb) cb.style.display = (view === 'original' && strip)
    ? 'inline-flex' : 'none';
}

/* Put the page back in front of the person after the stage has been away.
   Called on returning to the Edit tab; harmless when there is no page yet. */
function showPageAgain(){
  const img=$('img');
  if(img && img.naturalWidth){ fitZoom=fitScale(); applyZoom(); }
  refSync();
  centerPageSoon();
}

function refSync(){
  if(!sideBySide) return;
  const ri=$('refImg'), img=$('img');
  if(!ri) return;
  if(ri.dataset.page!==String(cur)){
    ri.dataset.page=String(cur);
    // With no key on the URL the server has to answer no-store, so the scan
    // came down the wire again on every single page turn — the lag the side by
    // side pane was adding. Keyed, the browser reuses the copy it has.
    // One definition of the URL, shared with showPage and the prefetcher, so
    // what was warmed is what gets asked for.
    const k = (typeof scanKey!=='undefined' && scanKey[cur]) || '';
    ri.src=(typeof pageUrl==='function') ? pageUrl(cur,'original')
      : apiUrl(`/img/${cur}`+(k?`?v=${encodeURIComponent(k)}`:''));
    ri.onload=()=>{ if(img&&img.naturalWidth)
      ri.style.width=img.style.width; refFollow(); };
  }
  if(img&&img.style.width) ri.style.width=img.style.width;
  refFollow();
}
function refFollow(){
  const a=$('canvasWrap'), b=$('refWrap');
  if(a&&b&&sideBySide){ b.scrollLeft=a.scrollLeft; b.scrollTop=a.scrollTop; }
}
(function refScrollSync(){
  const a=$('canvasWrap'), b=$('refWrap');
  if(!a||!b) return;
  let lock=false;
  const follow=(from,to)=>()=>{
    if(lock||!sideBySide) return;
    lock=true;
    to.scrollLeft=from.scrollLeft; to.scrollTop=from.scrollTop;
    soon(()=>{ lock=false; });
  };
  a.addEventListener('scroll',follow(a,b),{passive:true});
  b.addEventListener('scroll',follow(b,a),{passive:true});
})();

function zoomBy(f){
  const wrap=$('canvasWrap'), img=$('img');
  // Anchor on the PAGE, not on raw scroll offsets: the old math divided
  // scroll positions (which include the huge pan border) by the image size,
  // so every click of +/− pushed the page off centre. The image point in
  // the middle of the pane stays in the middle — an untouched, centred view
  // therefore zooms exactly on the centre of the page.
  const ir=img.getBoundingClientRect(), wr=wrap.getBoundingClientRect();
  let px=((wr.left+wr.width/2)-ir.left)/Math.max(1,ir.width);
  let py=((wr.top +wr.height/2)-ir.top )/Math.max(1,ir.height);
  if(centerPending){ px=0.5; py=0.5; }   // pristine view: the page centre
  px=Math.max(0,Math.min(1,px)); py=Math.max(0,Math.min(1,py));
  centerPending=false;               // zooming = the person owns the view now
  zoom=Math.max(0.1,Math.min(8,zoom*f));
  applyZoom();
  const ir2=img.getBoundingClientRect(), wr2=wrap.getBoundingClientRect();
  const imgL=wrap.scrollLeft+(ir2.left-wr2.left);
  const imgT=wrap.scrollTop +(ir2.top -wr2.top);
  wrap.scrollLeft=imgL+px*ir2.width -wr2.width/2;
  wrap.scrollTop =imgT+py*ir2.height-wr2.height/2;
}

/* The zoom steps in whole percentage points, and lands on round ones.

   It used to multiply by 1.25, so from a fit of 43% the readout walked 54, 67,
   84, 105 — every number a different arbitrary one, and never 100.
   lee: *"when i clcik the plus and minus in the zoom it shoud not go to theses
   random bumbers, it shiud increase and decrease by 5"*. */
const ZOOM_STEP = 5;
function zoomStep(d){
  const now = Math.round(scale * 100);
  // snap to the step grid on the way, so ± always lands on a round number
  const want = Math.max(5, Math.min(800,
    Math.round((now + d) / ZOOM_STEP) * ZOOM_STEP));
  if(scale > 0) zoomBy((want / 100) / scale);
}

function fitPage(){
  zoom=1; fitZoom=fitScale(); applyZoom();
  centerPageSoon();
}
/* Actual size: one page pixel to one screen pixel, which is what 100% means
   everywhere else and what the readout now says. `zoom` is measured from the
   fit, so 1:1 is however much undoes it. */
function zoomTo100(){
  if(!fitZoom) fitZoom=fitScale();
  zoom=Math.max(0.1,Math.min(8,1/(fitZoom||1)));
  applyZoom();
  centerPageSoon();
}
function centerPage(){
  const wrap=$('canvasWrap');
  wrap.scrollLeft=(wrap.scrollWidth-wrap.clientWidth)/2;
  wrap.scrollTop =(wrap.scrollHeight-wrap.clientHeight)/2;
}
/* Centre and KEEP it centred while the page is still settling. Fixed retry
   counts kept losing the race against slow renders and late layout — so
   instead the centre stays "pending" and a ResizeObserver re-centres on
   every size change of the wrap or the stage, until the person takes over
   the view themselves (drag, wheel, pan). */
let centerPending=false;
function centerPageSoon(){
  centerPending=true;
  centerPage();
  soon(centerPage);                        // once more after this frame settles
}
(function centerKeeper(){
  const wrap=$('canvasWrap'), stage=$('stage');
  if(!wrap||!stage) return;
  const enforce=()=>{
    if(!centerPending) return;
    const offT=Math.abs(wrap.scrollTop -(wrap.scrollHeight-wrap.clientHeight)/2);
    const offL=Math.abs(wrap.scrollLeft-(wrap.scrollWidth -wrap.clientWidth )/2);
    if(offT>2||offL>2) centerPage();
  };
  if(typeof ResizeObserver!=='undefined'){
    // The WRAP changing size is a different event from the stage changing
    // size, and it needs more than a re-centre: the fit was measured against
    // the old pane. A page opened while this pane was the wrong size — the
    // settings page still up, the window not yet laid out, a sidebar
    // appearing — was fitted to a pane that no longer exists, so it comes out
    // too big for the one you are looking at and centring it only puts its
    // middle in front of you. lee: *"some pages are still not at the center of
    // the workspace"*.
    //
    // Only while the centring is still pending: once the person has taken the
    // view over, resizing the window must not throw their zoom away.
    let wasW=0, wasH=0;
    const ro=new ResizeObserver(()=>{
      const w=wrap.clientWidth, h=wrap.clientHeight;
      const moved=(w!==wasW||h!==wasH);
      wasW=w; wasH=h;
      if(centerPending && moved && w>1 && h>1
         && typeof fitScale==='function' && typeof applyZoom==='function'){
        fitZoom=fitScale(); applyZoom();
        if(typeof drawOverlay==='function') drawOverlay();
      }
      enforce();
    });
    ro.observe(wrap);
    new ResizeObserver(enforce).observe(stage);
  }
  const img=$('img');
  if(img) img.addEventListener('load',enforce);
  // The browser itself sometimes claws the scroll back to 0 while a page is
  // still settling (flex centring + scroll anchoring). While the centre is
  // pending, a light heartbeat puts it back until the person takes over.
  setInterval(enforce,150);
  ['pointerdown','wheel'].forEach(ev=>
    wrap.addEventListener(ev,()=>{ centerPending=false; },{passive:true}));
})();

let handPanned=false;
function toggleHand(on, quiet){
  const was=handMode;
  handMode = (on===undefined) ? !handMode : !!on;
  if(handMode){ disarmTools('hand'); handPanned=false; }
  // Picking the hand up and putting it straight back down — without ever
  // panning — reads as "bring the page back": recentre it. NOT when another
  // tool put the hand away (quiet): switching tools must never move the view.
  else if(was && !handPanned && !quiet) centerPageSoon();
  // The toolbox is the one place that says what is armed; the hand's own
  // button in the top bar is gone.
  const hb=$('handbtn'); if(hb) hb.classList.toggle('on',handMode);
  if(typeof renderToolbar==='function') renderToolbar();
  $('canvasWrap').classList.toggle('hand',handMode);
}

/* ---- click-to-zoom tools ----
   The magnifier buttons arm a tool: the cursor becomes a glass with a plus
   or minus, and clicking the page zooms in or out anchored exactly where
   you clicked. Alt inverts, Escape or a second press puts it away. The
   plain + and − buttons zoom the whole view a step, like any viewer. */
let zoomTool=null;
function setZoomTool(t){
  zoomTool=t;
  const w=$('canvasWrap');
  w.classList.toggle('zoomin',  t==='in');
  w.classList.toggle('zoomout', t==='out');
  const bi=$('mzinBtn'), bo=$('mzoutBtn');
  if(bi) bi.classList.toggle('on', t==='in');
  if(bo) bo.classList.toggle('on', t==='out');
}
function toggleZoomTool(t){
  if(zoomTool===t){ setZoomTool(null); return; }
  disarmTools('zoom');
  setZoomTool(t);
}
function zoomAt(e, f){
  const wrap=$('canvasWrap'), img=$('img');
  const ir=img.getBoundingClientRect(), wr=wrap.getBoundingClientRect();
  const px=(e.clientX-ir.left)/Math.max(1,ir.width);
  const py=(e.clientY-ir.top)/Math.max(1,ir.height);
  const ox=e.clientX-wr.left, oy=e.clientY-wr.top;
  zoom=Math.max(0.1,Math.min(8,zoom*f));
  applyZoom();
  // where does the image now sit inside the scrollable content?
  const ir2=img.getBoundingClientRect(), wr2=wrap.getBoundingClientRect();
  const imgL=wrap.scrollLeft+(ir2.left-wr2.left);
  const imgT=wrap.scrollTop +(ir2.top -wr2.top);
  // the point you clicked stays under the cursor
  wrap.scrollLeft=imgL+px*ir2.width -ox;
  wrap.scrollTop =imgT+py*ir2.height-oy;
}

/* Photoshop-style panning: drag anywhere on the page to move it. */
(function panning(){
  const wrap=$('canvasWrap');
  let pan=null;
  wrap.addEventListener('mousedown',e=>{
    // Hand tool, or a middle-click drag, which every editor supports.
    if(handMode || e.button===1){
      pan={x:e.clientX,y:e.clientY,l:wrap.scrollLeft,t:wrap.scrollTop};
      wrap.classList.add('grabbing');
      e.preventDefault(); e.stopPropagation();
    }
  },true);
  window.addEventListener('mousemove',e=>{
    if(!pan) return;
    handPanned=true;
    wrap.scrollLeft=pan.l-(e.clientX-pan.x);
    wrap.scrollTop =pan.t-(e.clientY-pan.y);
  });
  window.addEventListener('mouseup',()=>{pan=null;wrap.classList.remove('grabbing');});
  wrap.addEventListener('dblclick',e=>{ if(handMode){fitPage();e.preventDefault();} });
  wrap.addEventListener('mousedown',e=>{
    if(!zoomTool || e.button!==0) return;
    e.preventDefault(); e.stopPropagation();
    const out = (zoomTool==='out') !== !!e.altKey;   // Alt flips it
    zoomAt(e, out ? 1/1.5 : 1.5);
  },true);
  // ctrl/cmd + wheel zooms, like every other image editor
  wrap.addEventListener('wheel',e=>{
    if(!(e.ctrlKey||e.metaKey)) return;
    e.preventDefault();
    zoomAt(e, e.deltaY<0?1.1:1/1.1);   // anchored under the cursor
  },{passive:false});
})();

function syncBoxesForView(v){
  const cb=$('hideboxes');
  if(v==='typeset'){
    // Only on the way IN. This runs again on every page change (showPage calls
    // it), and forcing the box unconditionally meant that turning the boxes
    // back on lasted exactly until the next page — lee: *"the hide boxes shoud
    // stay off wheni switch pages"*. Entering the view still hides them; after
    // that the choice is his.
    if(boxPrefBeforeText===null){ boxPrefBeforeText=cb.checked; cb.checked=true; }
  } else if(boxPrefBeforeText!==null){
    cb.checked=boxPrefBeforeText; boxPrefBeforeText=null;
  }
}

// A page is ready for the Edit view once its plate exists — that is, once it
// has been CLEANED. The Edit view is where you paint the plate and fix the
// typesetting, and the plate is the thing you paint on; holding the view shut
// until typeset kept you out of it while the only thing it needs was already
// sitting there, and made touching up a bad erase mean running a typeset pass
// you did not want yet. Typeset can be re-run from inside the view. A page
// with no text has nothing to erase and counts as ready.
/* The Edit view is always reachable. It used to wait for the page to be
   cleaned, on the grounds that it paints on the cleaned plate — but a page
   that has not been cleaned simply paints on the scan, which is a thing to
   look at rather than a thing to be stopped from doing.
   lee: *"allwo teh user to clcik teh edit tab whenever"*. */
function pageReady(p){
  return !!p;
}
function updateEditLock(){
  const b=$('vTypeset'); if(!b) return;
  b.disabled=false;
  b.classList.remove('locked');
  b.title='Edit the typesetting';
}

/* Has this page actually been typeset? A region only carries a layout once
   Typeset has laid one out, and a layout with nothing but blanks in it puts
   nothing on the page either. */
function pageTypeset(){
  return typeof regions!=='undefined' && Array.isArray(regions)
    && regions.some(r=>r.layout && r.layout.lines
                       && r.layout.lines.some(s=>(s||'').trim()));
}
/* The "Translated text" switch shows and hides typesetting, so before there IS
   any it has nothing to act on. Left live it read as broken: switched on, and
   still a bare page. It stays out of reach until Typeset has laid something
   out, and says so. */
function syncTextToggle(){
  const cb=$('showText'), wrap=$('showTextWrap');
  if(!cb || !wrap) return;
  const typeset=pageTypeset();
  cb.disabled=!typeset;
  wrap.classList.toggle('off',!typeset);
  wrap.title = typeset
    ? 'Hide the text'
    : 'Nothing is typeset yet — run Typeset to lay the text out.';
}

async function setView(v){
  // No gate. The Edit view on an uncleaned page paints on the scan, which is
  // a thing to look at rather than a thing to be stopped from doing.
  // lee: *"allwo teh user to clcik teh edit tab whenever"*.
  // Stroke changes save themselves; leaving the Cleaned view just makes
  // sure the save has happened before the other views composite them.
  if(view==='clean' && v!=='clean') await syncPaint();
  view=v;
  if(v!=='typeset') stopBrush();
  // The Edit tab draws the strokes itself on the paint canvas; everywhere
  // else (export, results) they are baked in server-side.
  const pcv=$('paint'); if(pcv) pcv.style.display = v==='typeset'?'':'none';
  syncViewChrome();
  syncTextToggle();
  syncBoxesForView(v);
  // The strip does not need redrawing here: the view change goes through
  // `stopBrush`/`paintToolUI` on the way out of the Edit view and through
  // `showPage` on the way back in, and both of those redraw it already. A
  // call here was a third one that could not be told from the other two —
  // and code no test can distinguish from its own absence is code that is
  // not really there.
  renderList();
  ['original','typeset'].forEach(k=>
    $('v'+k[0].toUpperCase()+k.slice(1)).classList.toggle('on',k===v));
  // ...and the lit pill slides to the one that is now on. The class is on the
  // GROUP, not the button: there is one pill and it belongs to neither.
  //
  // The class names a SIDE, not a view, and has to agree with the order in
  // the markup: Translation (the `original` view) is the left-hand button,
  // Image (the `typeset` view) the right-hand one.
  //
  // lee's *"no i wanted you to swithc the names not the button locations"*
  // was two things at once. The buttons were MOVING — the two switches for
  // the typeset view appeared to the right of the pill and shoved it along,
  // which is fixed in the markup — and the names were on the wrong buttons.
  const vg=document.querySelector('.views');
  if(vg) vg.classList.toggle('right', v==='typeset');
  // The bar over the canvas is a READOUT, not a lesson. It carries the live
  // position while something is being dragged and is out of the way the rest
  // of the time. lee: *"remove all the pop up explaiantion / tips — make teh
  // sorfware clean and prfesioanal"*.
  const hint=$('modehint');
  if(hint){ hint.textContent=''; hint.style.display='none'; }
  showPage(cur);
}

/* Whether anything has been exported yet — see refreshExports below. */
var hasExports = false;

/* Which of the four tabs can be pressed at all.

   Edit with no pages is a canvas with nothing on it and a sidebar about a page
   that does not exist; Results with nothing exported is a gallery of nothing.
   Neither is a place to be, so neither can be reached — by a click or by a
   call. lee: *"al the edit page shoud not be assibisble is therae are no
   pages"* and *"it hsoud not be accassel uptil the user export"*. */
function hasPages(){
  return !!(typeof proj!=='undefined' && proj && proj.pages
            && proj.pages.length);
}
/* Why a tab cannot be opened, in words, or "" if it can.

   The reason is the whole point. A greyed-out tab that does nothing when you
   press it tells you that you cannot go there and not one thing about why or
   what to do instead. lee: *"add and error pop up explaining whya p page is
   not assible when a peson try to clcik on them do taht for all of them"*.

   So these are NOT `disabled`: a disabled button swallows the click, and the
   click is the moment the person has asked the question. They take the press,
   say why, and stay where they are. */
/* Results was unlocked for exactly one round. lee: *"the result tab shoud be
   unloacked"*, then, having looked at it: *"re lock the results page after
   export is doen"*. So it is shut again until this project has written
   something out — which is what he asked for in the first place, *"it hsoud
   not be accassel uptil the user export"*. */
function tabShut(t){
  if(t==='edit' && !hasPages())
    return 'Nothing to work on yet — add pages on the File tab first.';
  if(t==='results' && !hasExports)
    return 'Nothing exported yet — finish a page and press Export on the ' +
           'Workspace tab, and the results appear here.';
  return '';
}
function syncTabs(){
  for(const [id, name] of [['tabEdit','edit'], ['tabRes','results']]){
    const b = $(id);
    if(!b) continue;
    const why = tabShut(name);
    b.disabled = false;              // it has to take the click to explain
    b.classList.toggle('off', !!why);
    b.setAttribute('aria-disabled', why ? 'true' : 'false');
    b.title = why;
  }
}

function setTab(t, byHand){
  // "manga" was a page of its own. It is a group inside Settings now, so the
  // old name still works and lands in the same place.
  if(t==='manga') t='settings';
  // A tab that cannot be opened says why — but only when a person asked. The
  // app itself calls setTab('edit') after saving settings and after closing
  // the picker, and a toast about missing pages in the middle of that is an
  // answer to a question nobody put.
  const why = tabShut(t);
  if(why){
    if(byHand && typeof toast==='function') toast(why);
    t = (t==='results' && hasPages()) ? 'edit' : 'new';
  }
  tab=t;
  $('tabEdit').classList.toggle('on',t==='edit');
  $('tabRes').classList.toggle('on',t==='results');
  const ts=$('tabSet'); if(ts) ts.classList.toggle('on',t==='settings');
  const tn=$('tabNew'); if(tn) tn.classList.toggle('on',t==='new');
  // New project is one of the four, so choosing any of the others puts it
  // away and choosing it puts the others away. `setTab` is the only thing that
  // decides which screen is up; `showPicker` calls back into it rather than
  // opening a screen behind the tab bar's back.
  if(typeof showPicker==='function' && !setTab._fromPicker)
    showPicker(t==='new');
  const full = t==='settings';
  $('stage').style.display = t==='edit'?'block':'none';
  $('results').classList.toggle('on',t==='results');
  $('side').style.display = t==='edit'?'block':'none';
  $('pages').style.display = (full || t==='new')?'none':'';
  const sp=$('settingsPage'); if(sp) sp.style.display = full?'flex':'none';
  const cw=$('canvasWrap');
  if(cw) cw.style.display = (full || t==='new')?'none':'';
  syncViewChrome();
  // Coming back to the page. While another tab was up the stage was hidden,
  // and a hidden scroll box has its scroll position reset to zero by the
  // browser — on a pane that centres the page with a wide pan border either
  // side, zero means the page is parked off in the corner, out of sight. The
  // pane also had no width to fit against while it was hidden, so the fit is
  // measured again now that it has one, and the page is put back in the
  // middle where it was left.
  if(t==='edit') showPageAgain();
  if(typeof renderToolbar==='function') renderToolbar();
  // The step bar (Find text / Read / … progress) belongs to the editing
  // workflow, so it only shows on the Edit page. So do the page tools in the
  // top bar — zoom, snap, hide boxes, Original/Edit — which on any other tab
  // are controls for a canvas that is not on screen.
  const wk=$('work'); if(wk) wk.style.display = t==='edit' ? '' : 'none';
  const pt=$('pageTools');
  if(pt) pt.style.display = t==='edit' ? '' : 'none';
  const rt=$('resultTools');
  if(rt) rt.style.display = t==='results' ? '' : 'none';
  // The page list carries the "+ Add pages" button, which is not offered on
  // Results — so the list has to be rebuilt when the tab changes, not only
  // when the pages do.
  if(typeof renderPages==='function') renderPages();
  syncTabs();
  if(t==='results') loadResults();
  if(full && typeof snapshotSettings==='function') snapshotSettings();
  if(full){
    if(typeof fillCkFont==='function') fillCkFont();
    if(typeof renderCustomKinds==='function') renderCustomKinds();
  }
  // A textarea inside a hidden page measures as zero, so the synopsis can
  // only be sized once its page is actually on screen.
  if(full && typeof growSynopsis==='function') growSynopsis();
}

/* Each full-page tab shows one section at a time; its left-hand nav picks it. */
function _pickSection(nav, body, name){
  document.querySelectorAll(nav+' .setnav-btn').forEach(b=>
    b.classList.toggle('on', b.dataset.sec===name));
  document.querySelectorAll(body+' .set-section').forEach(s=>
    s.classList.toggle('on', s.dataset.sec===name));
}
function setSettingsTab(name){
  _pickSection('#setNav','#setBody',name);
  // The synopsis lives on one of these sections and cannot be measured until
  // that section is the visible one — a textarea inside a hidden page measures
  // as zero.
  if(typeof growSynopsis==='function') growSynopsis();
}
/* The story sections used to be a page of their own. Anything that still asks
   for one by its old name lands on the same section. */
function setMangaTab(name){ setSettingsTab(name); }
/* The File screen's rail. One section on it today — New project — and the
   machinery is the settings page's, so adding the second is a button and a
   <section>. */
function setFileTab(name){ _pickSection('#fileNav','#fileBody',name); }
/* Whether anything has been exported yet. The Results tab is not a place to
   go and look at nothing — until a chapter has been exported there is nothing
   there and no reason to be able to press it.
   lee: *"the resulat page shoud be empty until the project is exported and it
   hsoud not be accassel uptil the user export"*.

   Asked of the server, not remembered: the folder is on disk and can be filled
   by a previous run of the app, or emptied by hand. */
async function refreshExports(){
  try{
    const j = await api('/api/exported');
    hasExports = !!(j.files && j.files.length);
  }catch(e){ /* leave it as it was */ }
  syncResultsTab();
  return hasExports;
}
function syncResultsTab(){ syncTabs(); }

async function loadResults(){
  const j=await api('/api/exported');
  hasExports = !!(j.files && j.files.length);
  syncResultsTab();
  $('results').innerHTML = (j.files&&j.files.length)
    // The three buttons live in the top bar now (#resultTools), so what is
    // left here is the one line saying what you are looking at.
    ? `<p class="muted" style="flex:1 0 100%;margin:0;text-align:center">
         ${j.files.length} pages in <code>${j.dir}</code></p>` +
      j.files.map(f=>`<div class="rcard" onclick="openResult(${f.index},'${f.name}')">
         <img src="/exported/${encodeURIComponent(f.name)}?t=${Date.now()}" loading="lazy">
         <div class="muted" style="margin-top:5px">${f.name}</div></div>`).join('')
    // `grid-column:1/-1` on the empty line too, or it lands in the first
    // column of a centred grid and reads as a caption for a page that is not
    // there.
    : `<p class="muted" style="flex:1 0 100%;text-align:center;margin:40px 0">
       Nothing exported yet. Press <b>Export folder</b> — pages
       will appear here and in <code>${j.dir||'out/pages'}</code>.</p>`;
}
function openResult(i,name){
  if(i>=0){setTab('edit');setView('typeset');showPage(i);}
  else window.open(apiUrl('/exported/'+encodeURIComponent(name)),'_blank');
}

function installFonts(){
  const st=document.createElement('style');
  st.textContent=['bubble','freefloat','sfx','narration'].map(k=>
    `@font-face{font-family:'ml-${k}';src:url('/font/${k}?v=${Date.now()}');}`
  ).join('\n');
  document.head.appendChild(st);
}
