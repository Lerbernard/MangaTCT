/* region-ops.js - Region CRUD against the API, typesetting save/auto-fit, stage mouse interactions + keyboard shortcuts.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* `before` is what to put back, for a caller that has already changed the
   region in the browser before saving it.

   Without it this reads `r.layout_override` as it stands NOW, which for the
   on-canvas editor is the edit itself - so the undo restored the state it was
   supposed to undo, and pressing it did nothing. That is what lee is looking
   at when he deletes the words out of a block: *"the text is deleting and teh
   empty box stay but its not in the history so i cant undo the delete"*.

   `{ov, text}`: the override, and the translation, which the server clears on
   its own when the lines come in empty - so an undo that only restored the
   override brought back an empty box. */
async function saveTypesetting(id, quiet, extra, norefresh, before){
  const r=regions.find(x=>x.id===id);
  if(r && !saveTypesetting._undoing){
    const prev=JSON.parse(JSON.stringify(
      (before&&before.ov!==undefined) ? (before.ov||{}) : (r.layout_override||{})));
    const prevText=(before&&before.text!==undefined) ? before.text : r.dst_text;
    // Say WHICH edit it was. "typesetting changed" over an emptied block is the
    // one entry in the list you would never think to press.
    const gone=!!(extra&&extra.lines&&
                  !extra.lines.some(l=>String(l).trim()));
    const what=gone?'text deleted':'typesetting changed';
    record('typeset', `Region ${(r.order??0)+1}: ${what}`,
      async ()=>{
        saveTypesetting._undoing=true;
        try{
          // The translation is a separate field on a separate branch of the
          // region endpoint, so putting it back is its own call - and it goes
          // FIRST. The layout post lays the block out from `dst_text`, so
          // restoring an empty override while the sentence is still deleted
          // lays out nothing and the box comes back blank.
          if(prevText!==undefined && prevText!==null)
            await api(`/api/page/${cur}/region/${id}`,'POST',{dst_text:prevText});
          // An empty override is not an override. Posting `{}` MERGES - every
          // field is read with a default, so the answer that comes back is a
          // full override holding the edit's own empty line list, and the undo
          // undid nothing. `reset` is the endpoint's own word for "there was
          // no hand edit here; typeset it from the sentence".
          const had=prev && Object.keys(prev).length;
          await api(`/api/page/${cur}/region/${id}`,'POST',
                    {layout: had ? prev : {reset:true}});
          const d=await api('/api/page/'+cur);
          setRegions(d.regions);
          // ...and the words themselves, which live on the canvas rather than
          // in the box list. Without this the undo lands in the data and not
          // on screen until something else happens to redraw.
          if(typeof drawText==='function') drawText();
        } finally { saveTypesetting._undoing=false; }
      });
  }
  const ticket=pageTicket;
  const my=++editSeq;
  const patch=Object.assign(currentPatch(r), extra||{});
  // Remembered until its own answer comes home, so a refresh that lands in
  // the meantime cannot put the old typesetting back on screen. See core.js.
  let mySeq = null;
  if(typeof markInFlight==='function'){
    // Only the fields a PERSON set, and only ones the server echoes back
    // verbatim. Marking the whole patch pinned the mark for ever: it carries
    // derived geometry (`frame`, `origins`) that comes home in a different
    // shape than it went out, so "has the server caught up" never became true.
    const mine = {};
    for(const k of ['font_size','lines','leading','rotate','stroke','lspace',
                    'fg','edge','fg1','fg2','grad_angle','curve','opacity',
                    'shadow','sh_dist','sh_blur','glow','glow_size',
                    'iglow','iglow_size','font']){
      if(patch[k] !== undefined) mine[k] = patch[k];
    }
    // WHERE the block is, which was the one thing a person can change that
    // nothing held on to. Dragging a block writes `frame` (and, for a divided
    // speech, `origins` and `fixed`) into the override and nothing else; with
    // none of them marked, a page refresh already on its way put the old
    // position straight back over the new one. lee, with a screen recording:
    // *"the text is snapping back to its prrevious location"*.
    //
    // Only on a plain MOVE. A wrap, a snug or a fit is the one case where the
    // server rewrites `frame` from the layout it computed, so the answer that
    // comes home is deliberately not what went out - and a mark that can never
    // agree is a mark that never lets go, which pins the stale value on screen
    // for ever. That is why the whole patch was excluded here in the first
    // place; the fix is to be specific, not to give up.
    // `frame`, `dx` and `dy` only, and only when they are actually set. Those
    // three are the ones the server stores in the override verbatim and hands
    // straight back. `fixed` and `origins` are NOT in the override it builds,
    // so marking them would ask for agreement that can never arrive; and a
    // null frame must not be marked either, because emptying a box is the one
    // case where the server fills that field in for itself.
    if(!patch.wrap && !patch.snug && !patch.fit){
      for(const k of ['frame','dx','dy']){
        if(patch[k] !== undefined) mine[k] = patch[k];
      }
    }
    const mark = markInFlight(id, {layout_override: mine,
                                   layout: {font_size: patch.font_size,
                                            lines: patch.lines,
                                            leading: patch.leading,
                                            rotate: patch.rotate}});
    mySeq = mark && mark.seq;
  }
  let j;
  try{
    j=await api(`/api/page/${cur}/region/${id}`,'POST',{layout:patch});
  } catch(e){
    if(typeof settleInFlight==='function') settleInFlight(id, mySeq);
    throw e;
  }
  // On disk. The mark is let go here, BEFORE the answer below is laid down -
  // that answer is the newest thing there is and must not be overlaid.
  if(typeof settleInFlight==='function') settleInFlight(id, mySeq);
  if(ticket!==pageTicket){                   // you have moved on; do not apply
    return;
  }
  if(j.regions && my===editSeq){
    // Rebuilding the sidebar mid-edit would pull the inputs out from under an
    // open colour dialog, so quiet background saves leave it alone - but the
    // boxes and their numbers are redrawn either way.
    setRegions(j.regions, {list: !norefresh});
    if(!norefresh) refreshPages();
  }
  if(!quiet) toast('Typesetting kept for bubble '+((r.order??0)+1));
}
async function autoFit(id){
  const j=await api(`/api/page/${cur}/region/${id}`,'POST',{layout:{reset:true}});
  if(j.regions) setRegions(j.regions);
}

/* Linked bubbles: two (or more) regions that are one continuous sentence split
   across balloons. They stay SEPARATE regions - read once each - but carry the
   same link id so the translator renders them as one flowing line in order. */
let linkPick=null;                       // id of the bubble waiting to be linked

/* A row is a card you click AND a piece of text you read. Those fight: the
   card rebuilds the whole list on every selection change, which throws away
   whatever the mouse just selected, and a `draggable` card in Chromium starts a
   drag instead of a selection so nothing can be picked out at all.

   So the row is no longer draggable by itself - the grip arms it for one drag -
   and a click that merely finished selecting some text is left alone. lee:
   "allow me to select and copy and paste etc like a regular text box". */
