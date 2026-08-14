/* paint.js — Paint engine: clean toggle, brush / heal / clone-stamp tools, stroke capture, brush tips, layer list.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* Each stroke is a layer, as in an image editor: it can be selected in the
   list, hidden, or deleted on its own. Layers live per page, in this session. */
let brush=false, painting=null, picking=false, eraser=false;
/* Shapes: a rectangle, an ellipse or a straight line, drawn as an ordinary
   paint layer so everything that already works for a brush stroke works for
   them too — the layer list, the eye, delete, undo, the selection fence, the
   saved overlay and therefore the exported page. `shapeKind` is which one is
   armed; `shapeFill` says filled rather than outlined. */
let shapeKind=null, shapeFill=false;
/* ...and one more shape tool that draws nothing: `shapeEdit` is the arrow.
   With it armed, clicking a shape on the page picks it up and puts the free
   transform round it — drag to move, corners and edges to resize, just
   outside a corner to turn. lee: *"mske teh shapes movable"*. A shape edited
   this way stays a SHAPE: only its two points and its angle change, so its
   colour, width and fill are still yours to change afterwards. Transforming
   it as pixels — which is what picking it in the layer list and pressing T
   used to do — froze it into a flat patch and took all of that away. */
let shapeEdit=false;
/* Is any paint tool armed? Asked in five files — for the canvas's pointer
   events, for the class that stops region boxes swallowing the click, for the
   selection canvas, and by the typesetting editor, which must not open a text
   box mid-stroke. It was written out longhand in each of them, which is
   exactly how a new tool ends up half-wired: the shape tool drew nothing at
   all until this became one function. */
function paintArmed(){
  return !!(brush || stamp || heal || eraser || shapeKind || shapeEdit);
}
let layers=[], layerSel=null, layerSeq=1;
/* Two families of paint layers, shown in separate panels: 'drawing' (brush,
   fill, transform, paste, eraser) and 'retouch' (heal + clone-stamp output,
   folded away so a heavily-healed page doesn't drown the list). Each family
   has its own master eye. */
let showDrawing=true, showRetouch=true;
function isRetouch(l){
  if(l.group) return l.group==='retouch';
  // layers saved before groups existed: heal (blue) and clone (grey) patches
  return l.type==='patch' && !l.label && (l.col==='#57b0ff'||l.col==='#8a8f98');
}
function toggleGroupEye(which){
  if(which==='drawing') showDrawing=!showDrawing; else showRetouch=!showRetouch;
  repaintAll(); renderLayers();
}

/* Read this box's writing against its own local background instead of the
   fixed ink levels — for gold text, or a see-through bubble, where the
   ordinary reading describes the BACKGROUND and not the words.

   One box at a time, deliberately: every attempt to fix gold for the whole
   chapter moved something else. See `inpaint.focus_mask`. */
async function toggleFocus(id){
  const r=regions.find(x=>x.id===id); if(!r) return;
  if(toggleFocus._busy) return;
  toggleFocus._busy=true;
  const next=!r.focus;
  r.focus=next; renderList();
  try{
    const j=await api(`/api/page/${cur}/region/${id}`,'POST',{focus:next});
    if(j&&j.error) throw new Error(j.error);
    if(j&&j.region&&!!j.region.focus!==next){
      throw new Error('the server ignored it — restart the editor from the '+
                      'new zip and hard-refresh (Ctrl+Shift+R)');
    }
    record('clean', `Region ${(r.order??0)+1}: focus clean turned ${next?'on':'off'}`,
      async ()=>{ await api(`/api/page/${cur}/region/${id}`,'POST',{focus:!next});
                  showPage(cur); });
    await showPage(cur);
  }catch(e){
    r.focus=!next; renderList();
    toast('Could not change the cleaning: '+e.message);
  }finally{ toggleFocus._busy=false; }
}

async function toggleClean(id){
  const r=regions.find(x=>x.id===id); if(!r) return;
  if(toggleClean._busy) return;                    // one flip at a time
  toggleClean._busy=true;
  const next=!r.skip_clean;
  r.skip_clean=next; renderList();                 // show it immediately
  try{
    const j=await api(`/api/page/${cur}/region/${id}`,'POST',{skip_clean:next});
    if(j&&j.error){ throw new Error(j.error); }
    // If the server echoes a different value than we sent, the running server
    // predates this feature — say so instead of flipping back silently.
    if(j&&j.region&&!!j.region.skip_clean!==next){
      throw new Error('the server ignored it — restart the editor from the '+
                      'new zip and hard-refresh (Ctrl+Shift+R)');
    }
    record('clean', `Region ${(r.order??0)+1}: cleaning turned ${next?'off':'on'}`,
      async ()=>{ await api(`/api/page/${cur}/region/${id}`,'POST',{skip_clean:!next});
                  showPage(cur); });
    await showPage(cur);
  }catch(e){
    r.skip_clean=!next; renderList();
    toast('Could not change the cleaning: '+e.message);
  }finally{ toggleClean._busy=false; }
}


/* Panel controls only exist while their panel is rendered — the typesetting
   panel replaces them. brushState (picker.js) always holds the live values,
   so every read goes through these, never straight at the DOM. */
function bSz(){ const el=$('brushSz'); return el? +el.value : brushState.sz; }
function bCol(){ const el=$('brushCol'); return el? el.value : brushState.col; }

/* One shape tool with three shapes, so arming one puts the others away and
   clicking the armed one again disarms it — the same feel as the brush. */
function toggleShape(kind){
  shapeKind = (shapeKind===kind) ? null : kind;
  if(shapeKind) disarmTools('shape');
  ['Rect','Circle','Line'].forEach(k=>{
    const b=$('shape'+k+'Btn');
    if(b) b.classList.toggle('pri', shapeKind===k.toLowerCase());
  });
  ensureCanvas(); ensureCursor();
  const c=$('paint');
  if(c){
    // the canvas only takes the mouse while a tool is armed, and a shape is
    // aimed with the pointer itself rather than with a brush ring
    c.style.pointerEvents = paintArmed() ? 'auto' : 'none';
    c.style.cursor = shapeKind ? 'crosshair' : '';
  }
  const w=$('canvasWrap'); if(w) w.classList.toggle('painting', paintArmed());
  if(shapeKind){ const bc=$('brushCursor'); if(bc) bc.style.display='none'; }
  paintToolUI();
}
function setShapeFill(on){
  shapeFill=!!on;
  const b=$('shapeFillBtn'); if(b) b.classList.toggle('pri', shapeFill);
}

/* ---- the shape arrow ---- */
function toggleShapeEdit(on){
  shapeEdit = (on===undefined) ? !shapeEdit : !!on;
  if(shapeEdit) disarmTools('shapeEdit');
  else if(typeof xf!=='undefined' && xf && xf.vector) xfApply();
  const b=$('shapeEditBtn'); if(b) b.classList.toggle('pri', shapeEdit);
  ensureCanvas();
  const c=$('paint');
  if(c){
    c.style.pointerEvents = paintArmed() ? 'auto' : 'none';
    c.style.cursor = shapeEdit ? 'default'
      : shapeKind ? 'crosshair' : (brush||stamp||heal||eraser) ? 'none' : '';
  }
  const w=$('canvasWrap'); if(w) w.classList.toggle('painting', paintArmed());
  if(shapeEdit){
    const bc=$('brushCursor'); if(bc) bc.style.display='none';
    if(typeof selEnsureHandlers==='function') selEnsureHandlers();
    toast(shapes().length
      ? 'Click a shape to pick it up — drag to move, corners resize, just '+
        'outside a corner turns it. Enter or Esc lets go.'
      : 'Draw a rectangle, an ellipse or a line first, then this moves it.');
  }
  paintToolUI();
}

/* Every shape on this page, bottom of the stack first. */
function shapes(){ return layers.filter(l=>l.type==='shape'); }

/* Distance from p to the segment a–b. Used to hit a LINE, which has no
   inside to be inside of. */
function segDist(p,a,b){
  const vx=b.x-a.x, vy=b.y-a.y;
  const len=vx*vx+vy*vy;
  const t=len ? Math.max(0,Math.min(1,((p.x-a.x)*vx+(p.y-a.y)*vy)/len)) : 0;
  return Math.hypot(p.x-(a.x+vx*t), p.y-(a.y+vy*t));
}

/* Which shape is under the page point — the TOPMOST one, because that is the
   one you can see there. Hidden shapes cannot be picked: they are not on the
   page to be clicked on. */
function shapeAt(p){
  const list=shapes().filter(l=>l.visible!==false &&
                                (isRetouch(l)?showRetouch:showDrawing));
  for(let i=list.length-1;i>=0;i--){
    if(shapeHit(list[i],p)) return list[i];
  }
  return null;
}
function shapeHit(l,p){
  const a=l.pts[0], b=l.pts[l.pts.length-1];
  if(!a||!b) return false;
  const x0=Math.min(a.x,b.x), y0=Math.min(a.y,b.y);
  const w=Math.abs(b.x-a.x), h=Math.abs(b.y-a.y);
  // undo the shape's own turn, then test the upright shape
  let q=p;
  if(l.rot){
    const cx=x0+w/2, cy=y0+h/2;
    const cos=Math.cos(-l.rot), sin=Math.sin(-l.rot);
    const dx=p.x-cx, dy=p.y-cy;
    q={x:cx+dx*cos-dy*sin, y:cy+dx*sin+dy*cos};
  }
  // A grab margin, so a hairline outline is still clickable.
  const m=Math.max(6, (l.sz||1)/2 + 3);
  // in the shape's own frame the geometry is exactly the two points again
  if(l.shape==='line') return segDist(q, a, b) <= m;
  return q.x>=x0-m && q.x<=x0+w+m && q.y>=y0-m && q.y<=y0+h+m;
}

