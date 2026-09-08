/* Cutting a page up by hand, and joining two back into one.
 *
 * lee: *"add page splitter that allow the user to splite the pages manualy to
 * the translation tab"*, then *"also add a page mergin feature"*, then *"can
 * you make it so that i can have multiple cut lines"*.
 *
 * The automatic re-cut in `strip.py` is deliberately narrow. It runs only on a
 * chapter that ARRIVED as a sliced strip, only before any work has been done
 * on it, and only when four separate tests agree - because being wrong there
 * rearranges somebody's chapter behind their back. Every one of those rules is
 * worth keeping, and between them they leave every other too-long page exactly
 * as it is. This is the knife for those: one page, the rows chosen by the
 * person looking at it.
 *
 * MANY ROWS AT ONCE and not one at a time, because one at a time is not the
 * same job done four times. A 10,413-row webtoon is four or five pages, and
 * cutting it a row at a time meant reopening the dialog on a piece whose
 * panels had all moved, with a renumber and a reload between each. The rows
 * go to the server together and it makes N+1 pages in one pass.
 *
 * It lives in the Translation view - the artwork as it came - because that is
 * the view you are in when you notice the page is wrong, and it is not offered
 * in the Image view at all, where the boxes are placed against the page and
 * the server refuses to cut anyway.
 *
 * Reads `cur`, `proj`, `api`, `toast`, `loadProject`, `renderPages`,
 * `showPage` from the other files. Classic script, one global scope. */

let _cutGaps = [], _cutH = 0;

/* The rows to cut at, sorted, in the page's own pixels. Sorted because the
   pieces are only in reading order if the rows are, and because "is there
   already a line here" is the question every click asks. */
let _cutRows = [];

/* How near a click has to land on a line, IN SCREEN PIXELS, to mean "take
   this one away" rather than "put one here". Screen pixels and not rows: a
   10,413-row page is drawn about a thousand tall, so a row is a tenth of a
   pixel and no tolerance measured in rows means anything to a hand. */
const NEAR = 5;

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
  cutClear();
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
      + `the piece it is on. Cleaning and typesetting are rebuilt.`
    : '';
  $('cutWhy').textContent = (_cutGaps.length
    ? `${proj.pages[i].name} - ${_cutH.toLocaleString()} rows tall, with `
      + `${_cutGaps.length} gap${_cutGaps.length === 1 ? '' : 's'} between `
      + `panels to cut at.`
    : `${proj.pages[i].name} - ${_cutH.toLocaleString()} rows tall. There is `
      + `no gap between panels on it, so wherever you cut goes through the `
      + `artwork.`) + carried;
  // NO LINE TO BEGIN WITH. It used to open with one across the middle, as a
  // hint that the thing was clickable - which was fair while a click MOVED
  // the line and cost nothing. Now a click ADDS one, so a line already there
  // means the first click somebody makes leaves them with two cuts they did
  // not ask for. The sentence under the preview does the hinting instead.
  drawCuts();
}

/* The row the last line went on, in the page's own pixels. One line is the
   ordinary case and this is the answer for it; `cutRows` is the whole list. */
function cutAt(){ return _cutRows.length ? _cutRows[_cutRows.length - 1] : 0; }

function cutRows(){ return _cutRows.slice(); }

/* Every row, in reading order. Not `cutAt` sorted afterwards - the pieces are
   named `a`, `b`, `c` down the page and the server trusts the order it is
   given, so the sort belongs where the row goes in. */
function sortCuts(){ _cutRows.sort((a, b) => a - b); }

/* The line goes on the row it was given. Nothing rounds it to a gap, nothing
   pulls it back from an edge, nothing waits for a drag to finish.
   lee: *"the cut line shoud apar where i click no matter hwat remove nything
   that is precenting that"*.

   The ONE thing that is still refused is a cut in the top or bottom sixteen
   rows, and it is refused by the Cut button going off with the reason beside
   it - not by moving the line. A sliver is not a page and the server says so
   anyway; being told why is different from being overruled. The same distance
   between two lines is refused the same way. */
const EDGE = 16;

/* ONE line, replacing whatever was there. This is what the dialog opens with
   and it is the whole gesture when a page only wants cutting once. */