/* Arm the row this was pressed in for ONE drag.
   The handle used to be the three-dot grip alone, which is nine pixels wide
   and the only part of a card that did anything on a press - so a row you had
   grabbed by its number, or anywhere along its top, simply did not move.
   lee: *"on teh original tab i lost teh ability to drag the tab to chnge tehre
   numbering"*. The whole head of the card arms it now; the text below stays
   selectable, which is what the grip-only rule was protecting in the first
   place. */
function armRowDrag(grip){
  const card = grip && grip.closest('.lrow');
  if(!card) return;
  // a press on a control in the head is that control's, not a drag
  if(grip.closest && grip.closest('button,input,select,textarea,.ordbtns')) return;
  card.draggable = true;
  // one drag only: whether it is dropped or abandoned, the row goes back to
  // being plain text
  const off = ()=>{ card.draggable = false;
                    window.removeEventListener('mouseup', off, true); };
  window.addEventListener('mouseup', off, true);
}
function disarmRowDrag(card){ if(card) card.draggable = false; }

function listTextSelected(ev){
  // Only a real click can be "the click that ended a selection". Anything
  // calling select() by hand - the page, a link, the keyboard - must never be
  // blocked by a selection left lying about somewhere else.
  if(!ev || !ev.target) return false;
  const s = window.getSelection && window.getSelection();
  if(!s || s.isCollapsed || !String(s).trim()) return false;
  const n = s.anchorNode;
  const el = n && (n.nodeType === 1 ? n : n.parentNode);
  const row = el && el.closest && el.closest('.lrow');
  if(!row) return false;
  // Only the row the selection is IN. Clicking a different row is a deliberate
  // move on, and the selection goes with it - otherwise every click after a
  // copy would have to be made twice.
  const clicked = ev.target.closest && ev.target.closest('.lrow');
  return clicked === row;
}

function select(id, ev){
  // A drag that selected some text ends in a click on the row. Re-rendering
  // here would wipe the selection before it could be copied.
  if(listTextSelected(ev)) return;
  // In "link" mode the next bubble you click gets joined to the first one.
  if(linkPick!=null && id!=null && id!==linkPick){
    const from=linkPick; endLinkMode();
    completeLink(from, id).then(()=>{sel=id;drawBoxes();drawOverlay();renderList();});
    return;
  }
  if(linkPick!=null){ endLinkMode(); }   // clicked nothing / same box → cancel
  // Ctrl+click (or "c" held) adds to the selection instead of replacing it -
  // works from the list rows (this function) and from the page itself (stage
  // mousedown). The list rows pass their click through as `ev`.
  if(id!=null && multiPick(ev)){ toggleMulti(id); return; }
  // Picking a text box in the Edit view swaps the whole side panel for the
  // typesetting controls - the tool you had armed is no longer anywhere on
  // screen, but it is still armed, and the next drag paints instead of moving
  // the words. lee: *"if im using a tool like the brush or any other tool and
  // i clcik a text box and open the text edit tab it shoud automaicaly
  // diactive the tool"*. Choosing the text IS choosing to stop painting.
  if(id!=null && typeof view!=='undefined' && view==='typeset'
     && typeof paintArmed==='function' && paintArmed()
     && typeof stopBrush==='function'){
    stopBrush();
    if(typeof toast==='function')
      toast('Tool put away - you are working on the text now.', 2200);
  }
  sel=id; selMulti.clear();
  drawBoxes();drawOverlay();renderList();
}

/* ------------- multi-select: Ctrl+click (or hold "c") -------------
   Several boxes at once, so one keypress retypes a whole panel's worth.
   `selMulti` holds every picked id (including `sel`); empty means the plain
   single selection is in force. */

/* True when this click should ADD to the selection rather than replace it.
   Ctrl (Cmd on a Mac) is what everyone reaches for first; "c" stays as well,
   because it leaves the mouse hand alone for a long run of picks. */
function multiPick(e){
  return cHeld || !!(e && (e.ctrlKey || e.metaKey));
}
let cHeld=false;
function _typingIn(a){
  return !a || a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName);
}
function _setCHeld(on){
  if(cHeld===on) return;
  cHeld=on;
  document.body.classList.toggle('multipick', on);
}
window.addEventListener('keydown',e=>{
  if((e.key==='c'||e.key==='C') && !e.ctrlKey && !e.metaKey && !_typingIn(e.target))
    _setCHeld(true);
});
window.addEventListener('keyup',e=>{ if(e.key==='c'||e.key==='C') _setCHeld(false); });
// Ctrl held gets the same "click to add" cursor. It does not arm cHeld - the
// click itself carries ctrlKey, and Ctrl is half of too many other shortcuts.
window.addEventListener('keydown',e=>{
  if(e.key==='Control'||e.key==='Meta') document.body.classList.add('multipick');
});
window.addEventListener('keyup',e=>{
  if((e.key==='Control'||e.key==='Meta') && !cHeld)
    document.body.classList.remove('multipick');
});
// A window that loses focus never sends the keyup, which would leave the
// editor stuck in "adding" mode.
window.addEventListener('blur',()=>{
  _setCHeld(false); document.body.classList.remove('multipick');
});

/* Every id the next action applies to. */
function selIds(){
  if(selMulti.size) return [...selMulti];
  return sel!=null ? [sel] : [];
}
function toggleMulti(id){
  if(id==null) return;
  // First c+click on a second box pulls the already-selected one in with it.
  if(!selMulti.size && sel!=null) selMulti.add(sel);
  if(selMulti.has(id)){
    selMulti.delete(id);
    if(sel===id) sel = selMulti.size ? [...selMulti][selMulti.size-1] : null;
  } else {
    selMulti.add(id); sel=id;
  }
  if(selMulti.size<2) selMulti.clear();   // one box left is just a selection
  drawBoxes(); drawOverlay(); renderList();
  if(selMulti.size>1) toast(`${selMulti.size} boxes selected`, 900);
}
/* Called by every redraw: drops ids that left the page and never lets the set
   drift out of step with `sel`. */
function syncMulti(){
  if(sel==null){ selMulti.clear(); return; }
  for(const id of [...selMulti])
    if(!regions.some(r=>r.id===id)) selMulti.delete(id);
  if(selMulti.size){ selMulti.add(sel); }
  if(selMulti.size<2) selMulti.clear();
}

/* ---- 1–8 set the text type of everything selected (Original tab) ----

   **1, 2 and 3 are the three main types**, always, in the order the menu
   lists them - balloon, outside text, sound effect. lee: *"the 1,2,3 shodu be
   the deahut shortcuts with teh defaut bubble"*. They are the only three keys
   that mean the same thing on every page of every project, which is what
   makes them worth learning.

   **4 to 8 are the sub-types of the family the box is already in.** A box has
   a family before it has a sub-type, so "the fourth one" is only a question
   once you know which family is being asked about - and the answer is the one
   the box is in. `kindLabel` lives in panels.js and reads for a sub-type too,
   so a toast never says "ck_angry". */
