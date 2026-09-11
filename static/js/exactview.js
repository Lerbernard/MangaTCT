/* THE PAGE, AS IT WILL BE EXPORTED, WHENEVER YOU ARE NOT TOUCHING IT.

   lee: *"i want you to make it so that what is in the editor and what is
   exported are 100% the exact same"*.

   The two pictures are drawn by two different programs. The editor lays the
   typesetting out in the browser - CSS text, SVG masks, `text-shadow` - over
   the cleaned plate, because that is the only way a change can appear as fast
   as it is typed. The export draws it with PIL on the server. They have been
   calibrated against each other until they agree to between 0.68 and 0.93 of
   each other's ink (`test_the_editor_looks_like_the_page`), and that is about
   as far as calibration goes: two rasterisers do not round a blur the same
   way, and never will.

   So this does not try to make the copy better. It shows the ORIGINAL.

   `/render/<i>?mode=typeset` is the exported page - the same `typeset_page`,
   the same `render_page`, the same compositing that `do_export` runs, one
   function away from the file that gets written. When nothing has changed for
   a moment, that picture is fetched and laid over the top, and the browser's
   own typesetting is hidden underneath it. Touch anything and it goes again
   instantly, so editing is exactly as quick as it was.

   What you get is: while you are moving something, a fast copy; a second
   after you stop, the real thing. Never both, and never in doubt about which
   - the badge in the corner says.

   THE OVERLAY IS NOT ALL HIDDEN. The boxes, the handles and the selection are
   the editor's own furniture and stay on screen; only the drawn text goes,
   because that is the part the render draws for us. */

let exactOn = false;                // off unless switched on; remembered below (lee: *"export preview should be off by default"*)
let exactShown = false;             // is the render on screen right now
let exactTimer = null;
let exactWant = 0;                  // bumped by every hide, so a late load can
                                    // tell it is answering an old question

/* How long "not touching it" has to last. 700ms when this was written,
   because settling cost a three-second layout on the server and asking too
   eagerly meant stale renders queueing behind each other. The fitting is
   remembered now (`typeset.page_fit_key`) and a settled page answers in
   ~100ms, so the wait only has to outlast the pause between two keystrokes,
   not protect the server. */
const EXACT_WAIT = 350;

try {
  const saved = localStorage.getItem('mangatl.exact');
  if (saved !== null) exactOn = saved === '1';
} catch (e) { /* a browser with storage off is not a reason to break */ }


/* Is the exact view even a question here? Only in the Image view, only on a
   page that has typesetting to show, and only when nothing is in flight. */
function exactPossible(){
  if(!exactOn) return false;
  if(typeof view === 'undefined' || view !== 'typeset') return false;
  if(typeof tab !== 'undefined' && tab !== 'edit') return false;
  if(typeof typesetDirty !== 'undefined' && typesetDirty !== null) return false;
  if(typeof editing !== 'undefined' && editing !== null) return false;
  // ...and not while ANY tool is in hand. The preview hides the paint canvas
  // (`#stage.exact #paint`) and swaps the picture under the marching ants, so
  // letting it appear over an armed tool leaves one that is lit and dead.
  // See `toolInHand`.
  if(typeof toolInHand === 'function' && toolInHand()) return false;
  const el = $('exact');
  return !!(el && typeof cur !== 'undefined' && cur !== null
            && tKey && tKey[cur]);
}


function exactUrl(i){
  // `ro=1` - READ ONLY, and it is not a nicety. Building this view lays the
  // page out again and commits the result, which is right when somebody asked
  // for it and wrong when it appears by itself: it would quietly re-typeset
  // the block being edited. An emptied box came back full. See
  // `editor.render_index`.
  //
  // NO CACHE KEY - deliberately, and this replaced a keyed design that
  // fought lee for a whole day. The key meant the image was served
  // "immutable, max-age one year", so any slip anywhere on this side - a
  // stale key, a race, an old tab - made the browser re-show year-old bytes
  // with no recourse, and every fix to the key plumbing had to be perfect
  // for ever. Without a key the server answers no-store: the browser keeps
  // NOTHING, every settle asks the server, and the server's own caches make
  // that a few milliseconds for a page already built. There is no client
  // state left that CAN go stale. lee: *"i wan t you to look at how teh
  // expoted preivew is made and fix it or replace ith with a better
  // system"*.
  return apiUrl(`/render/${i}?mode=typeset&ro=1`);
}


/* Put the browser's own typesetting back and take the render off. Called by
   everything that changes the page, and it must be cheap enough to call on
   every mouse move - so it does nothing at all when it is already off. */