function putLine(row){
  _cutRows = [Math.round(row)];
  drawCuts();
}

/* ...and one MORE line. lee: *"can you make it so that i can have multiple
   cut lines"*.

   A click landing within `NEAR` of a line already down does NOTHING, and that
   is the interesting case. It used to remove that line - the only undo the
   gesture had, and free. Then the lines became draggable, and the two gestures
   stopped being distinguishable: a grab and a nudge are the same thing with
   the distance turned down, so a hand that moved by nought pixels deleted the
   line it meant to move. lee: *"ad a way to delete the cut lines"*. There is
   an X on each line and a Clear all beside the button now, so this can go back
   to the only thing it was ever unambiguously good at: not stacking a second
   line on top of one that is already there.

   `NEAR` is in screen pixels for the reason written where it is defined. */
function addCut(row){
  row = Math.round(row);
  const img = $('cutImg');
  const per = (_cutH && img.offsetHeight) ? img.offsetHeight / _cutH : 0;
  if(per && _cutRows.some(r => Math.abs(r - row) * per <= NEAR)) return;
  _cutRows.push(row);
  sortCuts();
  drawCuts();
}

/* ONE line, gone. lee: *"ad a way to delete the cut lines"*.

   By its ROW and not by its index, because the only caller is the X on a line
   and the drawn lines are rebuilt from scratch on every change - an index
   read off the markup is an index that was true when the markup was written.
*/
function dropCut(row){
  const k = _cutRows.indexOf(+row);
  if(k < 0) return;
  _cutRows.splice(k, 1);
  drawCuts();
}

/* A CUT WITHOUT AIMING AT ONE. lee: *"add a button to add like and alow me to
   drag them into place"*.

   It goes in the MIDDLE OF THE BIGGEST PIECE, which is the one answer that is
   never wrong: it cannot land on a line already there, it needs no aim, and
   on a page with no cuts on it yet it is the middle of the page. Pressing it
   four times on a strip gives four evenly spaced cuts, which is what a
   ten-thousand-row webtoon wants before anything is nudged. */
function addCutButton(){
  if(!_cutH) return;
  const edges = [0].concat(_cutRows, [_cutH]);
  let best = 0, at = Math.round(_cutH / 2);
  for(let k = 0; k < edges.length - 1; k++){
    const span = edges[k + 1] - edges[k];
    if(span > best){ best = span; at = Math.round((edges[k] + edges[k + 1]) / 2); }
  }
  _cutRows.push(at);
  sortCuts();
  drawCuts();
}

/* ...and all of them. Four cuts placed by eye down a ten-thousand-row strip
   is four X's to find, and starting over is one thought rather than four. */
function cutClear(){ _cutRows = []; drawCuts(); }

/* DRAGGING A LINE INTO PLACE.

   lee: *"alow me to drag them into place"*. The drag that was taken OUT of
   this dialog was a different one: it was how a line got PLACED - pointer
   down anywhere on the page, capture, follow, release - and it swallowed
   clicks while the pointer was down, so a quick click on a slow frame
   sometimes did nothing. lee: *"remoeve teh click and drag and allow me to
   clci where i want it to cut"*.

   Placing is still a click. This is adjusting, which is what a drag is
   actually for, and it starts on the LINE - so a press on bare page is never
   held waiting to see whether it becomes a drag.

   A press that never moves is still a click, and a click on a line still
   takes it away. That is deliberate: a grab and a nudge are the same gesture
   with the distance turned down, so the only honest way to tell "I meant to
   move it" from "I meant to be rid of it" is whether it moved. */
let _dragK = -1, _dragged = false, _swallow = false, _xRow = null;

/* The pointer went down. A press on a LINE is a grab; a press on bare page is
   not held at all - it is a click, and it is handled as one when it comes.

   The capture goes on the WRAP and not on the line, because `drawCuts` builds
   the lines again on every move: capture held by an element that is about to
   be replaced is capture lost halfway through the drag. */
