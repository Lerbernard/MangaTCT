/* typesetting-edit.js - Live typesetting preview while typing, style edits, gradient/shadow clears, rotation.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */
/* ---------------- live typesetting overlay ----------------
   The browser draws the text itself over the CLEANED page. The server only
   supplies line positions, which costs about 9ms - so edits show up as you
   make them instead of waiting on a full page re-render.               */
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
   discarded when a newer request had already been sent - and typing between
   "sent" and "received" does not send anything. The reply for the press
   before last was then accepted as current, and it overwrites the whole
   layout: the size and the line breaks. So the page took the smaller size
   while the field still showed the bigger one, and words came back that had
   already been typed over.

   lee: *"something i make the text big it randonly becomes smalle while teh
   text box remain big"* and *"sometime the text just revert back why im
   eddit it"*. It reads as random because a preview is normally about nine
   milliseconds - but the first one after any save has to rebuild the page,
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
             // WHAT THE PAGE IS DRAWN IN, and separately WHAT SOMEBODY CHOSE.
             //
             // `fg` and `edge` are the drawn pair, which is what the preview
             // has to paint with; most of the time nobody picked them and
             // `_ink_colours` worked them out from the artwork. The two below
             // are the override's own, empty when there is none - so the
             // panel's colour wells can show the drawn colour while still
             // knowing it was never chosen, and a save of something else does
             // not quietly freeze it. See `editor.layout_preview`.
             fg_set:j.fg_set||'', edge_set:j.edge_set||'',
             lspace:+(j.lspace||0),
             shadow:j.shadow||'',sh_dist:+(j.sh_dist??2),sh_blur:+(j.sh_blur??3),
             curve:+(j.curve||0),
             glow:j.glow||'',glow_size:+(j.glow_size??6),
             glow_set:j.glow_set||'',
             iglow:j.iglow||'',iglow_size:+(j.iglow_size??5),
             opacity:+(j.opacity??100),
             fg1:j.fg1||'',fg2:j.fg2||'',grad_angle:+(j.grad_angle||0),
             edge1:j.edge1||'',edge2:j.edge2||'',
             edge_angle:+(j.edge_angle||0)};
    r.kind=j.kind||r.kind;
    // When the box reshaped the text, the panel must say what the page says -
    // same breaks, same size. (Left alone if you are typing in the field.)
    if(patch.fit||patch.wrap){
      const la=$('lyLines');
      if(la&&document.activeElement!==la) la.value=(j.lines||[]).join('\n');
      const sz=$('lySize');
      if(sz&&document.activeElement!==sz&&j.font_size) sz.value=j.font_size;
    }
    // If the block is being typed into on the canvas, the editor is what is
    // visible - resize it too, or size changes look like they did nothing.
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

   Used by anything that changes the words without a keystroke - turning a
   text layer into a picture, for one, which has to leave the box empty or the
   page carries the typesetting twice. */