function toggleBrush(on){
  brush = (on===undefined) ? !brush : !!on;
  if(brush) disarmTools('brush');
  const b=$('brushBtn'); if(b) b.classList.toggle('pri',brush);
  ensureCanvas(); ensureCursor();
  $('paint').style.pointerEvents = paintArmed() ? 'auto' : 'none';
  $('canvasWrap').classList.toggle('painting', paintArmed());
  // the circle IS the cursor, so hide the arrow while painting
  $('paint').style.cursor = shapeKind ? 'crosshair'
    : (brush||stamp||heal) ? 'none' : '';
  if(!brush&&!heal) $('brushCursor')&&($('brushCursor').style.display='none');
  paintToolUI();
}

/* ---- clone stamp, straight out of Photoshop ----
   Alt-click marks the source; painting then copies pixels from there,
   keeping the same source-to-brush offset for the whole stroke (and for
   later strokes, until a new Alt-click). */
let stamp=false, cloneSrc=null, cloneOff=null, heal=false;
/* The healing brush: the marked spot goes to the configured AI cleaner,
   which REDRAWS what was underneath.

   There were two of these. The other one rebuilt the spot by copying real
   pixels in from its surroundings — instant, offline, exact on flat paper and
   on screentone, and unable to invent a single line of artwork that was not
   already somewhere nearby. On the pages lee actually retouches, that is the
   whole job, and he said so with the brush in his hand: *"remoev teh regualr
   healing brush, its ass"*. So there is one brush now, and if the cleaner is
   not set up it says so rather than quietly handing back the other one's
   work. */
function toggleHeal(on){
  heal = (on===undefined) ? !heal : !!on;
  if(heal) disarmTools('heal');
  ensureCanvas(); ensureCursor();
  $('paint').style.pointerEvents = paintArmed() ? 'auto' : 'none';
  $('canvasWrap').classList.toggle('painting', paintArmed());
  $('paint').style.cursor = shapeKind ? 'crosshair'
    : (brush||stamp||heal||eraser) ? 'none' : '';
  if(!brush&&!heal&&!eraser) $('brushCursor')&&($('brushCursor').style.display='none');
  paintToolUI();
  if(heal) toast('Paint over a spot — the AI cleaner redraws what was underneath.');
}
function toggleStamp(on){
  stamp = (on===undefined) ? !stamp : !!on;
  if(stamp) disarmTools('stamp');
  const b=$('stampBtn'); if(b) b.classList.toggle('pri',stamp);
  ensureCanvas();
  $('paint').style.pointerEvents = paintArmed() ? 'auto' : 'none';
  $('canvasWrap').classList.toggle('painting', paintArmed());
  $('paint').style.cursor = shapeKind ? 'crosshair'
    : (brush||stamp||heal) ? 'none' : '';
  if(!stamp){ hideCloneMark(); hideClonePrev(); clonePrevSnap=null; }
  else{
    refreshCloneSnap();
  }
  paintToolUI();
}
/* ---- eraser ----
   Erases paint — strokes, fills, patches — never the page itself. Each pass
   is a layer of its own (undoable, hideable, reorderable): it erases only
   what sits BELOW it in the layer stack, exactly like a Photoshop erase on
   a merged group. */
function toggleEraser(on){
  eraser = (on===undefined) ? !eraser : !!on;
  if(eraser) disarmTools('eraser');
  const b=$('eraserBtn'); if(b) b.classList.toggle('pri',eraser);
  ensureCanvas(); ensureCursor();
  $('paint').style.pointerEvents = paintArmed() ? 'auto' : 'none';
  $('canvasWrap').classList.toggle('painting', paintArmed());
  $('paint').style.cursor = shapeKind ? 'crosshair'
    : (brush||stamp||heal||eraser) ? 'none' : '';
  if(!brush&&!heal&&!eraser) $('brushCursor')&&($('brushCursor').style.display='none');
  paintToolUI();
}

function cloneMark(x,y){
  let m=$('cloneMark');
  if(!m){
    m=document.createElement('div'); m.id='cloneMark';
    $('stage').appendChild(m);
  }
  // Source ring is exactly the brush size, so what you take and what you
  // lay down read as the same footprint.
  const s=Math.max(8,bSz()*scale);
  m.style.width=s+'px'; m.style.height=s+'px';
  m.style.display='block';
  m.style.left=(x*scale)+'px'; m.style.top=(y*scale)+'px';
}
function hideCloneMark(){ const m=$('cloneMark'); if(m) m.style.display='none'; }

/* Two things follow the pointer while the stamp is armed: a brush-sized
   ring right under it (where paint will land), and a loupe offset above —
   styled like the colour picker's — showing the source pixels magnified. */
let clonePrevSnap=null;
function refreshCloneSnap(){ clonePrevSnap = stamp ? cloneSnapshot() : null; }
function cloneHover(e){
  if(!stamp){ hideClonePrev(); return; }
  const p=canvasPt(e);
  const szImg=+($('brushSz')&&$('brushSz').value)||16;
  const szScr=Math.max(8, szImg*scale);
  let ring=$('cloneRing');
  if(!ring){
    ring=document.createElement('div'); ring.id='cloneRing';
    $('stage').appendChild(ring);
  }
  ring.style.display='block';
  ring.style.width=szScr+'px'; ring.style.height=szScr+'px';
  ring.style.left=(p.x*scale)+'px'; ring.style.top=(p.y*scale)+'px';
  let el=$('clonePrev');
  if(!el){
    el=document.createElement('div'); el.id='clonePrev';
    const cv=document.createElement('canvas');
    cv.width=48; cv.height=48;
    el.appendChild(cv);
    $('stage').appendChild(el);
  }
  if(!cloneSrc || !clonePrevSnap || painting){ el.style.display='none'; return; }
  el.style.display='block';
  el.style.left=(p.x*scale)+'px'; el.style.top=(p.y*scale)+'px';
  const cv=el.firstChild, g=cv.getContext('2d');
  g.imageSmoothingEnabled=false;
  g.clearRect(0,0,cv.width,cv.height);
  // pixels that will appear under the brush: source-anchored before the
  // first stroke, offset-anchored after
  const sx=cloneOff ? p.x+cloneOff.dx : cloneSrc.x;
  const sy=cloneOff ? p.y+cloneOff.dy : cloneSrc.y;
  g.drawImage(clonePrevSnap,
    sx-szImg/2, sy-szImg/2, szImg, szImg,
    0, 0, cv.width, cv.height);
}
function hideClonePrev(){
  const el=$('clonePrev'); if(el) el.style.display='none';
  const r=$('cloneRing'); if(r) r.style.display='none';
}
function cloneSnapshot(){
  // What the page looks like right now — plate plus every stroke so far —
  // frozen, so a stroke can't clone from itself while it is being drawn.
  const img=$('img'), c=document.createElement('canvas');
  c.width=img.naturalWidth; c.height=img.naturalHeight;
  const g=c.getContext('2d');
  g.drawImage(img,0,0,c.width,c.height);
  const pcv=$('paint'); if(pcv) g.drawImage(pcv,0,0);
  return c;
}

/* Everything you can see on the page, in one canvas: the plate, the paint
   under the typesetting, and the paint OVER it.

   `cloneSnapshot` is deliberately only the first two — a clone stamp or a
   heal reads from what is beneath the text, never through it. The free
   transform is the opposite case: it picks up what is inside a selection, and
   what is inside a selection is whatever is drawn there. Anything on the over
   band — a shape drawn on top of the typesetting, a highlight — was left
   standing where it was while the rest of the selection moved off without it.
   lee: *"the fre tansfor too shoude be able to move everything when i slect
   it"*. The typesetting itself is NOT baked in: it is drawn by its own overlay
   from the region records, so a copy in the patch would be a second copy on
   screen. */
function flatSnapshot(){
  const c=cloneSnapshot();
  const ov=$('paintOver');
  if(ov) c.getContext('2d').drawImage(ov,0,0);
  return c;
}

function stopBrush(){ brush=false; stamp=false; heal=false; picking=false;
  eraser=false; const eb=$('eraserBtn'); if(eb) eb.classList.remove('pri');
  shapeKind=null;
  shapeEdit=false;
  const sb=$('shapeEditBtn'); if(sb) sb.classList.remove('pri');
  ['Rect','Circle','Line'].forEach(k=>{
    const b2=$('shape'+k+'Btn'); if(b2) b2.classList.remove('pri'); });
  if(typeof selOnStopBrush==='function') selOnStopBrush();
  hideCloneMark(); hideClonePrev(); clonePrevSnap=null;
  const w=$('canvasWrap'); if(w) w.classList.remove('painting');
  const c=$('paint'); if(c){c.style.pointerEvents='none';c.style.cursor='';}
  paintToolUI(); }

/* The canvas for paint that sits ABOVE the typesetting. The ordinary one is at
   z-index 18, under the text overlay at 22; this is at 23. Two canvases is the
   whole of the two-band model on screen — a layer is drawn on one or the
   other. lee: *"i shoud be able to ... move other layers above the text
   folder"*. */
function ensureOverCanvas(){
  let c=$('paintOver');
  const img=$('img');
  if(!img||!img.naturalWidth) return null;
  if(!c){
    c=document.createElement('canvas');
    c.id='paintOver';
    c.style.cssText='position:absolute;left:0;top:0;z-index:23;'+
                    'pointer-events:none';
    $('stage').appendChild(c);
  }
  if(c.width!==img.naturalWidth||c.height!==img.naturalHeight){
    c.width=img.naturalWidth; c.height=img.naturalHeight;
  }
  c.style.width=img.clientWidth+'px'; c.style.height=img.clientHeight+'px';
  return c;
}
/* Is this layer drawn over the text? One question, asked in six places. */
function isOver(l){ return !!(l && l.over); }

function ensureCanvas(){
  let c=$('paint');
  if(!c){
    c=document.createElement('canvas');
    c.id='paint';
    c.style.cssText='position:absolute;left:0;top:0;z-index:18;pointer-events:none';
    $('stage').appendChild(c);
    c.addEventListener('mousedown',paintDown);
    c.addEventListener('mousemove',cloneHover);
    c.addEventListener('mouseleave',hideClonePrev);
    window.addEventListener('mousemove',paintMove);
    // A stroke — and its single history entry — ends only when the LEFT
    // button that started it is released.
    window.addEventListener('mouseup',e=>{
      if(e.button===0) finishStroke();
    });
  }
  const img=$('img');
  // Only touch the bitmap when the size really changed — setting width
  // clears a canvas, and that was quietly erasing strokes.
  if(c.width!==img.naturalWidth || c.height!==img.naturalHeight){
    c.width=img.naturalWidth; c.height=img.naturalHeight;
    repaintAll();
  }
  c.style.width=img.clientWidth+'px'; c.style.height=img.clientHeight+'px';
  return c;
}

