/* project-io.js — Export dialog + zip download, new chapter, settings dialog, custom kinds, staged uploads + drag-drop.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* ---------------- export ---------------- */
let lastExportDir='';

async function exportDialog(){
  const d=await api('/api/suggest_dirs');
  $('expDir').value = d.current || '';
  $('expName').value = d.name || 'pages';
  const so=$('expScope');
  so.options[1].textContent = 'Only this page — ' +
    (proj.pages[cur] ? proj.pages[cur].name : '');
  so.value='all';
  $('expMode').value='full';
  _expNameWas='';
  expModeChanged();
  const can=await api('/api/can_browse');
  $('expBrowse').style.display = can.ok ? '' : 'none';
  updateExpPath();
  ['expDir','expName'].forEach(id=>$(id).oninput=updateExpPath);
  $('expdlg').classList.add('on');
  setTimeout(()=>$('expName').focus(),40);
}

/* Cleaned-only pages, and box sheets, are different things from the finished
   ones, so they must not land on top of them. Steer the folder name instead of
   silently overwriting a chapter someone already exported — and put the name
   back if they change their mind. The suffix is always taken from the name as
   it was BEFORE any mode touched it, so going clean -> boxes cannot stack up
   as "chapter-cleaned-boxes". */
const EXP_SUFFIX={clean:'-cleaned', boxes:'-boxes'};
const EXP_BLURB={
  full:'The finished pages are written as PNGs into a folder of their own.',
  clean:'The cleaned art is written as PNGs with no English on it — the raws '+
    'with the Japanese erased. This does not tick the Export step.',
  boxes:'The original pages are written as PNGs with the boxes drawn on: the '+
    'same colours per text type, the same reading-order numbers and the same '+
    'faint balloons you see here. Nothing is cleaned or typeset, so it is '+
    'quick, and it does not tick the Export step.'};
let _expNameWas='';
function expModeChanged(){
  const m=$('expMode').value, n=$('expName');
  const suf=EXP_SUFFIX[m]||'';
  if(suf){
    if(!_expNameWas) _expNameWas=n.value;
    const base=(_expNameWas||'pages').trim();
    n.value = new RegExp(suf+'$','i').test(base) ? base : base+suf;
  } else if(_expNameWas){
    n.value=_expNameWas; _expNameWas='';
  }
  $('expBlurb').textContent = EXP_BLURB[m]||EXP_BLURB.full;
  updateExpPath();
}

function updateExpPath(){
  const dir=$('expDir').value.replace(/[\\/]+$/,'');
  const name=($('expName').value||'pages').trim();
  const sep = dir.includes('\\') ? '\\' : '/';
  $('expPath').textContent = dir ? `Pages will be written to ${dir}${sep}${name}` : '';
}

async function browseDir(){
  const b=$('expBrowse'); const label=b.textContent;
  b.textContent='Choose a folder…'; b.disabled=true;
  try{
    const j=await api('/api/pick_dir','POST',{start:$('expDir').value});
    if(j.path){ $('expDir').value=j.path; updateExpPath(); }
  } finally { b.textContent=label; b.disabled=false; }
}

async function doExport(){
  const dir=$('expDir').value.trim();
  if(!dir){toast('Choose a folder first.');return;}
  const body={dir, name:$('expName').value.trim(), mode:$('expMode').value};
  if($('expScope').value==='one') body.pages=[cur];
  const j=await api('/api/export','POST',body);
  if(j.error){toast(j.error);return;}
  $('expdlg').classList.remove('on');
  lastExportDir=j.dir;
  // There is something to look at now, so the Results tab opens up.
  if(typeof refreshExports==='function') await refreshExports();
  poll();
}

/* After exporting you are usually done with this chapter, so offer to clear
   it out — but never do it without asking. */
async function newChapter(){
  const yes=await ask('Start a new project?',
    'This clears everything for this story — pages, boxes, translations, the '+
    'synopsis, character names and custom bubble types. Your fonts and '+
    'translation settings are kept. Export first (Settings ▸ Export '+
    'everything) if you want to reuse this series’ content next chapter. '+
    'Anything already exported stays on disk.',
    'Clear and start over', true);
  if(!yes) return;
  await api('/api/reset','POST',{keep_settings:true});
  _seenPages=new Set(); selPages=new Set();   // new project -> all pages checked again
  sel=null; cur=0; lastExportDir=''; setRegions([]);
  $('results').innerHTML='';
  await loadProject();
  if(typeof refreshExports==='function') await refreshExports();
  staged=[]; renderStaged();
  $('pkmsg').textContent='';
  setTab('edit');
  showPicker(true);
}

/* Put the chapter down.

   lee: *"add a close project button in the file tab"*.

   Nothing is saved here because nothing needs to be: every step writes as it
   finishes, and `save_soon` has already run. So this is not "save and quit",
   it is "stop having this chapter open" - which is why it says what it is
   about to close, by name, and why the wording is about the EDITOR forgetting
   it rather than anything being cleared.

   It is `newChapter` without the clearing: the same reset, keeping the
   settings, and back to the File screen. The chapter itself is on disk in
   `project.json` and in whatever `.tctp` was saved, and Open project brings it
   back. The one way to lose work here is to close the wrong project, so it
   names the one it is closing and asks. */
async function closeProject(){
  const name=(proj&&proj.context&&proj.context.title)
    || (proj&&proj.settings&&proj.settings.project_file
        ? proj.settings.project_file.split(/[\\/]/).pop() : '')
    || 'this chapter';
  const n=(proj&&proj.pages&&proj.pages.length)||0;
  const yes=await ask(`Close ${name}?`,
    `The editor stops holding ${n===1?'it':'its '+n+' pages'} and goes back to `+
    'the File screen. Nothing is deleted and nothing is cleared: everything is '+
    'already written to disk, and Open project brings it back exactly as it is '+
    'now. Save it as a .tctp first if you want one file you can carry.',
    'Close it', false);
  if(!yes) return;
  await api('/api/reset','POST',{keep_settings:true});
  _seenPages=new Set(); selPages=new Set();
  sel=null; cur=0; lastExportDir=''; setRegions([]);
  $('results').innerHTML='';
  await loadProject();
  if(typeof refreshExports==='function') await refreshExports();
  staged=[]; renderStaged();
  $('pkmsg').textContent='';
  setTab('new');
  showPicker(true);
  toast('Closed. Open project brings it back.');
}

