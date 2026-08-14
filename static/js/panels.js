/* panels.js — Right-hand panels: region list, inspector, cleaning panel, typesetting panel.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* The tightest line gap the FITTER chooses for itself, the browser's copy of
   typeset.MIN_LEADING. It is what an unfitted box starts at; the box itself
   goes lower, because typing a number is a decision. A test holds the two
   numbers together. */
const MIN_LEADING = 1.20;

/* The link mark, as line art on the same 24-box as every tool icon. It was a
   🔗 emoji, which is a colour picture from the system font: a different weight,
   a different palette and a different size from everything beside it.
   lee: *"make the icon the same types as the other"*. */
function linkIcon(){
  return `<svg viewBox="0 0 24 24" width="11" height="11" aria-hidden="true"
    style="vertical-align:-1px;margin-right:3px"><path
    d="M10.2 13.8a4 4 0 0 0 5.7 0l3.1-3.1a4 4 0 0 0-5.7-5.7l-1.6 1.6M13.8 10.2
       a4 4 0 0 0-5.7 0l-3.1 3.1a4 4 0 0 0 5.7 5.7l1.6-1.6"
    fill="none" stroke="currentColor" stroke-width="1.9"
    stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

/* The eye, open or closed, as line art on the same 24-box as every tool icon —
   for the same reason the link mark is drawn rather than typed: an emoji is a
   colour picture from the system font, a different weight and size from
   everything beside it. */
function eyeIcon(open){
  return `<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"
    fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round"><path
    d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/><circle
    cx="12" cy="12" r="2.8"/>${open?'':'<path d="M4 20 20 4"/>'}</svg>`;
}

/* How a box was cleaned, in the person's words rather than the code's. The
   same names the chapter report uses, so a row and the report cannot describe
   the same thing differently. A count for the chapter says six boxes were
   filled flat; only the row can say WHICH six, which is the whole question
   when one of them is a column of outside text on artwork. */
const CLEAN_ROUTES={'flat fill':'filled flat','neural':'by the AI',
  'telea':'locally','pattern copy':'tone copied','fell back':'AI would not run'};
function cleanRouteLabel(k){ return CLEAN_ROUTES[k] || k; }

function renderList(){
  // Anything half-typed in the inspector is written out before this rebuilds
  // the DOM under it (see flushEdit in core.js).
  if(typeof flushEdit==='function') flushEdit();
  // ...and if a box in the list has the caret in it right now, the DOM under
  // it is not rebuilt at all. `flushEdit` only writes out the LAST change
  // noted; a rebuild mid-word takes the focus away and puts the field back
  // from `r.dst_text`, which is a keystroke behind by definition.
  // lee: *"sometime the text just revert back why im eddit it"*.
  const _live=document.activeElement;
  if(_live && $('list') && $('list').contains(_live)
     && /^(TEXTAREA|INPUT)$/.test(_live.tagName)){
    renderInspector();
    return;
  }
  // The proofreader's note about the page sits above the list, not inside a
  // region — it is usually about something BETWEEN two regions (a pronoun
  // with no clear owner, a line that does not answer the one before it).
  //
  // It is written FIRST, before the early return below, because it belongs to
  // the page on screen and nothing else here does. It used to be written after
  // that return, so in the Cleaned and Translated views — where the list is
  // hidden and this function stops early — the card was never touched again and
  // kept the note of whichever page had last been looked at in the Edit view,
  // sitting there on every page of the chapter. lee: *"these messages shoud
  // only be on teh relevenat page not on every page"*.
  //
  // Hidden with the plate, which has no text on it at all; kept in the
  // Translated view, where the English is exactly what is being read.
  const noteEl=$('pageNote');
  if(noteEl){
    const showNote = !!pageNote && view!=='clean';
    noteEl.style.display = showNote?'':'none';
    // Which boxes it is about, as the numbers on the page — the proofreader
    // works in region ids, which nobody ever sees. Clicking one selects it,
    // so "replaced the honorific" takes one click to check instead of a read
    // through the whole page.
    const ids=(typeof pageNoteIds!=='undefined'?pageNoteIds:[])
      .filter(id=>regions.some(r=>r.id===id));
    const chips = ids.map(id=>{
      const r=regions.find(x=>x.id===id);
      return `<b class="nchip" onclick="select(${id})"
        title="Show this box">${(r.order??0)+1}</b>`;
    }).join('');
    noteEl.innerHTML = showNote
      ? `<b>Proofreader:</b> ${esc(pageNote)}`
        + (chips?`<div class="nrow">Changed: ${chips}</div>`:'')
      : '';
  }
  // The Cleaned view is about the plate and the Translated view is about the
  // typesetting — the text list only takes up room on either.
  const hide = view==='clean' || view==='typeset';
  $('listHead').style.display = hide?'none':'';
  $('list').style.display = hide?'none':'';
  if(hide){ renderInspector(); return; }
  if(typeof syncMulti==='function') syncMulti();
  // Put away and still in its place. A hidden box used to be lifted out of
  // the list and stacked under a "Hidden" heading at the bottom, so putting
  // one away moved it, moved everything under it, and left you hunting for
  // the row you had just pressed. lee: *"when i click the eye button on teh
  // tab in screenshot 3 it shoud stay inplace instad of going to teh bottom,
  // and just grey out"*. It is greyed, it is not draggable and it does not
  // open — the eye is the one thing on it that answers — but it is exactly
  // where it was.
  const away=new Set((hiddenRows||[]).map(r=>r.id));
  // The list IS the translation: a row per piece of Japanese, with what it
  // says and what it will say. A box holding your own words is not one of
  // those, so it is not in here at all — it is edited on the page, in the
  // Edit view, where you drew it. lee: *"wheni create a text box its hsoud
  // JUST CREATE TEH ETXT BOX WITH NO TRANSLATION BOX"*.
  $('list').innerHTML=regions.filter(r=>!r.own_text).concat(hiddenRows||[])
    .sort((a,b)=>(a.order??0)-(b.order??0)).map(r=>{ const off=away.has(r.id);
      return `
    <div class="card lrow ${off?'away':''} ${r.id===sel&&!off?'on':''}${
      selMulti.has(r.id)&&!off?' msel':''}${r.link?' linked':''}"
      data-id="${r.id}"
      ${off?'':`onclick="select(${r.id},event)"
      draggable="false"
      ondragstart="listDragStart(event,${r.id})"
      ondragover="listDragOver(event,this)"
      ondragleave="listDragLeave(this)"
      ondragend="disarmRowDrag(this)"
      ondrop="listDrop(event,this,${r.id})"`}>
      <div class="row rowhead" ${off?'':'onmousedown="armRowDrag(this)"'}>
        <span class="chip num" ${off?'':'title="Drag to reorder"'}>${
          (r.order??0)+1}</span>
        <!-- No score on a box you drew yourself. Nothing read it and nothing
             was unsure of it, and a 1.00 beside your own rectangle is a
             confidence in a measurement that was never taken.
             lee: *"teh create text box is still creating a detection text
             box"*. -->
        ${r.own_text?'':`<span class="chip ${r.confidence>=0.55?'g':'r'}">${
          (r.confidence??0).toFixed(2)}</span>`}
        <span class="chip kind" title="${esc(kindLabel(r.kind))} — ${esc(familyLabel(familyOf(r.kind)))}"><i class="kd"
          style="background:${(typeof kindColor==='function')?kindColor(r.kind):'#888'}"></i><b
          class="kdn">${esc(kindLabel(r.kind))}</b></span>
        <!-- The "manual" chip is gone. Whether a box was drawn by hand or
             found by the detector is a fact about how it got here, not about
             what it is, and it took a slot on a row that has to fit on one
             line. lee: *"remove the manuel from the box"*. -->
        ${r.link?`<span class="chip link" title="Linked to #${r.link}"
           >${linkIcon()}${r.link}</span>`:''}
        <!-- The eye, hard right. One box put away or brought back, the same
             thing the group switches in the Current page card do for a whole
             kind at once. lee: *"i shud be able to hide individual boxes"*. -->
        <span class="beye ${off?'on':''}"
              title="${off?'Show this box':'Hide this box'}"
              onmousedown="event.stopPropagation()"
              onclick="event.stopPropagation();setBoxShown(${r.id},${off})"
          >${eyeIcon(!off)}</span></div>
      <div class="tx">${esc(r.dst_text)||'<span class="muted">not translated</span>'}</div>
      <!-- ...and no empty Japanese line under it either: there is no original
           to read, so "no text read" reads as a failure rather than as the
           absence of a question. -->
      ${r.own_text?'':`<div class="ja tx">${esc(r.src_text)||
        '<span class="muted">no text read</span>'}</div>`}
      <!-- No overflow warning here. It says something you can only act on in
           the Edit view — set the block smaller, widen the box, cut a word —
           and that is where it now lives, under the sub-type. Two copies of
           one sentence in two panels is one copy too many.
           lee, twice, with pictures: *"this shoud not be on this page anymore
           becasue its alraedy on teh edit page remve it"*. -->
      ${r.id===sel&&!off?regionInlineEditor(r):''}
    </div>`; }).join('')
    ||'<p class="muted">No regions. Drag on the page to add one.</p>';
  // On a NEW selection, scroll the freshly-expanded editor fully into view so
  // its buttons aren't stranded below the fold. Only on change, so it never
  // yanks the list while you're editing.
  if(sel!=null && renderList._scrolledFor!==sel){
    renderList._scrolledFor=sel;
    soon(()=>{
      const ed=$('list').querySelector('.lrow.on .rinline')
             || $('list').querySelector('.lrow.on');
      if(ed) ed.scrollIntoView({behavior:'smooth',block:'nearest'});
    });
  } else if(sel==null){ renderList._scrolledFor=null; }
  $('list').querySelectorAll('.rinline textarea').forEach(growBox);
  renderInspector();
}

/* A box that is exactly as tall as what is in it.

   These carried a resize grip and a fixed height, so every one of them was
   either cutting a line off or sitting half empty, and the only way to read a
   long line was to drag the corner. lee: *"get rid of teh expanding on the
   boxes ... it shou djust always fit the text"*. */
function growBox(t){
  if(!t) return;
  t.style.height='auto';
  t.style.height=(t.scrollHeight+2)+'px';
}

/* The region editor lives INSIDE the selected row (an accordion), so clicking a
   text on the page or in the list expands it in place rather than popping up a
   separate panel above the list. Clicks inside must not bubble to the row's
   select() — that would rebuild the list and drop focus mid-edit.

   The two boxes said "Japanese" and "English". On a Korean webtoon translated
   into English the first of those is simply wrong, and lee asked for what they
   actually are: *"make this say input text and output text"*. Whatever the
   languages happen to be, these are the two ends of the pipeline, and WHICH
   languages is a question already answered on the Settings page. The undo list
   named the same two fields the same wrong way — see `upd` in region-ops.js.

   (A note like this belongs here and not in the template below: an HTML
   comment inside the string is rendered into the panel, and this one would
   have put the word "Japanese" back into the DOM it is removing it from.) */
function regionInlineEditor(r){
  return `<div class="rinline" onclick="event.stopPropagation()">
      ${selMulti.size>1
        ? `<p class="help" style="margin:0 0 7px"><b>${selMulti.size} boxes selected</b></p>`
        : ''}
      ${kindSelects(r)}
      <label>Input text</label>
      <textarea rows="1"
                oninput="noteEdit(${r.id},'src_text',this.value);growBox(this)"
                onchange="flushEdit()">${esc(r.src_text)}</textarea>
      <label>Output text</label>
      <textarea rows="1"
                oninput="noteEdit(${r.id},'dst_text',this.value);growBox(this)"
                onchange="flushEdit()">${esc(r.dst_text)}</textarea>
      <div class="row" style="margin-top:9px;flex-wrap:wrap">
        <button onclick="splitRegion(${r.id})" title="This box covers several bubbles">Split</button>
        <button class="danger" onclick="delSelected()">Delete${
          selMulti.size>1?` ${selMulti.size} boxes`:''}</button>
      </div>
      <div class="row" style="margin-top:6px;flex-wrap:wrap;align-items:center">
        ${r.link
          ? `<span class="pill" title="Linked">${linkIcon()} linked #${r.link}</span>
             <button onclick="unlinkRegion(${r.id})">Unlink</button>`
          : `<button onclick="startLink(${r.id})"
                     title="Pick a bubble to link to">
               ${linkIcon()} Link…</button>
             <button onclick="linkNext(${r.id})"
                     title="Link to the next bubble">
               Link to next</button>`}
      </div>
    </div>`;
}
function esc(s){return (s||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));}

/* '#rrggbb' or 'rgb(r,g,b)' -> '#rrggbb', for <input type=color>. */
function cssHex(c, fallback){
  if(typeof c==='string'){
    const h=/^#([0-9a-f]{6})$/i.exec(c.trim());
    if(h) return '#'+h[1].toLowerCase();
    const m=/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/i.exec(c.trim());
    if(m) return '#'+[m[1],m[2],m[3]]
      .map(v=>(+v).toString(16).padStart(2,'0')).join('');
  }
  return fallback;
}

function renderInspector(){
  // Not while a stepper is held down. Rebuilding replaces the very button
  // being pressed, and a button that leaves the page between the press and
  // the release never reports the click at all. The release runs this again.
  if(typeof numHeld !== 'undefined' && numHeld) return;
  // Anything typed into the typesetting panel and not yet written down goes now,
  // before the DOM it was typed into is replaced. See flushTypesetEdit.
  if(typeof flushTypesetEdit==='function') flushTypesetEdit();
  // Never rebuild the panel out from under a control the person is using.
  // Every field in here saves on `change`, which the browser fires on BLUR —
  // and an element removed while it still has focus never blurs, so the change
  // is dropped and the field snaps back to the value the server last sent.
  // lee: *"when i make chnages in this menu sometime it dont apply or reverst
  // back"*. Chromium fires the event on removal and Firefox does not, which is
  // why this looked random. The redraw is deferred until the field is finished
  // with; nothing is lost, it just happens a moment later.
  //
  // A font dropdown is open, though, and that is not a field the panel is
  // waiting on — it is a menu the panel would DESTROY. lee, twice: *"the test
  // for this bubble is broken"*, and then *"this is still broken, when i open
  // it it opens and close and isnt repsosive after that"*. Opening the menu
  // moves focus into its own search box, which blurs whatever field was
  // focused before it — and any redraw that was waiting on that blur then
  // fired and replaced the whole panel, taking the just-opened menu with it.
  // From the outside: the list flickers open and shut, and the control you
  // were pointing at is not the one that is there now.
  // Two guards stood here, both of them about the custom font menu: one that
  // held the redraw while a `.fsel` list was open, and one that watched an
  // open menu until it closed however it closed. The picker is a native
  // <select> now (see `fontWidget` in project.js) — the browser owns it, a
  // redraw cannot destroy a list the browser is drawing over the page, and
  // holding the whole panel on a menu is what left it dead when the wait was
  // never released. lee: *"the text drop down still dosent work re design it
  // and remake it so taht it works"*. A focused select is still an
  // interaction, and the rule below covers it like any other field.
  const busy=document.activeElement;
  // A wait that is never released leaves the panel dead for the rest of the
  // session: every later redraw returns here and nothing on screen changes
  // again. `blur` alone is not enough to release it — an element removed from
  // the page while it still has focus does not reliably fire one, and this
  // panel replaces its own HTML constantly. So the wait is also released the
  // moment the element it is waiting on is gone.
  if(renderInspector._pending && renderInspector._on
     && !document.contains(renderInspector._on)){
    renderInspector._pending=false; renderInspector._on=null;
  }
  if(busy && $('inspector') && $('inspector').contains(busy)
     && /^(INPUT|TEXTAREA|SELECT)$/.test(busy.tagName)){
    if(!renderInspector._pending){
      renderInspector._pending=true;
      renderInspector._on=busy;
      // ...and the redraw runs a tick AFTER the blur, not during it. A blur is
      // the middle of an interaction, not the end of one: focus leaves the
      // field on MOUSEDOWN, before the click that follows has done anything.
      // Redrawing there tore the page out from under the click — the button
      // that was pressed was gone by the time its own handler ran, which is
      // what made the font dropdown open and shut again. One tick later the
      // interaction has finished and the panel can see what it turned into.
      const again=()=>{ busy.removeEventListener('blur',again);
                        renderInspector._pending=false;
                        renderInspector._on=null;
                        setTimeout(renderInspector, 0); };
      busy.addEventListener('blur',again);
    }
    return;
  }
  // Each view gets its own tools: Original is where regions are managed,
  // Cleaned is about the plate itself, Translated is about the typesetting.
  const r=regions.find(x=>x.id===sel);
  if(view==='clean' || (view==='typeset'&&(!r||!inText()))){
    $('inspector').innerHTML=cleanPanel();
    renderLayers();          // the fresh list must show the stored strokes
    paintToolUI();
    syncBrushFills();
    if(typeof selToolUI==='function'){ selToolUI(); selTolSync(selTol); }
    return;
  }
  if(view==='typeset'){
    $('inspector').innerHTML = r
      ? typesettingPanel(r)
      : `<div class="card"><h3>Translated view</h3></div>`;
    return;
  }
  // Original view: the region editor is folded INTO the selected list row
  // (see regionInlineEditor), so the inspector just says which page you are
  // looking at, with the shortcuts folded away underneath.
  $('inspector').innerHTML=pageCard();
}

/* The three groups of writing, named as the Find text dialog names them. One
   list, because what you can ask for and what you can put away are the same
   three things. */
/* The balloon types a typesetter names, and the order they are offered in.

   lee: *"Look for a manga translation guide to see what type of bubble i shoud
   use instad of speech bubble outide bubble etc"*. These are the standard
   ones — the shapes are drawn by the artist and the typesetter's job is to know
   which is which, so the app calls them what the guides call them rather than
   inventing names.

   Speech, thought and burst are all BALLOONS: a closed shape with a tail.
   What changes between them is the typesetting. A caption is the square
   narration box. Open typesetting is dialogue with no balloon at all, and a
   sound effect is drawn rather than typeset. */
/* The three families, in the order the menu offers them — which is also the
   order of the number keys 1, 2 and 3. See frames.js for the tables and
   kinds.py for why there are three. */
const KIND_ORDER = KIND_FAMILIES;
/* Every kind on offer: the three defaults, then whatever sub-types the person
   has made, grouped under the family each belongs to. */
function kindKeys(){
  return KIND_FAMILIES.reduce(
    (all,f)=>all.concat([f], subsOf(f).map(k=>k.key)), []);
}
function kindLabel(k){
  if(DEFAULT_LABELS[k]) return DEFAULT_LABELS[k];
  const s=subTypes().find(c=>c.key===k);
  return (s && s.label) || k;
}
function familyLabel(f){ return FAMILY_LABELS[f] || f; }

/* The two menus a box's type is now chosen with.

   lee: *"add a nothet drop down for the subcategories in the Text on this page
   tab"*. The main type says which of the three it is — that is what decides
   whether it has a balloon, whether it is cleaned, how it is typeset. The
   second says which KIND of that it is, which is a label and a colour and a
   font, and it is the person's alone: Find text never produces one.

   Changing the family drops the box on that family's default, because a
   thought balloon is not a kind of sound effect and carrying the sub-type
   across would mean nothing. A family with none of your own in it yet shows
   just its default rather than an empty menu. */
function kindSelects(r, pre){
  const fam=familyOf(r.kind);
  const subs=subsOf(fam);
  const id=n=>pre?` id="${pre}${n}"`:'';
  return `
    <label>Main type</label>
    <select${id('Fam')} onchange="setKindSelected(this.value)">
      ${KIND_FAMILIES.map(f=>
        `<option value="${f}"${f===fam?' selected':''}>`+
        `${esc(familyLabel(f))}</option>`).join('')}
    </select>
    <label>Sub-type</label>
    <select${id('Kind')} onchange="setKindSelected(this.value)">
      ${[fam].concat(subs.map(k=>k.key)).map(k=>
        `<option value="${k}"${k===r.kind?' selected':''}>`+
        `${esc(kindLabel(k))}</option>`).join('')}
    </select>`;
}
const BOX_GROUPS=KIND_FAMILIES.map(f=>[f, FAMILY_LABELS[f]]);

/* The key beside the page: what each colour on the boxes means.

   Built from the types this project actually has, not typed out — it used to
   list six flat types and their old colours, and after the revamp it was
   naming things that no longer existed in colours nothing was drawn in.
   lee: *"upadte teh bar with the type of boxes"*.

   The three main types come first, numbered, because 1, 2 and 3 are their
   keyboard shortcuts; the sub-types follow, grouped under whichever family
   they belong to and in the order the number keys hand them out. */
function renderLegend(){
  const el=$('legend'); if(!el) return;
  const bits=[];
  // ...and they are BUTTONS. lee: *"can you meke these 3 in the screenshoot
  // buttons adn make them diactaet twhat box is beign draw by degault"*. The
  // key already said what each colour means and what its number key is; now
  // the one that is lit is also the kind a box you draw comes out as, so
  // drawing three sound effects in a row is three drags rather than three
  // drags and three keypresses. Bubble text is lit at startup.
  KIND_FAMILIES.forEach((f,i)=>{
    const on = f===newBoxKind ? ' on' : '';
    bits.push(`<button type="button" class="lgmain${on}" data-fam="${f}" `+
              `onclick="setNewBoxKind('${f}')" `+
              `title="Draw new boxes as ${esc(FAMILY_LABELS[f])}`+
              ` — ${i+1} still sets the box you have selected">`+
              `<i style="background:${KIND_COLORS[f]}"></i>`+
              `${i+1} ${esc(FAMILY_LABELS[f])}</button>`);
  });
  // The three main types, and nothing under them. A row for every sub-type
  // as well made a paragraph of colour chips above the page that was longer
  // than anything it explained — and the shade of a box already says which
  // family it belongs to, which is the thing the legend is for.
  // lee: *"this shoud only show the 3 main type"*. Which sub-type a box is is
  // read off the box's own menu, one box at a time.
  bits.push('<span><i style="border:1px dashed #9aa4b2"></i>unsure</span>');
  el.innerHTML=bits.join('');
}

