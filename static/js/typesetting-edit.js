/* typesetting-edit.js — Live typesetting preview while typing, style edits, gradient/shadow clears, rotation.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */
/* ---------------- live typesetting overlay ----------------
   The browser draws the text itself over the CLEANED page. The server only
   supplies line positions, which costs about 9ms — so edits show up as you
   make them instead of waiting on a full page re-render.               */
let fontsReady=false;
function ensureFonts(){
  if(fontsReady) return;
  fontsReady=true;
  // One @font-face per kind that can carry a face of its own: the three main
  // types, and every sub-type somebody has made.
  const css=KIND_FAMILIES.concat(subTypes().map(k=>k.key)).map(k=>
    `@font-face{font-family:'ml-${k}';src:url('/font/${k}');font-display:swap}`
  ).join('');
  const el=document.createElement('style'); el.textContent=css;
  document.head.appendChild(el);
}

/* There used to be two text renderers and they disagreed: this one knew
   nothing about frames or rotation, so every live update flattened the text
   back into its bubble. There is now one. */
function drawOverlay(){ drawText(); }

let previewTimer=null;
/* Preview and save replies can come back out of order (the server is
   threaded); only the newest edit gets to paint. */
let editSeq=0;
/* Bumped by every EDIT, not by every request.

   `editSeq` was bumped where the request goes out, so a reply was only
   discarded when a newer request had already been sent — and typing between
   "sent" and "received" does not send anything. The reply for the press
   before last was then accepted as current, and it overwrites the whole
   layout: the size and the line breaks. So the page took the smaller size
   while the field still showed the bigger one, and words came back that had
   already been typed over.

   lee: *"something i make the text big it randonly becomes smalle while teh
   text box remain big"* and *"sometime the text just revert back why im
   eddit it"*. It reads as random because a preview is normally about nine
   milliseconds — but the first one after any save has to rebuild the page,
   which can take seconds, and that is the window.

   `editTick` is the truth: it moves the moment a key is pressed. A reply that
   was asked for before the last keystroke is stale by definition, however
   fast it came back. */
let editTick=0;
function noteTypesetEdit(){ editTick++; }

function livePreview(id, patch, immediate){
  const ticket=pageTicket;
  const asked=editTick;
  clearTimeout(previewTimer);
  const go=async()=>{
    const r=regions.find(x=>x.id===id); if(!r) return;
    const my=++editSeq;
    const j=await api(`/api/page/${cur}/layout_preview`,'POST',
      {region_id:id, layout:patch});
    if(j.error) return;
    if(asked!==editTick) return;             // typed since this was asked for
    // Keep the frame and rotation. Dropping them here is what made a moved
    // block spring back to its bubble the moment you let go.
    if(ticket!==pageTicket) return;          // page changed under us
    if(my!==editSeq) return;                 // a newer edit is in flight
    r.layout={lines:j.lines, font_size:j.font_size, leading:j.leading,
              origins:j.origins, fit_ok:j.fit_ok,
              frame:(j.frame&&j.frame.length===4) ? j.frame
                    : (r.layout&&r.layout.frame) || null,
              rotate:(j.rotate!==undefined) ? j.rotate
                    : ((r.layout&&r.layout.rotate)||0),
              // A speech divided between the lobes of a double balloon is two
              // blocks in one box, so its line positions are the layout and
              // must not be re-derived from the box. Dropping this flag here
              // is all it would take for the second half to slide back into
              // the waist the moment the block was touched.
              fixed:!!j.fixed};
    r.style={fg:j.fg,edge:j.edge,stroke:j.stroke,font:j.font,
             lspace:+(j.lspace||0),
             shadow:j.shadow||'',sh_dist:+(j.sh_dist??2),sh_blur:+(j.sh_blur??3),
             curve:+(j.curve||0),
             glow:j.glow||'',glow_size:+(j.glow_size??6),
             iglow:j.iglow||'',iglow_size:+(j.iglow_size??5),
             opacity:+(j.opacity??100),
             fg1:j.fg1||'',fg2:j.fg2||'',grad_angle:+(j.grad_angle||0),
             edge1:j.edge1||'',edge2:j.edge2||'',
             edge_angle:+(j.edge_angle||0)};
    r.kind=j.kind||r.kind;
    // When the box reshaped the text, the panel must say what the page says —
    // same breaks, same size. (Left alone if you are typing in the field.)
    if(patch.fit||patch.wrap){
      const la=$('lyLines');
      if(la&&document.activeElement!==la) la.value=(j.lines||[]).join('\n');
      const sz=$('lySize');
      if(sz&&document.activeElement!==sz&&j.font_size) sz.value=j.font_size;
    }
    // If the block is being typed into on the canvas, the editor is what is
    // visible — resize it too, or size changes look like they did nothing.
    if(editing===id && editBox) placeEditor(editBox, r);
    drawOverlay();
  };
  if(immediate) go(); else previewTimer=setTimeout(go,90);
}