async function downloadZip(){
  const r=await fetch(apiUrl('/api/export_zip'));
  if(!r.ok){toast('Nothing exported yet.');return;}
  const b=await r.blob(), u=URL.createObjectURL(b), a=document.createElement('a');
  a.href=u; a.download='translated-pages.zip'; a.click(); URL.revokeObjectURL(u);
}
async function downloadTranslationsJson(){
  const j=await api('/api/translations_json');
  if(j.error){toast(j.error);return;}
  const blob=new Blob([JSON.stringify(j,null,2)],{type:'application/json'});
  const u=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=u; a.download='translations.json'; a.click(); URL.revokeObjectURL(u);
}

/* ---------------- file picking ---------------- */
/* What each medium normally IS. The dropdown used to spell it out in the
   option itself — "Manga — Japanese, reads right to left" — which made the
   other two boxes beside it look like decoration, and left them saying "Same
   as the source material", a value that is not an answer to the question the
   label asks. lee: *"istad oaf saying manga- jappeneese ....., it shiud just
   fill the itehr boxes wit default options ... remove all instandt of same
   as ... it shud just pre fill it with teh potion"*.

   So the option is the name of the thing, and picking it FILLS the other two
   with this medium's usual answers, which are then plainly visible and can be
   changed. Nothing anywhere still says "same as". */
const MEDIA={
  manga: {source:'ja', direction:'rtl'},
  manhwa:{source:'ko', direction:'ltr'},
  manhua:{source:'zh', direction:'ltr'},
};
function mediumDefaults(m){ return MEDIA[m] || MEDIA.manga; }

/* `which` is 'pk' for the new-project screen and 'set' for the settings page —
   the same two boxes under different ids. */
function mediumChosen(which){
  const p = which==='pk' ? 'pk' : '';
  const id = s => p ? p+s.charAt(0).toUpperCase()+s.slice(1) : s;
  const d = mediumDefaults($(id('medium')).value);
  if($(id('source')))    $(id('source')).value    = d.source;
  if($(id('direction'))) $(id('direction')).value = d.direction;
  if(p) mediumHint();
  else if(typeof saveSettings==='function') saveSettings();
  stripSettings();
}

/* The formats that are DELIVERED as one long strip — the same set as
   `STRIP_MEDIA` in project.py, and it has to stay the same set: this one
   decides what is on screen and that one decides what actually happens.
   lee: *"this setting shoud only be a thing for manhwa and manhua"*. */
const STRIP_MEDIA=['manhwa','manhua'];

/* `which` picks the menu to ask, because there are two and they are the same
   question on two screens: `pkMedium` on the File tab, `medium` in Settings.
   The File tab's switch has to follow the File tab's menu — that is the one
   the person is looking at while they choose a folder. */
function stripMedium(which){
  const el=$(which==='pk' ? 'pkMedium' : 'medium');
  // `typeof`, not `window.proj`: `proj` is declared with `let`, and a
  // top-level `let` does not become a property of `window`.
  const has=(typeof proj!=='undefined') && proj;
  const m=(el && el.value) || (has && proj.settings && proj.settings.medium)
        || 'manga';
  return STRIP_MEDIA.indexOf(m)>=0;
}

/* Open or close the strip controls — both sets. On manga these are controls
   for something that cannot happen: a manga chapter is never re-cut, however
   much the files look like a strip. lee: *"the setting shoud not be there for
   manga"*, said the second time about the File tab, which the first pass
   missed. */
function stripSettings(){
  const box=$('stripSet');
  if(box) box.style.display = stripMedium() ? 'block' : 'none';
  const nb=$('restitchNewWrap');
  if(nb) nb.style.display = stripMedium('pk') ? 'inline-flex' : 'none';
  // Cut / join is gated on the format too, and lives in the top bar rather
  // than in Settings, so it is the view chrome that has to be told.
  if(typeof syncViewChrome==='function') syncViewChrome();
  stripPixels();
}

/* What the two multiples come to in pixels on THIS chapter, said underneath
   them. The multiple is the setting; the pixels are what it means today, and
   somebody who has been reading these boxes as pixels for a year needs both
   for one chapter at least. */
function stripPixels(){
  const el=$('stripPx'); if(!el) return;
  const w=((typeof proj!=='undefined') && proj && proj.pages
           && proj.pages.length && proj.pages[0].width) || 0;
  const tall=+($('strip_tall')||{}).value||3.5;
  const top=Math.max(+($('strip_tall_max')||{}).value||8.5, tall);
  el.textContent = w
    ? `On this chapter — ${w}px wide — that is about `
      + `${Math.round(w*tall).toLocaleString()}px a page, and anything past `
      + `${Math.round(w*top).toLocaleString()}px is reported.`
    : 'Open a chapter to see what that comes to in pixels.';
}

/* The File tab's copy of the re-cut switch and the Settings one are the same
   setting. lee: *"add a check box oprion in the files uoload page to turn on
   and off the automated merging thing and have it on by default"*. Two boxes
   showing one fact and able to disagree is worse than one box in the wrong
   place, so whichever is touched, the other follows. */
function stripSwitch(on){
  const a=$('restitch_strips'), b=$('restitch_new');
  if(a) a.checked=on;
  if(b) b.checked=on;
  if(typeof saveSettings==='function') saveSettings();
}

const MEDIUM_HINT={
  manga:'Japanese, read right to left. Uses manga-ocr, which is the strongest '+
        'reader for Japanese comic typesetting.',
  manhwa:'Korean, read left to right. Uses easyocr — install it with '+
         '<code>pip install easyocr</code>.',
  manhua:'Chinese, read left to right. Uses easyocr — install it with '+
         '<code>pip install easyocr</code>.'};