/* Which groups a switch is worth offering for.
   A switch for a kind the page does not contain does nothing, so only the
   groups there are boxes for get one — ask Find text for bubbles and outside
   text and no sound-effect switch appears. With "every page" on the question
   is about the CHAPTER, or a group could not be put away from a page that
   happens not to contain it. */
function groupsOffered(){
  if(hideEveryPage()){
    const all=new Set();
    ((proj&&proj.pages)||[]).forEach(p=>(p.kinds||[]).forEach(k=>all.add(k)));
    return all;
  }
  return new Set(kindsHere||[]);
}
function hideEveryPage(){
  return !!(proj&&proj.settings&&proj.settings.hide_all_pages);
}

/* Which page is on screen — name, position in the chapter, how much text is on
   it, and which kinds of box are in play. */
function pageCard(){
  const P=(proj&&proj.pages)||[];
  const p=P[cur];
  if(!p) return '';
  // One bubble and one box of your own is ONE piece of text to translate.
  // The count under the page name is the size of the job, and a box holding
  // lee's own words is not part of it.
  const n=regions.filter(r=>!r.own_text).length;
  const away=(p.hidden_boxes||0);
  const offer=groupsOffered();
  const rows=BOX_GROUPS.filter(([k])=>offer.has(k)).map(([k,label])=>{
    const on=!(hiddenKinds||[]).includes(k);
    return `<label class="opt hopt"><input type="checkbox" class="sw" ${on?'checked':''}
        onchange="setKindShown('${k}',this.checked)">
      <span><span class="kdot" style="background:${kindColor(k)}"></span>
      ${label}</span></label>`;
  }).join('');
  const hider = rows ? `
    <div style="margin-top:10px">
      <div class="muted" style="font-size:11px;text-transform:uppercase;
        letter-spacing:.06em">Show or hide</div>
      ${rows}
      <label class="opt hopt"><input type="checkbox" id="hideAllPages"
          ${hideEveryPage()?'checked':''} onchange="setKindShown(null,null)">
        <span>Apply to every page in the chapter</span></label>
    </div>` : '';
  return `<div class="card"><h3>Current page</h3>
    <div class="row" style="justify-content:space-between;align-items:baseline">
      <b style="font-size:13px;word-break:break-all">${esc(p.name||('Page '+(cur+1)))}</b>
      <span class="muted" style="flex:none">${cur+1} of ${P.length}</span></div>
    <div class="muted" style="margin-top:4px">
      ${n} text box${n===1?'':'es'}${away?` &middot; ${away} hidden`:''}${
        p.custom_clean ? ' &middot; your own cleaned page'
                       : (p.cleaned?' &middot; cleaned':'')}</div>
    ${hider}
  </div>`;
}