/* What is in the line box right now, line for line.

   No trimming and no dropping of blanks: a blank line is a paragraph break
   somebody typed, a leading space is an indent, and an empty box is a box
   somebody emptied. Trailing blank lines go, because those are only where the
   cursor was left. */
function lyLinesNow(){
  const el=$('lyLines'); if(!el) return [];
  const ls=el.value.split('\n');
  while(ls.length && !ls[ls.length-1].trim()) ls.pop();
  return ls;
}
/* Set a block's lines from code, the way typing into the box would.

   Used by anything that changes the words without a keystroke — turning a
   text layer into a picture, for one, which has to leave the box empty or the
   page carries the typesetting twice. */
function setTypesetLines(id, lines){
  const el=$('lyLines');
  const r0=regions.find(x=>x.id===id);
  // A locked block is not typed into, but it can still be SET — putting the
  // words back after undoing a conversion to an image is not an edit anybody
  // is making by hand.
  if(el && !(r0 && r0.locked) && (typeof sel==='undefined' || sel===id)){
    el.value=(lines||[]).join('\n');
    onTypesetEdit(id);
    flushTypesetEdit();
    return;
  }
  // The panel is showing some other block, so go straight to the record.
  const r=regions.find(x=>x.id===id); if(!r) return;
  noteTypesetEdit();
  if(r.layout) r.layout.lines=(lines||[]).slice();
  const ov=Object.assign({}, r.layout_override||{},
                         {lines:(lines||[]).slice(), locked:true});
  r.layout_override=ov;
  drawOverlay();
  api(`/api/page/${cur}/region/${id}`,'POST',{layout:ov})
    .then(j=>{ if(j&&j.regions) setRegions(j.regions); });
}

/* Is the Typesetting panel even about THIS block?

   `currentPatch` builds a save out of the panel's fields, which is right when
   the panel is showing the block being saved and wrong when it is not: it
   posts one block's size and line breaks onto another. The panel is only ever
   built for the SELECTED block, so that is the whole of the question.

   The other half of keeping these two in step is in frames.js: a drag that
   re-fits the text writes the answer onto the layout, and
   `panelSaysWhatTheLayoutSays` puts it into the panel at the same moment. Both
   are needed. Without the sync the panel is behind and posts a stale size back
   over the dragged one; without this guard the panel is about somebody else
   entirely. */
function panelIsAbout(r){
  return typeof sel==='undefined' || sel===null || sel===r.id;
}