function mediumHint(){
  const m=$('pkMedium').value, d=$('pkDirection').value;
  const usual=mediumDefaults(m).direction;
  const dir = d===usual ? '' :
    ` Reading direction set to ${d==='rtl'?'right to left':'left to right'}.`;
  $('pkHint').innerHTML=(MEDIUM_HINT[m]||'')+dir;
}

function openSettingsDlg(){
  // Settings is now a full page (a tab), not a modal. The synopsis, cast,
  // terms and the project file live on the Manga settings page next to it.
  fillCkFont(); renderCustomKinds();
  if(typeof setTab==='function') setTab('settings');
}
function openMangaDlg(){ if(typeof setTab==='function') setTab('manga'); }
function closeSettingsDlg(){ if(typeof setTab==='function') setTab('edit'); }
function fillCkFont(){
  const el=$('ckFont'); if(!el) return;
  const cur=el.value;
  el.innerHTML=fontOptionList(fontChoices(cur), cur);
  if(cur) el.value=cur;
  if(typeof fontWidget==='function') fontWidget(el);
}
/* ---- box types: three families, and sub-types under them ----

   Three main types — balloon, outside text, sound effect — each with an
   undeletable default that carries the family's colour, and up to five of
   your own under it whose colour can only be a SHADE of that. See
   `mangatl/kinds.py`; the tables live in frames.js.

   The list below is grouped by family, with each family's default shown at
   the top of its group. The default has no × and no colour swatch to cycle:
   it is what a box IS when nothing finer has been said about it, and there
   has to be one. lee: *"the user shoud be abe to modify and dletect teh
   subcategories exampty for teh default one"*. */
let _ckColor=null;                         // colour picked for the NEXT one
function ckFamily(){
  const el=$('ckFamily');
  return (el && KIND_FAMILIES.includes(el.value)) ? el.value : KIND_FAMILIES[0];
}
/* The shades of one family that no sub-type of it is already using. */
function _ckAvail(fam, exceptColor){
  const used=new Set(subsOf(fam).map(k=>(k.color||'').toLowerCase()));
  if(exceptColor) used.delete(exceptColor.toLowerCase());
  return (FAMILY_SHADES[fam]||[]).filter(c=>!used.has(c));
}
function renderCkFamilies(){
  const el=$('ckFamily'); if(!el) return;
  const cur=ckFamily();
  el.innerHTML=KIND_FAMILIES.map(f=>{
    const n=subsOf(f).length, full=n>=SUBS_PER_FAMILY;
    return `<option value="${f}"${f===cur?' selected':''}${full?' disabled':''}>`+
           `${_fesc(FAMILY_LABELS[f])}${full?' — full':''}</option>`;
  }).join('');
  el.value=cur;
}
function onCkFamily(){ _ckColor=null; renderCkSwatches(); renderCkLimit(); }
function renderCkSwatches(){
  const el=$('ckSwatches'); if(!el) return;
  const avail=_ckAvail(ckFamily());
  if(!_ckColor||!avail.includes(_ckColor)) _ckColor=avail[0]||null;
  el.innerHTML=avail.map(c=>
    `<span class="swatch${c===_ckColor?' on':''}" style="background:${c}"
       title="Colour" onclick="pickCkColor('${c}')"></span>`).join('');
}
function pickCkColor(c){ _ckColor=c; renderCkSwatches(); }
function renderCkLimit(){
  const fam=ckFamily(), full=subsOf(fam).length>=SUBS_PER_FAMILY;
  const all=KIND_FAMILIES.every(f=>subsOf(f).length>=SUBS_PER_FAMILY);
  if($('ckAddRow')) $('ckAddRow').style.display=all?'none':'';
  const el=$('ckLimit');
  if(el){
    el.style.display=(full||all)?'':'none';
    el.textContent=all
      ? `Every main type has its ${SUBS_PER_FAMILY}.`
      : `${FAMILY_LABELS[fam]} has its ${SUBS_PER_FAMILY} — remove one, or pick another main type.`;
  }
}
function renderCustomKinds(){
  const el=$('ckList'); if(!el) return;
  el.innerHTML = KIND_FAMILIES.map(f=>{
    const subs=subsOf(f);
    // The default's row carries the family's FONT — the one every sub-type
    // under it falls back to. It used to say "the default" and the face was
    // set in another section entirely, which is the same question asked in
    // two places. lee: *"merge the fonts selctor with the bubble insatd of
    // saying this sis default it shiud have the font selctor there"*.
    const fid = f==='bubble' ? 'font' : 'font_'+f;
    const fcur = (proj.settings.fonts||{})[f] || (f==='bubble'
                  ? (proj.settings.font||'') : '');
    const rows=[
      `<div class="row ckrow ckdef" style="align-items:center">
         <span class="swatch fixed" style="background:${KIND_COLORS[f]}"></span>
         <span class="cknm ckfix">${_fesc(DEFAULT_LABELS[f])}</span>
         <select class="fontsel ckft" style="flex:1"
                 onchange="setFamilyFont('${f}', this.value)">
           ${fontOptionList(fontChoices(fcur), fcur)}
         </select>
         <button class="danger ckpad" tabindex="-1" aria-hidden="true"
                 disabled>&times;</button>
       </div>`
    ].concat(subs.map(k=>`
      <div class="row ckrow" style="align-items:center">
        <span class="swatch" title="Change the colour"
              style="background:${kindColor(k.key)}"
              onclick="cycleKindColor('${k.key}')"></span>
        <input class="cknm" value="${_fesc(k.label||'')}"
               onchange="renameKind('${k.key}', this.value)">
        <select class="fontsel ckft" style="flex:1"
                onchange="setKindFont('${k.key}', this.value)">
          <!-- A sub-type with no face of its own typesets in its family's, and
               the row says WHICH — it used to show the first font in the list
               as though it had been chosen. lee: *"it shoud just say the
               font, do that for all of the spot fonts are used"*. -->
          <option value=""${k.font?'':' selected'}
            data-name="${_fesc(inheritedFontLabel(f))}"
            >${_fesc(inheritedFontLabel(f))}</option>
          ${fontOptionList(fontChoices(k.font||''), k.font||'')}
        </select>
        <button class="danger" title="Remove" onclick="delCustomKind('${k.key}')">&times;</button>
      </div>`));
    return `<div class="ckfam"><h4 class="ckfamh">${_fesc(FAMILY_LABELS[f])}</h4>`+
           rows.join('')+`</div>`;
  }).join('');
  renderCkFamilies(); renderCkSwatches(); renderCkLimit();
  // The font pickers in the rows are the same widget as everywhere else.
  if(typeof fontWidget==='function')
    el.querySelectorAll('select.fontsel').forEach(fontWidget);
}
/* The face for a whole family. `bubble` is the project default — the one
   everything falls back to — so it lands in `settings.font`; the other two are
   rows in `settings.fonts`. The hidden selects in the Fonts section are kept
   in step because `saveSettings` reads them. */