/* Which tool section the panel on screen is actually showing. A keyboard
   shortcut can arm a tool from a section that is not open — `toolTab()` then
   answers differently from what was drawn, and the lit button is on a tab
   nobody can see. paintToolUI compares the two and asks for a redraw. */
let _renderedTab=null;

function cleanPanel(){
  _renderedTab = toolTab();
  const custom = proj && proj.pages[cur] && proj.pages[cur].custom_clean;
  // sound effects are cleaned too now, so they belong in the per-region list
  const cleanable=regions;
  // With your own plate in use nothing on this page is ever cleaned, so the
  // per-bubble eyes have nothing to decide — showing them would promise a
  // choice that does nothing.
  const cleanLayers = (cleanable.length && !custom) ? `
  <div class="card"><h3>Cleaning per bubble</h3>
    <div class="scrolllist">
    ${cleanable.map(r=>`
      <div class="lay ${r.id===sel?'on':''}" onclick="select(${r.id})">
        <i style="background:${r.skip_clean?'#555':'#9fe870'}"></i>
        <span>Region ${(r.order??0)+1}${r.skip_clean?' — not cleaned'
          :(r.focus?' — focus':'')+(r.clean_route?' — '+esc(cleanRouteLabel(r.clean_route))
            +(r.clean_core?', strokes only':''):'')}</span>
        <span class="lx" title="${r.skip_clean?'Clean this bubble':'Leave the original text'}"
              onclick="event.stopPropagation();toggleClean(${r.id})">
          ${r.skip_clean?'&#8709;':'&#128065;'}</span>
        <span class="lx" title="${r.focus?'Read this box the ordinary way'
            :'Focus clean \u2014 read the writing against its own background, for gold '
             +'text or a see-through bubble the ordinary reading misses'}"
              style="${r.focus?'color:#ffd166':''}"
              onclick="event.stopPropagation();toggleFocus(${r.id})">&#9678;</span>
      </div>`).join('')}
    </div>
  </div>` : '';
  return cleanLayers + `<div class="card"><h3>Cleaned plate</h3>
    ${custom
      ? `<p class="help"><b>This page is excluded from cleaning.</b></p>
         <div class="row"><button class="danger" onclick="clearPlate()">Back to automatic</button></div>`
      : `<div class="row"><button class="pri" onclick="$('plateFile').click()">
           Use my own cleaned page…</button></div>`}
    <input id="plateFile" type="file" accept="image/*" style="display:none"
           onchange="uploadPlate(this.files[0]);this.value=''">
  </div>
  <div class="card"><h3>Tool settings</h3>
    <!-- The tools themselves are in the toolbox down the left of the page —
         one place, always on screen, with the ones that do the same kind of
         job folded into a slot. They used to be HERE as well, in four tabbed
         sections, so every tool was on screen twice and neither copy was
         obviously the real one. lee: *"the tools are duplicated it shoud only
         be onteh side bar"*.
         What is left is what a tool is set WITH: its colour, its size, its
         hardness, its tolerance. Those belong beside the page you are
         painting, not in a strip of icons. -->
    <div class="sl" id="rowTol" style="display:none">
      <span title="Tolerance">Tolerance</span>
      <input id="selTolR" type="range" min="0" max="128" value="32"
             oninput="selTolSync(this.value)">
      <input id="selTolN" type="number" min="0" max="128" value="32"
             oninput="selTolSync(this.value)"></div>
    <div class="row" id="rowShapeFill" style="display:none;margin-bottom:8px">
      <button id="shapeFillBtn" class="${shapeFill?'pri':''}"
              onclick="setShapeFill(!shapeFill)">
        ${shapeFill?'Filled':'Outline'}</button>
      <button id="deselBtn" onclick="selDeselect()">Deselect</button>
    </div>
    <div id="shapeListBox">${toolTab()==='shapes'?shapeList():''}</div>
    <div class="row" id="rowCol" style="align-items:center;gap:8px;margin-top:9px">
      <span class="colwell" id="brushWell" title="Brush colour" onclick="openPicker(this)">
        <i id="colChip" style="background:${brushState.col}"></i>
        <input id="brushCol" type="hidden" value="${brushState.col}">
        <b id="colHex">${brushState.col}</b></span>
      <button id="eyeBtn" class="${picking?'pri':''}" onclick="pickColour()"
              title="Eyedropper">
        <svg viewBox="0 0 24 24" width="13" height="13">
          <path fill="currentColor" d="M19.4 2.6a3 3 0 0 0-4.2 0l-2.1 2.1-1-1a1
            1 0 1 0-1.4 1.4l.3.3-7.6 7.6a2 2 0 0 0-.5.9l-.9 3.6a1 1 0 0 0 1.2
            1.2l3.6-.9a2 2 0 0 0 .9-.5l7.6-7.6.3.3a1 1 0 0 0 1.4-1.4l-1-1
            2.1-2.1a3 3 0 0 0 0-4.2ZM6.4 16.2l6.9-6.9 1.4 1.4-6.9 6.9-1.9.5.5-1.9Z"/>
        </svg></button>
    </div>
    <div class="sl" id="rowSize"><span title="[ and ] also step the size">Size</span>
      <input id="brushSz" type="range" min="1" max="60" value="${brushState.sz}"
             oninput="brushSync('Sz',this.value)">
      <input id="brushSzN" type="number" min="1" max="60" value="${brushState.sz}"
             oninput="brushSync('Sz',this.value)"></div>
    <div class="sl" id="rowOp"><span>Opacity</span>
      <input id="brushOp" type="range" min="1" max="100" value="${brushState.op}"
             oninput="brushSync('Op',this.value)">
      <input id="brushOpN" type="number" min="1" max="100" value="${brushState.op}"
             oninput="brushSync('Op',this.value)"></div>
    <div class="sl" id="rowHard"><span>Hardness</span>
      <input id="brushHard" type="range" min="0" max="100" value="${brushState.hard}"
             oninput="brushSync('Hard',this.value)">
      <input id="brushHardN" type="number" min="0" max="100" value="${brushState.hard}"
             oninput="brushSync('Hard',this.value)"></div>
  </div>
  <div class="card"><h3>Layers</h3>
    <div id="stackList" class="scrolllist"></div>
  </div>`;
}

