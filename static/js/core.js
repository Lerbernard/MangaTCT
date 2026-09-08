/* Next frame, in any host.

   jsdom has no `requestAnimationFrame` and the UI tests run there, so a bare
   call throws - and inside a MutationObserver callback nothing catches it, so
   the console fills and whatever came after the call never happens. Browsers
   both have it; this is the one line that keeps the tests honest and the app
   the same in Chrome, in Firefox and under test.
   lee: *"the website need to fully work the same on chrome and on firefox"*. */
const soon = (typeof requestAnimationFrame === 'function')
  ? (f)=>requestAnimationFrame(f) : (f)=>setTimeout(f, 16);

/* At most one of each kind of redraw per frame.

   A mouse can report a hundred moves a second; a screen shows sixty. Every
   one of those moves was repainting the whole page - clearing a canvas the
   size of the scan, replaying every paint layer onto it, compositing it - so
   on a 3000-pixel page dragging a shape did several times more work than the
   screen could ever show, and the drag fell behind the pointer. lee: *"there
   is a lot of lag with the shapes"*.

   Keyed, so a stroke redraw and an ants redraw both happen, but ten stroke
   redraws in one frame happen once. The LAST one wins, which is the one that
   matches where the pointer is now. */
let _frameJobs=null;
function onFrame(key, fn){
  if(!_frameJobs){
    _frameJobs=new Map();
    soon(flushFrame);
  }
  _frameJobs.set(key, fn);
}
/* Do the pending redraws now. Anything that ENDS an interaction - letting go
   of a stroke, applying a transform - calls this, so what is on screen when
   the mouse comes up is the finished thing and not a frame from mid-drag. */
function flushFrame(){
  const jobs=_frameJobs;
  _frameJobs=null;
  if(!jobs) return;
  jobs.forEach(f=>{ try{ f(); }catch(e){ console.error(e); } });
}

/* core.js - App state shared by every module, the api() fetch helper, toast, top-bar resize.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */
let proj=null, cur=0, regions=[], sel=null, scale=1, pageW=1;
/* The proofreader's remark about the page as a whole - what it could not fix
   on its own. Per page, refreshed by showPage. */
let pageNote='';
/* Which boxes the proofreader's remark is about, as region ids. Rendered
   as clickable chips beside the note: a remark with no way to tell WHERE
   means reading the whole page to find it. */
let pageNoteIds=[];
/* ONE WAY IN for a new set of regions.
   The page draws the boxes and their reading-order numbers; the sidebar draws
   the same numbers in its own list; the overlay draws the typesetting. All three
   read `(r.order??0)+1` off the same array, so they cannot disagree - unless
   one of them is simply not redrawn, and then the screen shows two different
   answers until something else happens to refresh it.

   That is exactly what lee caught: box 5 and box 7 swapped between the list and
   the page. Every region POST runs `reorder()` on the server, so any reply can
   carry renumbered boxes, and three call sites (both typesetting saves and
   auto-fit) refreshed the list and the typesetting but never the boxes. The
   badges kept the old numbers.

   So there is one function now, every site that replaces `regions` goes through
   it, and a test fails if a new assignment appears anywhere else. `opts.list`
   is false for a quiet background save, which must not rebuild the sidebar
   under an open colour dialog - the boxes are still redrawn. */
/* ---- typing in the side panel is never thrown away ----
   The two text boxes in the inspector saved on `change`, which the browser
   fires on blur - and blur never happens if the element is REMOVED while it
   still has focus. Clicking the page, another box, or anything that redraws the
   list did exactly that, so a line typed and then clicked away from was gone.
   lee: *"whne i add text to the side panel in the original tab it hsoud stay
   and not clear when i clcik off"*.

   So the keystrokes are remembered as they are typed, and anything that is
   about to rebuild the list writes them out first. `flushEdit` is safe to call
   at any time: with nothing pending, or nothing changed, it does nothing. */
let pendingEdit = null;
function noteEdit(id, field, value){ pendingEdit = {id, field, value}; }
function flushEdit(){
  const e = pendingEdit;
  pendingEdit = null;
  if(!e || flushEdit._busy) return;
  const r = regions.find(x=>x.id===e.id);
  if(!r || (r[e.field]||'') === (e.value||'')) return;
  r[e.field] = e.value;                    // on screen now, saved in a moment
  flushEdit._busy = true;
  markInFlight(e.id, {[e.field]: e.value});
  try{
    const done = upd(e.id, {[e.field]: e.value});
    if(done && done.catch) done.catch(()=>dropInFlight(e.id));
  }
  finally { flushEdit._busy = false; }
}