function cutDown(e){
  // ANY press clears the swallow, and it has to be cleared here rather than
  // only by the click it was meant for. A pointerup that ended a real drag
  // does not always produce a click - the pointer moved too far for the
  // browser to call it one - so a flag waiting for that click waits for ever
  // and eats the NEXT one instead: one drag, and the following click on bare
  // page did nothing at all. A pointerdown always comes before a click.
  _swallow = false;
  if(!_cutH) return;
  _xRow = null;
  // THE X IS NOT A HANDLE, and it is not a click either - it is decided
  // across the press, here and in `cutUp`. Two things went wrong before it
  // was: pressing it started a drag, and the drag then swallowed the very
  // click that was going to delete the line; and once the drag was stopped,
  // a press that slid off the X before letting go turned into a NEW cut
  // wherever the pointer had got to.
  const hitX = e.target.closest && e.target.closest('.cutline .x');
  if(hitX){
    _xRow = +hitX.closest('.cutline').dataset.row;
    return;
  }
  const line = e.target.closest && e.target.closest('.cutline');
  if(!line) return;
  _dragK = _cutRows.indexOf(+line.dataset.row);
  if(_dragK < 0) return;
  _dragged = false;
  const wrap = $('cutWrap');
  if(wrap.setPointerCapture) wrap.setPointerCapture(e.pointerId);
  e.preventDefault();
}

function cutDragTo(e){
  if(_dragK < 0) return;
  const r = $('cutImg').getBoundingClientRect();
  if(!r.height) return;
  const row = Math.round(
    Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)) * _cutH);
  if(row === _cutRows[_dragK]) return;
  _dragged = true;
  _cutRows[_dragK] = row;
  // Sorted on every move, because dragging one line PAST another changes
  // which piece is which - and the pieces are named down the page. The
  // dragged one is found again by its value, so the rest of the drag follows
  // the line under the pointer rather than whatever is now at that index.
  sortCuts();
  _dragK = _cutRows.indexOf(row);
  drawCuts();
}

function cutUp(e){
  if(_xRow !== null){
    // Let go still ON the X: that line goes. Let go somewhere else: nothing
    // goes, the way letting go off a button you pressed means you thought
    // better of it. Either way the click that follows is swallowed, because
    // in here a click means "put a cut somewhere" and neither of those did.
    const over = document.elementFromPoint(e.clientX, e.clientY);
    const x = over && over.closest && over.closest('.cutline .x');
    if(x && +x.closest('.cutline').dataset.row === _xRow) dropCut(_xRow);
    _xRow = null;
    _swallow = true;
    return;
  }
  if(_dragK < 0) return;
  const wrap = $('cutWrap');
  if(wrap.releasePointerCapture && wrap.hasPointerCapture
     && wrap.hasPointerCapture(e.pointerId))
    wrap.releasePointerCapture(e.pointerId);
  // The click that follows a pointerup is the one that would ADD a cut where
  // the drag ended. It is swallowed after a drag and let through after a
  // press that never moved - which is how a click on a line still takes it
  // away, and why a nudge and a removal can be the same gesture without
  // being the same outcome.
  _swallow = _dragged;
  _dragK = -1;
  _dragged = false;
}

/* Is this row one nothing will let us cut at? Said here rather than at each
   line, because a cut too close to its NEIGHBOUR is as bad as one too close
   to the edge and neither line is the one at fault. */
function cutTight(k){
  const row = _cutRows[k];
  if(row < EDGE || row > _cutH - EDGE) return 'too close to the edge';
  if(k > 0 && row - _cutRows[k - 1] < EDGE) return 'too close to the one above';
  if(k < _cutRows.length - 1 && _cutRows[k + 1] - row < EDGE)
    return 'too close to the one below';
  return '';
}

/* The lines, drawn where they are.

   IN PIXELS, measured off the picture. lee: *"th e line is still not where i
   clicked, use the mouse cordinate to draw the line"*.

   It was `top: <percent>`, and a percentage `top` on an absolutely positioned
   box resolves against the HEIGHT OF ITS CONTAINING BLOCK - which is
   `#cutWrap`, capped at 52vh with the picture scrolling inside it. So on every
   page tall enough to scroll, "40% of the way down the page" was drawn 40% of
   the way down the WINDOW ONTO the page. The taller the page, the further out
   it was, and on a short one it looked perfect.

   `offsetTop` is measured from the same origin an absolutely positioned child
   is placed from, so this is the picture's own top plus however far down the
   picture the row is. No percentages, no assumptions about the scroll. */