/* The tool sections. `toolTab()` is a function, not a variable, because an
   ARMED tool decides which section is showing: arming the brush with a
   keyboard shortcut has to bring the Paint section up with it, or the lit
   button is on a tab nobody can see. */
const TOOL_TABS=[
  {k:'select',  label:'Select',  tip:'Marquee, lasso, wand, bucket fill and free transform'},
  {k:'paint',   label:'Paint',   tip:'Brush and eraser'},
  {k:'shapes',  label:'Shapes',  tip:'Rectangle, ellipse and line \u2014 and the arrow that moves them'},
  {k:'retouch', label:'Retouch', tip:'Clone stamp and the healing brush'},
];
let _toolTab='paint';
function toolTab(){
  if(typeof shapeKind!=='undefined' && (shapeKind || shapeEdit)) return 'shapes';
  if(typeof stamp!=='undefined' && (stamp || heal)) return 'retouch';
  if(typeof brush!=='undefined' && (brush || eraser)) return 'paint';
  if(typeof selTool!=='undefined' && (selTool || xf)) return 'select';
  return _toolTab;
}
function setToolTab(t){
  _toolTab=t;
  // Whatever was armed belonged to the section you just left. Leaving it
  // armed means a tool acting on the page with nothing on screen saying so.
  if(toolTab()!==t) disarmTools('none');
  _toolTab=t;
  if(typeof renderInspector==='function') renderInspector();
}