/* Edits whose save has not come back yet.

   Saving is a round trip, and the page is refreshed from the server by all
   sorts of things that have nothing to do with the edit - clicking another
   box, a poll landing, the picture being rebuilt. If one of those answers
   arrives while a save is still in the air it carries the value from BEFORE
   the edit, and laying it over the region puts the old number back on screen.
   The change is not lost - it reaches disk - but it looks exactly as though it
   were, and the next edit then starts from the stale number.

   lee: *"sometime some edits just revert when i lcik on a ballon"*. Measured:
   4 times in 6 with a poll landing mid-edit.

   So anything in the air is remembered and laid back over whatever the server
   sends, until its own reply comes home. */
const inFlight = new Map();          // region id -> the fields still in the air

/* How a block is drawn, from every source with an opinion, in order: what
   somebody SET beats what the original was MEASURED to be, and both beat the
   automatic choice the server worked out and sent in `layout`.

   `render.style_of` is the same three lines on the server, and they have to
   stay the same three - this is what the preview draws with and that is what
   the exported page is drawn with, so any difference between them is a page
   that does not look like what you were shown. */
/* ...and HOW MUCH of the measurement a block may use depends on what it is -
   `render.measured_for` is the same rule, with the reasoning on it.
   A big drawn sound takes all of it; any other drawn sound takes the LINE
   only (the rim width and whether the letterform is hollow, which is "a pen
   has a width" and not a palette); everything else takes none and is typeset
   in the pair that can be read. A hand override is unaffected either way. */
const BIG_SOUND = 'sfx_big';
const SHAPE_KEYS = ['stroke', 'rim', 'hollow'];

function measuredFor(r){
  const got = (r && r.layout_measured) || {};
  const kind = (r && r.kind) || '';
  if(kind === BIG_SOUND) return Object.assign({}, got);
  // The family, the way the server asks it: the sub-type list the page was
  // sent knows which family each key belongs to. `familyOf` lives in
  // frames.js, which loads after this file - fine at draw time, and guarded
  // anyway. The fallback is the safe direction: take nothing, and let the
  // block be typeset in the pair that can be read.
  const fam = (typeof familyOf === 'function') ? familyOf(kind) : '';
  if(fam === 'sfx'){
    const out = {};
    for(const k of SHAPE_KEYS){ if(k in got) out[k] = got[k]; }
    return out;
  }
  return {};
}

function styleOf(r){
  const out = measuredFor(r);
  const ov = (r && r.layout_override) || {};
  for(const k in ov){ if(ov[k] !== null && ov[k] !== '') out[k] = ov[k]; }
  return out;
}

/* Bumped every time an edit is made. A page fetch that was already on its way
   when that happened is answering a question about the page as it WAS, so it
   is not allowed to redraw the regions - it is stale by definition, however
   quickly it comes back. */
let editStamp = 0;

let markSeq = 0;

function markInFlight(id, patch){
  const at = inFlight.get(id) || {fields: {}};
  for(const k in patch){
    at.fields[k] = (k === 'layout_override' || k === 'layout')
      ? Object.assign({}, at.fields[k], patch[k])
      : patch[k];
  }
  at.seq = ++markSeq;                 // which edit this is, so a stale save
  inFlight.set(id, at);               // cannot let go of a newer one's mark
  editStamp += 1;
  return at;
}

/* A save that never came back - the request failed, the page went away. The
   mark would otherwise sit over every future answer for ever. */
function dropInFlight(id){ inFlight.delete(id); }

/* The save's own answer is home. That is proof the value is on disk, so every
   request made from here on carries it and the mark has done its job.

   It cannot be held any longer than this. Agreement alone is not enough to let
   go: not every save is answered with the regions, so a mark can be left with
   nothing to agree with, and then the next answer that says something DIFFERENT
   - a change made elsewhere, a re-fit the server did - is pinned under the old
   number for ever, because "the server agrees" never comes true.

   `seq` is the edit this reply belongs to: a slow first save must not release
   the mark a second, later edit put there. */
function settleInFlight(id, seq){
  const at = inFlight.get(id);
  if(at && (seq == null || at.seq === seq)) inFlight.delete(id);
}

function _matches(have, want){
  // Arrays FIRST. `typeof [] === 'object'`, so an array fell into the branch
  // below and was walked key by key - over the indices present in `want`
  // only. `_matches(["A","B"], ["A"])` therefore came back true: the server
  // still holding two lines "agreed" with the one line just typed, the mark
  // was dropped, and the deleted line came straight back.
  // lee: *"sometime the text just revert back why im eddit it"*. Deleting a
  // line, or a line break, is exactly the shape of edit that did it.
  if(Array.isArray(want)){
    if(!Array.isArray(have) || have.length !== want.length) return false;
    return want.every((w, i) => _matches(have[i], w));
  }
  if(want && typeof want === 'object'){
    if(!have) return false;
    for(const k in want){ if(!_matches(have[k], want[k])) return false; }
    return true;
  }
  return (have ?? null) === (want ?? null) || String(have) === String(want);
}