/* 1, 2, 3 and nothing else. lee: *"only 1,2,3 shud work to swith box types"*.

   4 upwards used to reach into the SELECTED box's family and pick a sub-type
   out of it by position, which means the same key did a different thing
   depending on what was already selected - 4 on a bubble and 4 on a caption
   were two different types, and there was nothing on screen numbering them.
   The three families are the three you can name, and they are numbered the
   same way in the legend and in the Kind menu. Sub-types are still a menu
   away, where they are written out. */
function kindForKey(n){
  return (n >= 1 && n <= 3) ? KIND_FAMILIES[n - 1] : null;
}
/* What a box you DRAW comes out as. Bubble text until told otherwise, which
   is what almost every hand-drawn box is. Set by clicking one of the three
   keys in the legend; see `renderLegend`. Held in memory only - it is a
   this-session preference like the zoom, not a property of the chapter. */
let newBoxKind = 'bubble';

function setNewBoxKind(kind){
  if(!KIND_FAMILIES.includes(kind)) return;
  newBoxKind = kind;
  if(typeof renderLegend==='function') renderLegend();
  // A kind you are about to draw and cannot see is a box that vanishes the
  // moment you finish the drag. Same reasoning as `setKindSelected`.
  if((hiddenKinds||[]).includes(kind) && typeof setKindShown==='function')
    setKindShown(kind, true);
  toast(`New boxes: ${kindLabel(kind)}.`);
}

async function setKindSelected(kind){
  const ids=selIds();
  if(!ids.length){
    // Nothing selected. The keypress used to be answered with "Select a box
    // first", which is true and useless; now it sets what the NEXT box you
    // draw will be, which is the only thing 1/2/3 could sensibly mean with no
    // box under them.
    const fam = (typeof familyOf==='function') ? familyOf(kind) : kind;
    if(KIND_FAMILIES.includes(fam)){ setNewBoxKind(fam); return; }
    toast('Select a box first.');
    return;
  }
  for(const id of ids) await upd(id,{kind});
  // A box set to a kind whose GROUP is put away disappears at that moment, and
  // the person who just pressed 3 sees the box vanish with no explanation.
  //
  // That is what lee was hitting: *"still cant make manual sfx boxes"*, on a
  // chapter whose pages all carry `hidden_kinds: ["sfx"]`. He pressed the key,
  // the box became a sound effect, the sound effects were hidden, and it went.
  // Nothing was broken and nothing said so.
  //
  // Asking for a box of a kind is asking to SEE it, so the group comes back
  // out. Its own switch is still there to put it away again on purpose.
  const fam = (typeof familyOf==='function') ? familyOf(kind) : kind;
  if((hiddenKinds||[]).includes(fam)){
    await setKindShown(fam, true);
    return;
  }
  toast(ids.length>1
    ? `${ids.length} boxes set to ${kindLabel(kind)}.`
    : `Set to ${kindLabel(kind)}.`);
}
/* ---- Alt + digits: renumber the selected box ----
   Hold Alt and type the position you want it to have - Alt+1 is #1,
   Alt+1+2 is #12 - then let Alt go to apply it. 0 and anything past the last
   box on the page are ignored: there is no such position to move to. */
let altBuf='';
function _altDigit(e){
  if(/^[0-9]$/.test(e.key)) return e.key;
  // Some keyboard layouts hand back a symbol for Alt+digit, so fall back to
  // the physical key.
  const m=/^(?:Digit|Numpad)([0-9])$/.exec(e.code||'');
  return m ? m[1] : null;
}
function _altFlush(){
  const s=altBuf; altBuf='';
  if(!s || sel==null) return;
  const n=parseInt(s,10);
  if(!n || n>regions.length){
    toast(regions.length
      ? `No position ${n} - this page has ${regions.length} box${regions.length===1?'':'es'}.`
      : 'No text on this page yet.', 1600);
    return;
  }
  const r=regions.find(x=>x.id===sel);
  if(r && (r.order??0)===n-1){ toast(`Already #${n}.`, 1100); return; }
  orderTo(sel, n-1);
}
window.addEventListener('keydown',e=>{
  if(!e.altKey || e.ctrlKey || e.metaKey) return;
  if(view!=='original' || _typingIn(e.target)) return;
  const d=_altDigit(e);
  if(d==null) return;
  e.preventDefault();
  // Alt+0 must be inert, and Alt+1..4 must not also retype the box - so the
  // plain-key handler further down never sees a digit pressed with Alt.
  e.stopImmediatePropagation();
  if(sel==null){ toast('Select a box first.', 1200); return; }
  if(altBuf.length>=3) altBuf='';        // no silly long numbers
  altBuf+=d;
  toast(`Move to #${altBuf}… (let Alt go)`, 1500);
});
window.addEventListener('keyup',e=>{ if(e.key==='Alt') _altFlush(); });
window.addEventListener('blur',()=>{ altBuf=''; });

async function delSelected(){
  const ids=selIds();
  if(ids.length<2){ if(ids.length) del(ids[0]); return; }
  // One undo entry for the whole batch: Ctrl+Z brings all of them back, in
  // their old positions, rather than one press per box.
  const snaps=ids.map(id=>_snap(regions.find(x=>x.id===id))).filter(Boolean)
    .sort((a,b)=>(a.order??0)-(b.order??0));
  const pg=cur;
  let last=null;
  for(const id of ids) last=await api(`/api/page/${cur}/region/${id}`,'DELETE');
  sel=null; selMulti.clear();
  setRegions((last&&last.regions)||[]);
  refreshPages();
  record('region-del', `${snaps.length} boxes deleted`,
    ()=>restoreRegions(pg,snaps));
  toast(`${ids.length} boxes deleted.`);
}

/* MERGE THE SELECTED BOXES INTO ONE.

   lee: *"also add a merge box button to the side bar that mrerges all the
   selected boxes"*, then *"add an m shoortcut foe that"*.

   The detector splits a balloon in two often enough -- two columns of one
   sentence, a line and its ruby -- and until now the only fix was to delete
   both and draw one by hand, which loses the text that was already read.

   ## WHAT SURVIVES

   The FIRST box in reading order keeps its identity: its id, its kind, its
   link, its order. It gets the union of every rectangle, and the texts of the
   others appended to its own in reading order -- because the alternative is
   choosing one text to keep and silently dropping the rest, and a translator
   discovering that half a sentence is gone has no way of knowing it was ever
   there.

   The kind is the FIRST box's and not a vote, for the same reason: a merge is
   somebody saying "these are one thing", and the thing they clicked first is
   the one they were looking at.

   ## ONE UNDO ENTRY

   Ctrl+Z brings all of them back where they were, like `delSelected` -- a
   merge that took four presses to undo would be a merge nobody trusted. */
/* `ids` is optional and the right-click menu always passes it.

   The menu is built from `selIds()` when it OPENS, and read the selection
   again when a row was clicked - so anything that touched the selection in
   between (a redraw landing while the menu was up, `syncMulti` finding `sel`
   null and clearing the set) left a menu offering "Merge 3 boxes" over a
   merge that saw one box and quietly did nothing. lee: *"thsi donst work when
   multtiple boxes are slected"*.

   So the menu says what it will act on and then acts on exactly that. */