function currentPatch(r){
  const ov=r.layout_override||{};
  const L=r.layout||{};
  const mine=panelIsAbout(r);
  const el=(id)=>mine ? $(id) : null;
  return {align:el('lyAlign')?$('lyAlign').value:(ov.align||'center'),
          caps:el('lyCaps')?!!$('lyCaps').checked:!!ov.caps,
          lines:(el('lyLines')?lyLinesNow():(L.lines||[])),
          font_size:el('lySize')?+$('lySize').value:(L.font_size||14),
          dx:+ov.dx||0,          // set by dragging the text, not by a field
          dy:+ov.dy||0,
          rotate:el('lyRot')?+$('lyRot').value:(+ov.rotate||0),
          font:el('lyFont')?$('lyFont').value:(ov.font||''),
          fg:el('lyFg')?$('lyFg').value:(ov.fg||''),
          edge:el('lyEdge')?$('lyEdge').value:(ov.edge||''),
          fg1:el('lyFg1')?$('lyFg1').value:(ov.fg1||''),
          fg2:el('lyFg2')?$('lyFg2').value:(ov.fg2||''),
          grad_angle:el('lyGrad')?+$('lyGrad').value||0:(+ov.grad_angle||0),
          edge1:el('lyEdge1')?$('lyEdge1').value:(ov.edge1||''),
          edge2:el('lyEdge2')?$('lyEdge2').value:(ov.edge2||''),
          edge_angle:el('lyEdgeG')?+$('lyEdgeG').value||0:(+ov.edge_angle||0),
          shadow:el('lySh')?$('lySh').value:(ov.shadow||''),
          sh_dist:el('lyShD')?+$('lyShD').value||0:(+ov.sh_dist||2),
          sh_blur:el('lyShB')?+$('lyShB').value||0:(+ov.sh_blur||3),
          curve:el('lyCurve')?+$('lyCurve').value||0:(+ov.curve||0),
          glow:el('lyGlow')?$('lyGlow').value:(ov.glow||''),
          glow_size:el('lyGlowS')?+$('lyGlowS').value||0:(+ov.glow_size||6),
          iglow:el('lyIGlow')?$('lyIGlow').value:(ov.iglow||''),
          iglow_size:el('lyIGlowS')?+$('lyIGlowS').value||0:(+ov.iglow_size||5),
          // 0 is a real answer here — a fully transparent block — so this one
          // cannot be written with `||`.
          opacity:($('lyOpacity') ? Math.max(0,Math.min(100,+$('lyOpacity').value||0))
                                  : (ov.opacity ?? 100)),
          // Falls back to the layout's own leading, not to 1.12: the panel is
          // only built in the typeset view, so saving from anywhere else used
          // to reset the line spacing to the default.
          leading:el('lyLead')?+$('lyLead').value||1.12
                            :(+ov.leading||(r.layout&&r.layout.leading)||undefined),
          lspace:el('lyLspace')?+$('lyLspace').value||0:(+ov.lspace||0),
          // ONLY a frame the person actually dragged. Echoing back the frame
          // the server just computed turned every save into a hand placement,
          // and the dx/dy baked into it were then added a second time — so
          // the block crept by one nudge on every click.
          frame:ov.frame||null,
          // Two blocks in one box keep their own line positions: send them
          // back so the server rebuilds what is on screen rather than
          // spacing everything evenly down the box.
          fixed:!!(r.layout&&r.layout.fixed),
          origins:(r.layout&&r.layout.fixed&&r.layout.origins
                   &&r.layout.origins.length===((r.layout.lines||[]).length))
                  ? r.layout.origins.map(o=>[Math.round(o[0]),
                                             Math.round(o[1])]) : null,
          stroke:el('lyStroke')?+$('lyStroke').value:(ov.stroke??null)};
}