function canvasPt(e){
  const img=$('img'), b=img.getBoundingClientRect();
  return {x:(e.clientX-b.left)/b.width*img.naturalWidth,
          y:(e.clientY-b.top)/b.height*img.naturalHeight};
}

function paintDown(e){
  if(picking){
    // read the colour under the cursor from the composited view
    const img=$('img'), c=document.createElement('canvas');
    c.width=img.naturalWidth; c.height=img.naturalHeight;
    const g=c.getContext('2d'); g.drawImage(img,0,0);
    const p=canvasPt(e);
    const d=g.getImageData(Math.round(p.x),Math.round(p.y),1,1).data;
    setPicked('#'+[d[0],d[1],d[2]].map(v=>v.toString(16).padStart(2,'0')).join(''));
    stopPagePick();
    const h=$('colHex'); if(h&&!pkTarget) h.textContent=bCol();
    e.preventDefault(); e.stopPropagation();
    return;
  }
  if(shapeEdit){
    if(e.button!==0) return;
    const p=canvasPt(e);
    // A live transform's own handles belong to select.js, which listens on
    // this same canvas right after us. Stepping aside is the whole handling:
    // stopPropagation does not stop a sibling listener, so both always run.
    if(typeof xf!=='undefined' && xf && xfHandleAt(p)) return;
    e.preventDefault(); e.stopPropagation();
    const l=shapeAt(p);
    // Clicking away from every shape puts down the one being held, which is
    // how you stop without reaching for a key.
    if(typeof xf!=='undefined' && xf) xfApply();
    if(!l){ layerSel=null; renderLayers(); return; }
    layerSel=l.id; renderLayers();
    xfStart();
    return;
  }
  if(heal){
    if(e.button!==0) return;
    e.preventDefault(); e.stopPropagation();
    // The overlay shows what you have marked; the fill happens on release.
    painting={id:layerSeq++, type:'heal', col:'#57b0ff',
              sz:bSz(), hard:1, op:0.35,
              pts:[canvasPt(e)], visible:true};
    drawStroke(painting);
    return;
  }
  if(stamp){
    const p=canvasPt(e);
    if(e.altKey){                       // pick where to clone FROM
      cloneSrc={x:p.x,y:p.y}; cloneOff=null;
      cloneMark(p.x,p.y);
      refreshCloneSnap();
      cloneHover(e);                    // the ring fills in right away
      e.preventDefault(); e.stopPropagation(); return;
    }
    if(e.button!==0) return;
    if(!cloneSrc){ toast('Alt-click the spot to clone from first.'); return; }
    e.preventDefault(); e.stopPropagation();
    if(!cloneOff) cloneOff={dx:cloneSrc.x-p.x, dy:cloneSrc.y-p.y};
    hideClonePrev();
    painting={id:layerSeq++, type:'clone', col:'#8a8f98',
              sz:bSz(),
              op:(+($('brushOp')&&$('brushOp').value)||100)/100,
              hard:(+($('brushHard')?$('brushHard').value:100))/100,
              off:{dx:cloneOff.dx,dy:cloneOff.dy},
              snap:cloneSnapshot(), pts:[p], visible:true};
    drawStroke(painting);
    return;
  }
  if(shapeKind){
    if(e.button!==0) return;
    e.preventDefault(); e.stopPropagation();
    const p=canvasPt(e);
    painting={id:layerSeq++, type:'shape', shape:shapeKind, col:bCol(),
              sz:bSz(), fill:shapeFill,
              op:(+($('brushOp')&&$('brushOp').value)||100)/100,
              // a shape is defined by where you pressed and where you are now
              pts:[p, p], visible:true};
    drawStroke(painting);
    return;
  }
  if(eraser){
    if(e.button!==0) return;
    e.preventDefault(); e.stopPropagation();
    painting={id:layerSeq++, type:'erase', col:'#8892a3',
              sz:bSz(),
              op:(+($('brushOp')&&$('brushOp').value)||100)/100,
              hard:(+($('brushHard')?$('brushHard').value:100))/100,
              pts:[canvasPt(e)], visible:true};
    drawStroke(painting);
    return;
  }
  if(!brush) return;
  if(e.button!==0) return;                 // the brush answers to the left button only
  e.preventDefault(); e.stopPropagation();
  painting={id:layerSeq++, col:bCol(), sz:bSz(),
            op:(+($('brushOp')&&$('brushOp').value)||100)/100,
            hard:(+($('brushHard')?$('brushHard').value:100))/100,
            pts:[canvasPt(e)], visible:true};
  drawStroke(painting);
}
function extendStroke(p){
  if(painting.type==='shape'){
    // Shift makes a rectangle square, an ellipse a circle and a line one of
    // the eight compass directions — the usual bargain.
    painting.pts[1]=shapeSnap(painting, p);
    drawStroke(painting);
    return;
  }
  painting.pts.push(p);
  drawStroke(painting);
  // the ring shows where the pixels are being copied FROM
  if(painting.type==='clone'){
    cloneMark(p.x+painting.off.dx, p.y+painting.off.dy);
    const ring=$('cloneRing');
    if(ring){ ring.style.left=(p.x*scale)+'px'; ring.style.top=(p.y*scale)+'px'; }
  }
}

/* Arrow keys steer the stroke while the button is held — pixel-precise
   lines without a steady hand. Shift strides in 8s. */
window.addEventListener('keydown',e=>{
  if(!painting) return;
  const d={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];
  if(!d) return;
  e.preventDefault(); e.stopPropagation();
  const step=e.shiftKey?8:1;
  const last=painting.pts[painting.pts.length-1];
  extendStroke({x:last.x+d[0]*step, y:last.y+d[1]*step});
},true);

function finishStroke(){
  if(!painting) return;
  // Whatever the frame clock deferred, draw it: everything below reads the
  // stroke's buffer, and a stroke released inside one frame would never have
  // had one made.
  drawStrokeNow(painting);
  if(painting.pts.length>=3){
    // close the last half-segment the curve walk leaves open
    const q=painting.pts, g=strokeBuf(painting).getContext('2d');
    const seg = painting.type==='clone' ? stampSeg : tipSeg;
    seg(g,painting,mid(q[q.length-2],q[q.length-1]),q[q.length-1]);
    compositeLive(painting);
  }
  if(painting.type==='heal'){
    const st=painting; painting=null;
    finalizeHeal(st);
    return;
  }
  if(painting.type==='erase'){
    // Erase strokes replay from their points with destination-out. If a
    // selection fenced this pass, freeze the fence with the stroke — the
    // selection may be gone by the next replay.
    const st=painting; painting=null;
    if(typeof selHasMask==='function' && selHasMask()){
      st.clip=selMask.toDataURL('image/png');
      const ci=new Image();
      ci.onload=()=>{ st.clipImg=ci; repaintAll(); };
      ci.src=st.clip;
    }
    delete st.buf;
    layers.push(st); layerSel=st.id;
    record('paint', `Eraser ${st.id}`, undoPaintLast);
    repaintAll(); renderLayers(); queueSync();
    return;
  }
  if(painting.type==='shape'){
    const st=painting; painting=null;
    const [a,b]=[st.pts[0], st.pts[1]];
    if(Math.abs(b.x-a.x)<2 && Math.abs(b.y-a.y)<2){
      // a click, not a drag: nothing to keep
      repaintAll(); return;
    }
    delete st.buf;
    if(typeof selHasMask==='function' && selHasMask()){
      layers.push(selBakeStroke(st));
    } else {
      layers.push(st);
    }
    layerSel=st.id;
    record('paint', `${st.shape[0].toUpperCase()+st.shape.slice(1)} ${st.id}`,
           undoPaintLast);
    repaintAll(); renderLayers(); queueSync();
    return;
  }
  if(typeof selHasMask==='function' && selHasMask() && painting.buf){
    // A stroke painted inside a selection freezes to a clipped patch layer:
    // strokes normally replay from their points, and the selection may be
    // long gone by replay time, so the clip must be baked in now.
    painting=selBakeStroke(painting);
  }
  else if(painting.type==='clone' && painting.buf){
    // Freeze the clone into a small image patch so it can be saved with the
    // project and edited when you come back.
    const xs=painting.pts.map(p=>p.x), ys=painting.pts.map(p=>p.y);
    const pad=painting.sz/2+2, c=$('paint');
    const x0=Math.max(0,Math.floor(Math.min(...xs)-pad));
    const y0=Math.max(0,Math.floor(Math.min(...ys)-pad));
    const x1=Math.min(c.width, Math.ceil(Math.max(...xs)+pad));
    const y1=Math.min(c.height,Math.ceil(Math.max(...ys)+pad));
    const cc=document.createElement('canvas');
    cc.width=Math.max(1,x1-x0); cc.height=Math.max(1,y1-y0);
    cc.getContext('2d').drawImage(painting.buf,
      x0,y0,cc.width,cc.height, 0,0,cc.width,cc.height);
    const png=cc.toDataURL('image/png');
    const rep={id:painting.id, type:'patch', col:'#8a8f98', sz:painting.sz,
               group:'retouch', label:'Clone',
               x:x0, y:y0, png, img:null, op:painting.op,
               pts:painting.pts, visible:true};
    const im=new Image();
    im.onload=()=>{ rep.img=im; repaintAll(); };
    im.src=png;
    // bake the buffer so the screen stays right until the image decodes
    const L=layersBuf(), g=L.getContext('2d');
    g.globalAlpha = painting.op==null?1:painting.op;
    g.drawImage(painting.buf,0,0);
    g.globalAlpha=1;
    compositeLive(null);
    painting=rep;
  } else if(painting.buf){
    const L=layersBuf(), g=L.getContext('2d');
    g.globalAlpha = painting.op==null?1:painting.op;
    g.drawImage(painting.buf,0,0);
    g.globalAlpha=1;
    delete painting.buf;                  // replay from points from now on
    compositeLive(null);
  }
  layers.push(painting); layerSel=painting.id;
  const n=painting.id,
        kind=painting.label||(painting.type==='clone'?'Clone stamp':'Brush stroke');
  painting=null;
  record('paint', `${kind} ${n} painted`, undoPaintLast);
  renderLayers();
  queueSync();
  if(stamp){
    if(cloneSrc) cloneMark(cloneSrc.x, cloneSrc.y);
    refreshCloneSnap();
  }
}
function paintMove(e){
  if(!painting) return;
  // If the left button is no longer held (released off-window, etc.),
  // close the stroke instead of dragging it back in.
  if(!(e.buttons&1)){ finishStroke(); return; }
  const raw=canvasPt(e);
  if(painting.type==='shape'){
    // A shape's far corner IS the pointer. The smoothing below is for a hand
    // drawing a line, and putting a rectangle through it made the corner trail
    // the cursor and then settle short of it on release — you never got the
    // box you drew. The micro-move guard is wrong here for the same reason:
    // a one-pixel nudge to line an edge up is a real edit, not jitter.
    extendStroke(raw);
    return;
  }
  const last=painting.pts[painting.pts.length-1];
  // gentle exponential smoothing takes hand jitter out of the line
  const K=0.55;
  const p={x:last.x+(raw.x-last.x)*K, y:last.y+(raw.y-last.y)*K};
  if(Math.hypot(p.x-last.x,p.y-last.y)<1.2) return;   // ignore micro moves
  extendStroke(p);
}
/* ---- brush engine ----
   Strokes are stamped from a round tip whose edge softness comes from the
   hardness setting. Each stroke draws opaque into its own buffer and is
   composited at its opacity, so a stroke never darkens where it crosses
   itself. `layersCanvas` holds every finished stroke; the visible canvas is
   layersCanvas plus the stroke being drawn. */
