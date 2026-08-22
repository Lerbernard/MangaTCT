/* Drag a square over the page and take every box under it.

   lee: *"also add annew seclet tool that alloww me to dran a scquer on the
   boxs and all the boxesin that square sihoud be slected and make clicking s
   activate it"*.

   The editor could already select several boxes -- Ctrl+click, or hold "c" --
   but only one at a time, which is fine for three boxes and miserable for a
   panel of twelve. This is the same selection, filled in one drag.

   ## IT SELECTS BOXES, NOT PIXELS

   There is already a "Rectangular select (M)" in the toolbox and it is a
   different thing entirely: that one marks an area of the ARTWORK for the
   brush and the fill to work inside. This one never touches a pixel - it
   picks regions, and what it fills in is `selMulti`, the same set Ctrl+click
   fills, so every action that already works on a multi-selection works on
   this one with no further wiring.

   ## TOUCHING IS ENOUGH

   A box counts as taken when the rectangle OVERLAPS it, not when it contains
   it. Containment is the tidier rule and the wrong one here: boxes of
   Japanese are tall, they run to the edge of a panel, and a drag that had to
   swallow a whole column whole would mean starting outside the artwork every
   time. Overlap is also what every drawing program does, which means nobody
   has to be told.

   ## AND IT STAYS ARMED

   It used to put itself away after one drag, on the theory that a mode still
   armed eats the next click on a box. lee, using it: *"make the selevct
   button be persistent and not turn off after one use"* - the actual next
   thing after selecting twelve boxes was selecting twelve more, and re-arming
   between every panel is worse than pressing Escape once at the end.

   So: armed by "s", the toolbox or the legend button, and disarmed ONLY by
   those - "s" again, Escape, or clicking the button. A drag leaves it armed;
   a click that never became a drag clears the selection and leaves it armed
   too, because while the tool is up a click cannot reach a box anyway and
   "click empty space to deselect" is what every drawing program means by it. */

let boxSel = false;          // armed?
let _bsDrag = null;          // {x0,y0,add,el} while dragging

function toggleBoxSelect(on){
  boxSel = (on === undefined) ? !boxSel : !!on;
  // Arming this puts the paint tools down, the same way picking a text box
  // does - two modes that both want the next drag is one mode too many.
  if(boxSel){
    if(typeof stopBrush === 'function' && typeof paintArmed === 'function'
       && paintArmed()) stopBrush();
    if(typeof stopAddText === 'function') stopAddText();
  }
  const st = $('stage'); if(st) st.style.cursor = boxSel ? 'crosshair' : '';
  const cw = $('canvasWrap');
  if(cw) cw.classList.toggle('boxselecting', boxSel);
  if(typeof drawToolbox === 'function') drawToolbox();
  // ...and the legend row, which carries the same button.
  if(typeof renderLegend === 'function') renderLegend();
  if(!boxSel) _bsCancel();
}

function _bsCancel(){
  if(_bsDrag && _bsDrag.el && _bsDrag.el.parentNode)
    _bsDrag.el.parentNode.removeChild(_bsDrag.el);
  _bsDrag = null;
}

function _bsPt(e){
  const b = $('img').getBoundingClientRect();
  return {x: Math.max(0, Math.min(e.clientX - b.left, b.width)),
          y: Math.max(0, Math.min(e.clientY - b.top, b.height))};
}

/* Every region the rectangle touches. `r.bbox` is [x, y, w, h] in PAGE
   pixels; the drag is in displayed pixels, so it is divided by `scale`
   once, here, rather than multiplying 200 boxes the other way. */
function boxesUnder(x0, y0, x1, y1){
  const out = [];
  (typeof regions !== 'undefined' ? regions : []).forEach(function(r){
    const b = r.bbox || r.draw_box; if(!b) return;
    const bx = b[0], by = b[1], bw = b[2], bh = b[3];
    if(bx < x1 && bx + bw > x0 && by < y1 && by + bh > y0) out.push(r.id);
  });
  return out;
}

function _bsDown(e){
  if(!boxSel || e.button !== 0) return;
  const img = $('img'); if(!img) return;
  e.preventDefault(); e.stopPropagation();
  const p = _bsPt(e);
  const el = document.createElement('div');
  el.className = 'boxselrect';
  const wrap = img.parentNode;
  wrap.appendChild(el);
  // Shift ADDS to what is already selected, which is the one thing you want
  // when a panel's boxes are in two clumps.
  _bsDrag = {x0: p.x, y0: p.y, add: !!(e.shiftKey), el: el};
  _bsMove(e);
}

function _bsMove(e){
  if(!_bsDrag) return;
  const p = _bsPt(e), d = _bsDrag;
  const x = Math.min(p.x, d.x0), y = Math.min(p.y, d.y0);
  const w = Math.abs(p.x - d.x0), h = Math.abs(p.y - d.y0);
  d.el.style.left = x + 'px'; d.el.style.top = y + 'px';
  d.el.style.width = w + 'px'; d.el.style.height = h + 'px';
}

function _bsUp(e){
  if(!_bsDrag) return;
  const p = _bsPt(e), d = _bsDrag;
  const s = (typeof scale !== 'undefined' && scale) ? scale : 1;
  const x0 = Math.min(p.x, d.x0) / s, y0 = Math.min(p.y, d.y0) / s;
  const x1 = Math.max(p.x, d.x0) / s, y1 = Math.max(p.y, d.y0) / s;
  const add = d.add;
  _bsCancel();
  // A click rather than a drag clears the selection - four pixels of travel
  // is the line, the same slop a drag anywhere else in this editor allows.
  // It does NOT put the tool away any more; only "s", Escape or the button
  // do. lee: *"make the selevct button be persistent"*.
  if((x1 - x0) * s < 4 && (y1 - y0) * s < 4){
    selMulti.clear(); sel = null;
    if(typeof drawBoxes === 'function') drawBoxes();
    if(typeof drawOverlay === 'function') drawOverlay();
    if(typeof renderList === 'function') renderList();
    return;
  }
  const ids = boxesUnder(x0, y0, x1, y1);
  if(!add) selMulti.clear();
  else if(!selMulti.size && sel != null) selMulti.add(sel);
  ids.forEach(function(id){ selMulti.add(id); });
  if(selMulti.size) sel = [...selMulti][selMulti.size - 1];
  if(selMulti.size < 2) selMulti.clear();   // one box is a plain selection
  if(typeof drawBoxes === 'function') drawBoxes();
  if(typeof drawOverlay === 'function') drawOverlay();
  if(typeof renderList === 'function') renderList();
  const n = selMulti.size || (sel != null ? 1 : 0);
  if(typeof toast === 'function')
    toast(n ? `${n} box${n === 1 ? '' : 'es'} selected` : 'nothing in there',
          900);
  // ...and the tool STAYS UP for the next drag. See "AND IT STAYS ARMED".
}

window.addEventListener('pointerdown', _bsDown, true);
window.addEventListener('pointermove', _bsMove, true);
window.addEventListener('pointerup', _bsUp, true);

window.addEventListener('keydown', function(e){
  if(e.ctrlKey || e.metaKey || e.altKey) return;
  const a = document.activeElement;
  if(a && (a.isContentEditable ||
           /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))) return;
  if(e.key === 's' || e.key === 'S'){ toggleBoxSelect(); e.preventDefault(); }
  else if(e.key === 'Escape' && boxSel) toggleBoxSelect(false);
});