async function mergeSelected(ids){
  ids = (ids && ids.length) ? ids.slice() : selIds();
  if(ids.length < 2){ toast('Select two or more boxes to merge.'); return; }
  const rs = ids.map(id => regions.find(x => x.id === id)).filter(Boolean)
               .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  // ...and when the boxes it named are not there any more, it says THAT
  // rather than "select two or more", which is a puzzle with three selected.
  if(rs.length < 2){
    toast(ids.length >= 2 ? 'Those boxes are not on this page any more.'
                          : 'Select two or more boxes to merge.');
    return;
  }
  /* ONE TYPE ONLY. lee: *"male it so that i can only merge boxes of the same
     type"*.

     The merged box has to be SOME type, and it was quietly the first one's -
     so merging a sound effect into a balloon turned the sound into dialogue,
     and the reverse hid a line from the cleaning pass. Neither is anything
     you asked for by dragging a box over another. */
  const kinds = [...new Set(rs.map(r => r.kind || 'bubble'))];
  if(kinds.length > 1){
    toast('Boxes have to be the same type to merge - '
          + kinds.map(kindLabel).join(' and ') + ' here.');
    return;
  }
  const snaps = rs.map(_snap).filter(Boolean);
  const pg = cur;
  // The union of every rectangle, which is the box lee asked for: *"it shoud
  // dlete the curent boxes and make a new box taht fits all the boxes inside
  // of it"*.
  const x0 = Math.min(...rs.map(r => r.bbox[0]));
  const y0 = Math.min(...rs.map(r => r.bbox[1]));
  const x1 = Math.max(...rs.map(r => r.bbox[0] + r.bbox[2]));
  const y1 = Math.max(...rs.map(r => r.bbox[1] + r.bbox[3]));
  const join = (k) => rs.map(r => (r[k] || '').trim()).filter(Boolean).join(' ');
  const kind = rs[0].kind;
  const src = join('src_text'), dst = join('dst_text');
  // DELETE FIRST, THEN DRAW ONE.
  //
  // Resizing the first box was the obvious way and it did not work: a region
  // carries `bbox`, `draw_box` and the fitted `bubble_bbox`, the server
  // re-measures some of them from the ink under the new rectangle, and what
  // came back was the old small box wearing a new number. A fresh box has
  // none of that history to fight -- it is drawn exactly where it is asked
  // for, the same call the "draw a box by hand" tool makes.
  for(const r of rs) await api(`/api/page/${cur}/region/${r.id}`, 'DELETE');
  const j = await api(`/api/page/${cur}/region`, 'POST', {
    x: Math.round(x0), y: Math.round(y0),
    w: Math.round(x1 - x0), h: Math.round(y1 - y0),
    snap: false, kind: kind});
  const made = j && j.region ? j.region.id : null;
  if(j && j.regions) setRegions(j.regions);
  // ...and the words the old boxes were carrying, put back on the new one.
  // Not in the POST: the create endpoint is about a rectangle, and a second
  // call is cheaper than a third meaning for one of its fields.
  if(made != null && (src || dst)) await upd(made, {src_text: src, dst_text: dst});
  sel = made; selMulti.clear();
  refreshPages();
  drawBoxes(); drawOverlay(); renderList();
  record('region-merge', `${rs.length} boxes merged`,
    async () => {
      // The merge MADE a box as well as deleting some - undo has to take
      // both back or the union box sits on top of the restored originals.
      // lee: *"if i undo a merge it shoud delete the merge box"*.
      if(made != null){
        try{ await api(`/api/page/${pg}/region/${made}`, 'DELETE'); }
        catch(e){ /* already gone: deleting it again is not a failure */ }
      }
      await restoreRegions(pg, snaps);
    });
  toast(`${rs.length} boxes merged.`);
}

/* A persistent banner + a pulsing highlight on the source box make it obvious
   the editor is waiting for you to click the second bubble. */
function startLink(id){
  linkPick=id;
  const r=regions.find(x=>x.id===id);
  let b=document.getElementById('linkbanner');
  if(!b){ b=document.createElement('div'); b.id='linkbanner';
    document.body.appendChild(b); }
  b.innerHTML=`&#128279; Linking bubble ${(r&&(r.order??0))+1} - `
    +`click another bubble on the page or in the list to join them `
    +`&nbsp;<b>Esc</b> to cancel`;
  b.style.display='block';
  drawBoxes();
}
function endLinkMode(){
  linkPick=null;
  const b=document.getElementById('linkbanner');
  if(b) b.style.display='none';
}
async function completeLink(a,b){
  const ra=regions.find(x=>x.id===a), rb=regions.find(x=>x.id===b);
  if(!ra||!rb||a===b) return;
  const g=ra.link||rb.link||(1+Math.max(0,...regions.map(x=>x.link||0)));
  await upd(a,{link:g});
  await upd(b,{link:g});
  toast(`Linked bubbles ${(ra.order??0)+1} + ${(rb.order??0)+1} - translated as one line.`);
}
async function linkNext(id){
  const r=regions.find(x=>x.id===id); if(!r) return;
  const nxt=regions.filter(x=>(x.order??0)>(r.order??0))
                   .sort((a,b)=>(a.order??0)-(b.order??0))[0];
  if(!nxt){toast('No next bubble in reading order to link to.');return;}
  await completeLink(id, nxt.id);
}
async function unlinkRegion(id){
  const r=regions.find(x=>x.id===id); if(!r||!r.link) return;
  const g=r.link;
  for(const x of regions.filter(y=>y.link===g)){ await upd(x.id,{link:0}); }
  toast('Unlinked.');
}
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&linkPick!=null){ endLinkMode(); drawBoxes();
    toast('Link cancelled.'); }
});
async function upd(id,patch){
  const r0=regions.find(x=>x.id===id);
  if(r0 && !upd._undoing){
    const keys=Object.keys(patch);
    const prev={}; keys.forEach(k=>prev[k]=r0[k]);
    // Named the way the side panel names them - see `regionInlineEditor`. The
    // undo list saying "Japanese changed" on a Korean chapter was the same
    // wrong word in a second place.
    const what=keys.map(k=>({src_text:'Input text',dst_text:'Output text',
      kind:'kind'}[k]||k)).join(', ');
    record('edit', `Region ${(r0.order??0)+1}: ${what} changed`,
      async ()=>{
        upd._undoing=true;
        try{ await upd(id, prev); } finally { upd._undoing=false; }
      });
  }
  const j=await api(`/api/page/${cur}/region/${id}`,'POST',patch);
  if(j.regions) setRegions(j.regions);
}
async function asDrawn(id){
  const r=regions.find(x=>x.id===id);
  const box=r.draw_box||r.bubble_bbox||r.bbox;
  const j=await api(`/api/page/${cur}/region/${id}`,'POST',
    {resnap:true,snap:false,bbox:box});
  if(j.regions) setRegions(j.regions);
}
async function resnap(id,snap){
  const r=regions.find(x=>x.id===id);
  // Re-snap works from the WRITING and finds the balloon round it again. Handing
  // it the balloon instead fed the last answer back in, so each press grew the
  // box: balloon -> balloon of the balloon -> half the panel.
  const j=await api(`/api/page/${cur}/region/${id}`,'POST',
    {resnap:true,snap:snap,bbox:r.bbox||r.bubble_bbox});
  if(j.regions) setRegions(j.regions);
}
/* Put deleted boxes back exactly as they were - the same Japanese and English,
   the same shape and polygon, the same typesetting, the same place in the reading
   order. The whole stored record goes back to the server, so nothing is rebuilt
   from a bare rectangle and nothing it carried is lost. */