let layersCanvas=null;
function layersBuf(){
  const c=$('paint');
  if(!layersCanvas) layersCanvas=document.createElement('canvas');
  if(c && (layersCanvas.width!==c.width||layersCanvas.height!==c.height)){
    layersCanvas.width=c.width; layersCanvas.height=c.height;
  }
  return layersCanvas;
}
const _tips={};
function _ah(a){ return Math.round(Math.max(0,Math.min(1,a))*255)
                  .toString(16).padStart(2,'0'); }
function brushTip(sz,hard,col){
  const key=sz+'|'+hard+'|'+col;
  if(_tips[key]) return _tips[key];
  const s=Math.max(2,Math.ceil(sz));
  const c=document.createElement('canvas'); c.width=c.height=s;
  const g=c.getContext('2d'), r=s/2;
  if(hard>=0.99){
    g.fillStyle=col;
    g.beginPath(); g.arc(r,r,r,0,7); g.fill();
  }else{
    // Photoshop-style profile: solid out to `hard` of the radius, then a
    // gaussian tail to the edge — a soft brush keeps a full dark core with
    // a wide feather, instead of thinning out from the very centre.
    const gr=g.createRadialGradient(r,r,0, r,r,r);
    gr.addColorStop(0, col);
    if(hard>0) gr.addColorStop(Math.min(0.98,hard), col);
    const STEPS=7;
    for(let k=1;k<=STEPS;k++){
      const u=k/STEPS;                       // 0..1 across the feather
      const a=Math.exp(-(u*u)*4.6);          // ≈1 at core edge, ≈1% at rim
      gr.addColorStop(Math.min(1,hard+(1-hard)*u), col+_ah(a));
    }
    g.fillStyle=gr;
    g.beginPath(); g.arc(r,r,r,0,7); g.fill();
  }
  _tips[key]=c;
  return c;
}
function tipSeg(g,st,a,b){
  const hard=st.hard==null?1:st.hard;
  if(hard>=0.99){
    // A hard stroke is a smooth round-capped path — no stamp scallops.
    g.strokeStyle=st.col; g.fillStyle=st.col;
    g.lineWidth=st.sz; g.lineCap='round'; g.lineJoin='round';
    if(a.x===b.x&&a.y===b.y){
      g.beginPath(); g.arc(a.x,a.y,st.sz/2,0,7); g.fill();
    }else{
      g.beginPath(); g.moveTo(a.x,a.y); g.lineTo(b.x,b.y); g.stroke();
    }
    return;
  }
  const tip=brushTip(st.sz, hard, st.col);
  // tighter spacing for soft tips, or the centres show through as dots
  const d=Math.hypot(b.x-a.x,b.y-a.y), step=Math.max(0.75,st.sz/8);
  const n=Math.max(1,Math.ceil(d/step));
  for(let i=0;i<=n;i++){
    const x=a.x+(b.x-a.x)*i/n, y=a.y+(b.y-a.y)*i/n;
    g.drawImage(tip, x-tip.width/2, y-tip.height/2);
  }
}

/* ---- smooth strokes ----
   Raw mouse points make polygons. Drawing quadratic curves that pass
   through the midpoints of successive points (with the point itself as
   the control) turns them into one continuous smooth line — the standard
   ink-smoothing trick. Works for paths, tip stamping and clone stamping
   alike: everything goes through the same curve walk. */
const mid=(a,b)=>({x:(a.x+b.x)/2, y:(a.y+b.y)/2});
function curveSeg(g,st,a,b,c){
  // from mid(a,b) to mid(b,c), bending around b
  const m1=mid(a,b), m2=mid(b,c);
  const hard=st.hard==null?1:st.hard;
  if(st.type!=='clone' && hard>=0.99){
    g.strokeStyle=st.col; g.lineWidth=st.sz;
    g.lineCap='round'; g.lineJoin='round';
    g.beginPath(); g.moveTo(m1.x,m1.y);
    g.quadraticCurveTo(b.x,b.y,m2.x,m2.y); g.stroke();
    return;
  }
  const approx=Math.hypot(b.x-m1.x,b.y-m1.y)+Math.hypot(m2.x-b.x,m2.y-b.y);
  const step=Math.max(0.75, st.sz/(st.type==='clone'?6:8));
  const n=Math.max(1,Math.ceil(approx/step));
  const tip = st.type==='clone' ? null : brushTip(st.sz,hard,st.col);
  for(let i=0;i<=n;i++){
    const t=i/n, u=1-t;
    const x=u*u*m1.x+2*u*t*b.x+t*t*m2.x;
    const y=u*u*m1.y+2*u*t*b.y+t*t*m2.y;
    if(st.type==='clone') cloneStampAt(g,st,x,y);
    else g.drawImage(tip, x-tip.width/2, y-tip.height/2);
  }
}
let _cloneTmp=null;
function cloneStampAt(g,st,x,y){
  const sz=Math.max(2,Math.ceil(st.sz));
  if(!_cloneTmp) _cloneTmp=document.createElement('canvas');
  if(_cloneTmp.width!==sz){ _cloneTmp.width=_cloneTmp.height=sz; }
  const t=_cloneTmp.getContext('2d');
  t.globalCompositeOperation='source-over';
  t.clearRect(0,0,sz,sz);
  t.drawImage(st.snap, x+st.off.dx-sz/2, y+st.off.dy-sz/2, sz, sz, 0,0, sz, sz);
  t.globalCompositeOperation='destination-in';
  t.drawImage(brushTip(sz, st.hard==null?1:st.hard, '#ffffff'), 0,0);
  t.globalCompositeOperation='source-over';
  g.drawImage(_cloneTmp, x-sz/2, y-sz/2);
}
function stampSeg(g,st,a,b){
  const hard=st.hard==null?1:st.hard;
  const d=Math.hypot(b.x-a.x,b.y-a.y);
  const step=Math.max(0.75, st.sz/(hard>=0.99?4:8));
  const n=Math.max(1,Math.ceil(d/step));
  for(let i=0;i<=n;i++)
    cloneStampAt(g, st, a.x+(b.x-a.x)*i/n, a.y+(b.y-a.y)*i/n);
}
function strokeBuf(st){
  if(!st.buf){
    const c=$('paint');
    st.buf=document.createElement('canvas');
    st.buf.width=c.width; st.buf.height=c.height;
  }
  return st.buf;
}
function compositeLive(st){
  const c=$('paint'), m=c.getContext('2d');
  m.clearRect(0,0,c.width,c.height);
  m.drawImage(underOnScreen(),0,0);
  if(st&&st.buf){
    // inside a selection, the live preview clips like the finished stroke will
    const src=(typeof selClipLive==='function' && selClipLive(st.buf)) || st.buf;
    m.globalAlpha = st.op==null?1:st.op;
    if(st.type==='erase') m.globalCompositeOperation='destination-out';
    m.drawImage(src,0,0);
    m.globalCompositeOperation='source-over';
    m.globalAlpha=1;
  }
}
/* Draw the ENTIRE stroke smoothly into context g — a lead-in, a curve
   through every point, and a tail. The live preview and the committed replay
   both go through this, so what you see mid-stroke is exactly what lands on
   release: no rougher, no lag. */
/* Shift-constrain: square/circle from the corner, or a line to 45s. */
let shapeShift=false;
function shapeSnap(st, p){
  if(!shapeShift) return p;
  const a=st.pts[0];
  let dx=p.x-a.x, dy=p.y-a.y;
  if(st.shape==='line'){
    const step=Math.PI/4;
    const r=Math.hypot(dx,dy), th=Math.round(Math.atan2(dy,dx)/step)*step;
    return {x:a.x+r*Math.cos(th), y:a.y+r*Math.sin(th)};
  }
  const m=Math.max(Math.abs(dx),Math.abs(dy));
  return {x:a.x+Math.sign(dx||1)*m, y:a.y+Math.sign(dy||1)*m};
}
window.addEventListener('keydown',e=>{ if(e.key==='Shift') shapeShift=true; });
window.addEventListener('keyup',  e=>{ if(e.key==='Shift') shapeShift=false; });