/* Lay anything still in the air back over whatever the server just sent, and
   let go of it the moment the server's own answer agrees.
   
   Agreement is the right condition and a timer is not: the mark has to
   outlive not just the save but every reply that was already on its way when
   the save was made, and there is no length of time that is reliably longer
   than "every request in flight". "Until the server says the same thing"
   needs no guess. */
function applyInFlight(list){
  if(!inFlight.size) return list;
  for(const r of (list || [])){
    const at = inFlight.get(r.id);
    if(!at) continue;
    let caughtUp = true;
    for(const k in at.fields){
      if(_matches(r[k], at.fields[k])) continue;
      caughtUp = false;
      r[k] = (k === 'layout_override' || k === 'layout')
        ? Object.assign({}, r[k], at.fields[k])
        : at.fields[k];
    }
    if(caughtUp) inFlight.delete(r.id);
  }
  return list;
}

function setRegions(list, opts){
  // Never redraw over an unsaved edit - from EITHER panel. This used to flush
  // only the region list, and the typesetting panel was flushed by
  // `renderInspector` - which a refresh with `{list:false}` never calls. So a
  // page reload landing while a size or a line was half-typed dropped it, and
  // the panel came back showing the value from before.
  flushEdit();
  if(typeof flushTypesetEdit === 'function') flushTypesetEdit();
  const o = opts || {};
  regions = applyInFlight(list || []);
  // a box that is gone cannot stay selected
  if(sel!=null && !regions.some(r=>r.id===sel)) sel=null;
  if(typeof syncMulti==='function') syncMulti();
  if(o.boxes!==false && typeof drawBoxes==='function') drawBoxes();
  if(o.overlay!==false && typeof drawOverlay==='function') drawOverlay();
  if(o.list!==false && typeof renderList==='function') renderList();
}

/* Which of the three groups of boxes this page has, and which are put away.
   A hidden group is not drawn and takes no part in any stage; the server
   already leaves it out of `regions`, so these two lists exist only to build
   the switches in the Current page card. Refreshed by showPage. */
let kindsHere=[], hiddenKinds=[];
/* Boxes put away ONE AT A TIME, by id, and the little the list needs to draw a
   row for each with a closed eye on it. They are deliberately not in
   `regions` - a hidden box takes no part in the page's work, and anything that
   walks `regions` would start treating it as work again - so this is the only
   way back to one. lee: *"i shud be able to hide individual boxes"*. */
let hiddenIds=[], hiddenRows=[];
/* Extra boxes picked with c+click. Empty means "just `sel`"; when it has
   members `sel` is the last one clicked and is always inside it. Kept in sync
   by syncMulti() (region-ops.js), which every redraw calls. */
let selMulti=new Set();
let view='original';                 // original | clean | typeset
let zoom=1, fitZoom=1, handMode=false, pageH=1;
const inText = ()=> view==='typeset'
  && (!$('showText') || $('showText').checked);
function onShowText(){
  if(!inText()){
    closeCanvasEdit(true);
    sel=null;                      // no text on screen, nothing selected
    renderList();
    drawBoxes();
  }
  drawOverlay();
}
window.addEventListener('resize',()=>{
  // Recompute the fit through the zoom code; setting scale directly here left
  // the overlay and the image disagreeing about how big the page was.
  if($('img').naturalWidth){ fitZoom=fitScale(); applyZoom(); drawOverlay(); }
});
const $=id=>document.getElementById(id);
/* Every server URL - api calls, page images, exports - goes through apiUrl().
   Today API_BASE is '' and this is a no-op. When the editor is hosted with
   several projects open at once, set API_BASE to the project scope (for
   example '/p/<project-id>') and the whole client follows; nothing else in
   the modules builds a server URL on its own. */