function onTypesetEdit(id){
  noteTypesetEdit();
  const r=regions.find(x=>x.id===id); if(!r) return;
  // Colours and the outline are drawn by the browser, so show them the
  // instant they change instead of waiting on the server round trip.
  if(r.layout){
    // Everything typed goes into the region AT ONCE, before any request is
    // made. The panel is rebuilt on all sorts of things — a save landing, a
    // poll, a stepper being released — and it is built from the region, so
    // anything not written down here is a field that snaps back to the last
    // answer the server gave while the new one is still in flight. That is
    // the "it reverts back" lee kept seeing, and with a stepper it swallowed
    // every other press.
    if($('lyLead')) r.layout.leading=+$('lyLead').value
      || (typeof MIN_LEADING!=='undefined' ? MIN_LEADING : 1.2);
    if($('lySize')) r.layout.font_size=+$('lySize').value||r.layout.font_size;
    if($('lyRot'))  r.layout.rotate=+$('lyRot').value||0;
    // ALL CAPS shows AT ONCE. It is a change to what the letters look like,
    // not to what the fitter decides, so waiting on the round trip to see it
    // was waiting for nothing — and the first preview after any save rebuilds
    // the page cache, which can take seconds. lee: *"the all caps either take
    // a long time or dosn't work"*. The server does the same thing to the
    // same lines; this only stops the screen lagging behind the switch.
    const _caps=$('lyCaps') ? !!$('lyCaps').checked : false;
    if(_caps && r.layout.lines)
      r.layout.lines=r.layout.lines.map(x=>String(x).toUpperCase());
    if($('lyLines')){
      // Every line as typed — blanks and leading spaces included, and an
      // empty box accepted. They used to be trimmed and dropped, so a blank
      // line between two paragraphs could not be typed and clearing the box
      // did nothing at all. lee: *"allow the text bx to acces line breaks
      // without text and empty space just like photoshop"* and *"if i dlete
      // all teh text from a text box its shoud accesp the edit"*.
      r.layout.lines=lyLinesNow();
      if(_caps) r.layout.lines=r.layout.lines.map(x=>String(x).toUpperCase());
    }
    r.layout.dirty=true;               // line positions follow immediately
  }
  r.style=Object.assign({}, r.style, {
    align:$('lyAlign')?$('lyAlign').value:((r.style&&r.style.align)||'center'),
    caps:$('lyCaps')?$('lyCaps').checked:!!(r.style&&r.style.caps),
    lspace:$('lyLspace')?(+$('lyLspace').value||0)
          :((r.style&&r.style.lspace)||0),
    fg:$('lyFg')?$('lyFg').value:(r.style&&r.style.fg),
    edge:$('lyEdge')?$('lyEdge').value:(r.style&&r.style.edge),
    stroke:$('lyStroke')?+$('lyStroke').value:(r.style&&r.style.stroke),
    fg1:$('lyFg1')?$('lyFg1').value:(r.style&&r.style.fg1)||'',
    fg2:$('lyFg2')?$('lyFg2').value:(r.style&&r.style.fg2)||'',
    grad_angle:$('lyGrad')?(+$('lyGrad').value||0):((r.style&&r.style.grad_angle)||0),
    edge1:$('lyEdge1')?$('lyEdge1').value:(r.style&&r.style.edge1)||'',
    edge2:$('lyEdge2')?$('lyEdge2').value:(r.style&&r.style.edge2)||'',
    edge_angle:$('lyEdgeG')?(+$('lyEdgeG').value||0):((r.style&&r.style.edge_angle)||0),
    shadow:$('lySh')?$('lySh').value:(r.style&&r.style.shadow)||'',
    sh_dist:$('lyShD')?(+$('lyShD').value||0):((r.style&&r.style.sh_dist)??2),
    sh_blur:$('lyShB')?(+$('lyShB').value||0):((r.style&&r.style.sh_blur)??3),
    curve:$('lyCurve')?(+$('lyCurve').value||0):((r.style&&r.style.curve)||0),
    glow:$('lyGlow')?$('lyGlow').value:(r.style&&r.style.glow)||'',
    glow_size:$('lyGlowS')?(+$('lyGlowS').value||0):((r.style&&r.style.glow_size)??6),
    iglow:$('lyIGlow')?$('lyIGlow').value:(r.style&&r.style.iglow)||'',
    iglow_size:$('lyIGlowS')?(+$('lyIGlowS').value||0):((r.style&&r.style.iglow_size)??5),
    opacity:$('lyOpacity')?Math.max(0,Math.min(100,+$('lyOpacity').value||0))
                          :((r.style&&r.style.opacity)??100)});
  drawOverlay();
  livePreview(id, currentPatch(r));
  typesetDirty = id;          // there is now a change that has not been saved
}