function setFamilyFont(fam, path){
  if(fam==='bubble'){
    proj.settings.font=path||'';
    const el=$('font'); if(el) el.value=path||'';
  }else{
    proj.settings.fonts=proj.settings.fonts||{};
    proj.settings.fonts[fam]=path||'';
    const el=$('font_'+fam); if(el) el.value=path||'';
  }
  saveSettings();
  if(typeof showPage==='function' && typeof cur!=='undefined') showPage(cur);
}
function setKindFont(key, path){
  const k=(proj.settings.custom_kinds||[]).find(x=>x.key===key); if(!k) return;
  k.font=path||'';
  saveSettings();
  if(typeof showPage==='function' && typeof cur!=='undefined') showPage(cur);
}
function addCustomKind(){
  const list=proj.settings.custom_kinds||[];
  const fam=ckFamily();
  const name=$('ckName').value.trim();
  if(!name){ toast('Give the box type a name first.'); return; }
  const key='ck_'+name.toLowerCase().replace(/[^a-z0-9]+/g,'_')
                     .replace(/^_+|_+$/g,'');
  if(KIND_FAMILIES.includes(key)){ toast('That name is a main type.'); return; }
  const replacing=list.some(k=>k.key===key);
  if(!replacing && subsOf(fam).length>=SUBS_PER_FAMILY){
    toast(`${FAMILY_LABELS[fam]} already has ${SUBS_PER_FAMILY}.`); return; }
  proj.settings.custom_kinds=list.filter(k=>k.key!==key);
  proj.settings.custom_kinds.push({key, label:name, family:fam,
    font:$('ckFont').value, color:_ckColor||_ckAvail(fam)[0]||FAMILY_SHADES[fam][0]});
  $('ckName').value=''; _ckColor=null;     // the next one takes the next shade
  saveSettings(); renderCustomKinds(); kindsChanged();
}
/* Renaming is the only thing about a sub-type that can be edited in place —
   its family is what it IS, and changing that would silently move every box
   already using it into another family. Delete it and make another. */
/* Everything that draws a box type, brought up to date at once.

   A colour was only reaching the outlines: change the shade of a sub-type you
   already had boxes in and the page updated, while the list rows, the key
   beside the page and the two menus on the selected box all kept the old one.
   lee: *"if i chnage the colr of a subtype while i alread have some created it
   shoud update"*. */
function kindsChanged(){
  if(typeof drawBoxes==='function') drawBoxes();
  if(typeof drawOverlay==='function') drawOverlay();
  if(typeof renderList==='function') renderList();
  if(typeof renderLegend==='function') renderLegend();
  if(typeof renderLayers==='function') renderLayers();
}
function renameKind(key, label){
  const k=(proj.settings.custom_kinds||[]).find(x=>x.key===key); if(!k) return;
  const name=String(label||'').trim();
  if(!name){ renderCustomKinds(); return; }
  k.label=name;
  saveSettings(); renderCustomKinds(); kindsChanged();
}
function cycleKindColor(key){
  const k=(proj.settings.custom_kinds||[]).find(x=>x.key===key); if(!k) return;
  const fam=familyOf(key);
  // Its own shade stays in play; the ones its siblings hold do not. A colour
  // can never leave the family — that is the whole point of the families.
  const avail=_ckAvail(fam, k.color);
  if(avail.length<2){ toast(`No other free ${FAMILY_LABELS[fam].toLowerCase()} shade.`); return; }
  const i=Math.max(0, avail.indexOf((k.color||'').toLowerCase()));
  k.color=avail[(i+1)%avail.length];
  saveSettings(); renderCustomKinds(); kindsChanged();
}
function delCustomKind(key){
  proj.settings.custom_kinds=(proj.settings.custom_kinds||[])
    .filter(k=>k.key!==key);
  saveSettings(); renderCustomKinds(); kindsChanged();
}
/* ---------------- the chapter, in one file (.tctp) ----------------
   lee: *"make it so tht everything is save including kayers custom boxes
   fonts besicaly everything when ii load this project file it shoud be excaty
   as it it now"*. The server writes it, not the browser: it is the machine
   with the files on it, so Save can overwrite the same path twice instead of
   filling Downloads with copies. */