/* A shape, on whichever canvas it is asked to draw on: the live preview
   buffer, a replay of the layer list, or the flattened overlay that is saved
   and exported. One function, so all three can never disagree. */
function shapePath(g, st){
  const [a,b]=[st.pts[0], st.pts[st.pts.length-1]];
  const x0=Math.min(a.x,b.x), y0=Math.min(a.y,b.y);
  const w=Math.abs(b.x-a.x), h=Math.abs(b.y-a.y);
  g.save();
  // A shape can be turned after it is drawn. The angle is kept on the layer
  // rather than baked into the points, so the shape stays a shape — its
  // colour, width and fill are still editable afterwards, and the two points
  // still mean the two corners you dragged between.
  if(st.rot){
    const cx=x0+w/2, cy=y0+h/2;
    g.translate(cx,cy); g.rotate(st.rot); g.translate(-cx,-cy);
  }
  g.strokeStyle=st.col; g.fillStyle=st.col;
  g.lineWidth=Math.max(1, st.sz||1);
  g.lineCap='round'; g.lineJoin='round';
  g.beginPath();
  if(st.shape==='line'){ g.moveTo(a.x,a.y); g.lineTo(b.x,b.y); g.stroke(); }
  else if(st.shape==='circle'){
    g.ellipse(x0+w/2, y0+h/2, Math.max(0.5,w/2), Math.max(0.5,h/2), 0, 0, Math.PI*2);
    if(st.fill) g.fill(); else g.stroke();
  } else {
    g.rect(x0, y0, w, h);
    if(st.fill) g.fill(); else g.stroke();
  }
  g.restore();
}

function paintPath(g, st){
  if(st.type==='shape'){ shapePath(g, st); return; }
  const seg = st.type==='clone' ? stampSeg : tipSeg;
  const q=st.pts, n=q.length;
  if(!n) return;
  if(n===1) seg(g,st,q[0],q[0]);
  else if(n===2) seg(g,st,q[0],q[1]);
  else{
    seg(g,st,q[0],mid(q[0],q[1]));               // lead-in
    for(let i=2;i<n;i++) curveSeg(g,st,q[i-2],q[i-1],q[i]);
    seg(g,st,mid(q[n-2],q[n-1]),q[n-1]);         // tail
  }
}
function drawStroke(st){
  // Once per frame, not once per mouse move. The points are already recorded
  // by the time this is called, so the redraw that actually runs is the one
  // that draws all of them.
  onFrame('stroke', ()=>{
    if(painting!==st && !st._final) return;   // that stroke is over
    const buf=strokeBuf(st), g=buf.getContext('2d');
    // Redraw the whole stroke each move instead of appending the newest
    // segment. Appending left the hand-jitter un-smoothed until release, so
    // the live preview looked scribbly next to the clean result.
    g.clearRect(0,0,buf.width,buf.height);
    paintPath(g, st);
    compositeLive(st);
  });
}
/* Draw this stroke NOW, whatever the frame clock says. Releasing the button
   has to leave the finished stroke on screen, not the last frame drawn. */
function drawStrokeNow(st){
  st._final=true;
  drawStroke(st);
  flushFrame();
  delete st._final;
}
/* Did the last replay have to leave something out?

   A patch's picture and an eraser's fence are decoded from a data URL, which
   is asynchronous — so a replay that runs in the moment between a layer being
   made and its picture arriving quietly draws one layer fewer. On SCREEN that
   is invisible and self-correcting: the decode fires `repaintAll` when it
   lands. The buffer is not only for the screen, though. It is also the picture
   that is SAVED, composited into the cleaned plate and drawn under the
   typesetting on the exported page — and a save that caught this moment wrote a
   page missing the very stroke that had just been drawn, which is what lee saw:

     *"when typesetting the clean page it uses shoud have all the edit i make
     in it ... i fixed it but its still not using the fixed version"*

   The gap he had painted over was there on his screen — the browser replays
   the editable layers, and by then they had decoded — and gone from the plate,
   which had been written from the one replay that ran too early. So the flag,
   and `syncPaint` waits rather than saving what it can see. */
let replayIncomplete=false;
function replayStroke(dst, st){
  const d=dst.getContext('2d');
  if(st.type==='patch'){
    if(!st.img){ replayIncomplete=true; return; }   // still decoding
    d.globalAlpha = st.op==null?1:st.op;
    d.drawImage(st.img, st.x, st.y);
    d.globalAlpha=1;
    return;
  }
  const b=document.createElement('canvas');
  b.width=dst.width; b.height=dst.height;
  const g=b.getContext('2d');
  paintPath(g, st);
  if(st.type==='erase'){
    if(st.clip && !st.clipImg){ replayIncomplete=true; return; }   // decoding
    if(st.clipImg){
      const bg=b.getContext('2d');
      bg.globalCompositeOperation='destination-in';
      bg.drawImage(st.clipImg,0,0);
      bg.globalCompositeOperation='source-over';
    }
    d.globalAlpha = st.op==null?1:st.op;
    d.globalCompositeOperation='destination-out';
    d.drawImage(b,0,0);
    d.globalCompositeOperation='source-over';
    d.globalAlpha=1;
    return;
  }
  d.globalAlpha = st.op==null?1:st.op;
  d.drawImage(b,0,0);
  d.globalAlpha=1;
}
/* What the PAGE has: every layer whose own eye is open. This is the set that
   is saved, baked into the cleaned plate and printed. */
function pageLayers(){ return layers.filter(st=>st.visible!==false); }
/* What the SCREEN shows: the same, less whichever family is folded away.
   `showDrawing`/`showRetouch` are the two master eyes over the panels, they
   live only in this tab and are back on the moment the page is reopened — so
   they are a way of looking at the page, not a fact about it. They used to
   filter the buffer that gets SAVED as well, which meant folding the retouch
   family away and carrying on painting quietly wrote a plate with every heal
   and clone-stamp patch missing from it, and reopening the page put them all
   back on screen with no sign that the saved copy disagreed. */
function screenLayers(){
  return pageLayers().filter(st=>isRetouch(st)?showRetouch:showDrawing);
}
function _folded(){ return !showDrawing || !showRetouch; }
/* A scratch canvas the size of the paint canvas, made once and kept. */
let _viewUnder=null, _viewOver=null;
function _viewBuf(which){
  const c=$('paint');
  let b = which==='over' ? _viewOver : _viewUnder;
  if(!b){ b=document.createElement('canvas');
          if(which==='over') _viewOver=b; else _viewUnder=b; }
  if(c && (b.width!==c.width || b.height!==c.height)){
    b.width=c.width; b.height=c.height;
  }
  b.getContext('2d').clearRect(0,0,b.width,b.height);
  return b;
}
function repaintAll(){
  const c=$('paint'); if(!c) return;
  replayIncomplete=false;
  const keep=pageLayers();
  const L=layersBuf();
  L.getContext('2d').clearRect(0,0,L.width,L.height);
  keep.filter(st=>!isOver(st)).forEach(st=>replayStroke(L,st));
  const B=overBuf();
  B.getContext('2d').clearRect(0,0,B.width,B.height);
  keep.filter(isOver).forEach(st=>replayStroke(B,st));
  compositeLive(null);
  repaintOver();
}
/* The two buffers as the SCREEN should show them. With nothing folded away —
   which is nearly always — that is the saved buffer itself and costs nothing. */
function underOnScreen(){
  if(!_folded()) return layersBuf();
  const S=_viewBuf('under');
  screenLayers().filter(st=>!isOver(st)).forEach(st=>replayStroke(S,st));
  return S;
}
function overOnScreen(){
  if(!_folded()) return overBuf();
  const S=_viewBuf('over');
  screenLayers().filter(isOver).forEach(st=>replayStroke(S,st));
  return S;
}
/* The band above the text. Its own canvas, so nothing about the ordinary
   paint path had to learn about it. */
function repaintOver(){
  const o=ensureOverCanvas(); if(!o) return;
  const g=o.getContext('2d');
  g.clearRect(0,0,o.width,o.height);
  if(!screenLayers().some(isOver)) return;
  g.drawImage(overOnScreen(),0,0);
}
let overCanvasBuf=null;
function overBuf(){
  const c=$('paint');
  if(!overCanvasBuf) overCanvasBuf=document.createElement('canvas');
  if(c && (overCanvasBuf.width!==c.width||overCanvasBuf.height!==c.height)){
    overCanvasBuf.width=c.width; overCanvasBuf.height=c.height;
  }
  return overCanvasBuf;
}
/* Move a layer across the Text divider, and put it at the near edge of the
   band it lands in so the list order matches what you just did. */
function setLayerOver(id, on){
  const l=_layer(id); if(!l) return;
  if(!!l.over===!!on) return;
  l.over=!!on;
  layers.splice(layers.indexOf(l),1);
  // The array is the stack, bottom first, and the two bands do not interleave:
  // everything over the text lives at the END of it. So the divider in the
  // list is simply where the first `over` layer starts, and a layer crossing
  // it lands at the near edge of the band it joins.
  const firstOver=layers.findIndex(isOver);
  const edge = firstOver<0 ? layers.length : firstOver;
  if(on) layers.splice(edge, 0, l);      // bottom of the over band
  else   layers.splice(edge, 0, l);      // top of the under band — same index
  record('paint', `${layerName(l)} moved ${on?'above':'below'} the text`, null);
  repaintAll(); renderLayers(); queueSync();
}

/* ---- the healing brush ----
   The marked spot plus a margin of context goes to the server, which sends
   it to the AI cleaner and hands the patch back. The patch becomes an
   ordinary layer: undoable, hideable, kept with the rest. */