/* Everything typed into the typesetting panel is only PREVIEWED as you type —
   the page redraws, but nothing is written down. The style fields used to be
   the only ones that then saved themselves, after a pause; the text, the size
   and the rotation were saved by "Keep this" and by nothing else. So typing a
   new line and clicking away lost it, and because the preview had already
   redrawn the page it looked as though it had gone in and then come back out.
   lee: *"sometime when i update someything loike teh text or ouline and clcik
   off it it reverts back to what it was before"*.

   One dirty flag, flushed from three places: when a field is finished with
   (`change`, which fires on blur), when the pause runs out, and before the
   panel is rebuilt for any reason at all. */
let typesetDirty = null;

function flushTypesetEdit(){
  const id = typesetDirty;
  if(id == null) return;
  typesetDirty = null;                 // cleared FIRST: saving redraws
  clearTimeout(styleSaveTimer);
  const r = regions.find(x=>x.id===id);
  if(!r) return;
  saveTypesetting(id, true, null, true);
}

/* Discrete style picks (colour, outline, font) should just stick — save them
   quietly once the person pauses, no "Keep this" needed. */
let styleSaveTimer=null;
function onTypesetStyle(id){
  onTypesetEdit(id);
  clearTimeout(styleSaveTimer);
  styleSaveTimer=setTimeout(flushTypesetEdit, 600);
}


/* `which` is 'fg' for the letters and 'edge' for the outline round them —
   two gradients, one clear button each. */
function clearGradient(id, which){
  const ids = which==='edge' ? ['lyEdge1','lyEdge2'] : ['lyFg1','lyFg2'];
  ids.forEach(fid=>{
    const f=$(fid); if(f) f.value='';
    const c=$(fid+'Chip'); if(c) c.style.background='transparent';
    const b=$(fid+'Hex'); if(b) b.textContent='OFF';
  });
  onTypesetStyle(id);
}
function clearShadow(id){
  _clearWell('lySh');
  onTypesetStyle(id);
}
function clearGlow(id){
  _clearWell('lyGlow');
  onTypesetStyle(id);
}
function clearIGlow(id){
  _clearWell('lyIGlow');
  onTypesetStyle(id);
}
/* One colour well, emptied: the hidden input, the chip and the label all say
   "off" together, or the panel disagrees with the page. */
function _clearWell(fid){
  const f=$(fid); if(f) f.value='';
  const c=$(fid+'Chip'); if(c) c.style.background='transparent';
  const b=$(fid+'Hex'); if(b) b.textContent='off';
}

/* Text/outline swatches open the app's own picker (with its eyedropper),
   not the operating system's colour dialog. */
function openTypesetPicker(anchor, fid, rid){
  openPicker(anchor, {
    get:()=>{ const f=$(fid); return f?f.value:'#000000'; },
    set:hex=>{
      const f=$(fid); if(!f) return;      // panel was rebuilt; nothing to do
      f.value=hex;
      const c=$(fid+'Chip'); if(c) c.style.background=hex;
      const b=$(fid+'Hex'); if(b) b.textContent=hex;
      onTypesetStyle(rid);
    }
  });
}

function rotateBy(id, delta){
  const r=regions.find(x=>x.id===id); if(!r) return;
  const ov=r.layout_override||{};
  // Nudge from wherever the text is actually sitting, not from zero. A sound
  // effect comes out of the fitter already leaning at the angle it was drawn
  // at, and "5 degrees more" has to mean five more than that.
  const cur = (ov.rotate===undefined||ov.rotate==='')
      ? +((r.layout&&r.layout.rotate)||0) : +ov.rotate;
  const next = delta===null ? 0 : Math.round(cur + delta);
  const f=$('lyRot'); if(f) f.value=next;
  r.layout_override=Object.assign({}, ov, {rotate:next, locked:true});
  if(r.layout) r.layout.rotate=next;
  drawOverlay();                       // turn on screen at once
  saveTypesetting(id, true, null, true); // and stay turned after a reload
}