function exactOff(){
  exactWant++;
  clearTimeout(exactTimer);
  if(!exactShown) return;
  exactShown = false;
  const el = $('exact');
  if(el){ el.classList.remove('on'); }
  const st = $('stage');
  if(st) st.classList.remove('exact');
  exactBadge();
}


/* ...and ask for it again in a moment, if nothing else happens first. */
function exactSoon(){
  clearTimeout(exactTimer);
  if(!exactPossible()) return;
  const mine = ++exactWant;
  exactTimer = setTimeout(()=>exactLoad(mine), EXACT_WAIT);
}


async function exactLoad(mine){
  if(mine !== exactWant || !exactPossible()) return;
  const i = cur;
  const el = $('exact');
  const url = exactUrl(i);
  // Building a changed page takes honest seconds - say so in the badge
  // instead of leaving the corner silent while it happens. After a grace,
  // so a page the server already holds never flashes it.
  const saying = setTimeout(()=>{
    if(mine !== exactWant) return;
    const b = $('exactBadge');
    if(b){ b.textContent = 'building the exported page…';
           b.classList.add('on'); }
  }, 150);
  // FETCHED AS BYTES, not assigned as a URL. `fetch(..., cache:'no-store')`
  // is required by spec to bypass the browser's HTTP cache entirely - not
  // consult it, not revalidate it, BYPASS it - and the blob it returns is
  // this response and nothing else. An <img src> assignment, by contrast,
  // negotiates with every cache layer the browser has, and one of lee's
  // survived both a server restart and an F5: his screen showed a picture
  // that six server builds spanning the afternoon never produced and his
  // render_cache does not contain. Whatever holds that copy, it cannot
  // answer a no-store fetch. lee: *"i think it might be saved in teh cache
  // or soemthing thats why the new one is not showing up"* - he was right,
  // and this makes the question unaskable.
  let bytes = null;
  try{
    const r = await fetch(url, {cache: 'no-store'});
    if(r.ok) bytes = await r.blob();
  }catch(e){ /* server briefly away; the settle will come round again */ }
  clearTimeout(saying);
  if(!bytes || mine !== exactWant || i !== cur || !exactPossible()){
    exactBadge(); return;
  }
  const ob = URL.createObjectURL(bytes);
  if(typeof readyImage === 'function') await readyImage(ob, 8000);
  if(mine !== exactWant || i !== cur || !exactPossible()){
    URL.revokeObjectURL(ob); exactBadge(); return;
  }
  const prev = exactLoad._ob;
  el.src = ob;
  exactLoad._ob = ob;
  if(prev){ try{ URL.revokeObjectURL(prev); }catch(e){} }
  if(typeof exactSize === 'function') exactSize();
  exactShown = true;
  el.classList.add('on');
  const st = $('stage');
  if(st) st.classList.add('exact');
  exactBadge();
}


/* The same width the page image is wearing. Set from `applyZoom`, which is
   the one place that decides how big a page is on screen. */
function exactSize(){
  const im = $('img'), el = $('exact');
  if(im && el) el.style.width = im.style.width || '';
}


function exactBadge(){
  const b = $('exactBadge');
  if(!b) return;
  b.textContent = exactShown ? 'exported page' : '';
  b.classList.toggle('on', !!exactShown);
}


/* The switch. Off means the editor behaves exactly as it did before this
   existed - which is the honest default for anyone who finds the swap
   distracting rather than reassuring. */
function toggleExact(on){
  exactOn = (on === undefined) ? !exactOn : !!on;
  try { localStorage.setItem('mangatl.exact', exactOn ? '1' : '0'); }
  catch (e) { /* nothing to remember it with, and that is fine */ }
  const ck = $('exactCk');
  if(ck) ck.checked = exactOn;
  if(exactOn) exactSoon(); else exactOff();
}


/* The switch belongs to the Image view, because that is the only view with
   typesetting in it to be exact about. Called by `setView` and at boot. */
function exactChrome(){
  const w = $('exactWrap');
  // Shown only in the Image view, the same way `sbsWrap` is shown only where
  // it means something - and by display, like its neighbours, not by a class
  // of its own.
  if(w) w.style.display =
    (typeof view !== 'undefined' && view === 'typeset') ? '' : 'none';
  const ck = $('exactCk');
  if(ck) ck.checked = exactOn;
}

if(document.readyState === 'loading')
  document.addEventListener('DOMContentLoaded', exactChrome);
else exactChrome();