function tctpSay(m, bad){
  const n=$('tctpMsg'); if(!n) return;
  n.textContent=m||''; n.classList.toggle('bad', !!bad);
}
function tctpWhere(path){
  const n=$('tctpWhere'); if(!n) return;
  n.textContent = path ? 'Saved as ' + path : '';
}
async function saveProject(){
  // Pressed from the rail, so show the screen that says what happened and
  // where it went — otherwise Save is a button that gives no answer.
  setTab('new'); setFileTab('save');
  // No file chosen yet means Save has nowhere to go, and asking is what Save
  // as is for — so it asks, once, and remembers.
  if(!(proj.settings||{}).project_file) return saveProjectAs();
  tctpSay('Saving…');
  const j=await api('/api/project_save','POST',{});
  if(j.error) return tctpSay(j.error, true);
  proj.settings.project_file=j.path;
  tctpSay(`Saved — ${Math.round((j.bytes||0)/1048576)} MB.`);
  tctpWhere(j.path);
}
async function saveProjectAs(){
  setTab('new'); setFileTab('save');
  const pick=await api('/api/pick_project','POST',{save:true});
  if(!pick.path){
    // Nothing chosen. Either the person changed their mind — in which case
    // saying anything would be noise — or this machine cannot show a file
    // dialog at all, and then the browser's own download is the way out and
    // needs nothing from the operating system.
    if(!(await api('/api/can_browse')).ok) return downloadProject();
    return;
  }
  tctpSay('Saving…');
  const j=await api('/api/project_save','POST',{path:pick.path});
  if(j.error) return tctpSay(j.error, true);
  proj.settings.project_file=j.path;
  tctpSay(`Saved — ${Math.round((j.bytes||0)/1048576)} MB.`);
  tctpWhere(j.path);
}
async function openProject(){
  setTab('new'); setFileTab('save');
  const pick=await api('/api/pick_project','POST',{});
  if(!pick.path) return $('tctpFile') ? $('tctpFile').click() : null;
  await adoptProject(api('/api/project_open','POST',{path:pick.path}));
}
async function uploadProject(inp){
  const f=inp.files[0]; inp.value=''; if(!f) return;
  tctpSay(`Opening ${f.name}…`);
  await adoptProject(fetch('/api/project_upload',
    {method:'POST', headers:{'Content-Type':'application/zip'}, body:f})
      .then(r=>r.json()));
}
async function adoptProject(pending){
  tctpSay('Opening…');
  let j;
  try{ j=await pending; }catch(e){ return tctpSay('Could not open it: '+e.message, true); }
  if(!j || j.error) return tctpSay((j&&j.error)||'Could not open it.', true);
  // Everything on screen was about the chapter that is no longer open.
  await loadProject();
  if(typeof refreshExports==='function') await refreshExports();
  renderPages();
  if(proj.pages.length) showPage(0);
  tctpWhere(j.path||'');
  tctpSay(`Opened ${j.name||'project'} — ${j.pages} pages.`);
  setTab('edit');
}
function downloadProject(){
  // The browser's own copy. Not a button of its own — lee replaced that with
  // the story context — but it is what Save as falls back to on a machine
  // with no file dialog, which is any headless install.
  tctpSay('Building the file…');
  location.href='/api/project_file';
  setTimeout(()=>tctpSay(''), 3000);
}