async function finalizeHeal(st){
  try{
    const c=$('paint');
    const xs=st.pts.map(p=>p.x), ys=st.pts.map(p=>p.y);
    // Context margin: 96px, matching what the Clean step hands the cleaner
    // (inpaint.NEURAL_CTX). A model can only continue artwork it can SEE, and
    // a thin collar is not enough.
    const M=Math.ceil(st.sz/2)+96;
    const x0=Math.max(0,Math.floor(Math.min(...xs)-M));
    const y0=Math.max(0,Math.floor(Math.min(...ys)-M));
    const x1=Math.min(c.width, Math.ceil(Math.max(...xs)+M));
    const y1=Math.min(c.height,Math.ceil(Math.max(...ys)+M));
    const w=x1-x0, h=y1-y0;
    if(w<4||h<4){ repaintAll(); return; }
    // the page as it currently looks, without the blue marking
    const rc=document.createElement('canvas'); rc.width=w; rc.height=h;
    const rg=rc.getContext('2d');
    rg.drawImage($('img'), x0,y0,w,h, 0,0,w,h);
    rg.drawImage(layersBuf(), x0,y0,w,h, 0,0,w,h);
    // the marked spot, as a black/white mask
    const mc=document.createElement('canvas'); mc.width=w; mc.height=h;
    const mg=mc.getContext('2d');
    mg.fillStyle='#000'; mg.fillRect(0,0,w,h);
    mg.save(); mg.translate(-x0,-y0);
    const white={sz:st.sz, hard:1, col:'#ffffff', pts:st.pts};
    if(st.pts.length===1) tipSeg(mg,white,st.pts[0],st.pts[0]);
    for(let i=1;i<st.pts.length;i++) tipSeg(mg,white,st.pts[i-1],st.pts[i]);
    mg.restore();
    // an active selection fences the heal in, like every other tool
    if(typeof selClipHealMask==='function') selClipHealMask(mc,x0,y0);
    repaintAll();                                  // marking overlay off
    toast('Healing with the AI cleaner\u2026', 1500);
    const j=await api(`/api/page/${cur}/heal`,'POST',
      {image:rc.toDataURL('image/png'), mask:mc.toDataURL('image/png')});
    if(j.error){ toast('Heal failed: '+j.error); return; }
    if(!j.patch){ toast('Heal failed: empty reply from the server.'); return; }
    const im=new Image();
    im.onload=()=>{
      layers.push({id:st.id, type:'patch', col:'#57b0ff', sz:st.sz,
                   group:'retouch', label:'Heal',
                   x:x0, y:y0, png:j.patch, img:im, pts:st.pts, visible:true});
      layerSel=st.id;
      record('paint', `Healed spot ${st.id}`, undoPaintLast);
      toast('Healed with the AI cleaner.', 2400);
      repaintAll(); renderLayers();
      queueSync();                   // healed means kept, automatically
    };
    im.onerror=()=>toast('Heal failed: the patch image would not load.');
    im.src=j.patch;
  }catch(err){
    toast('Heal failed: '+err.message);
    repaintAll();
  }
}

function undoPaintLast(){ if(!layers.length) return;
  layers.pop(); layerSel=null; repaintAll(); renderLayers(); queueSync(); }
function undoStroke(){
  if(!layers.length) return;
  record('paint-undo', 'Brush stroke removed', null);
  undoPaintLast();
}
/* A locked layer is left alone: it cannot be restacked, deleted, picked up by
   the transform, or recoloured. The eye still works — hiding something is not
   changing it — and the lock itself is one click away.

   Only the page had one, which is the one layer nobody was going to move by
   accident. lee: *"allow me to lock other layers"*. */
function toggleLayerLock(id){
  const l=layers.find(x=>x.id===id); if(!l) return;
  l.locked=!l.locked;
  if(l.locked && layerSel===id) layerSel=null;
  renderLayers(); queueSync();
}
function layerLocked(id){
  const l=layers.find(x=>x.id===id);
  return !!(l && l.locked);
}
function toggleTextLock(id){
  const r=regions.find(x=>x.id===id); if(!r) return;
  r.locked=!r.locked;
  renderLayers();
  upd(id, {locked: !!r.locked});
}

function deleteLayer(id){
  if(layerLocked(id)) return;                 // locked: left alone
  layers=layers.filter(l=>l.id!==id);
  if(layerSel===id) layerSel=null;
  record('layer-del', `Brush stroke ${id} deleted`, null);
  repaintAll(); renderLayers(); queueSync();
}
function toggleLayer(id){
  const l=layers.find(x=>x.id===id); if(!l) return;
  l.visible=!(l.visible!==false);
  repaintAll(); renderLayers(); queueSync();
}
function selectLayer(id){ layerSel=id; renderLayers(); }

/* ---- layers panel, Photoshop-style ----
   Top of the list = top of the stack. Drag a row to restack (the composite
   follows the order), the eye hides, × deletes, and the selected layer gets
   an opacity slider. Thumbnails are drawn from the layer's own pixels. */
const SHAPE_NAMES={rect:'Rectangle', circle:'Ellipse', line:'Line'};
function layerName(l){
  return `${l.label||(l.type==='erase'?'Eraser'
                     :l.type==='shape'?(SHAPE_NAMES[l.shape]||'Shape')
                     :l.type==='patch'?'Patch':'Stroke')} ${l.id}`;
}
function layerThumb(l){
  const s=22, c=document.createElement('canvas'); c.width=c.height=s;
  const g=c.getContext('2d');
  if(l.type==='shape'){
    g.strokeStyle=l.col; g.fillStyle=l.col; g.lineWidth=2;
    g.beginPath();
    if(l.shape==='line'){ g.moveTo(4,s-4); g.lineTo(s-4,4); g.stroke(); }
    else if(l.shape==='circle'){
      g.ellipse(s/2,s/2,s/2-4,s/2-5,0,0,Math.PI*2);
      if(l.fill) g.fill(); else g.stroke();
    } else {
      g.rect(4,5,s-8,s-10);
      if(l.fill) g.fill(); else g.stroke();
    }
    return c.toDataURL('image/png');
  }
  if(l.type==='erase'){                       // checkerboard = transparency
    g.fillStyle='#3a4150';
    for(let y=0;y<4;y++) for(let x=0;x<4;x++)
      if((x+y)%2===0) g.fillRect(x*s/4,y*s/4,s/4,s/4);
    g.strokeStyle='#e07a7a'; g.lineWidth=2;
    g.beginPath(); g.moveTo(4,s-4); g.lineTo(s-4,4); g.stroke();
  } else if(l.type==='patch' && l.img){
    const w=l.img.naturalWidth||l.img.width||1,
          h=l.img.naturalHeight||l.img.height||1;
    const k=Math.min(s/w, s/h);
    g.fillStyle='#fff'; g.fillRect(0,0,s,s);
    g.drawImage(l.img, (s-w*k)/2,(s-h*k)/2, Math.max(1,w*k),Math.max(1,h*k));
  } else {
    g.fillStyle=l.col||'#8a8f98';
    g.beginPath(); g.arc(s/2,s/2,s/2-3,0,7); g.fill();
  }
  return c.toDataURL();
}
/* ---- restacking by dragging the row ----

   HTML5 drag-and-drop was the only way, and it is the fiddliest input the
   browser has: the row has an <img> in it, which the browser would rather
   drag by itself; it fights the scroll; and on a trackpad it often just does
   not start. So it is done with plain pointer events, which always work.
   lee: *"i sjoud also be anble to ... clci ad drag up and doen teh list and
   remove the un and down arrow to move them"*.

   A press that never moves is a CLICK — it selects the layer. Four pixels of
   travel is what turns it into a drag, so a slightly unsteady click still
   selects instead of silently restacking something. */
/* A text row in the list. A plain click opens the typesetting panel, which
   REPLACES this list — so a press-and-drag on one used to swap the panel out
   from under the drag before it had gone anywhere. lee: *"i shoud be able to
   click and hold the text layer wiythout going into the text edit tab"*.

   Same bargain as a paint row: the panel only changes when the press turns
   out to have been a click. */
let textDrag=null;
function textRowDown(e,id){
  if(e.button!==0) return;
  if(e.target.closest && e.target.closest('.lx,input,button,.llock')) return;
  const rr=regions.find(x=>x.id===id);
  if(rr && rr.locked) return;                 // locked: not restacked
  textDrag={id, y0:e.clientY, moved:false, ev:e};
  document.addEventListener('mousemove', textRowMove, true);
  document.addEventListener('mouseup', textRowUp, true);
}
function textRowMove(e){
  if(!textDrag) return;
  if(!textDrag.moved){
    if(Math.abs(e.clientY-textDrag.y0)<4) return;
    textDrag.moved=true;
    document.body.classList.add('laydragging');
  }
  e.preventDefault();
  markDrag(textDrag.id, false);
  if(typeof textRowDragTo==='function') textRowDragTo(e, textDrag.id);
}
/* Dragging a text row moves it through the READING ORDER — the numbers on the
   page and the order the translator sees. Text and drawings live in two bands
   that do not interleave, so a text row cannot be dragged among the drawings;
   what it can do is change where it comes in the script, which is the thing
   the numbers on the page are for. */
function textRowDragTo(e,id){
  const rows=[...document.querySelectorAll('#stackList .lay[data-tid]')];
  const row=rows.find(r=>{
    const b=r.getBoundingClientRect();
    return e.clientY>=b.top && e.clientY<=b.bottom;
  });
  if(!row) return;
  const overId=+row.getAttribute('data-tid');
  if(overId===id) return;
  const a=regions.find(r=>r.id===id), b=regions.find(r=>r.id===overId);
  if(!a||!b) return;
  textDrag.to=(b.order??0);
  // move it in the list as you drag, so what you see is where it will land
  const from=(a.order??0), to=(b.order??0);
  regions.forEach(r=>{
    if(r.id===id) return;
    const o=r.order??0;
    if(from<to && o>from && o<=to) r.order=o-1;
    if(from>to && o>=to && o<from) r.order=o+1;
  });
  a.order=to;
  renderLayers(); drawBoxes(); drawOverlay();
  markDrag(id, false);              // the list was just rebuilt under it
}
function textRowDropped(id){
  const to=(regions.find(r=>r.id===id)||{}).order;
  if(to==null) return;
  if(typeof orderTo==='function') orderTo(id, to);
}

