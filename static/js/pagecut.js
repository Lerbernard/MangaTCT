/* Cutting a page in two by hand, and joining two back into one.
 *
 * lee: *"add page splitter that allow the user to splite the pages manualy to
 * the translation tab"*, then *"also add a page mergin feature"*.
 *
 * The automatic re-cut in `strip.py` is deliberately narrow. It runs only on a
 * chapter that ARRIVED as a sliced strip, only before any work has been done
 * on it, and only when four separate tests agree - because being wrong there
 * rearranges somebody's chapter behind their back. Every one of those rules is
 * worth keeping, and between them they leave every other too-long page exactly
 * as it is. This is the knife for those: one page, one row, chosen by the
 * person looking at it.
 *
 * It lives in the Translation view - the artwork as it came - because that is
 * the view you are in when you notice the page is wrong, and it is not offered
 * in the Image view at all, where the boxes are placed against the page and
 * the server refuses to cut anyway.
 *
 * Reads `cur`, `proj`, `api`, `toast`, `loadProject`, `renderPages`,
 * `showPage` from the other files. Classic script, one global scope. */

let _cutGaps = [], _cutH = 0;

/* Nothing here moves the line. It jumped to the nearest gap within sixty rows
   on every click; that became a `Snap to the nearest gap` button; and lee took
   the button off too - *"and removethe cut a the nearst gap button"*.

   What is left of it is the readout: the line goes green when the row it is
   on happens to BE a gap between panels. Which is the useful half. It tells
   you the cut is clean without ever taking the decision off you. */

async function openCut(){
  if(!proj || !proj.pages || !proj.pages.length) return;
  const i = cur;
  const dlg = $('cutdlg');
  _cutGaps = []; _cutH = 0;
  // The picture is asked for AFTER the answer comes back, because the answer
  // carries the key it has to be asked for BY. See below.
  $('cutImg').removeAttribute('src');
  $('cutRow').textContent = '';
  $('cutLine').style.display = 'none';
  $('cutWhy').textContent = 'Loading…';
  $('cutGo').disabled = true;
  // Joining needs somewhere to join TO.
  // "Join with page 1" told you the FILENAME, which is not what you are
  // picking: you are picking a direction. lee: *"instad of saying join with
  // pagess 1 its hsou be join with preiouis and join with next page"*.
  $('cutPrev').disabled = i < 1;
  $('cutNext').disabled = i + 1 >= proj.pages.length;
  dlg.classList.add('on');

  const g = await api('/api/page/' + i + '/gaps') || {};
  _cutGaps = g.gaps || [];
  _cutH = g.height || 0;
  // Keyed on the file's CONTENTS. It was a bare `/img/3`, which is the same
  // string every time, and an <img> already holding that src does not
  // re-request when it is set to what it already says - so after cutting page
  // 3 in two, opening the dialog on the top half showed the whole uncut page
  // again. lee: *"its still showing the previous uncut picure after i cut it,
  // the the originalpage dosnt work the other haft works fine"* - the other
  // half worked because its index had not been looked at before.
  //
  // A fingerprint of the bytes cannot collide with the picture it replaced,
  // and it lets the browser keep the one it has when nothing changed.
  $('cutImg').src = '/img/' + i + '?v=' + encodeURIComponent(g.key || 'x');
  if(g.busy){
    // The server will refuse, and saying so now beats saying it after the
    // person has chosen a row.
    $('cutWhy').textContent = 'This page has touch-up strokes or a clean '
      + 'plate of your own on it. Those are pictures the size of the page and '
      + 'cutting them is a different job - boxes come through a cut, painting '
      + 'does not. Undo the painting, or cut before you paint.';
    $('cutStage').style.display = 'none';
    $('cutPrev').disabled = $('cutNext').disabled = true;
    return;
  }
  $('cutStage').style.display = '';
  // Boxes come through the cut, so say so before the person decides: it
  // used to refuse outright and this is the sentence that tells them it no
  // longer does.
  const boxes = (proj.pages[i].regions || 0);
  const carried = boxes
    ? ` The ${boxes} box${boxes === 1 ? '' : 'es'} on it come with it, each to `
      + `the half it is on. Cleaning and typesetting are rebuilt.`
    : '';
  $('cutWhy').textContent = (_cutGaps.length
    ? `${proj.pages[i].name} - ${_cutH.toLocaleString()} rows tall, with `
      + `${_cutGaps.length} gap${_cutGaps.length === 1 ? '' : 's'} between `
      + `panels to cut at.`
    : `${proj.pages[i].name} - ${_cutH.toLocaleString()} rows tall. There is `
      + `no gap between panels on it, so wherever you cut goes through the `
      + `artwork.`) + carried;
  putLine(Math.round(_cutH / 2));
}

/* The row the line is on, in the page's own pixels. Kept on the element so
   there is one copy of it and it is the one being drawn. */