function setTypesetLines(id, lines){
  const el=$('lyLines');
  const r0=regions.find(x=>x.id===id);
  // A locked block is not typed into, but it can still be SET - putting the
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

/* What a colour well is worth SENDING.

   A well showing a colour the page worked out for itself is a readout, and
   sending it back would turn it into a hand edit - so it is worth nothing, and
   the empty string is how "nobody chose one" travels to the server (see
   `editor`'s override builder: `str(lay.get("fg") or "")`).

   lee: *"when changing the outerglow number, the outline color also
   switches"*. The outline the panel showed was the automatic one, every save
   of every other field wrote it down as though it had been picked, and from
   then on `_ink_colours` was not consulted about that block again. */
function wellNow(id){
  const f=$(id);
  if(!f) return '';
  const d=f.dataset||{};
  // A readout only while it still shows what the page put there. `data-was` is
  // that value; a field holding anything else has been set by somebody, and
  // the picker clearing `data-auto` is then the belt to this pair of braces.
  if(d.auto && (d.was === undefined || d.was === f.value)) return '';
  return f.value;
}

function currentPatch(r){
  const ov=r.layout_override||{};
  const L=r.layout||{};
  const mine=panelIsAbout(r);
  const el=(id)=>mine ? $(id) : null;
  // A span-capable field is only a person's choice when it no longer shows
  // what the panel put there: while a RANGE is selected the inputs display
  // the range's values, and a field mixed across spans displays blank -
  // sending either back as the BLOCK's style would be the bug where
  // reading a control turns into writing it.
  const pv=(key, raw, base)=>{
    if(!mine) return base;
    // only a REMEMBERED display suppresses the input - once a field is
    // chosen its snapshot is deleted, and from then on whatever stands in
    // it (an emptied gradient well included) is the person's answer
    if((key in panelShown) && String(raw)===String(panelShown[key]))
      return base;
    return raw;
  };
  return {align:el('lyAlign')?$('lyAlign').value:(ov.align||'center'),
          caps:el('lyCaps')?!!$('lyCaps').checked:!!ov.caps,
          lines:(el('lyLines')?lyLinesNow():(L.lines||[])),
          // SIZE AND FACE are range tools now, so they go through `pv` like
          // every other one: while a range is selected these two boxes show
          // the RANGE's answer, and a size field showing blank (the range
          // carries more than one) must not be sent back as the block's -
          // `+""` is 0, and a block saved at size zero has no letters left.
          font_size:el('lySize')
            ? (+pv('font_size', $('lySize').value, L.font_size||14)
               || (L.font_size||14))
            : (L.font_size||14),
          dx:+ov.dx||0,          // set by dragging the text, not by a field
          dy:+ov.dy||0,
          rotate:el('lyRot')?+$('lyRot').value:(+ov.rotate||0),
          font:el('lyFont')
            ? pv('font', $('lyFont').value, ov.font||'') : (ov.font||''),
          fg:el('lyFg')?pv('fg', wellNow('lyFg'), ov.fg||''):(ov.fg||''),
          edge:el('lyEdge')?pv('edge', wellNow('lyEdge'), ov.edge||''):(ov.edge||''),
          fg1:el('lyFg1')?pv('fg1', $('lyFg1').value, ov.fg1||''):(ov.fg1||''),
          fg2:el('lyFg2')?pv('fg2', $('lyFg2').value, ov.fg2||''):(ov.fg2||''),
          grad_angle:el('lyGrad')?+pv('grad_angle', $('lyGrad').value, +ov.grad_angle||0)||0:(+ov.grad_angle||0),
          edge1:el('lyEdge1')?pv('edge1', $('lyEdge1').value, ov.edge1||''):(ov.edge1||''),
          edge2:el('lyEdge2')?pv('edge2', $('lyEdge2').value, ov.edge2||''):(ov.edge2||''),
          edge_angle:el('lyEdgeG')?+pv('edge_angle', $('lyEdgeG').value, +ov.edge_angle||0)||0:(+ov.edge_angle||0),
          shadow:el('lySh')?pv('shadow', $('lySh').value, ov.shadow||''):(ov.shadow||''),
          sh_dist:el('lyShD')?+pv('sh_dist', $('lyShD').value, +ov.sh_dist||2)||0:(+ov.sh_dist||2),
          sh_blur:el('lyShB')?+pv('sh_blur', $('lyShB').value, +ov.sh_blur||3)||0:(+ov.sh_blur||3),
          curve:el('lyCurve')?+$('lyCurve').value||0:(+ov.curve||0),
          curve_kind:el('lyCurveKind')?($('lyCurveKind').value||'arch')
                                      :(ov.curve_kind||'arch'),
          glow:el('lyGlow')?pv('glow', wellNow('lyGlow'), ov.glow||''):(ov.glow||''),
          glow_size:el('lyGlowS')?+pv('glow_size', $('lyGlowS').value, +ov.glow_size||6)||0:(+ov.glow_size||6),
          iglow:el('lyIGlow')?pv('iglow', $('lyIGlow').value, ov.iglow||''):(ov.iglow||''),
          iglow_size:el('lyIGlowS')?+pv('iglow_size', $('lyIGlowS').value, +ov.iglow_size||5)||0:(+ov.iglow_size||5),
          // 0 is a real answer here - a fully transparent block - so this one
          // cannot be written with `||`. And through `pv` like every other
          // range tool: it skipped the guard when it became one, so fading
          // a RANGE also saved the number as the BLOCK's and the whole box
          // faded on the next debounced save. lee: *"everything else does
          // teh whole tetx box"*.
          opacity:($('lyOpacity')
            ? Math.max(0,Math.min(100,
                +pv('opacity', $('lyOpacity').value, ov.opacity ?? 100)||0))
            : (ov.opacity ?? 100)),
          // Falls back to the layout's own leading, not to 1.12: the panel is
          // only built in the typeset view, so saving from anywhere else used
          // to reset the line spacing to the default.
          leading:el('lyLead')?+$('lyLead').value||1.12
                            :(+ov.leading||(r.layout&&r.layout.leading)||undefined),
          lspace:el('lyLspace')?+$('lyLspace').value||0:(+ov.lspace||0),
          // ONLY a frame the person actually dragged. Echoing back the frame
          // the server just computed turned every save into a hand placement,
          // and the dx/dy baked into it were then added a second time - so
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
          stroke:el('lyStroke')?+pv('stroke', $('lyStroke').value, ov.stroke??'')||null:(ov.stroke??null),
          // the ranges ride every save, or a save of anything else
          // would quietly wipe them
          spans:(Array.isArray(ov.spans)&&ov.spans.length)?ov.spans:null};
}

function onTypesetEdit(id){
  noteTypesetEdit();
  const r=regions.find(x=>x.id===id); if(!r) return;
  /* WHAT THE PANEL SHOWS IS NOT ALWAYS THE BLOCK'S.

     While a range is selected the span-capable inputs display the RANGE's
     values, and this function's job is to keep the region's LIVE copy in
     step with the panel - two truths that collide the moment it runs with a
     range on screen. It does: any no-change call lands here (opening a
     picker re-applies the well's own colour, a slider fires on the press
     that does not move it), and the range's gradient, glow or opacity was
     then written onto `r.style`, which `runStyle` reads FIRST for every run
     without a value of its own - so the whole block wore the range's style
     until the next server reply rebuilt `r.style` from the truth, which
     after a save means the page-cache rebuild, which takes seconds.

     lee: *"whe i am editing it appears as if its universal but when i let
     teh app site it evently remove teh edits form teh other unslected
     text, it juts takes time"*. The guard is `currentPatch`'s own (`pv`):
     a span-capable field still showing what the panel put there is a
     READOUT, and a readout is not written down - the live copy keeps what
     it had. A field a person actually chose for the block has had its
     snapshot deleted (`onTypesetStyle`'s strip path), so it passes. */
  const _kept=(key)=>((key in panelShown)
    && String(panelValue(key))===String(panelShown[key]));
  // Colours and the outline are drawn by the browser, so show them the
  // instant they change instead of waiting on the server round trip.
  if(r.layout){
    // Everything typed goes into the region AT ONCE, before any request is
    // made. The panel is rebuilt on all sorts of things - a save landing, a
    // poll, a stepper being released - and it is built from the region, so
    // anything not written down here is a field that snaps back to the last
    // answer the server gave while the new one is still in flight. That is
    // the "it reverts back" lee kept seeing, and with a stepper it swallowed
    // every other press.
    if($('lyLead')) r.layout.leading=+$('lyLead').value
      || (typeof MIN_LEADING!=='undefined' ? MIN_LEADING : 1.2);
    // the size box is a range tool: with a range selected it shows the
    // RANGE's size, and writing that onto the layout resized every line
    // on screen until the reply put it back
    if($('lySize') && !_kept('font_size'))
      r.layout.font_size=+$('lySize').value||r.layout.font_size;
    if($('lyRot'))  r.layout.rotate=+$('lyRot').value||0;
    // ALL CAPS shows AT ONCE. It is a change to what the letters look like,
    // not to what the fitter decides, so waiting on the round trip to see it
    // was waiting for nothing - and the first preview after any save rebuilds
    // the page cache, which can take seconds. lee: *"the all caps either take
    // a long time or dosn't work"*. The server does the same thing to the
    // same lines; this only stops the screen lagging behind the switch.
    const _caps=$('lyCaps') ? !!$('lyCaps').checked : false;
    if(_caps && r.layout.lines)
      r.layout.lines=r.layout.lines.map(x=>String(x).toUpperCase());
    if($('lyLines')){
      // Every line as typed - blanks and leading spaces included, and an
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
  const live={
    align:$('lyAlign')?$('lyAlign').value:((r.style&&r.style.align)||'center'),
    caps:$('lyCaps')?$('lyCaps').checked:!!(r.style&&r.style.caps),
    lspace:$('lyLspace')?(+$('lyLspace').value||0)
          :((r.style&&r.style.lspace)||0),
    // The DRAWN pair - what the preview paints with. The well shows the drawn
    // colour whether or not anybody picked it, and a colour that has just been
    // picked IS the drawn one, so this is the same field either way.
    fg:$('lyFg')?$('lyFg').value:(r.style&&r.style.fg),
    edge:$('lyEdge')?$('lyEdge').value:(r.style&&r.style.edge),
    // ...and the CHOSEN pair, carried alongside so that the next rebuild of
    // the panel knows which wells are still only readouts. Without these two
    // a colour picked here would come back marked automatic on the very next
    // rebuild, and be dropped by the save after it.
    fg_set:$('lyFg')?wellNow('lyFg'):(r.style&&r.style.fg_set),
    edge_set:$('lyEdge')?wellNow('lyEdge'):(r.style&&r.style.edge_set),
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
    curve_kind:$('lyCurveKind')?($('lyCurveKind').value||'arch')
                               :((r.style&&r.style.curve_kind)||'arch'),
    glow:$('lyGlow')?$('lyGlow').value:(r.style&&r.style.glow)||'',
    glow_set:$('lyGlow')?wellNow('lyGlow'):((r.style&&r.style.glow_set)||''),
    glow_size:$('lyGlowS')?(+$('lyGlowS').value||0):((r.style&&r.style.glow_size)??6),
    iglow:$('lyIGlow')?$('lyIGlow').value:(r.style&&r.style.iglow)||'',
    iglow_size:$('lyIGlowS')?(+$('lyIGlowS').value||0):((r.style&&r.style.iglow_size)??5),
    opacity:$('lyOpacity')?Math.max(0,Math.min(100,+$('lyOpacity').value||0))
                          :((r.style&&r.style.opacity)??100)};
  // ...and the guard itself: a span-capable field the panel still shows
  // unchanged stays OFF the live copy - see the note at the top.
  SPAN_STYLE_KEYS.forEach(k=>{ if((k in live) && _kept(k)) delete live[k]; });
  if(!('fg' in live))   delete live.fg_set;
  if(!('edge' in live)) delete live.edge_set;
  if(!('glow' in live)) delete live.glow_set;
  r.style=Object.assign({}, r.style, live);
  drawOverlay();
  livePreview(id, currentPatch(r));
  typesetDirty = id;          // there is now a change that has not been saved
}

/* Everything typed into the typesetting panel is only PREVIEWED as you type -
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

/* Discrete style picks (colour, outline, font) should just stick - save them
   quietly once the person pauses, no "Keep this" needed. */
let styleSaveTimer=null;
/* ---------------- part of the text, styled by itself ----------------

   Photoshop-fashion: select characters in the box you type into and the
   panel's colour-and-effect tools work on THAT RANGE; with nothing
   selected they work on the whole block exactly as before. lee: *"if te
   user selects part of teh text ... theey shoud be able to modifly that
   soesific part of teh text with all teh tools"*. Ranges live in
   `layout_override.spans` - [{s, e, st}] over the flat text of the lines
   joined with newlines - and are drawn by `runStyle`/`drawText` here and
   `render._ink_layer` on the export, the same numbers both sides. */

// The tools a RANGE can carry - which is EVERY tool on the Colour and
// Effects panels, transparency included. lee: *"all these affct shodu be
// able to be doen to xelecetd part of a text box with out changing or
// affceting teh rest of teh text"*. Every spanned line is laid out run by
// run (there are no bands - see `drawText`); the last two keys also
// change how much room the words take, which is why only they force a
// refit. See `render.METRIC_KEYS`.
const SPAN_STYLE_KEYS=['fg','edge','stroke','fg1','fg2','grad_angle',
  'edge1','edge2','edge_angle','glow','glow_size','iglow','iglow_size',
  'shadow','sh_dist','sh_blur','opacity','font','font_size'];
// ...and the two of those that MOVE the letters rather than repaint them.
const SPAN_METRIC_KEYS=['font','font_size'];

// The character range selected in the box you type into, in flat offsets.
//
// It used to be a variable - `editSel` - kept alive by hand, because
// clicking a colour well throws the browser's own selection away and the
// range had to outlive that or the tools had nothing to work on. It is the
// EDITOR's selection now, held in its state, and a well that steals focus
// cannot take away something the browser never owned. `editRange` in
// typesetting.js is the one reader.
function editSelNow(){
  return (typeof editRange==='function') ? editRange() : null;
}
// what the panel's span-capable fields SHOWED when they were last filled -
// the diff against this is what a person actually changed
let panelShown={};

function rangeActive(){
  return editing!==null && !!editSelNow();
}

/* Effective value of one field over an interval: {mixed, value}, or null
   when the key is not span-capable / block has no spans and no range. */
function spanFieldInfo(r, key){
  if(!r || SPAN_STYLE_KEYS.indexOf(key)<0) return null;
  // With a range selected, ask the EDITOR - it is the one holding the
  // marks, and asking the region's saved copy would answer about the block
  // as it was before the last keystroke.
  const _rng=(sel===r.id) ? editSelNow() : null;
  if(_rng && typeof tbFieldInfo==='function' && tbIsOpen())
    return tbFieldInfo(key, _rng.s, _rng.e);
  const ovr=r.layout_override||{};
  const raw=Array.isArray(ovr.spans)?ovr.spans:[];
  const L=r.layout;
  if(!L||!L.lines) return null;
  const inRange=!!_rng;
  if(!raw.length && !inRange) return null;
  const n=L.lines.reduce((a,l)=>a+l.length,0)+Math.max(0,L.lines.length-1);
  const s0=inRange?Math.max(0,_rng.s):0;
  const e0=inRange?Math.min(n,_rng.e):n;
  if(e0<=s0) return null;
  // walk the boundaries; base value = "not set by a span"
  const marks=new Set([s0,e0]);
  raw.forEach(sp=>{marks.add(Math.max(s0,Math.min(e0,sp.s|0)));
                   marks.add(Math.max(s0,Math.min(e0,sp.e|0)));});
  const bs=[...marks].sort((a,b)=>a-b);
  let seen=null, mixed=false, any=false;
  for(let i=0;i<bs.length-1;i++){
    const mid=(bs[i]+bs[i+1])/2;
    if(bs[i+1]<=bs[i]) continue;
    let v; // undefined = the block's own value
    raw.forEach(sp=>{ if(sp.s<=mid&&mid<sp.e&&sp.st&&sp.st[key]!==undefined)
      v=sp.st[key]; });
    if(!any){ seen=v; any=true; }
    else if(String(v)!==String(seen)) mixed=true;
  }
  if(!any) return null;
  if(mixed) return {mixed:true};
  return {mixed:false, value:seen};
}

/* Write `diff` onto [s0,e0): split whatever spans overlap the ends, set
   the keys (an empty-string value REMOVES the key - that is what pressing
   an x means), coalesce neighbours that came out identical, and drop spans
   left with nothing to say. */
function applySpanStyle(r, s0, e0, diff){
  // WHILE THE EDITOR IS OPEN, the editor owns the ranges. It has the
  // document, so it splits and merges them itself - and, more to the
  // point, it keeps them right when the words move afterwards, which is
  // what `remapSpans` used to try to do by hand.
  if(typeof tbIsOpen==='function' && tbIsOpen() && editing===r.id){
    tbMark(s0, e0, diff);
    if(typeof syncFromTextbox==='function') syncFromTextbox(r);
    return;
  }
  const ovr=r.layout_override=(r.layout_override||{});
  let sp=Array.isArray(ovr.spans)?ovr.spans.map(x=>({s:x.s|0,e:x.e|0,
      st:Object.assign({},x.st||{})})):[];
  // split at the range ends
  const cut=(at)=>{ sp.forEach(x=>{ if(x.s<at&&at<x.e){
      sp.push({s:at,e:x.e,st:Object.assign({},x.st)}); x.e=at; } }); };
  cut(s0); cut(e0);
  // make sure every character of the range has a span to carry the style
  const covered=[];
  sp.filter(x=>x.s>=s0&&x.e<=e0).forEach(x=>covered.push([x.s,x.e]));
  covered.sort((a,b)=>a[0]-b[0]);
  let at=s0;
  covered.forEach(([a,b])=>{ if(a>at) sp.push({s:at,e:a,st:{}}); at=Math.max(at,b); });
  if(at<e0) sp.push({s:at,e:e0,st:{}});
  // the style itself
  sp.forEach(x=>{ if(x.s>=s0&&x.e<=e0){
    for(const k in diff){
      if(diff[k]===''||diff[k]===null||diff[k]===undefined) delete x.st[k];
      else x.st[k]=diff[k];
    } } });
  // tidy: empty spans out, equal neighbours joined
  sp=sp.filter(x=>x.e>x.s && Object.keys(x.st).length);
  sp.sort((a,b)=>a.s-b.s||a.e-b.e);
  const out=[];
  sp.forEach(x=>{ const p=out[out.length-1];
    if(p && p.e===x.s && JSON.stringify(p.st)===JSON.stringify(x.st)) p.e=x.e;
    else out.push(x); });
  ovr.spans=out;
  ovr.locked=true;
}

/* One key taken off every span - what setting a MIXED field on the whole
   block means: the new value applies to everything, Photoshop-fashion. */
function stripSpanKey(r, key){
  if(typeof tbIsOpen==='function' && tbIsOpen() && editing===r.id){
    tbStripKey(key);
    if(typeof syncFromTextbox==='function') syncFromTextbox(r);
    return;
  }
  const ovr=r.layout_override||{};
  if(!Array.isArray(ovr.spans)) return;
  ovr.spans.forEach(x=>{ if(x.st) delete x.st[key]; });
  ovr.spans=ovr.spans.filter(x=>x.st&&Object.keys(x.st).length);
}

/* `remapSpans` used to live here: the wording moved under the spans, so
   every start and end was shifted by hand, by finding the common head and
   tail of the old and new flat text and guessing what the edit had done to
   anything straddling it. It is gone. The editor moves its own marks with
   the text it is editing, exactly and by construction, which is the single
   biggest thing this swap bought. */

/* What the panel's span-capable inputs hold right now - read after the
   panel is (re)built, and after every applied change, so the next diff is
   only what the person actually touched. */
/* WHAT THE PANEL IS SHOWING FOR THIS FIELD - read the same way `currentPatch`
   reads it, which is the whole point of the snapshot.

   Three of these fields go through `wellNow`, which returns '' while the well
   is still only a READOUT of what the page worked out for itself. The
   snapshot used to record the raw `el.value` instead, so for an automatic
   colour the two disagreed by construction: shown '#000000', read ''.

   `currentPatch` then found `raw !== panelShown[key]`, decided the field had
   been CHOSEN, and sent it as the BLOCK's colour - while the edit had
   actually gone to a range. `markInFlight` pinned that colour over the region
   locally, so the editor drew the whole block in the range's colour while the
   server, which was sent the right thing, drew it correctly. It came good
   when the in-flight mark cleared, which is why it looked like a delay.

   lee, with two screenshots: *"only the word cloudy should be orange but the
   editor shows the whole thing as orange while the exported preview gets it
   right"* and *"after a while the editor version gets it right too"*. */
function panelValue(key){
  const el=$(FIELD_IDS[key]);
  if(!el) return undefined;
  return WELL_FIELDS.indexOf(key)>=0 ? wellNow(FIELD_IDS[key]) : el.value;
}

//: The span-capable fields `currentPatch` reads through `wellNow`.
const WELL_FIELDS=['fg','edge','glow'];

/* WHAT THE SIZE BOX SHOWS.

   With a range selected in the box you type into, the range's size - and
   blank when the range carries more than one, the way every other
   span-capable field on this panel already behaves.

   Otherwise the LIVE layout's size, and this is the part `styleNow` cannot
   do: it falls back to `layout_override`, which is the last answer the
   SERVER gave, and nothing writes the size there until the save lands. So
   a stepper press changed `L.font_size` and the panel rebuild that
   followed it put the saved number straight back - one press in two went
   missing, and holding the button for eight moved four. */
function sizeShown(r, ov, L){
  if(typeof spanFieldInfo === 'function'){
    const inf = spanFieldInfo(r, 'font_size');
    if(inf) return inf.mixed ? ''
      : (inf.value !== undefined ? inf.value : (L.font_size || ''));
  }
  return L.font_size;
}

function snapshotTypesetPanel(){
  panelShown={};
  SPAN_STYLE_KEYS.forEach(k=>{
    const v=panelValue(k);
    if(v!==undefined) panelShown[k]=v;
  });
}
const FIELD_IDS={fg:'lyFg', edge:'lyEdge', stroke:'lyStroke',
  fg1:'lyFg1', fg2:'lyFg2', grad_angle:'lyGrad',
  edge1:'lyEdge1', edge2:'lyEdge2', edge_angle:'lyEdgeG',
  glow:'lyGlow', glow_size:'lyGlowS', iglow:'lyIGlow', iglow_size:'lyIGlowS',
  shadow:'lySh', sh_dist:'lyShD', sh_blur:'lyShB', opacity:'lyOpacity',
  // the two that move the letters: the face menu and the size stepper
  font:'lyFont', font_size:'lySize'};

/* A style edit while a range is selected goes to the RANGE. Returns true
   when it was taken (the block-wide path must then leave the base style
   alone - `currentPatch` reads the base for these keys anyway). */
function spanRoute(id){
  const rng=editSelNow();
  if(!rng || editing===null) return false;
  const r=regions.find(x=>x.id===id);
  if(!r || sel!==id) return false;
  const diff={};
  SPAN_STYLE_KEYS.forEach(k=>{
    const el=$(FIELD_IDS[k]);
    if(!el) return;
    // Compared - and remembered - the way `currentPatch` reads it. See
    // `panelValue`: a raw `el.value` here and a `wellNow` there is how a
    // range's colour used to end up saved as the block's.
    const now=panelValue(k);
    if(!(k in panelShown) || String(now)!==String(panelShown[k]))
      diff[k]=el.value;
  });
  if(!Object.keys(diff).length) return false;
  applySpanStyle(r, rng.s, rng.e, diff);
  SPAN_STYLE_KEYS.forEach(k=>{
    const v=panelValue(k);
    if(v!==undefined) panelShown[k]=v; });
  noteTypesetEdit();
  typesetDirty=id;      // or the debounced flush finds nothing to save
  drawOverlay();
  // placeEditor, not just the mirror: the FIRST span on a block is the
  // moment the box's own text goes transparent and the mirror takes over
  // the fill - a mirror refresh alone leaves the box's ink painted on top.
  //
  // A SIZE or a FACE also changes where the caret belongs, and the box has
  // to be as wide as the runs it now holds. It used to be REFILLED here,
  // with the selection put back by hand afterwards; the editor re-renders
  // its own marks and keeps its own selection, so there is nothing left to
  // do but let the box make room.
  if(editing===id && editBox){
    editInkMirror(editBox, r);
    placeEditor(editBox, r);
  }
  // the save carries base + spans together through the ordinary channel
  clearTimeout(styleSaveTimer);
  styleSaveTimer=setTimeout(flushTypesetEdit, 600);
  return true;
}

function onTypesetStyle(id){
  // a range selected in the box you type into takes the edit for itself
  if(spanRoute(id)){ gradientOwnsTheWell(); return; }
  // ...and setting a field that was MIXED across spans applies the new
  // value to everything: the spans' own copies of that key go, so the base
  // value about to be saved is the one answer left, Photoshop-fashion
  const r=regions.find(x=>x.id===id);
  if(r){
    SPAN_STYLE_KEYS.forEach(k=>{
      const el=$(FIELD_IDS[k]);
      if(el && (k in panelShown)
         && String(panelValue(k))!==String(panelShown[k])){
        stripSpanKey(r, k);
        // the field is a CHOICE from here on: forgetting what the panel
        // showed is what lets `currentPatch` keep sending the new value -
        // remembering it as "shown" made the edit invisible to the save,
        // and the glow the person picked never reached the page
        delete panelShown[k];
      }
    });
  }
  onTypesetEdit(id);
  gradientOwnsTheWell();
  clearTimeout(styleSaveTimer);
  styleSaveTimer=setTimeout(flushTypesetEdit, 600);
}


/* WHILE A GRADIENT IS ON, THE PLAIN WELL IS OFF.

   With both set, the panel offered two answers to one question - a text
   colour AND a fill gradient, an outline colour AND an outline gradient -
   and the two renderers each had to pick, which is exactly the kind of
   ambiguity that shows up as the editor and the export disagreeing at the
   letters' edges. lee: *"wheni apply a gradient on teh oulibe or teh etxt
   itself it should disable the regular box ... and if i click teh x on
   gradient teh regular colo shoud come back"*.

   The gradient wins while it is set: the plain well greys out and stops
   taking clicks. Its VALUE is left alone on purpose - pressing the
   gradient's × clears only the gradient, and the colour that was standing
   in the well is simply in charge again, exactly as it was. */
function gradientOwnsTheWell(){
  const hex=v=>/^#[0-9a-f]{6}$/i.test(v||'');
  [['lyFg','lyFg1','lyFg2'],['lyEdge','lyEdge1','lyEdge2']]
    .forEach(([well,g1,g2])=>{
      const f=$(well); if(!f) return;
      const w=f.closest('.colwell'); if(!w) return;
      const on=hex($(g1)&&$(g1).value) && hex($(g2)&&$(g2).value);
      w.classList.toggle('welloff', on);
      w.title=on?'The gradient is in charge - press its × to use one colour.'
               :'';
    });
}


/* `which` is 'fg' for the letters and 'edge' for the outline round them -
   two gradients, one clear button each. */
function clearGradient(id, which){
  const ids = which==='edge' ? ['lyEdge1','lyEdge2'] : ['lyFg1','lyFg2'];
  // With a RANGE selected, × has to say *no gradient HERE* over a block
  // that has one - an emptied field would just be deleted from the range
  // and the block's gradient would show straight through it. So the range
  // is handed the app's own spelling of a colour that is not there
  // (`NO_FILL`), which every "is this on" question already reads as off.
  const off = (typeof rangeActive==='function' && rangeActive())
    ? (typeof NO_FILL==='string' ? NO_FILL : '#00000000') : '';
  ids.forEach(fid=>{
    const f=$(fid); if(f) f.value=off;
    const c=$(fid+'Chip'); if(c) c.style.background='transparent';
    const b=$(fid+'Hex'); if(b) b.textContent='OFF';
  });
  // ...and the plain colour well wakes back up with the colour it had all
  // along - `gradientOwnsTheWell` never touched its value, only its switch.
  onTypesetStyle(id);
}
function clearShadow(id){
  // the same range rule as `clearGradient`: × on a selection means *no
  // shadow here*, not *whatever the block says*
  _clearWell('lySh', (typeof rangeActive==='function' && rangeActive())
    ? (typeof NO_FILL==='string' ? NO_FILL : '#00000000') : '');
  onTypesetStyle(id);
}
/* NOT THE SAME "OFF" AS THE OTHER TWO.

   A sound effect over artwork is given a halo in the opposite colour whether
   or not anybody asked for one (`render.auto_glow`), so an EMPTY glow field
   means *nobody has said*, and the automatic one applies. Emptying it here
   would be pressing × and getting the glow back.

   So this one writes a colour: `NO_FILL`, an eight-digit hex with a zero
   alpha, which is how this app has always spelled a colour that is not there.
   The page reads it as a glow that was chosen and is invisible, which is
   exactly what was asked for, and it survives a save the way any other choice
   does. */
function clearGlow(id){
  _clearWell('lyGlow', typeof NO_FILL === 'string' ? NO_FILL : '#00000000');
  onTypesetStyle(id);
}
function clearIGlow(id){
  // the same range rule as `clearGradient` and `clearShadow`
  _clearWell('lyIGlow', (typeof rangeActive==='function' && rangeActive())
    ? (typeof NO_FILL==='string' ? NO_FILL : '#00000000') : '');
  onTypesetStyle(id);
}
/* One colour well, emptied: the hidden input, the chip and the label all say
   "off" together, or the panel disagrees with the page. `off` is the value to
   put in it - empty for a well whose blank state already means off. */
function _clearWell(fid, off){
  const f=$(fid);
  if(f){
    f.value = off || '';
    // Emptied BY HAND, so it is no longer a readout of what the page decided.
    f.removeAttribute('data-auto');
  }
  const c=$(fid+'Chip');
  if(c){ c.classList.toggle('noswatch', !!off); c.style.background='transparent'; }
  const b=$(fid+'Hex'); if(b) b.textContent = off ? 'none' : 'off';
}

/* Which of the colour wells may be emptied to nothing at all.
   The FILL, and only the fill. Letters with no fill are a real thing - the
   outline is the letterform, which is how half the sound effects on a page
   are drawn - and letters with no OUTLINE are just letters, which is what
   clearing that field already gives you. An outline of nothing on a fill of
   nothing is a block that does not exist, and there is no reason to offer a
   way to ask for one.

   ...and the OUTER GLOW, for the opposite reason: an empty glow field is not
   "no glow" any more. A sound effect over artwork is given one in the opposite
   colour whether or not anybody asked (`render.auto_glow`), so *no* has to be
   sayable, and this is where it is said. */
const CAN_BE_EMPTY = ['lyFg', 'lyGlow'];

/* Text/outline swatches open the app's own picker (with its eyedropper),
   not the operating system's colour dialog. */
function openTypesetPicker(anchor, fid, rid){
  openPicker(anchor, {
    none: CAN_BE_EMPTY.includes(fid),
    get:()=>{ const f=$(fid); return f?f.value:'#000000'; },
    set:hex=>{
      const f=$(fid); if(!f) return;      // panel was rebuilt; nothing to do
      f.value=hex;
      // Somebody has now CHOSEN this one, so it stops being a readout and is
      // saved from here on. See `wellBits`.
      f.removeAttribute('data-auto');
      // An emptied fill is shown the way it was CHOSEN - the white box with
      // the red line through it - rather than as the eight hex digits it is
      // stored as, which say nothing to anybody. A transparent chip on a dark
      // panel is a chip that looks like it has no colour set at all, and
      // "not set" and "set to nothing" are different answers.
      const gone = isNoFill(hex);
      const c=$(fid+'Chip');
      if(c){ c.classList.toggle('noswatch', gone);
             c.style.background = gone ? '' : hex; }
      const b=$(fid+'Hex'); if(b) b.textContent = gone ? 'none' : hex;
      onTypesetStyle(rid);
    }
  });
}

/* Is this colour no colour? Any eight-digit hex whose alpha is zero, not just
   the one `NO_FILL` writes - the answer has to be about the value rather than
   about which button produced it, or a project saved with a different
   transparent black would draw one way and read another. */
function isNoFill(c){
  return typeof c === 'string' && /^#[0-9a-f]{6}00$/i.test(c.trim());
}

/* The curve picker's four chips. Arch and Sag are the same shape with the
   sign flipped; Wave and Rise are kinds of their own. Picking a chip when
   the Amount is 0 seeds a sensible number, or the click would change the
   stored kind and draw nothing - a control that does nothing when pressed
   reads as broken. */
function setCurveKind(id, chip){
  const kindOf={arch:'arch', sag:'arch', wave:'wave', rise:'rise'};
  const seed={arch:40, sag:-40, wave:30, rise:20};
  const kf=$('lyCurveKind'); if(kf) kf.value=kindOf[chip];
  const cf=$('lyCurve');
  if(cf){
    let amt=+cf.value||0;
    if(!amt) amt=seed[chip];
    // Arch wants the amount positive, Sag negative; Wave and Rise keep
    // whatever sign is there (their sign is a direction, not a kind).
    if(chip==='arch') amt=Math.abs(amt);
    if(chip==='sag') amt=-Math.abs(amt||40);
    cf.value=amt;
  }
  document.querySelectorAll('.curvekinds .alignb')
    .forEach(b=>b.classList.remove('pri'));
  const hit=[...document.querySelectorAll('.curvekinds .alignb')]
    .find(b=>(b.getAttribute('onclick')||'').includes("'"+chip+"'"));
  if(hit) hit.classList.add('pri');
  onTypesetStyle(id);
}

/* Set or nudge a block's rotation from code - the number box and the corner
   handles write the angle themselves, but the sfx harness (and anything
   else that needs "5 degrees more than wherever it is") comes through here.
   Nearly went in the 2026-09-02 dead-code sweep: the app's own buttons for
   it are gone, but tests/ui/sfx_rotate.test.js holds the contract that a
   hand-set angle survives a re-read. */
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