/* The shapes on this page, in the Shapes section, so they are where you are
   already looking when you want to change one. Clicking a row picks it, which
   opens the same colour / width / fill editor the layer list uses. */
function shapeList(){
  const list=(typeof layers!=='undefined'?layers:[]).filter(l=>l.type==='shape');
  if(!list.length) return `<p class="help" style="margin:6px 0 0">
    <i>No shapes on this page yet.</i></p>`;
  return `<div style="margin-top:8px">` + list.slice().reverse().map(l=>`
    <div class="lay ${l.id===layerSel?'on':''}" data-lid="${l.id}"
         onmousedown="layDown(event,${l.id})"
         title="Click to work on this shape">
      <i style="background:${l.col}"></i>
      <span class="lnm">${esc(layerName(l))}</span>
      <span class="lx" title="${l.visible!==false?'Hide':'Show'}"
            onclick="event.stopPropagation();toggleLayer(${l.id})"
        >${l.visible!==false?'&#128065;':'&#8709;'}</span>
      <span class="lx" title="Delete this shape"
            onclick="event.stopPropagation();deleteLayer(${l.id})">&times;</span>
    </div>
    ${l.id===layerSel?layerEditor(l):''}`).join('') + `</div>`;
}

let stackOpen=true, retouchOpen=false;
let strokesOpen=false;      // folded away until asked for
/* Opacity's default is 100, and `||` would turn a deliberate 0 into it. */
function _opOf(r, ov){
  const v = styleNow(r, ov, 'opacity', undefined);
  return (v===undefined || v===null || v==='') ? 100
    : Math.max(0, Math.min(100, +v || 0));
}