async function restoreRegions(pg, snaps){
  let last=null;
  for(const rec of snaps)
    last=await api(`/api/page/${pg}/region/restore`,'POST',{region:rec});
  if(pg!==cur){ await showPage(pg); }      // undone from another page
  else { setRegions((last&&last.regions)||regions); }
  refreshPages();
}
/* A deep copy, because `regions` is replaced wholesale on the next reply and a
   reference would be pointing at nothing by the time undo runs. */
function _snap(r){ return r?JSON.parse(JSON.stringify(r)):null; }

async function del(id){
  const snap=_snap(regions.find(x=>x.id===id));
  const pg=cur;                            // undo belongs to THIS page
  // Nothing about a deleted box may still be in the air. A keystroke waiting
  // to be sent, and an edit whose save has not come home, are both filed under
  // the region's NUMBER - so anything left behind here is laid over whatever
  // holds that number next. The server does not hand a number out twice any
  // more, which is the other half of this; forgetting them is this half.
  // lee: *"when i deleet an text box and create a new one it come back with
  // teh same text as teh olde text box"*.
  if(typeof pendingEdit!=='undefined' && pendingEdit && pendingEdit.id===id)
    pendingEdit=null;
  if(typeof dropInFlight==='function') dropInFlight(id);
  const j=await api(`/api/page/${cur}/region/${id}`,'DELETE');
  sel=null; setRegions(j.regions); refreshPages();
  if(snap) record('region-del', `Region ${(snap.order??0)+1} deleted`,
    ()=>restoreRegions(pg,[snap]));
}

async function refreshPages(){proj=await api('/api/project');renderPages();}

/* Put a group of boxes away, or bring it back.
   `group` null means only the "every page" switch moved: the same set of
   hidden groups, applied to a different number of pages. Nothing is deleted -
   the server keeps every box and simply stops counting the hidden ones, so the
   page is refetched afterwards rather than patched, and the picture comes back
   without them typeset on it. */
async function setKindShown(group, on){
  const set=new Set(hiddenKinds||[]);
  if(group){ if(on) set.delete(group); else set.add(group); }
  const every=$('hideAllPages') ? $('hideAllPages').checked : hideEveryPage();
  const j=await api(`/api/page/${cur}/hidden`,'POST',
    {groups:[...set], all:every});
  if(!j || j.error) return;
  await refreshPages();          // the counts, the statuses, the other pages
  await showPage(cur);           // regions, the switches, and the picture
  renderInspector();
  const label=(BOX_GROUPS.find(g=>g[0]===group)||[,''])[1].toLowerCase();
  if(group) toast(`${on?'Showing':'Hiding'} ${label}`+
    (every?' on every page.':' on this page.'), 2600);
  else toast(every ? 'These choices now apply to every page.'
                   : 'These choices now apply to this page only.', 2600);
}

/* Put ONE box away, or bring it back - the eye on its row in the box list.

   The same rule as a whole group: nothing is deleted, the box stops being part
   of the page's work, and it comes back the moment the eye opens. The page is
   refetched rather than patched because a hidden box leaves `regions`
   entirely, and the row that replaces it comes from `hidden_rows`.

   lee: *"add a eye button ... that allow me to hid a box, just like i can hide
   all the sfx box"*. */
async function setBoxShown(id, on){
  if(setBoxShown._busy) return;                 // one flip at a time
  setBoxShown._busy=true;
  try{
    const was=(regions.find(x=>x.id===id)||
               (hiddenRows||[]).find(x=>x.id===id)||{});
    const n=(was.order??0)+1;
    const j=await api(`/api/page/${cur}/region/${id}`,'POST',{hidden:!on});
    if(!j || j.error){ toast('Could not hide that box.'); return; }
    // A server that predates this answers without the two lists, and would
    // otherwise look like "the box vanished".
    if(!('hidden_ids' in j)){
      toast('The server ignored it - restart the editor from the new zip '+
            'and hard-refresh (Ctrl+Shift+R).');
      return;
    }
    await refreshPages();
    await showPage(cur);
    renderInspector();
    record('hidden', `Box ${n} ${on?'shown':'hidden'}`,
      async ()=>{ await api(`/api/page/${cur}/region/${id}`,'POST',{hidden:on});
                  await refreshPages(); await showPage(cur); });
    toast(on ? `Box ${n} is back.` : `Box ${n} put away.`, 2200);
  } finally { setBoxShown._busy=false; }
}

/* Move a region one step earlier or later in the reading order. The server
   renumbers the whole page and keeps the choice - geometry will not undo a
   number a human set. */
async function orderTo(id,to){
  const r=regions.find(x=>x.id===id); if(!r) return;
  to=Math.max(0,to);
  if(to===(r.order??0)) return;
  const j=await api(`/api/page/${cur}/region/${id}`,'POST',{order:to});
  if(j&&j.regions){
    setRegions(j.regions);
    record('order', `Text moved to position ${to+1} in the reading order`, null);
  }
}
async function moveOrder(id,delta){
  const r=regions.find(x=>x.id===id); if(!r) return;
  await orderTo(id,(r.order??0)+delta);
}

/* Rows in "Text on this page" can simply be dragged into place - the
   arrows stay for one-step nudges, a drag covers the long hauls. */
let listDrag=null;
function listDragStart(e,id){
  listDrag=id;
  e.dataTransfer.effectAllowed='move';
  try{ e.dataTransfer.setData('text/plain',String(id)); }catch(_){}
}
function listDragOver(e,card){
  if(listDrag==null) return;
  e.preventDefault();
  const r=card.getBoundingClientRect();
  const before = e.clientY < r.top + r.height/2;
  card.classList.toggle('ins-t',before);
  card.classList.toggle('ins-b',!before);
}
function listDragLeave(card){ card.classList.remove('ins-t','ins-b'); }
async function listDrop(e,card,targetId){
  e.preventDefault(); e.stopPropagation();
  card.classList.remove('ins-t','ins-b');
  const id=listDrag; listDrag=null;
  if(id==null||id===targetId) return;
  const src=regions.find(x=>x.id===id), tgt=regions.find(x=>x.id===targetId);
  if(!src||!tgt) return;
  const r=card.getBoundingClientRect();
  const before = e.clientY < r.top + r.height/2;
  let to=(tgt.order??0)+(before?0:1);
  if((src.order??0)<to) to--;      // taking src out shifts everything below up
  await orderTo(id,to);
}

/* ---------------- mouse: draw / move / resize ----------------
   Rule: snapping applies when you DRAW a new box, never when you move or
   resize one. Re-snapping an edit would just undo it, which is what made
   resizing look broken. Hold Shift to invert whichever applies.          */