function exportSettings(){
  // Everything about this manga travels in one file: the technical settings
  // (fonts, backend, custom bubble types) AND the series content — the
  // synopsis, the character names, and the glossary. Continue a series next
  // chapter by starting fresh and importing this back.
  const ctx=proj.context||{};
  const bundle={
    mangatl_export:1,
    mangatct_series:1,
    settings:proj.settings,
    title:ctx.title||'',
    synopsis:ctx.synopsis||'',
    glossary:ctx.glossary||{},
    characters:ctx.characters||{},
  };
  // Renamed, not rebuilt: lee asked for *"just a rename of the json file we
  // already have withthe spory synopsis and charatter and places"*. The bytes
  // are the same JSON, so a .json somebody exported last month still imports.
  const blob=new Blob([JSON.stringify(bundle,null,2)],
                      {type:'application/json'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download=(seriesName()||'series')+'.tct';
  a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 4000);
}
function seriesName(){
  const t=((proj.context||{}).title||'').trim();
  if(t) return t.replace(/[\\/:*?"<>|]+/g,'-').slice(0,60);
  const f=((proj.settings||{}).project_file||'');
  if(f) return f.split(/[\\/]/).pop().replace(/\.tctp?$/i,'');
  return 'series';
}
async function importSettings(inp){
  const f=inp.files[0]; if(!f) return;
  try{
    const imported=JSON.parse(await f.text());
    if(typeof imported!=='object'||!imported) throw new Error('not a project file');
    // New bundle format carries the content alongside the settings; an older
    // file is just the settings object, so send it as-is.
    const body = imported.mangatl_export
      ? {settings:imported.settings||{},
         title:imported.title||'',
         synopsis:imported.synopsis||'',
         glossary:imported.glossary||{},
         characters:imported.characters||{}}
      : {settings:imported};
    const j=await api('/api/settings','POST',body);
    if(j.error) return;
    // Apply in place — re-read the project and repopulate the panels — instead
    // of a full page reload, so the page selection and view are kept. Importing
    // again just replaces the current settings.
    await loadProject();
    if(proj.pages[cur]) showPage(cur);
    toast('Story context imported.');
    const m=$('pkJsonMsg');
    if(m){ m.textContent='Imported — '+f.name; m.classList.remove('bad'); }
    const d=$('pkDoneBtn');
    if(d){ d.disabled=false; d.title=''; }
  }catch(e){
    toast('Import failed: '+e.message);
    const m=$('pkJsonMsg');
    if(m){ m.textContent='Could not read that file: '+e.message;
           m.classList.add('bad'); }
    // A file that would not read is not a file added. Done stays shut.
  }
  inp.value='';
}
function filterFontOptions(sel,q){
  if(!sel) return;
  const cur=sel.value, blank=sel.dataset.blank;
  const keep=fontChoices(cur).filter(f=>!q||f.name.toLowerCase().includes(q));
  sel.innerHTML=(blank!=null?`<option value="">${blank}</option>`:'')+
    fontOptionList(keep, cur);
  if([...sel.options].some(o=>o.value===cur)) sel.value=cur;
  if(typeof fontWidget==='function') fontWidget(sel);
}
function filterAllFontSels(q){
  ['font','font_freefloat','font_sfx','font_narration','ckFont']
    .forEach(id=>filterFontOptions($(id), q));
}

async function savePickerChoices(){
  await api('/api/settings','POST',{settings:{
    medium:$('pkMedium').value, target:$('pkTarget').value,
    source:$('pkSource').value,
    direction:$('pkDirection').value}});
}

function showPicker(on){
  on = !!on;
  // The tab bar is the one place that decides which screen is up, so opening
  // or closing this from anywhere else goes through it — and the flag stops
  // the two calling each other for ever.
  if(typeof setTab==='function' && !showPicker._busy){
    showPicker._busy = true;
    try{
      setTab._fromPicker = true;
      if(on){ if(tab!=='new') setTab('new'); }
      // With no pages there is nowhere to go: Edit is shut until there are
      // some, so this screen stays until it has done its job.
      else if(tab==='new' && proj && proj.pages && proj.pages.length){
        setTab('edit');
      }
      else if(!on && !(proj && proj.pages && proj.pages.length)){
        showPicker._busy = false;
        setTab._fromPicker = false;
        return;
      }
    } finally { setTab._fromPicker = false; showPicker._busy = false; }
  }
  $('picker').classList.toggle('on',on);
  // The overlay starts under the top bar rather than over it, so it has to be
  // told how tall the bar actually is — that changes with the window, and a
  // number written into the stylesheet would be right at one width only.
  const top=$('top');
  if(on && top) document.documentElement.style.setProperty(
    '--topbar', Math.round(top.getBoundingClientRect().height)+'px');
  if(on) pkStep(1);
  // Close is only a way out when there is something to go back to.
  const loaded = !!(proj && proj.pages && proj.pages.length);
  for(const id of ['pkClose','pkClose2']){
    const b=$(id); if(b) b.style.display = loaded ? '' : 'none';
  }
  if(on && proj){
    const md=mediumDefaults($('pkMedium').value=proj.settings.medium||'manga');
    // A project written before the "same as the source material" option went
    // still carries `auto` in these two. It never meant anything but the
    // medium's own answer, so that is what it now shows.
    const src=proj.settings.source, dir=proj.settings.direction;
    $('pkSource').value=(src && src!=='auto') ? src : md.source;
    $('pkTarget').value=proj.settings.target||'en';
    $('pkDirection').value=(dir && dir!=='auto') ? dir : md.direction;
    mediumHint();
  }
  // The File tab's re-cut switch follows the File tab's format menu, which
  // has just been filled in.
  if(on) stripSettings();
}
function changeChapter(){showPicker(true);}

/* ---- Add pages is two screens ----

   lee: *"Change the add pages so it's 2 pages, add the pages , next, add json,
   with done or skip button"*.

   One screen asked for the language, the pages AND a settings file at once,
   with the .json button sitting between "Add pages from a folder" and the drop
   zone as though it were a third way of adding pages. It is not — it is the
   thing you do after, once, and most of the time not at all.

   So: pages first, Next; then the settings file, with Done or Skip. Nothing
   about what the buttons DO changed — the pages upload where they always did,
   and importing still happens the moment a file is chosen. What changed is
   that the second question is not asked until the first is answered. */
let pkStepNow = 1;
function pkStep(n){
  pkStepNow = n;
  // Done is for "I added the file". With no file added it is a second Skip
  // wearing the primary colour, which is the button people press — and then
  // they have skipped the step without meaning to.
  // lee: *"done shoud not work if no file was uploaded"*.
  const done=$('pkDoneBtn');
  if(done && n!==2){ done.disabled=true; const m=$('pkJsonMsg');
                     if(m){ m.textContent=''; m.classList.remove('bad'); } }
  document.querySelectorAll('#picker .pkstep').forEach(el=>
    el.classList.toggle('on', Number(el.dataset.step) === n));
  document.querySelectorAll('#picker .pkdot').forEach(el=>
    el.classList.toggle('on', Number(el.dataset.step) <= n));
  const t=$('pkTitle');
  if(t) t.textContent = n===1 ? 'Open a chapter' : 'Add a settings file';
}
/* Next carries whatever is staged, and is not a dead end when nothing is:
   opening this again on a chapter that is already loaded is a real thing to
   do — you came back for the settings file. */
async function pkNext(){
  if(staged.length){ await loadStaged(); return; }   // loadStaged goes on to 2
  if(proj && proj.pages && proj.pages.length){ pkStep(2); return; }
  $('pkmsg').textContent='Add some pages first.';
}
/* Done and Skip are the same button with two names, on purpose: the import
   already happened when the file was chosen, so there is nothing left to
   confirm. Two names because "Done" on a screen you did nothing with reads as
   though you missed a step. */
function pkFinish(){
  showPicker(false);
  setTab('edit');
}

const readFile=f=>new Promise(res=>{
  const r=new FileReader();
  r.onload=()=>res({name:f.name,data:r.result});
  r.onerror=()=>res(null);
  r.readAsDataURL(f);
});

/* Files are staged first so they can be reviewed, added to and pruned before
   anything is uploaded. */
let staged=[];

function stageFiles(fileList){
  const incoming=[...fileList].filter(f=>/\.(png|jpe?g|webp|bmp)$/i.test(f.name));
  if(!incoming.length){$('pkmsg').textContent='No images in that selection.';return;}
  const seen=new Set(staged.map(f=>f.name+':'+f.size));
  let added=0, dupes=0;
  for(const f of incoming){
    const key=f.name+':'+f.size;
    if(seen.has(key)){dupes++; continue;}
    seen.add(key); staged.push(f); added++;
  }
  staged.sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
  $('pkmsg').textContent = dupes ? `Skipped ${dupes} already in the list.` : '';
  renderStaged();
}

function renderStaged(){
  const box=$('staged');
  box.style.display = staged.length ? 'block' : 'none';
  if(!staged.length){ $('pkmsg').textContent=''; return; }
  const kb=n=>n<1024*1024 ? Math.round(n/1024)+' KB'
                          : (n/1048576).toFixed(1)+' MB';
  $('stagedCount').textContent=`${staged.length} page${staged.length>1?'s':''} ready`;
  $('stagedNote').textContent='They load in this order — page 1 at the top.';
  $('stagedList').innerHTML=staged.map((f,i)=>`
    <div class="sf">
      <span class="i">${i+1}</span>
      <span class="n" title="${f.name}">${f.name}</span>
      <span class="sz">${kb(f.size)}</span>
      <span class="x" title="Remove" onclick="unstage(${i})">&times;</span>
    </div>`).join('');
}

function unstage(i){ staged.splice(i,1); renderStaged(); }
function clearStaged(){ staged=[]; renderStaged(); }

async function loadStaged(){
  if(!staged.length) return;
  $('loadBtn').disabled=true;
  await uploadFiles(staged);
  staged=[]; renderStaged();
  $('loadBtn').disabled=false;
}

/* The bar on the File tab. `at` is a fraction, or null for "working on
   something with no count to give" — the re-cut, which is one long step on the
   server. lee: *"add a loading bar in the file page when the files are getting
   processed"*. */
function pkBar(at, what){
  const box=$('pkbar'), outer=$('pkBarOuter'), fill=$('pkBarFill');
  if(!box) return;
  if(at===false){ box.style.display='none'; return; }
  box.style.display='block';
  $('pkBarWhat').textContent=what||'';
  if(at===null){ outer.classList.add('wait'); fill.style.width=''; return; }
  outer.classList.remove('wait');
  fill.style.width=Math.round(Math.max(0,Math.min(1,at))*100)+'%';
}

/* A bar left running is worse than no bar: it says the chapter is still
   loading for as long as the tab is open. Whatever happens in there, it goes
   away on the way out. */
async function uploadFiles(fileList, append){
  try{ return await _uploadFiles(fileList, append); }
  finally{ pkBar(false); }
}

async function _uploadFiles(fileList, append){
  const files=[...fileList].filter(f=>/\.(png|jpe?g|webp|bmp)$/i.test(f.name))
        .sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
  const say=m=>{ if(append) toast(m); else $('pkmsg').textContent=m; };
  if(!files.length){say('No images in that selection.');return;}
  pkBar(0, `Reading ${files.length} file${files.length===1?'':'s'}…`);
  if(!append){
    // Starting a chapter clears the last one — that is what starting one
    // means, and there is no separate "Clear this project" button any more.
    // lee: *"remoev teh close this project it shoud do it by default"*.
    // `keep_settings` keeps the fonts and the translation engine and drops the
    // story's own content: the custom text types and where the last chapter
    // was exported to. Without it those two followed the new chapter around.
    await api('/api/reset','POST',{keep_settings:true});
    await savePickerChoices();
    if(typeof refreshExports==='function') await refreshExports();
  }
  let done=0, firstNew=null, failed=[];
  for(let i=0;i<files.length;i+=4){                 // small batches keep memory sane
    const read=await Promise.all(files.slice(i,i+4).map(readFile));
    read.forEach((r,k)=>{ if(!r) failed.push(files[i+k].name); });
    const j=await api('/api/upload','POST',{files:read.filter(Boolean)});
    done+=(j.added||0);
    if(j.indices && j.indices.length && firstNew===null) firstNew=j.indices[0];
    if(j.problems && j.problems.length) failed.push(...j.problems);
    say(`Loading ${done}/${files.length}…`);
    pkBar(Math.min(i+4,files.length)/files.length,
          `Loading ${done} of ${files.length} pages…`);
  }
  if(failed.length) toast(`Could not read: ${failed.slice(0,3).join(', ')}`);
  say(`Added ${done} pages.`);
  // The re-cut runs inside this one call and can take a while on a chapter of
  // a hundred tiles, with nothing to report until it is finished. The bar
  // paces rather than inventing a number.
  pkBar(null, stripMedium('pk') && $('restitch_new')
        && $('restitch_new').checked
        ? 'Checking whether this chapter is a strip, and re-cutting it…'
        : 'Finishing…');
  const fin=await api('/api/upload_done','POST',{})||{};
  pkBar(false);
  // A webtoon came in as tiles and has just been put back together. Say so:
  // the page count changed underneath the person, and a chapter that silently
  // turns 105 files into 66 looks like something went wrong.
  if(fin.strip && fin.strip.after){
    const s=fin.strip;
    say(`Re-cut ${s.before} strip slices into ${s.after} pages.`);
    toast(`That chapter arrived as ${s.before} slices of one long strip — `
        + `joined back up and cut into ${s.after} pages in the gaps between `
        + `panels.` + (s.over ? ` ${s.over} had to run past the height you `
        + `asked for to reach a gap rather than cut through the artwork: `
        + `${(s.over_pages||[]).slice(0,3).join(', ')}.` : ''));
  }
  if(append){
    // Adding to a chapter that is already open. This screen was never up, so
    // there is nothing to advance and nothing to close — you are here to look
    // at the pages you just added.
    setTab('edit');
  } else {
    // The pages are in; now the settings file. Deliberately NOT setTab('edit')
    // here: the tab bar owns which screen is up, and moving to Edit now would
    // close this screen before its second question had been asked. `pkFinish`
    // does it, on Done or Skip.
    pkStep(2);
  }
  await loadProject();
  // Land on the first page that was just added, not the one already open —
  // otherwise adding pages looks like nothing happened.
  // The server says where the pages landed; guessing an index was what made
  // "add pages" appear to do nothing.
  const target = (firstNew!==null && firstNew<proj.pages.length) ? firstNew
               : (append ? cur : 0);
  renderPages();
  showPage(target);
  if(append) toast(`Added ${done} page${done===1?'':'s'}`);
  poll();
}

const drop=$('drop');
['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{
  ev.preventDefault();drop.classList.add('hot');}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{
  ev.preventDefault();drop.classList.remove('hot');}));
drop.addEventListener('drop',async ev=>{
  const items=[...(ev.dataTransfer.items||[])];
  const entries=items.map(i=>i.webkitGetAsEntry&&i.webkitGetAsEntry()).filter(Boolean);
  if(entries.length && entries.some(e=>e.isDirectory)){
    const out=[];
    const walk=dir=>new Promise(res=>{
      dir.createReader().readEntries(async es=>{
        for(const e of es){
          if(e.isFile) await new Promise(r=>e.file(f=>{out.push(f);r();}));
          else if(e.isDirectory) await walk(e);
        }
        res();
      });
    });
    for(const e of entries){ if(e.isDirectory) await walk(e); else await new Promise(r=>e.file(f=>{out.push(f);r();})); }
    return stageFiles(out);          // review before loading, same as the buttons
  }
  stageFiles(ev.dataTransfer.files);
});

/* The second screen takes a drop too. Anything that can be clicked to open a
   file dialog should also accept the file being dragged onto it — half the
   point of a drop zone is not having to find the folder twice. */
const dropJson=$('dropJson');
if(dropJson){
  ['dragenter','dragover'].forEach(e=>dropJson.addEventListener(e,ev=>{
    ev.preventDefault(); dropJson.classList.add('hot');}));
  ['dragleave','drop'].forEach(e=>dropJson.addEventListener(e,ev=>{
    ev.preventDefault(); dropJson.classList.remove('hot');}));
  dropJson.addEventListener('drop',ev=>{
    const f=[...(ev.dataTransfer.files||[])].find(x=>/\.json$/i.test(x.name));
    if(!f){ $('pkJsonMsg').textContent='That is not a .json file.'; return; }
    importSettings({files:[f], value:''});
  });
}


/* --- the up/down on a number box -------------------------------------------
   lee: *"make teh up and down button look better"*, with a picture of the
   cramped little control Firefox draws.

   Neither browser's own spinner can be made to look like the other's:
   Chromium's can be painted through ::-webkit-inner-spin-button, Firefox's
   cannot be touched at all. So both are switched off in the stylesheet and one
   is built here out of two real buttons. Same control everywhere, big enough
   to hit, and it can be styled.

   The buttons go INSIDE the box — the wrapper takes the size the input had —
   so wrapping one changes nothing about the layout around it. */
let numHeld = false;          // a stepper is being pressed right now

function stepNum(inp, dir){
  // The panel is rebuilt whenever a save comes back, and a rebuild replaces
  // this very input. Find it again by name rather than writing into a node
  // that is no longer on the page — that is what made a second press appear
  // to do nothing at all.
  if(!inp.isConnected && inp.id){
    const again = document.getElementById(inp.id);
    if(again) inp = again;
  }
  const step = parseFloat(inp.step) || 1;
  let n = (parseFloat(inp.value) || 0) + dir * step;
  const lo = parseFloat(inp.min), hi = parseFloat(inp.max);
  if(!isNaN(lo)) n = Math.max(lo, n);
  if(!isNaN(hi)) n = Math.min(hi, n);
  // Match the step's own precision, or 0.05 lands on 1.1500000000000001.
  const dp = (String(step).split('.')[1] || '').length;
  inp.value = dp ? n.toFixed(dp) : String(Math.round(n));
  // Everything in the panels saves on one or the other, and a value set from
  // script fires neither by itself.
  inp.dispatchEvent(new Event('input', {bubbles:true}));
  inp.dispatchEvent(new Event('change', {bubbles:true}));
  return inp;
}

/* Press and hold to keep going, the way a native spinner does. The step runs
   on POINTER DOWN, not on `click`: a click only fires if the button is still
   on the page when the mouse comes up, and pressing one of these saves, which
   rebuilds the panel — so the button could be replaced between the press and
   the release and the click would never arrive. lee, in Firefox: *"it donsent
   update at all right now"*. */
function holdStep(inp, dir){
  // A repeat that never stops is a runaway: it saves on every step, and a save
  // storm makes the whole app stop answering. So the release is listened for
  // in every way the pointer can leave — up, cancel, the window losing focus,
  // the tab going away — and on top of that the run is CAPPED. Nothing here
  // depends on one particular event arriving.
  holdStep.stop && holdStep.stop();          // never two at once
  numHeld = true;
  let live = stepNum(inp, dir);
  let left = 300;                            // ~24s of holding, then it stops
  let timer = setTimeout(function again(){
    if(--left <= 0) return release();
    live = stepNum(live, dir);
    timer = setTimeout(again, 80);
  }, 400);
  const EVENTS = ['mouseup','pointerup','pointercancel','blur','visibilitychange'];
  function release(){
    clearTimeout(timer);
    numHeld = false;
    holdStep.stop = null;
    EVENTS.forEach(n=>window.removeEventListener(n, release, true));
    // Whatever was held off while the button was down happens now.
    if(typeof renderInspector === 'function') renderInspector();
  }
  holdStep.stop = release;
  EVENTS.forEach(n=>window.addEventListener(n, release, true));
}

function dressNumbers(root){
  const scope = root && root.querySelectorAll ? root : document;
  scope.querySelectorAll('input[type=number]').forEach(inp=>{
    if(inp.dataset.dressed) return;
    // A number box that already has a slider beside it does not need one: the
    // slider IS the coarse control and the box is only there to read and type.
    if(inp.closest('.sl')){ inp.dataset.dressed='skip'; return; }
    inp.dataset.dressed='1';
    const wrap = document.createElement('span');
    wrap.className = 'numwrap';
    // A box with a width of its own hands it to the wrapper — otherwise the
    // wrapper stretches to the whole row and the buttons, which hang off ITS
    // right edge, end up floating somewhere off to the side of the box they
    // belong to. The gradient angle did exactly that.
    if(inp.style.width){ wrap.style.width = inp.style.width; }
    inp.style.width = '100%';
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(inp);
    for(const [cls, dir, glyph] of [['up',1,'▲'],['dn',-1,'▼']]){
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'numbtn ' + cls;
      b.tabIndex = -1;                 // tabbing runs through the FIELDS
      b.textContent = glyph;
      b.title = dir > 0 ? 'More' : 'Less';
      b.addEventListener('mousedown', e=>{
        // Keep the focus where it was: moving it into the button blurs
        // whatever field the person was in, which saves and rebuilds.
        e.preventDefault();
        if(e.button === 0) holdStep(inp, dir);
      });
      wrap.appendChild(b);
    }
  });
}

// Panels are rebuilt from scratch all over the app — every render, every
// dialog, every list redraw — so rather than remembering to call this in each
// of them, watch for boxes arriving.
(function watchNumbers(){
  if(typeof MutationObserver !== 'function') return;
  const run = ()=>dressNumbers(document);
  run();
  let queued = false;
  new MutationObserver(()=>{
    if(queued) return;
    queued = true;
    soon(()=>{ queued = false; run(); });
  }).observe(document.body, {childList:true, subtree:true});
})();