/* The typesetting panel is fourteen controls deep, and it used to be one
   unbroken strip of them — lee: *"make teh side bar more organized"*. They are
   grouped now, by the question each group answers, and each group remembers
   whether it was open. The controls themselves are untouched: same ids, same
   handlers, same order within a group.

   Every group starts OPEN — lee asked for that outright — and each remembers
   whether he folded it, so the panel comes back the way he left it. */
// lee: *"make all the section in the dide bar come open not collaped"*. They
// start open and stay however he leaves them.
// Every group starts open. A control folded away on a panel you have just
// opened is a control you have to go looking for, and the panel is short
// enough to read in one pass. `box` and `shape` are gone — the two menus moved
// to the head of the panel and the rest split into Paragraph and Character,
// the way a typesetter's panels are laid out — but they stay in this map so a
// browser holding the old state does not come back with anything shut.
var lyOpen = {text:true, para:true, char:true, colour:true, fx:true,
              shape:true, box:true};

/* Which edge the lines hang from. Everything was centred, which is right for
   a balloon and wrong for a caption box: a block of narration ranged left is
   what a typesetter sets, and there was no way to ask for it. */
function setAlign(id, how){
  const el=$('lyAlign'); if(el) el.value=how;
  document.querySelectorAll('.alignb').forEach(b=>b.classList.remove('pri'));
  const hit=[...document.querySelectorAll('.alignb')]
    .find(b=>(b.getAttribute('onclick')||'').includes(`'${how}'`));
  if(hit) hit.classList.add('pri');
  if(typeof onTypesetStyle==='function') onTypesetStyle(id);
}
function lyGrp(key, title, body){
  return `<details class="grp" ${lyOpen[key] ? 'open' : ''}
      ontoggle="lyOpen['${key}']=this.open">
    <summary>${title}</summary>
    <div class="grpbody">${body}</div></details>`;
}

/* What a typesetting control should SHOW.

   Two copies of every style value exist while an edit is in flight: the live
   one, kept on the region by onTypesetEdit as you type and refreshed from the
   server's reply, and the saved one in `layout_override`, which is only as
   fresh as the last request that finished. The panel is rebuilt constantly —
   a save landing, a poll, a stepper being released — so a field that reads the
   saved copy shows the value from BEFORE the edit and the next press starts
   from there.

   lee, on the outline box: *"i can manuly tye a number and wheni try to use
   teh arrow its reverts back to 1"*. Typing works because nothing rebuilds
   mid-keystroke; the arrow saves, the save rebuilds, and the rebuild read the
   stale copy.

   Live first, saved second, default last. `??` throughout: 0 is a real answer
   for an outline, a gap and an angle alike. */
function styleNow(r, ov, key, dflt){
  const st = (r && r.style) || {};
  return st[key] ?? (ov || {})[key] ?? dflt;
}