let drag=null;

function clamp(v,lo,hi){return Math.max(lo,Math.min(hi,v));}
function pt(e){
  const b=$('img').getBoundingClientRect();
  return {x:clamp(e.clientX-b.left,0,b.width), y:clamp(e.clientY-b.top,0,b.height)};
}
// Off by default: most of the time the rectangle you drew is what you meant.
// Hold Shift while releasing to invert whatever the toggle says.
/* The snap toggle is gone: new boxes always snap to the bubble outline they
   were drawn inside (hold Shift while releasing for an exact box). */
/* Boxes never snap to the balloon outline any more, and there is no switch
   for it. lee: *"remove this and make it so that the the box never snapes
   anymore"* - a box you drew jumping to whatever outline it landed on was
   undoing the drawing you had just done, and the box is the WRITING, not the
   balloon. The server still knows how to snap; nothing asks it to. */
function snapOn(){ return false; }
/* The Translated tab is for reading the result, so boxes stay out of the way
   there unless you ask for them. The toggle still wins if you tick it. */
/* Placing a text box of your own.

   Every other box on the page stands for writing that is already in the
   artwork - found, read, translated, and the original erased under the
   English. This one stands for nothing that was there: it is a place you
   want words. lee: *"add a way to allow me to add text boxes independently
   of teh boxes"*.

   Armed, the next drag on empty page draws one, on whichever view you are
   looking at. It puts itself away afterwards, so it cannot swallow the next
   drag by surprise; and arming it puts any paint tool down, the same way
   picking a text box does. */
let addingText=false;
function toggleAddText(on){
  addingText = (on===undefined) ? !addingText : !!on;
  if(addingText && typeof stopBrush==='function' && typeof paintArmed==='function'
     && paintArmed()) stopBrush();
  const b=$('addTextBtn'); if(b) b.classList.toggle('pri', addingText);
  const st=$('stage'); if(st) st.style.cursor = addingText ? 'crosshair' : '';
  const cw=$('canvasWrap'); if(cw) cw.classList.toggle('addingtext', addingText);
}
function stopAddText(){ if(addingText) toggleAddText(false); }

/* A SOUND-EFFECT BOX BY HAND -- and there is no tool for it, on purpose.

   There was one, twice. First as the second tool in the toolbox's text slot,
   behind a right-click, on a view the toolbox does not appear on; lee: *"still
   cant make manual sfx boxes"*. Then as a `+ Sound effect` button beside Hide
   boxes, which he could see and did not want: *"i dont want a button i wan to
   be able to clcik 3 to st teh button to a sond affct like the manga
   version"*.

   He is right, and the second attempt was the sillier of the two: **the manga
   way already worked here.** Draw a box on the Translation view, and press 3 -
   `kindForKey` has meant balloon / outside text / sound effect on 1, 2 and 3
   since he asked for those keys. A tool that arms a mode so the NEXT drag
   comes out as a sound effect is a second way to do a thing one key already
   does, and a mode you can leave armed by accident.

   What was actually stopping him is in `setKindSelected`: a box set to a kind
   whose group is hidden disappears, and the sound effects are hidden on his
   pages. That is fixed where it lives, not with a tool. */

let boxPrefBeforeText=null;
function boxesHidden(){
  // On the Translated tab the region boxes stay out of the way unless you
  // deliberately ask for them with B.
  return $('hideboxes').checked;
}

/* ============================ the right-click menu on boxes ============
   lee: *"add a right clcik setting for boxes that allwa me to mege ,
   delete  And othrer stuff"*. The same actions the side panel and the keys
   offer, at the cursor - nothing here is a THIRD way to do anything, every
   row calls the function the panel already calls. Right-clicking a box that
   is not selected selects it first (keeping a multi-selection it is part
   of), so the menu always describes the boxes it will act on. */
function boxMenuClose(){ const f=$('boxmenu'); if(f) f.remove(); }

function boxMenu(ev, id){
  boxMenuClose();
  if(typeof pgMenuClose==='function') pgMenuClose();
  const ids = selIds();
  const many = ids.length;
  const r = regions.find(x=>x.id===id);
  if(!r) return;
  const row = (label, act, extra='') =>
    `<button class="tbrow" ${extra} onclick="boxMenuClose();${act}">`+
    `<span>${label}</span></button>`;
  const hr = '<div class="tbhr"></div>';
  let h = '';
  // Merge is offered only when it would work: two or more boxes, all of one
  // type. A row that answers with a refusal is a row that should not be lit.
  const oneKind = new Set(ids.map(i => {
    const q = regions.find(x => x.id === i); return q ? (q.kind || 'bubble') : '';
  })).size === 1;
  if(many >= 2 && oneKind)
    h += row(`Merge ${many} boxes <i class="mkey">M</i>`,
             `mergeSelected(${JSON.stringify(ids)})`);
  h += row(many >= 2 ? `Delete ${many} boxes <i class="mkey">Del</i>`
                     : 'Delete <i class="mkey">Del</i>', 'delSelected()');
  h += hr;
  h += row('Bubble text <i class="mkey">1</i>',
           "setKindSelected('bubble')");
  h += row('Freefloat text <i class="mkey">2</i>',
           "setKindSelected('freefloat')");
  h += row('Sound effect <i class="mkey">3</i>',
           "setKindSelected('sfx')");
  h += hr;
  if(many < 2){
    h += row('Split&hellip;', `splitRegion(${id})`);
    h += row('Link to another bubble&hellip; <i class="mkey">L</i>',
             `startLink(${id})`);
    h += row('Link to next', `linkNext(${id})`);
    h += hr;
  }
  h += row(many >= 2 ? 'Hide these boxes' : 'Hide this box',
           many >= 2 ? 'selIds().forEach(i=>setBoxShown(i,false))'
                     : `setBoxShown(${id},false)`);
  const f = document.createElement('div');
  f.id = 'boxmenu'; f.className = 'tbflyout';
  f.innerHTML = h;
  document.body.appendChild(f);
  const b = f.getBoundingClientRect();
  f.style.left = Math.round(Math.max(8,
    Math.min(ev.clientX, window.innerWidth - b.width - 8))) + 'px';
  f.style.top = Math.round(Math.max(8,
    Math.min(ev.clientY, window.innerHeight - b.height - 8))) + 'px';
}

$('stage').addEventListener('contextmenu', e=>{
  const box = e.target.closest('.box');
  if(!box) return;                 // empty page keeps the browser's own menu
  const r = regions.find(x=>x.id==box.dataset.id);
  if(!r) return;
  // Text hidden means text untouchable - same rule as the left click above.
  if(view==='typeset' && !inText()) return;
  e.preventDefault(); e.stopPropagation();
  if(!selMulti.has(r.id) && sel!==r.id){
    sel = r.id; selMulti.clear();
    drawBoxes(); renderList();
  }
  boxMenu(e, r.id);
});
document.addEventListener('click', e=>{
  if(!e.target.closest || !e.target.closest('#boxmenu')) boxMenuClose();
});
document.addEventListener('keydown', e=>{
  if(e.key==='Escape') boxMenuClose();
});