function textRowUp(e){
  document.removeEventListener('mousemove', textRowMove, true);
  document.removeEventListener('mouseup', textRowUp, true);
  document.body.classList.remove('laydragging');
  clearDragMarks();
  const d=textDrag; textDrag=null;
  if(!d) return;
  if(d.moved){
    // nothing to save unless the drag actually passed over another row
    if(d.to!=null && typeof textRowDropped==='function') textRowDropped(d.id);
  }else{
    select(d.id, d.ev);
  }
}

let layDrag=null;
function layDown(e,id){
  if(e.button!==0) return;
  // the eye and the × are buttons, not handles
  if(e.target.closest && e.target.closest('.lx,input,button,.llock')) return;
  if(layerLocked(id)) return;                 // locked: not picked up
  layDrag={id, y0:e.clientY, moved:false};
  document.addEventListener('mousemove', layDragMove, true);
  document.addEventListener('mouseup', layDragUp, true);
}
/* What a drag looks like while it is happening.

   lee: *"add a visula for when im moving layers"*. The list reorders live, so
   the row under the pointer already IS where the layer will land — what was
   missing was any sign that a row had been picked up at all, and any mark on
   the Text band when a drag is about to cross it and change which side of the
   typesetting the drawing is drawn on. Both are classes; the list rebuilds
   constantly during a drag, so they are re-applied after every rebuild rather
   than set once. */
function markDrag(id, crossing){
  document.querySelectorAll('#stackList .lay.dragging')
    .forEach(el=>el.classList.remove('dragging'));
  const band=document.querySelector('#stackList .textband');
  if(band) band.classList.toggle('crossing', !!crossing);
  if(id==null) return;
  const row=document.querySelector(`#stackList .lay[data-lid="${id}"]`)
         || document.querySelector(`#stackList .lay[data-tid="${id}"]`);
  if(row) row.classList.add('dragging');
}
function clearDragMarks(){
  markDrag(null, false);
}
function layDragMove(e){
  if(!layDrag) return;
  if(!layDrag.moved){
    if(Math.abs(e.clientY-layDrag.y0)<4) return;
    layDrag.moved=true;
    document.body.classList.add('laydragging');
  }
  e.preventDefault();
  const me=_layer(layDrag.id); if(!me) return;
  {
    const band=document.querySelector('#stackList .textband');
    const b=band && band.getBoundingClientRect();
    markDrag(layDrag.id, !!(b && b.height &&
             e.clientY>=b.top-6 && e.clientY<=b.bottom+6));
  }
  // Dragged across the Text block? That is the one thing in this list that
  // changes what the page LOOKS like rather than just the order of the
  // drawings, so it is checked first. lee: *"i shoud be able to ... move other
  // layers above the text folder"*.
  const band=document.querySelector('#stackList .textband');
  if(band){
    const b=band.getBoundingClientRect();
    if(b.height){
      const wantOver = e.clientY < (b.top+b.bottom)/2;
      if(wantOver!==isOver(me)){ setLayerOver(me.id, wantOver); return; }
    }
  }
  // ...otherwise an ordinary restack, and only against layers in the same
  // band: the array keeps the two bands apart and a splice across the
  // boundary would silently move a layer through the text.
  const rows=[...document.querySelectorAll('#stackList .lay[data-lid]')];
  const row=rows.find(r=>{
    const b=r.getBoundingClientRect();
    return e.clientY>=b.top && e.clientY<=b.bottom;
  });
  if(!row) return;
  const overId=+row.getAttribute('data-lid');
  if(overId===layDrag.id) return;
  const target=_layer(overId);
  if(!target || isOver(target)!==isOver(me)) return;
  const from=layers.findIndex(l=>l.id===layDrag.id);
  const to=layers.findIndex(l=>l.id===overId);
  if(from<0||to<0) return;
  const [moved]=layers.splice(from,1);
  layers.splice(to,0,moved);
  layerSel=layDrag.id;
  repaintAll(); renderLayers();
  markDrag(layDrag.id, false);      // the list was just rebuilt under it
}
function layDragUp(){
  document.removeEventListener('mousemove', layDragMove, true);
  document.removeEventListener('mouseup', layDragUp, true);
  document.body.classList.remove('laydragging');
  const d=layDrag; layDrag=null;
  clearDragMarks();
  if(!d) return;
  if(d.moved){
    const l=layers.find(x=>x.id===d.id);
    record('paint', `${l?layerName(l):'Layer'} restacked`, null);
    repaintAll(); renderLayers(); queueSync();
  }else{
    selectLayer(d.id);
  }
}

function layerOpacity(id,v,commit){
  const l=layers.find(x=>x.id===id); if(!l) return;
  l.op=Math.max(1,Math.min(100,+v||100))/100;
  const r=$('layOpR'), n=$('layOpN');
  if(r){ r.value=Math.round(l.op*100); sliderFill(r); }
  if(n) n.value=Math.round(l.op*100);
  repaintAll();
  if(commit){ record('paint', `${layerName(l)} opacity ${Math.round(l.op*100)}%`, null);
              queueSync(); }
}
/* ---- editing a layer after it is drawn ----
   A shape and a brush stroke both replay from what they are MADE of — two
   points or a path, a colour, a width — so all three can still be changed
   afterwards. lee: *"allwo chnage color"*. A patch cannot: it is pixels by
   then (a heal, a clone, a transformed selection), and there is no colour in
   it to change. `canRecolour` is the one place that knows which is which. */
function canRecolour(l){
  return !!l && (l.type==='shape' || l.type===undefined || l.type===null);
}
function _layer(id){ return layers.find(x=>x.id===id) || null; }
function setLayerColour(id, col, commit){
  const l=_layer(id); if(!l||!canRecolour(l)) return;
  l.col=col;
  const chip=$('layColChip'); if(chip) chip.style.background=col;
  const hex=$('layColHex'); if(hex) hex.textContent=col;
  repaintAll();
  if(commit){ record('paint', `${layerName(l)} recoloured`, null);
              renderLayers(); queueSync(); }
}
/* The colour popover writes through this instead of at the brush. Dragging
   round the wheel repaints live; the one history entry and the one save land
   when the popover closes, not on every pixel of the drag. */
function layerColourTarget(id){
  return {
    get: ()=>{ const l=_layer(id);
               return cssHex((l&&l.col)||'#ffffff', '#ffffff'); },
    set: hex=>setLayerColour(id, hex),
    done: ()=>{ const l=_layer(id);
                if(l){ record('paint', `${layerName(l)} recoloured`, null);
                       renderLayers(); queueSync(); } },
  };
}
function setLayerWidth(id, v, commit){
  const l=_layer(id); if(!l) return;
  l.sz=Math.max(1, Math.min(60, +v||1));
  const r=$('layWR'); if(r){ r.value=l.sz; sliderFill(r); }
  const n=$('layWN'); if(n) n.value=l.sz;
  repaintAll();
  if(commit){ record('paint', `${layerName(l)} width ${l.sz}`, null);
              renderLayers(); queueSync(); }
}
function setLayerFill(id, on){
  const l=_layer(id); if(!l||l.type!=='shape'||l.shape==='line') return;
  l.fill=!!on;
  record('paint', `${layerName(l)} ${l.fill?'filled':'outlined'}`, null);
  repaintAll(); renderLayers(); queueSync();
}
/* The move handles, from the layer list — the same thing the shape arrow
   does on the page, for people who found the shape in the list instead. */
function moveLayer(id){
  const l=_layer(id); if(!l) return;
  layerSel=id;
  if(typeof xf!=='undefined' && xf) xfCancel();
  // Name the layer. Without it the transform prefers a live selection, and
  // "move this layer" would pick up something else entirely.
  if(typeof xfStart==='function') xfStart(l);
}

function layerEditor(l){
  const isShape=l.type==='shape';
  const col=cssHex(l.col, '#ffffff');
  return `
    ${canRecolour(l)?`
    <div class="sl"><span>Colour</span>
      <span class="colwell" id="layWell" title="This layer's colour"
            onclick="openPicker(this, layerColourTarget(${l.id}))" style="flex:1">
        <i id="layColChip" style="background:${col}"></i>
        <b id="layColHex">${col}</b></span></div>`
    :`<p class="help" style="margin:2px 4px 6px">Healed, cloned and
        transformed layers are finished pixels — there is no colour left in
        them to change. Hide or delete it and draw again.</p>`}
    ${isShape?`
    <div class="sl"><span>${l.shape==='line'?'Thickness':'Line width'}</span>
      <input id="layWR" type="range" min="1" max="60" value="${l.sz||1}"
             oninput="setLayerWidth(${l.id},this.value)"
             onchange="setLayerWidth(${l.id},this.value,true)">
      <input id="layWN" type="number" min="1" max="60" value="${l.sz||1}"
             oninput="setLayerWidth(${l.id},this.value)"
             onchange="setLayerWidth(${l.id},this.value,true)"></div>`:''}
    <div class="row" style="margin:0 4px 8px;gap:6px;flex-wrap:wrap">
      ${isShape && l.shape!=='line'?`<button id="layFillBtn" class="${l.fill?'pri':''}"
         onclick="setLayerFill(${l.id},${!l.fill})"
         title="Solid instead of outlined">${l.fill?'Filled':'Outline'}</button>`:''}
      <button id="layMoveBtn" onclick="moveLayer(${l.id})"
              title="${isShape
                ? 'Transform'
                : 'Transform'}">
        Move &amp; resize</button>
      <button onclick="deleteLayer(${l.id})" class="danger">Delete</button>
    </div>`;
}