function typesettingPanel(r){
  const L=r.layout;
  if(!L) return `<div class="card"><h3>Typesetting</h3>
    <p class="help">Not laid out yet. Press <b>Typeset</b> in the toolbar,
    or <button onclick="api('/api/typeset_all','POST',{pages:[cur]});poll()">lay out this page</button>.</p></div>`;
  const edited = !!(r.layout_override && r.layout_override.locked);
  const ov = r.layout_override || {};
  return `<div class="card ${edited?'on':''}">
    <h3>Typesetting ${edited?'<span class="chip g">edited</span>':''}</h3>
    ${kindSelects(r, 'ly')}
    <!-- The Text box is gone: the words are typed on the PAGE, in the block
         itself, which is where you can see them land. A second copy of them in
         the panel was the same sentence in two places, and the two had to be
         kept in step with each other on every keystroke.
         lee, with a picture of it: *"remove this box"*.
         The line box still exists, hidden, because every control below reads
         the current wording from it and the save sends it. -->
    <textarea id="lyLines" style="display:none"
      oninput="onTypesetEdit(${r.id})"
      onchange="flushTypesetEdit()">${esc(L.lines.join('\n'))}</textarea>
    <!-- What went wrong laying this block out, where the block is being
         worked on. It used to be a chip in the box list, which is not on
         screen in the Edit view at all — so the one view where you would do
         something about it was the one view that never mentioned it.
         lee: *"this message sho8d show on teh edit page"*. -->
    ${r.flagged?`<div class="chip r lyflag">${esc(r.flagged)}</div>`:''}
    ${lyGrp('para','Paragraph',`
    <!-- What a typesetter sets for the BLOCK: how the lines sit against each
         other and where they hang in the box. lee sent Photoshop's Paragraph
         and Character panels and asked for *"only ... what you time will
         acuuucaly be useful"* — so no first-line indent, no space-before and
         space-after (there is one paragraph in a balloon), and no hyphenation,
         which this project has never done and never will. -->
    <label style="margin-top:0">Alignment</label>
    <input id="lyAlign" type="hidden" value="${styleNow(r,ov,'align','center')}">
    <div class="row alignrow">
      ${[['left','Left','M3 5h18M3 10h12M3 15h18M3 20h9'],
         ['center','Centre','M3 5h18M6 10h12M3 15h18M7 20h10'],
         ['right','Right','M3 5h18M9 10h12M3 15h18M12 20h9']].map(a=>`
        <button class="alignb ${styleNow(r,ov,'align','center')===a[0]?'pri':''}"
                title="${a[1]}" onclick="setAlign(${r.id},'${a[0]}')">
          <svg viewBox="0 0 24 24" width="14" height="14"><path d="${a[2]}"
            fill="none" stroke="currentColor" stroke-width="1.8"
            stroke-linecap="round"/></svg></button>`).join('')}
    </div>
    <div class="row" style="margin-top:7px">
      <div style="flex:1"><label style="margin-top:0"
           title="Line gap">Line gap</label>
        <input id="lyLead" type="number" min="0.7" max="3" step="0.05"
               value="${(+L.leading||MIN_LEADING).toFixed(2)}"
               oninput="onTypesetStyle(${r.id})"></div>
      <div style="flex:1"><label style="margin-top:0"
           title="Letter spacing">Letter gap</label>
        <input id="lyLspace" type="number" min="-10" max="40" step="0.5"
               value="${+styleNow(r,ov,'lspace',0)}"
               oninput="onTypesetStyle(${r.id})"></div>
    </div>
    <label style="display:flex;gap:7px;align-items:center;text-transform:none;
                  margin-top:9px">
      <input type="checkbox" id="lyCaps" style="width:auto"
             ${styleNow(r,ov,'caps',false)?'checked':''}
             onchange="onTypesetStyle(${r.id})">
      <span>ALL CAPS</span></label>
    `)}
    ${lyGrp('char','Character',`
    <label style="margin-top:0">Font</label>
    <select id="lyFont" class="fontsel" onchange="onTypesetStyle(${r.id})">
      <!-- Not "same as the bubble setting": you opened this menu to find out
           which face, and the one thing that was not on it was the name of
           the face. lee: *"it shoud just say the font"*. -->
      <option value="" data-name="${esc(inheritedFontLabel(r.kind))}"
        >${esc(inheritedFontLabel(r.kind))}</option>
      <!-- styleNow, not the saved override: a face picked a moment ago is
           in r.style and will not be in the override until the round trip
           lands. Reading the override meant that a rebuild in between put the
           OLD face back in the box, so the pick looked as though it had not
           taken. -->
      ${fontOptions(styleNow(r,ov,'font',''))}
    </select>
    <div class="row" style="margin-top:7px">
      <div style="flex:1"><label style="margin-top:0">Size</label>
        <input id="lySize" type="number" value="${L.font_size}"
               oninput="onTypesetEdit(${r.id})"
               onchange="flushTypesetEdit()"></div>
      <div style="flex:1"><label style="margin-top:0">Rotation</label>
        <input id="lyRot" type="number" step="1" value="${+(L.rotate||0)}"
               oninput="onTypesetEdit(${r.id})"
               onchange="flushTypesetEdit()"></div>
      <div style="flex:1"><label style="margin-top:0"
           title="Outline thickness">
           Outline</label>
        <!-- Falls back to the LAYOUT's outline, which is the number actually
             in use, and not to a bare 1. The saved style only exists after a
             save has been round-tripped, so on a freshly opened page the box
             said 1 while the canvas drew the width the fitter chose — three
             or four pixels on a sound effect. lee, with a screenshot of a
             heavily outlined COUGH: *"make sure the outile alway match, the
             caufht outline says 1 when it clearly not"*.
             The same fallback drawText uses, so the box and the letters on
             the page can only ever say the same thing. A colour well left
             blank means "automatic" and is honest; a number that says 1 when
             it is 3 is not. -->
        <input id="lyStroke" type="number" min="0" max="30" step="1"
               value="${styleNow(r,ov,'stroke',(r.layout&&r.layout.stroke)??1)}"
               oninput="onTypesetStyle(${r.id})"></div>
    </div>
    <div class="sl" title="Arc">
      <span>Curve</span>
      <input type="range" min="-180" max="180" step="5"
             value="${+styleNow(r,ov,'curve',0)}"
             oninput="$('lyCurve').value=this.value;onTypesetStyle(${r.id})">
      <input id="lyCurve" type="number" min="-180" max="180" step="5"
             value="${+styleNow(r,ov,'curve',0)}"
             oninput="onTypesetStyle(${r.id})">
    </div>
    `)}
    ${/* The two 5-degree nudges and the Straighten button used to sit here.
         lee: *"get rid of these"*. A box turns from any of its four corners
         now, and the number box above takes an exact angle. */''}
    ${lyGrp('colour','Colour',`
    <div class="row" style="margin-top:7px">
      <div style="flex:1"><label style="margin-top:0">Text colour</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lyFg',${r.id})">
          <i id="lyFgChip" style="background:${cssHex(styleNow(r,ov,'fg',L.fg),'#000000')}"></i>
          <input id="lyFg" type="hidden"
                 value="${cssHex(styleNow(r,ov,'fg',L.fg),'#000000')}">
          <b id="lyFgHex">${cssHex(styleNow(r,ov,'fg',L.fg),'#000000')}</b></span></div>
      <div style="flex:1"><label style="margin-top:0">Outline colour</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lyEdge',${r.id})">
          <i id="lyEdgeChip" style="background:${cssHex(styleNow(r,ov,'edge',L.edge),'#ffffff')}"></i>
          <input id="lyEdge" type="hidden"
                 value="${cssHex(styleNow(r,ov,'edge',L.edge),'#ffffff')}">
          <b id="lyEdgeHex">${cssHex(styleNow(r,ov,'edge',L.edge),'#ffffff')}</b></span></div>
    </div>
    <!-- Each well says which end of the gradient it IS, over the well, the
         way every other pair in this panel is labelled. The heading used to
         carry all three names in a row — "from / to / angle" — which meant
         reading a list and counting across to work out which box was which.
         lee: *"make the gradn say from to"*. -->
    <label style="margin-top:9px">Gradient</label>
    <div class="row" style="align-items:flex-end">
      <span style="flex:1">
        <label style="margin:0 0 3px">From</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lyFg1',${r.id})">
          <i id="lyFg1Chip" style="background:${cssHex(styleNow(r,ov,'fg1',''),'')||'transparent'}"></i>
          <input id="lyFg1" type="hidden"
                 value="${cssHex(styleNow(r,ov,'fg1',''),'')}">
          <b id="lyFg1Hex">${cssHex(styleNow(r,ov,'fg1',''),'')||'OFF'}</b></span></span>
      <span style="flex:1">
        <label style="margin:0 0 3px">To</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lyFg2',${r.id})">
          <i id="lyFg2Chip" style="background:${cssHex(styleNow(r,ov,'fg2',''),'')||'transparent'}"></i>
          <input id="lyFg2" type="hidden"
                 value="${cssHex(styleNow(r,ov,'fg2',''),'')}">
          <b id="lyFg2Hex">${cssHex(styleNow(r,ov,'fg2',''),'')||'OFF'}</b></span></span>
      <span style="width:56px">
        <label style="margin:0 0 3px">Angle</label>
        <input id="lyGrad" type="number" step="15" style="width:100%"
               value="${+styleNow(r,ov,'grad_angle',0)}"
               oninput="onTypesetStyle(${r.id})"></span>
      <button class="danger" title="No gradient"
              onclick="clearGradient(${r.id},'fg')">&times;</button>
    </div>
    <!-- The same three again, for the ring round the letters. It is a separate
         gradient with its own angle, not the fill\'s bent round the outside:
         a red-to-blue outline under a yellow-to-green fill is a perfectly
         ordinary piece of typesetting and neither should be deciding the other.
         lee: *"can you make it so that i can add gradient to the ouline of the
         text"*. -->
    <label style="margin-top:9px">Outline gradient</label>
    <div class="row" style="align-items:flex-end">
      <span style="flex:1">
        <label style="margin:0 0 3px">From</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lyEdge1',${r.id})">
          <i id="lyEdge1Chip" style="background:${cssHex(styleNow(r,ov,'edge1',''),'')||'transparent'}"></i>
          <input id="lyEdge1" type="hidden"
                 value="${cssHex(styleNow(r,ov,'edge1',''),'')}">
          <b id="lyEdge1Hex">${cssHex(styleNow(r,ov,'edge1',''),'')||'OFF'}</b></span></span>
      <span style="flex:1">
        <label style="margin:0 0 3px">To</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lyEdge2',${r.id})">
          <i id="lyEdge2Chip" style="background:${cssHex(styleNow(r,ov,'edge2',''),'')||'transparent'}"></i>
          <input id="lyEdge2" type="hidden"
                 value="${cssHex(styleNow(r,ov,'edge2',''),'')}">
          <b id="lyEdge2Hex">${cssHex(styleNow(r,ov,'edge2',''),'')||'OFF'}</b></span></span>
      <span style="width:56px">
        <label style="margin:0 0 3px">Angle</label>
        <input id="lyEdgeG" type="number" step="15" style="width:100%"
               value="${+styleNow(r,ov,'edge_angle',0)}"
               oninput="onTypesetStyle(${r.id})"></span>
      <button class="danger" title="No outline gradient"
              onclick="clearGradient(${r.id},'edge')">&times;</button>
    </div>
    <div class="sl" title="Opacity">
      <span>Opacity</span>
      <input type="range" min="0" max="100" step="1"
             value="${_opOf(r,ov)}"
             oninput="$('lyOpacity').value=this.value;onTypesetStyle(${r.id})">
      <input id="lyOpacity" type="number" min="0" max="100" step="1"
             value="${_opOf(r,ov)}"
             oninput="onTypesetStyle(${r.id})">
    </div>
    `)}
    ${lyGrp('fx','Effects',`
    <div class="row fxrow" style="margin-top:7px">
      <span style="flex:1"><label style="margin-top:0"
            title="Shadow">Shadow</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lySh',${r.id})">
          <i id="lyShChip" style="background:${cssHex(styleNow(r,ov,'shadow',''),'')||'transparent'}"></i>
          <input id="lySh" type="hidden"
                 value="${cssHex(styleNow(r,ov,'shadow',''),'')}">
          <b id="lyShHex">${cssHex(styleNow(r,ov,'shadow',''),'')||'off'}</b></span></span>
      <span style="width:52px"><label style="margin-top:0" title="Shadow distance, px">Dist</label>
        <input id="lyShD" type="number" min="0" max="30" step="1" style="width:100%"
               value="${+styleNow(r,ov,'sh_dist',2)}"
               oninput="onTypesetStyle(${r.id})"></span>
      <span style="width:52px"><label style="margin-top:0" title="Shadow softness, px">Blur</label>
        <input id="lyShB" type="number" min="0" max="30" step="1" style="width:100%"
               value="${+styleNow(r,ov,'sh_blur',3)}"
               oninput="onTypesetStyle(${r.id})"></span>
      <button class="danger" title="No shadow" onclick="clearShadow(${r.id})">&times;</button>
    </div>
    <div class="row fxrow" style="margin-top:7px">
      <span style="flex:1"><label style="margin-top:0"
            title="Outer glow">Outer glow</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lyGlow',${r.id})">
          <i id="lyGlowChip" style="background:${cssHex(styleNow(r,ov,'glow',''),'')||'transparent'}"></i>
          <input id="lyGlow" type="hidden"
                 value="${cssHex(styleNow(r,ov,'glow',''),'')}">
          <b id="lyGlowHex">${cssHex(styleNow(r,ov,'glow',''),'')||'off'}</b></span></span>
      <span style="width:52px"><label style="margin-top:0" title="How far the glow reaches, px">Size</label>
        <input id="lyGlowS" type="number" min="0" max="40" step="1" style="width:100%"
               value="${+styleNow(r,ov,'glow_size',6)}"
               oninput="onTypesetStyle(${r.id})"></span>
      <button class="danger" title="No outer glow" onclick="clearGlow(${r.id})">&times;</button>
    </div>
    <div class="row fxrow" style="margin-top:7px">
      <span style="flex:1"><label style="margin-top:0"
            title="Inner glow">Inner glow</label>
        <span class="colwell" style="width:100%;box-sizing:border-box"
              onclick="openTypesetPicker(this,'lyIGlow',${r.id})">
          <i id="lyIGlowChip" style="background:${cssHex(styleNow(r,ov,'iglow',''),'')||'transparent'}"></i>
          <input id="lyIGlow" type="hidden"
                 value="${cssHex(styleNow(r,ov,'iglow',''),'')}">
          <b id="lyIGlowHex">${cssHex(styleNow(r,ov,'iglow',''),'')||'off'}</b></span></span>
      <span style="width:52px"><label style="margin-top:0" title="How far in from the edge, px">Size</label>
        <input id="lyIGlowS" type="number" min="0" max="40" step="1" style="width:100%"
               value="${+styleNow(r,ov,'iglow_size',5)}"
               oninput="onTypesetStyle(${r.id})"></span>
      <button class="danger" title="No inner glow" onclick="clearIGlow(${r.id})">&times;</button>
    </div>
    `)}
  </div>`;
}