$('stage').addEventListener('mousedown',e=>{
  if(e.button!==0) return;
  const hd=e.target.closest('.hd,.rotz'), box=e.target.closest('.box');

  if(!box){
    // A shape is picked up by clicking it, the same as a text box.
    // lee: *"make it so that i can select shapes like i can text boxes"*.
    // The arrow (V) had to be armed first, so on a page with a rectangle on
    // it the obvious click - straight at the rectangle - did nothing at all,
    // and nothing on screen said which tool was missing. Now the click arms
    // the arrow itself and hands you the shape. A tool that IS armed keeps
    // the click: a brush stroke across a shape must still paint.
    if(view==='typeset' && !addingText && typeof shapeAt==='function'
       && !(typeof paintArmed==='function' && paintArmed())
       && !(typeof xf!=='undefined' && xf)){
      const s=shapeAt(canvasPt(e));
      if(s){
        if(typeof toggleShapeEdit==='function') toggleShapeEdit(true);
        layerSel=s.id;
        if(typeof renderLayers==='function') renderLayers();
        if(typeof xfStart==='function') xfStart(s);
        e.preventDefault(); e.stopPropagation(); return;
      }
    }
                                              // draw a new box
    // A text box of your own goes on any view - it is placed where you want
    // words, and the Translated view is where you can see whether they land
    // in the right spot. Everywhere else an empty-space drag was too easy to
    // do by accident, so the ordinary new-bubble drag stays on Original.
    if(view!=='original' && !addingText) return;
    const p=pt(e);
    drag={mode:'new',x0:p.x,y0:p.y,own:addingText};
    const rb=$('rubber');
    rb.style.cssText=`display:block;left:${p.x}px;top:${p.y}px;width:0;height:0`;
    e.preventDefault(); return;
  }

  const r=regions.find(x=>x.id==box.dataset.id);
  if(!r) return;
  // Link mode: clicking any OTHER box on the page joins it to the pending one,
  // the same as clicking it in the sidebar list. Clicking the source box again
  // cancels. (Without this, a canvas click set `sel` directly and skipped the
  // link step entirely - you could only link from the list.)
  if(linkPick!=null){
    if(r.id!==linkPick){
      const from=linkPick; endLinkMode();
      completeLink(from, r.id)
        .then(()=>{sel=r.id;drawBoxes();drawOverlay();renderList();});
    } else {
      endLinkMode(); drawBoxes(); toast('Link cancelled.');
    }
    e.preventDefault(); e.stopPropagation(); return;
  }
  // Text hidden means text untouchable: on the Edit tab with the switch
  // off, region boxes are display only - no selection sneaks in.
  if(view==='typeset' && !inText()) return;
  // Ctrl+click (or "c" held) adds this box to the selection rather than
  // replacing it. No drag starts - you are picking, not moving.
  if(multiPick(e)){ toggleMulti(r.id); e.preventDefault(); e.stopPropagation(); return; }
  if(r.id!==sel || selMulti.size){             // select without rebuilding the DOM
    sel=r.id; selMulti.clear();
    document.querySelectorAll('.box,.tagf').forEach(b=>b.classList.remove('sel','msel'));
    box.classList.add('sel');
    const tf=document.querySelector(`.tagf[data-id="${r.id}"]`);
    if(tf) tf.classList.add('sel');
    addHandles(box);
    renderList();
  }
  const p=pt(e);
  if(hd && hd.dataset.c==='rot'){
    // Turning the box, from any of the four corner zones. The centre it turns
    // about is the box's own centre, on screen and on the server both, so the
    // angle is simply where the pointer stands relative to it - which is why
    // all four corners can drive the same drag without any of them needing to
    // know which corner it is.
    const [bx,by,bw,bh]=(r.bbox||r.bubble_bbox);
    drag={mode:'rotate', id:r.id, a0:(+(r.turn||0)||0),
          cx:(bx+bw/2)*scale, cy:(by+bh/2)*scale};
    drag.grab=Math.atan2(p.y-drag.cy, p.x-drag.cx)*180/Math.PI;
    e.preventDefault(); e.stopPropagation(); return;
  }
  if(inText() && r.layout){
    // In the translated view a drag moves the typesetting inside its bubble,
    // which is what you actually want to adjust at this stage.
    const ov=r.layout_override||{};
    drag={mode:'text', x0:p.x, y0:p.y, id:r.id,
          dx0:+(ov.dx||0), dy0:+(ov.dy||0)};
  } else {
    // Drag the box that is ON SCREEN, which is the writing (bbox), not the
    // balloon behind it. Taking the balloon's rectangle here meant grabbing a
    // box and watching a different, larger rectangle move instead.
    drag={mode:hd?'resize':'move', corner:hd?hd.dataset.c:null,
          x0:p.x, y0:p.y, bb:(r.bbox||r.bubble_bbox).slice(), id:r.id};
  }
  e.preventDefault(); e.stopPropagation();
});

window.addEventListener('mousemove',e=>{
  if(!drag) return;
  const p=pt(e);
  if(drag.mode==='new'){
    const rb=$('rubber');
    rb.style.left=Math.min(p.x,drag.x0)+'px'; rb.style.top=Math.min(p.y,drag.y0)+'px';
    rb.style.width=Math.abs(p.x-drag.x0)+'px'; rb.style.height=Math.abs(p.y-drag.y0)+'px';
    return;
  }
  const el=document.querySelector(`.box[data-id="${drag.id}"]`); if(!el) return;
  if(drag.mode==='rotate'){
    const now=Math.atan2(p.y-drag.cy, p.x-drag.cx)*180/Math.PI;
    let a=drag.a0+(now-drag.grab);
    // Shift snaps to fifteens, for the angles you actually want: level, a
    // quarter, and the eighths in between.
    if(e.shiftKey) a=Math.round(a/15)*15;
    a=Math.max(-89, Math.min(89, Math.round(a*10)/10));
    drag.live=a;
    el.style.transform=`rotate(${a}deg)`;
    $('modehint').textContent=`Turning  ${a.toFixed(1)}\u00b0`;
    $('modehint').style.display='block';
    return;
  }
  const dx=(p.x-drag.x0)/scale, dy=(p.y-drag.y0)/scale;
  if(drag.mode==='text'){
    drag.live=[Math.round(drag.dx0+dx), Math.round(drag.dy0+dy)];
    // move the drawn text straight away - no round trip while dragging
    const grp=document.querySelector(`.tgrp[data-id="${drag.id}"]`);
    if(grp){
      grp.classList.add('moving');
      grp.style.transform=
        `translate(${(drag.live[0]-drag.dx0)*scale}px,${(drag.live[1]-drag.dy0)*scale}px)`;
    }
    $('modehint').textContent=`Moving text  x ${drag.live[0]}  y ${drag.live[1]}`;
    $('modehint').style.display='block';
    return;
  }
  let [x,y,w,h]=drag.bb;
  if(drag.mode==='move'){x+=dx;y+=dy;}
  else{
    if(drag.corner.includes('n')){y+=dy;h-=dy;} else h+=dy;
    if(drag.corner.includes('w')){x+=dx;w-=dx;} else w+=dx;
  }
  if(w<0){x+=w;w=-w;} if(h<0){y+=h;h=-h;}     // allow dragging past the far edge
  w=Math.max(8,w); h=Math.max(8,h);
  drag.live=[Math.round(x),Math.round(y),Math.round(w),Math.round(h)];
  el.style.left=x*scale+'px'; el.style.top=y*scale+'px';
  el.style.width=w*scale+'px'; el.style.height=h*scale+'px';
  // the floating order number rides along with the box, live
  const tg=document.querySelector(`.tagf[data-id="${drag.id}"]`);
  if(tg){ tg.style.left=(x*scale-9)+'px'; tg.style.top=(y*scale-9)+'px'; }
});