const API_BASE='';
const apiUrl=u=>API_BASE+u;
/* Which page a URL is about, or null for anything that is not about one. */
function pageOfUrl(u){
  const m=/^\/api\/page\/(\d+)(?:[/?#]|$)/.exec(String(u||''));
  return m ? +m[1] : null;
}
const api=async(u,m,b)=>{
  // Which page this question was asked ABOUT, taken from the URL and not from
  // `cur`, so the answer is checked against the page it actually describes.
  const asked=pageOfUrl(u);
  const r=await fetch(apiUrl(u),{method:m||'GET',headers:{'Content-Type':'application/json'},
    body:b?JSON.stringify(b):null});
  const j=await r.json().catch(()=>(
    {error:`The server answered ${r.status} without data - if it was just `+
           `updated, restart it and reload this page.`}));
  if(j.error) toast(j.error);
  // An answer about a page you have already left is not about what is on
  // screen, and its boxes are another page's boxes.
  //
  // lee, switching pages quickly on a slow one: *"the page lagged and merge 2
  // section from one page with another when i switch pages too fast"*. Two
  // dozen places apply `j.regions` the moment it arrives, and each of them is
  // somewhere the check can be forgotten - one of them already had it and the
  // rest did not. Worse than a wrong picture: with another page's boxes in
  // `regions`, the next drag or type posts THAT id to the page you are now on,
  // so the mix-up gets written to disk.
  //
  // So it is refused here, in the one place every one of them passes through,
  // and by the SAME rule for all of them. What is dropped is only the part
  // that belongs to a page - an answer also carrying a job id or a setting
  // keeps it.
  if(asked!=null && typeof cur!=='undefined' && cur!==asked
     && j && typeof j==='object' && !Array.isArray(j)){
    // The BOXES and nothing else. They are what carries ids, and an id is
    // what turns a wrong picture into a wrong write. Everything else an answer
    // holds - the page's size, its cache key, which groups it has - is applied
    // by `showPage` behind its own ticket check and is only ever cosmetic if
    // it slips; stripping those as well broke a panel that reads them.
    // A COPY. Deleting from the answer itself edits an object the caller may
    // still be holding, which is a second way to make one page's data turn up
    // somewhere it should not be.
    const {regions, region, ...rest}=j;
    return Object.assign(rest, {stale:true});
  }
  // A WRITE THAT LANDED IS A REASON TO SETTLE AGAIN. The export preview
  // re-settles when something is DRAWN, which covers typing and dragging -
  // but a layer's eye, a restack, a delete change the page without drawing
  // anything, so the preview sat on the old picture until the next page
  // turn. lee: *"when i turn off tehhela layer or anythy other layer it
  // dont update teh exported page"*. Every state-changing call passes
  // through here; asking for a settle AFTER the server has the new state
  // also closes the race where a settle fired before its save arrived.
  // `exactSoon` is a no-op outside the Image view and while editing, and a
  // settled page answers from the server's cache in milliseconds - so the
  // spare settles this adds cost nothing worth counting.
  if((m||'GET')!=='GET' && !(j&&j.error) && typeof exactSoon==='function'){
    try{ exactSoon(); }catch(e){}
  }
  return j;
};
function toast(m,ms){const t=$('toast');t.textContent=m;t.style.display='block';
  clearTimeout(t._t);t._t=setTimeout(()=>t.style.display='none',ms||4200);}

/* ---- one tool at a time ----
   Every tool arms itself through this: picking any tool puts every OTHER
   tool away - hand, magnifiers, brush, clone, heal, eraser, selections,
   free transform. Each toggle stays responsible for its own UI; this only
   guarantees the exclusivity. (Defined here in core.js, called at runtime
   when every module is loaded - the typeof guards cover boot order.) */
function disarmTools(keep){
  if(keep!=='hand'   && typeof handMode!=='undefined' && handMode) toggleHand(false,true);
  if(keep!=='zoom'   && typeof zoomTool!=='undefined' && zoomTool) setZoomTool(null);
  if(keep!=='brush'  && typeof brush!=='undefined'  && brush)  toggleBrush(false);
  if(keep!=='stamp'  && typeof stamp!=='undefined'  && stamp)  toggleStamp(false);
  if(keep!=='heal'   && typeof heal!=='undefined'   && heal)   toggleHeal(false);
  if(keep!=='eraser' && typeof eraser!=='undefined' && eraser) toggleEraser(false);
  if(keep!=='unclean' && typeof unclean!=='undefined' && unclean)
    toggleUnclean(false);
  // The clone stamp's source mark and ring are page furniture, not cursor:
  // they were only ever cleared when the stamp itself was put away, so arming
  // any other tool while one was up left a dashed green circle sitting on the
  // artwork. Whatever is being armed, if it is not the stamp, they go.
  if(keep!=='stamp'){
    if(typeof hideCloneMark==='function') hideCloneMark();
    if(typeof hideClonePrev==='function') hideClonePrev();
  }
  if(keep!=='shape'  && typeof shapeKind!=='undefined' && shapeKind)
    toggleShape(shapeKind);
  // The shape arrow survives 'xf' on purpose: the free transform is the thing
  // the arrow STARTS, and putting the arrow away as it opened would drop the
  // shape the moment it was picked up.
  if(keep!=='shapeEdit' && keep!=='xf'
     && typeof shapeEdit!=='undefined' && shapeEdit) toggleShapeEdit(false);
  if(keep!=='sel'    && typeof selTool!=='undefined'&& selTool) selToolOff();
  if(keep!=='xf'     && typeof xf!=='undefined'     && xf)     xfCancel();
}