function cutAt(){ return +($('cutLine').dataset.row || 0); }

/* The line goes on the row it was given. Nothing rounds it to a gap, nothing
   pulls it back from an edge, nothing waits for a drag to finish.
   lee: *"the cut line shoud apar where i click no matter hwat remove nything
   that is precenting that"*.

   The ONE thing that is still refused is a cut in the top or bottom sixteen
   rows, and it is refused by the Cut button going off with the reason beside
   it - not by moving the line. A sliver is not a page and the server says so
   anyway; being told why is different from being overruled. */
const EDGE = 16;

function putLine(row){
  if(!_cutH) return;
  const img = $('cutImg');
  row = Math.round(row);
  const line = $('cutLine');
  line.dataset.row = row;
  line.style.display = 'block';
  // IN PIXELS, measured off the picture. lee: *"th e line is still not where i
  // clicked, use the mouse cordinate to draw the line"*.
  //
  // It was `top: <percent>`, and a percentage `top` on an absolutely
  // positioned box resolves against the HEIGHT OF ITS CONTAINING BLOCK - which
  // is `#cutWrap`, capped at 52vh with the picture scrolling inside it. So on
  // every page tall enough to scroll, "40% of the way down the page" was drawn
  // 40% of the way down the WINDOW ONTO the page. The taller the page, the
  // further out it was, and on a short one it looked perfect.
  //
  // `offsetTop` is measured from the same origin an absolutely positioned
  // child is placed from, so this is the picture's own top plus however far
  // down the picture the row is. No percentages, no assumptions about the
  // scroll.
  const at = Math.max(0, Math.min(_cutH, row)) / _cutH;
  line.style.top = (img.offsetTop + at * img.offsetHeight) + 'px';
  // Green means this row IS a gap between panels. It is a readout, not a
  // promise that anything moved.
  const on = _cutGaps.some(g => Math.abs(g - row) <= 2);
  line.classList.toggle('snap', on);
  const tight = (row < EDGE || row > _cutH - EDGE);
  $('cutRow').textContent = row.toLocaleString()
    + (tight ? '  ·  too close to the edge' : on ? '  ·  on a gap' : '');
  $('cutGo').disabled = tight;
}

/* The row under the pointer, straight off the mouse coordinate: how far down
   the PICTURE the click was, as a fraction, times the page's real height. */
function cutFromEvent(e){
  const r = $('cutImg').getBoundingClientRect();
  if(!r.height) return;
  putLine((e.clientY - r.top) / r.height * _cutH);
}

function cutHere(){
  const at = cutAt();
  if(!at) return;
  doCut('/api/page/' + cur + '/split', {at: at},
        'Cut into two pages.');
}

function joinNext(){
  doCut('/api/page/' + cur + '/merge', {count: 2}, 'Joined into one page.');
}

/* Joining with the one BEFORE is the same call one page up: `merge` always
   takes a run starting at the page it is given. */
function joinPrev(){
  if(cur < 1) return;
  doCut('/api/page/' + (cur - 1) + '/merge', {count: 2},
        'Joined into one page.');
}

async function doCut(route, body, said){
  $('cutGo').disabled = true;
  $('cutPrev').disabled = $('cutNext').disabled = true;
  // Joining with the page before leaves the joined page where THAT one was.
  const at = /\/(\d+)\/merge$/.test(route)
    ? Number(route.match(/\/(\d+)\/merge$/)[1]) : cur;
  let r;
  try{
    r = await api(route, 'POST', body);
  }catch(e){
    // `api` toasts the reason itself; the dialog stays open so the row that
    // was chosen is still there to try again with.
    $('cutGo').disabled = false;
    $('cutPrev').disabled = cur < 1;
    $('cutNext').disabled = cur + 1 >= proj.pages.length;
    return;
  }
  $('cutdlg').classList.remove('on');
  await loadProject();
  renderPages();
  showPage(Math.min(at, proj.pages.length - 1));
  toast(said + ' The pages you had are kept beside the chapter.');
}

/* One click, one line, on the row under the pointer.

   It was a drag: pointer down, capture, follow, release. Dragging is what you
   want for something you are ADJUSTING, and this is not that - you look at the
   page, you see where the cut goes, you click. The capture also meant a click
   inside the preview was swallowed while the pointer was down, so a quick
   click on a slow frame sometimes did nothing at all.
   lee: *"remoeve teh click and drag and allow me to clci where i want it to
   cut"*.

   `click` and not `pointerdown`, so scrolling the preview with a touch or a
   flicked pointer does not drop a line where the finger happened to land. */
function cutBind(){
  const wrap = $('cutWrap');
  if(!wrap || wrap.dataset.bound) return;
  wrap.dataset.bound = '1';
  wrap.addEventListener('click', cutFromEvent);
}

if(document.readyState === 'loading')
  document.addEventListener('DOMContentLoaded', cutBind);
else cutBind();