window.addEventListener('mouseup',async e=>{
  if(!drag) return;
  const d=drag; drag=null;

  if(d.mode==='new'){
    $('rubber').style.display='none';
    const p=pt(e);
    const x=Math.min(p.x,d.x0)/scale, y=Math.min(p.y,d.y0)/scale;
    const w=Math.abs(p.x-d.x0)/scale, h=Math.abs(p.y-d.y0)/scale;
    if(w<8||h<8){                              // a click, not a drag
      // clicking empty page puts the selection down - the corner handles
      // should not linger on a box you have moved on from
      if(sel!=null){ sel=null; drawBoxes(); renderList(); }
      return;
    }
    const j=await api(`/api/page/${cur}/region`,'POST',{
      x:Math.round(x), y:Math.round(y), w:Math.round(w), h:Math.round(h),
      snap: false,
      // The legend's lit key. An "own text" box is its own thing and is not
      // one of the three.
      ...(d.own ? {own_text:true, kind:'freefloat', text:'TEXT'}
                : {kind:newBoxKind})});
    if(d.own){
      stopAddText();
      // Lay it out at once. A box with no layout shows "not laid out yet"
      // instead of the typesetting controls, and the whole point of putting one
      // down is to type into it - so it arrives ready to edit.
      if(j.regions){ sel=j.region.id; setRegions(j.regions); refreshPages(); }
      return;
    }
    if(j.regions){
      sel=j.region.id; setRegions(j.regions); refreshPages();
    }
    return;
  }

  if(d.mode==='text'){
    if(!d.live) return;
    const r=regions.find(x=>x.id===d.id);
    const L=r.layout||{};
    const j=await api(`/api/page/${cur}/region/${d.id}`,'POST',{layout:{
      lines:L.lines||[], font_size:L.font_size, leading:L.leading,
      dx:d.live[0], dy:d.live[1]}});
    if(j.regions){
      setRegions(j.regions);
    }
    $('modehint').textContent='';
    $('modehint').style.display='none';
    return;
  }

  if(d.mode==='rotate'){
    $('modehint').textContent=''; $('modehint').style.display='none';
    if(d.live==null || d.live===d.a0) return;
    const j=await api(`/api/page/${cur}/region/${d.id}`,'POST',{turn:d.live});
    if(j.regions) setRegions(j.regions);
    return;
  }

  if(d.live){
    // A move or resize is a deliberate manual edit and is never re-snapped -
    // not even with Shift held, which used to be the escape hatch back INTO
    // snapping. The box stays exactly where you put it.
    const j=await api(`/api/page/${cur}/region/${d.id}`,'POST',
      {resnap:true, snap:false, bbox:d.live});
    if(j.regions) setRegions(j.regions);
  }
});

/* ---------------- keyboard ---------------- */
window.addEventListener('keydown',e=>{
  const a=e.target;
  // Real writing surfaces keep their keys; sliders, number boxes, buttons
  // and checkboxes do not - that lingering focus was why [ ] "sometimes"
  // did nothing after touching a control.
  const writing = a.tagName==='TEXTAREA' || a.isContentEditable ||
    (a.tagName==='INPUT' &&
     /^(text|search|password|email|url)$/.test(a.type||'text'));
  if(!writing && (e.key==='['||e.key===']') && paintArmed()){
    e.preventDefault(); nudgeBrush(e.key==='['?-1:1); return;
  }
  if(/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return;
  if(e.key==='Delete'||e.key==='Backspace'){
    // While painting (Edit view, a paint layer picked), Delete belongs to the
    // LAYERS - it must never quietly take out a text region instead.
    if(view==='typeset' && layerSel!=null && layers.some(l=>l.id===layerSel)){
      e.preventDefault(); deleteLayer(layerSel);
    } else if(sel!=null){ e.preventDefault(); delSelected(); }
  }
  // 1, 2, 3 retype the selected box(es) - the three families, in the order the
  // legend and the Kind menu put them in. Translation view only: on the other
  // one those keys belong to painting and typesetting.
  // lee: *"only 1,2,3 shud work to swith box types"*. It went to 8, and 4
  // upwards picked a sub-type by position out of whatever family the box was
  // already in - the same key doing a different thing depending on what was
  // selected, with nothing on screen numbering them.
  //
  // WHICH keys is `kindForKey`'s answer and nothing else's. The range used to
  // be written out here as well, so there were two places that had to agree
  // about it and one of them could be widened without doing anything - a key
  // swallowed by `preventDefault` and then dropped.
  else if(view==='original' && !e.altKey && sel!=null
          && kindForKey(+e.key)){
    e.preventDefault();
    setKindSelected(kindForKey(+e.key));
  }
  else if(e.key==='s'&&sel!=null) setKindSelected('sfx');
  // `l` arms the link: the next box you click is joined to this one. The
  // button in the sidebar does the same thing, but linking is a two-box job
  // and reaching for the mouse twice for it is one reach too many.
  // lee: *"if i lcik l while a box is selected ted it shoud start thelink
  // thing and i shoud be able to click another box to linkthem"*.
  else if((e.key==='l'||e.key==='L')&&sel!=null){ e.preventDefault();
    startLink(sel); }
  // Left and right turn the page and NOTHING else. Without this the browser
  // also scrolled the stage, so every page turn slid the page sideways under
  // you and had to be dragged back.
  else if(e.key==='ArrowRight'){
    e.preventDefault();
    if(cur<proj.pages.length-1) showPage(cur+1);
  }
  else if(e.key==='ArrowLeft'){
    e.preventDefault();
    if(cur>0) showPage(cur-1);
  }
  else if(e.key==='h'){toggleHand();}
  else if(e.key==='b'){$('hideboxes').checked=!$('hideboxes').checked;drawBoxes();}
  else if(e.key==='+'||e.key==='='){zoomBy(1.25);}
  else if(e.key==='-'){zoomBy(1/1.25);}
  else if(e.key==='0'){fitPage();}
  else if(e.key==='['&&(brush||stamp||eraser)){nudgeBrush(-1);}
  else if(e.key===']'&&(brush||stamp||eraser)){nudgeBrush(1);}
  else if(e.key==='Escape'){
    if(zoomTool){setZoomTool(null);return;}
    sel=null;drawBoxes();renderList();
  }
});