function layerRow(l){
  return `
    <div class="lay ${l.id===layerSel?'on':''}" data-lid="${l.id}"
         onmousedown="layDown(event,${l.id})"
         title="Drag to restack">
      <span class="lgrip" title="Drag to restack">&#8942;</span>
      <img class="lth" src="${layerThumb(l)}" alt="" draggable="false">
      <span class="lnm">${layerName(l)}</span>
      <span class="lx" title="${l.visible!==false?'Hide':'Show'}"
            onclick="event.stopPropagation();toggleLayer(${l.id})">${l.visible!==false?'&#128065;':'&#8709;'}</span>
      <span class="llock ${l.locked?'':'off'}"
            title="${l.locked?'Locked — click to unlock':'Lock this layer'}"
            onclick="event.stopPropagation();toggleLayerLock(${l.id})">${LOCK_SVG}</span>
      ${l.locked?'':`<span class="lx" title="Delete this layer"
            onclick="event.stopPropagation();deleteLayer(${l.id})">&times;</span>`}
    </div>
    ${l.id===layerSel?`
    <div class="sl" style="margin:2px 4px 8px">
      <span>Opacity</span>
      <input id="layOpR" type="range" min="1" max="100"
             value="${Math.round((l.op==null?1:l.op)*100)}"
             oninput="layerOpacity(${l.id},this.value)"
             onchange="layerOpacity(${l.id},this.value,true)">
      <input id="layOpN" type="number" min="1" max="100"
             value="${Math.round((l.op==null?1:l.op)*100)}"
             oninput="layerOpacity(${l.id},this.value)"
             onchange="layerOpacity(${l.id},this.value,true)">
    </div>
    ${layerEditor(l)}`:''}`;
}
/* The document stack: what sits above what on the page — text on top, the
   drawing above the page itself. Clone/heal retouching lives in its own
   fold below, not in this stack. */
let pageLocked=true, pageVisible=true;
function togglePageLock(){
  pageLocked=!pageLocked;
  if(pageLocked && !pageVisible) togglePageEye();   // locking restores it
  else renderLayers();
}
function togglePageEye(){
  pageVisible=!pageVisible;
  const im=$('img'); if(im) im.style.visibility=pageVisible?'':'hidden';
  renderLayers();
}
function toggleTextLayer(id){
  const r=regions.find(x=>x.id===id); if(!r) return;
  r._hideText=!r._hideText;
  drawOverlay(); renderLayers();
}
/* Turn a text block into a picture: the same line art as everywhere else, a
   T with a frame round it. */
const RASTER_SVG=`<svg viewBox="0 0 24 24" width="12" height="12"
  fill="none" stroke="currentColor" stroke-width="1.9"
  stroke-linecap="round" stroke-linejoin="round"><path
  d="M3.5 4.5h17v15h-17zM7.5 8.5h9M12 8.5v7"/></svg>`;

/* The block's typesetting, as an ordinary image layer.

   The words stop being words: what lands in the paint stack is a picture of
   them exactly as they were set — font, colour, outline, glow, gradient,
   rotation and all — and the text box is emptied, so nothing is drawn twice.
   lee: *"allow me to turn text layer into image layers"*.

   The picture is made by the SERVER, by the same renderer that writes the
   exported page, so what you get is what would have been printed rather than
   the browser's approximation of it. */
async function textToImage(id){
  const r=regions.find(x=>x.id===id);
  if(!r || !r.layout || !(r.layout.lines||[]).length) return;
  const j=await api(`/api/page/${cur}/region/${id}/rasterise`,'POST',{});
  if(!j || j.error){ toast(j&&j.error ? j.error : 'Could not draw it.'); return; }
  const im=new Image();
  const st={id:layerSeq++, type:'patch', label:('Text — '+(j.name||'')).trim(),
            group:'drawing', col:'#c9a2ff', sz:0,
            x:j.x, y:j.y, png:j.png, img:null, op:1, pts:[], visible:true};
  im.onload=()=>{ st.img=im; repaintAll(); renderLayers(); };
  im.src=j.png;
  // What it takes to put this back: the words, and whether the block was
  // locked before. One step, both halves — Ctrl+Z on a conversion has to
  // undo the WHOLE conversion, not leave the picture and the empty box.
  // lee: *"tuening a text to an image shoud be reversable with control + z"*.
  const wasLines=((r.layout&&r.layout.lines)||[]).slice();
  const wasLocked=!!r.locked;
  layers.push(st); layerSel=st.id;
  record('paint', `${layerName(st)} from text`, ()=>{
    layers=layers.filter(l=>l!==st);
    if(layerSel===st.id) layerSel=null;
    const rr=regions.find(x=>x.id===id);
    if(rr && rr.locked!==wasLocked) rr.locked=wasLocked;
    setTypesetLines(id, wasLines);
    repaintAll(); renderLayers(); queueSync();
  });
  // …and the words go, or the page carries both — and the block is LOCKED,
  // because it is a picture now. lee: *"when i chanhge text to an image it
  // shoud be trated as an image, no more modifying teh text"*. Unlocking it
  // is one click if the picture turns out to be wrong.
  setTypesetLines(id, []);
  if(!r.locked) toggleTextLock(id);
  renderLayers(); queueSync();
}

const LOCK_SVG=`<svg viewBox="0 0 24 24" width="12" height="12">
  <path fill="currentColor" d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0
    0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5Zm-3 8V7a3 3
    0 1 1 6 0v3H9Z"/></svg>`;
function textLayerName(r){
  const t=(r.dst_text||'').trim().replace(/\s+/g,' ');
  const esc=s=>s.replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
  return t ? esc(t.length>20?t.slice(0,20)+'…':t) : `Text ${(r.order??0)+1}`;
}
/* ONE list, the way an image editor shows a document: text on top, then
   every paint layer in stack order, then the artwork at the bottom.

   It used to be three — a "page stack" that only named the groups, a
   "Strokes" fold and a "Retouch" fold — so the thing you had just drawn was
   never in the list you were looking at, and nothing said what sat above
   what. lee: *"layers shoud be one compabined layer"*.

   Healing and cloning patches are in it too. They were folded away because a
   heavily retouched page makes a long list; a long list you can scroll is
   better than a layer you cannot find. */
/* Is the Text block folded away? A page with twenty bubbles puts twenty rows
   between the drawings above the typesetting and the drawings below it, and the
   two ends of the stack cannot be seen at once. Folding it does not hide the
   text on the page — the eye beside it still does that — and the band itself
   stays in the list, because it is what a layer is dragged across to move
   from one side of the typesetting to the other. */
let textShut=true;
function toggleTextFold(){ textShut=!textShut; renderLayers(); }
function renderStack(){
  const el=$('stackList'); if(!el) return;
  const textOn = !$('showText') || $('showText').checked;
  const texts=(typeof regions!=='undefined'?regions:[])
    // A block emptied on purpose stays in the list — it is still a text
    // layer, and taking it out of the list is how you lose track of it.
    .filter(r=>r.layout&&r.layout.lines)
    .slice().sort((a,b)=>(a.order??0)-(b.order??0));
  const over=layers.filter(isOver), under=layers.filter(l=>!isOver(l));
  el.innerHTML=`
    ${over.slice().reverse().map(layerRow).join('')}
    <div class="textband${textShut?' shut':''}">
    <div class="lay stackrow" onclick="toggleTextFold()"
         style="cursor:pointer">
      <span class="lcar${textShut?' shut':''}">&#9662;</span>
      <span class="lth-glyph">T</span>
      <span class="lnm">Text${texts.length?` (${texts.length})`:''}</span>
      <span class="lx" title="${textOn?'Hide all text':'Show the text'}"
            onclick="event.stopPropagation();const c=$('showText');
                     if(c){c.checked=!c.checked;onShowText();}renderLayers();">
        ${textOn?'&#128065;':'&#8709;'}</span>
    </div>
    ${texts.map(r=>`
    <div class="lay textrow ${typeof sel!=='undefined'&&sel===r.id?'on':''}"
         data-tid="${r.id}" onmousedown="textRowDown(event,${r.id})"
         title="Drag to reorder">
      <span class="lgrip" title="Drag to restack">&#8942;</span>
      <span class="lnm">${textLayerName(r)}</span>
      <span class="lx" title="Turn this text into an image layer"
            onclick="event.stopPropagation();textToImage(${r.id})">${RASTER_SVG}</span>
      <span class="lx" title="${r._hideText?'Show this text box':'Hide this text box'}"
            onclick="event.stopPropagation();toggleTextLayer(${r.id})">
        ${r._hideText?'&#8709;':'&#128065;'}</span>
      <span class="llock ${r.locked?'':'off'}"
            title="${r.locked?'Locked — click to unlock':'Lock this text box'}"
            onclick="event.stopPropagation();toggleTextLock(${r.id})">${LOCK_SVG}</span>
    </div>`).join('')}
    </div>
    ${under.length
      ? under.slice().reverse().map(layerRow).join('')
      : (layers.length?'':'<p class="help" style="margin:4px 0 6px">Nothing painted yet.</p>')}
    <div class="lay stackrow">
      <img class="lth" src="${$('img')&&$('img').src?$('img').src:''}" alt="">
      <span class="lnm">Page</span>
      ${pageLocked?'':`<span class="lx" title="${pageVisible?'Hide the artwork':'Show the artwork'}"
            onclick="event.stopPropagation();togglePageEye()">
        ${pageVisible?'&#128065;':'&#8709;'}</span>`}
      <span class="llock ${pageLocked?'':'off'}"
            title="${pageLocked ? 'Locked' : 'Unlocked'}"
            onclick="event.stopPropagation();togglePageLock()">${LOCK_SVG}</span>
    </div>`;
}
function renderLayers(){
  renderStack();
  // The Shapes section keeps its own list of the shapes on the page. Drawing
  // one does not rebuild the whole panel — that would throw away whatever
  // control was being used — so the list is refreshed here, where every
  // change to `layers` already ends up.
  const sl=$('shapeListBox');
  if(sl && typeof shapeList==='function') sl.innerHTML=shapeList();
  const r=$('layOpR'); if(r) sliderFill(r);
}
/* The eyedroppers must taste the page, not the translated text drawn on
   top of it — the overlay ducks out for the moment of the pick. */
function hideTextForPick(){
  const els=[$('overlay'),$('tframe'),$('canvasEdit')].filter(Boolean);
  const saved=els.map(el=>el.style.visibility);
  els.forEach(el=>el.style.visibility='hidden');
  return ()=>els.forEach((el,k)=>el.style.visibility=saved[k]||'');
}