function drawCuts(){
  const box = $('cutLines');
  if(!box) return;
  box.innerHTML = '';
  if(!_cutH){ syncCutGo(); return; }
  const img = $('cutImg');
  _cutRows.forEach(function(row, k){
    const line = document.createElement('div');
    line.className = 'cutline';
    line.dataset.row = row;
    const at = Math.max(0, Math.min(_cutH, row)) / _cutH;
    line.style.top = (img.offsetTop + at * img.offsetHeight) + 'px';
    // Green means this row IS a gap between panels. It is a readout, not a
    // promise that anything moved.
    const on = _cutGaps.some(g => Math.abs(g - row) <= 2);
    const tight = cutTight(k);
    line.classList.toggle('snap', on && !tight);
    line.classList.toggle('bad', !!tight);
    const tag = document.createElement('b');
    tag.textContent = row.toLocaleString()
      + (tight ? '  ·  ' + tight : on ? '  ·  on a gap' : '');
    // ...and an X on it. lee: *"ad a way to delete the cut lines"*. It is a
    // target of its own rather than a gesture on the line, because the line
    // is a thing you drag now and a hand that moved by nought pixels must not
    // be read as a hand that meant to delete something.
    const x = document.createElement('u');
    x.className = 'x';
    x.textContent = '×';
    x.title = 'Take this cut away';
    tag.appendChild(x);
    // Something to take hold of. The line itself is two pixels of border and
    // nothing is grabbing that; the strip is thirteen tall, invisible, and
    // centred on it. It is also what makes a CLICK on a line land on the
    // line rather than on the page behind it.
    //
    // FIRST, and the badge after it, because the strip runs the full width -
    // under the badge as well. Appended the other way round it is painted on
    // top and takes every click meant for the X, which then does nothing at
    // all. The badge carries a `z-index` for the same reason said twice.
    const grab = document.createElement('i');
    grab.className = 'grab';
    line.appendChild(grab);
    line.appendChild(tag);
    box.appendChild(line);
  });
  syncCutGo();
}

/* What the button says and whether it can be pressed. The count is on it
   because "Cut here" beside four lines is a button that does not say what it
   is about to do. */
function syncCutGo(){
  const go = $('cutGo');
  if(!go) return;
  const n = _cutRows.length;
  const bad = _cutRows.some((_r, k) => cutTight(k));
  go.disabled = !n || bad;
  go.textContent = n > 1 ? `Cut into ${n + 1} pages` : 'Cut here';
  const help = $('cutCount');
  if(help) help.textContent = n
    ? `${n} cut${n === 1 ? '' : 's'} — ${n + 1} pages.`
    : '';
  const add = $('cutAdd');
  if(add) add.disabled = !_cutH;
  const wipe = $('cutClearAll');
  if(wipe) wipe.disabled = !n;
}

/* The row under the pointer, straight off the mouse coordinate: how far down
   the PICTURE the click was, as a fraction, times the page's real height. */
function cutFromEvent(e){
  if(_swallow){ _swallow = false; return; }   // that click was an X or a drag
  const r = $('cutImg').getBoundingClientRect();
  if(!r.height) return;
  addCut((e.clientY - r.top) / r.height * _cutH);
}

function cutHere(){
  const rows = cutRows();
  if(!rows.length) return;
  doCut('/api/page/' + cur + '/split', {ats: rows},
        rows.length === 1 ? 'Cut into two pages.'
                          : `Cut into ${rows.length + 1} pages.`);
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
  // ...and dragging a line already down into place. lee: *"alow me to drag
  // them into place"*. Delegated on the wrap so the lines can be rebuilt
  // under the pointer, which they are, on every move.
  wrap.addEventListener('pointerdown', cutDown);
  wrap.addEventListener('pointermove', cutDragTo);
  wrap.addEventListener('pointerup', cutUp);
  wrap.addEventListener('pointercancel', cutUp);
}

if(document.readyState === 'loading')
  document.addEventListener('DOMContentLoaded', cutBind);
else cutBind();
