/* project.js - Project summary load, page strip rendering + drag reorder, add/remove pages, ask() dialog, settings save, region split.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* The synopsis is the one box you read rather than fill in, so it takes whatever
   height its text needs instead of hiding the end behind a scrollbar. A hidden
   textarea measures as zero, so this is also called when Settings opens. */
const SYNOPSIS_MAX_LINES=10;
function growSynopsis(){
  const t=$('synopsis');
  if(!t || !t.offsetParent) return;     // not on screen yet - nothing to measure
  const cs=getComputedStyle(t);
  let lh=parseFloat(cs.lineHeight);
  if(!isFinite(lh)||!lh) lh=(parseFloat(cs.fontSize)||13)*1.45;
  // border-box: the height has to carry the padding and the border too.
  const chrome=(parseFloat(cs.paddingTop)||0)+(parseFloat(cs.paddingBottom)||0)
              +(parseFloat(cs.borderTopWidth)||0)+(parseFloat(cs.borderBottomWidth)||0);
  const cap=Math.round(lh*SYNOPSIS_MAX_LINES+chrome);
  t.style.height='auto';
  const want=t.scrollHeight+(parseFloat(cs.borderTopWidth)||0)
                           +(parseFloat(cs.borderBottomWidth)||0);
  const over=want>cap;
  t.style.height=(over?cap:want)+'px';
  // Whole thing on screen while it fits; a scrollbar only once it does not.
  t.style.overflowY=over?'auto':'hidden';
}

/* ---------------- project ---------------- */
/* The number on the pill. `version.py` is the one source; the pill is the
   one place a person sees it, and a support message that starts "1.0.0"
   is a message that can be answered. A launcher-started editor also learns
   here whether a newer version is waiting - it is installed on the next
   start, so the pill says so and nothing else moves. */
async function showVersion(){
  const pill=document.querySelector('.brand .betapill');
  if(!pill) return;
  try{
    const v=await api('/api/version');
    _support=v.support||_support;
    pill.textContent=(v.channel?v.channel+' ':'')+v.version;
    pill.title='MangaTCT '+v.version+(v.channel?' ('+v.channel+')':'');
    const u=v.update;
    if(u&&u.available){
      pill.title+='\n'+(u.state==='ready'
        ?'Version '+u.available+' is ready - Settings > Updates > Restart now.'
        :u.state==='offered'
        ?'Version '+u.available+' is available - Settings > Updates.'
        :'Version '+u.available+' is downloading.');
      pill.classList.add('hasupdate');
    }
    // The pill is the way to the Updates section from anywhere.
    pill.style.cursor='pointer';
    pill.onclick=()=>{ if(typeof openSettingsDlg==='function'){ openSettingsDlg(); setSettingsTab('updates'); } };
  }catch(e){}
}

/* ---------------- updates ----------------
   Settings > Updates. lee: *"add an updates tab in the settings that
   downloads the update automatically"*. The server side (`updates.py`) runs
   the launcher's own check/download code; this only shows it and presses
   it. While something downloads the section polls every second. */
let _updTimer=null, _upd=null;
function _ago(t){
  if(!t) return '';
  const s=Math.max(0,(Date.now()/1000)-t);
  if(s<90) return 'Checked just now';
  if(s<5400) return 'Checked '+Math.round(s/60)+' min ago';
  if(s<172800) return 'Checked '+Math.round(s/3600)+' h ago';
  return 'Checked '+Math.round(s/86400)+' days ago';
}
function renderUpdates(u){
  _upd=u;
  const st=$('updState'), act=$('updAct'), bar=$('updBar'), chk=$('updCheck');
  if(!st) return;
  $('updVersion').textContent='MangaTCT '+u.version+(u.channel?' ('+u.channel+')':'');
  $('updLauncher').textContent=u.launcher?'launcher '+u.launcher:'';
  act.hidden=true; bar.hidden=true; $('updSetup').hidden=true;
  if(!u.launched){
    st.textContent='Started from a checkout - updates come from git.';
    chk.disabled=true; $('updAutoRow').style.display='none'; $('updWhen').textContent='';
    return;
  }
  chk.disabled=!!u.busy;
  $('updAuto').checked=!!u.auto;
  $('updWhen').textContent=u.busy?'':_ago(u.last_check);
  const up=u.update, pct=(u.percent!=null?u.percent:(up&&up.percent!=null?up.percent:null));
  if(u.busy==='install'){
    st.textContent='Downloading the new setup…'+(pct!=null?' '+pct+'%':'');
    bar.hidden=false; bar.firstElementChild.style.width=(pct||0)+'%';
  }else if(up&&up.state==='downloading'||u.busy==='check'&&up){
    st.textContent='Downloading '+(up?up.available:'')+'…'+(pct!=null?' '+pct+'%':'');
    bar.hidden=false; bar.firstElementChild.style.width=(pct||0)+'%';
  }else if(u.busy==='check'){
    st.textContent='Checking…';
  }else if(up&&up.state==='ready'){
    st.textContent='Version '+up.available+' is ready.';
    act.hidden=false; act.textContent=u.can_restart?'Restart now':'Quit and start again';
    act.dataset.do='restart';
  }else if(up&&up.state==='offered'){
    st.textContent='Version '+up.available+' is available.';
    act.hidden=false; act.textContent='Download'; act.dataset.do='download';
  }else if(u.problem){
    st.textContent=u.problem;
  }else{
    st.textContent='You have the latest version.';
  }
  const inst=u.installer;
  if(inst&&!u.busy){
    $('updSetup').hidden=false;
    $('updSetupLine').textContent=(inst.required
      ?'This version needs the new setup (launcher '+inst.launcher+').'
      :'A new setup is available (launcher '+inst.launcher+') - it replaces the launcher and runtime, about '
        +Math.round((inst.size||0)/1048576)+' MB.');
  }
  if(u.busy){ if(!_updTimer) _updTimer=setTimeout(()=>{_updTimer=null;refreshUpdates();},1000); }
}
async function refreshUpdates(){
  try{
    const u=await api('/api/updates');
    renderUpdates(u);
    // Opening the section is asking. A check that is older than ten
    // minutes is asked again, which - with the switch on - is the download.
    if(u.launched && !u.busy && (Date.now()/1000-(u.last_check||0))>600) checkUpdates();
  }catch(e){}
}
async function checkUpdates(force){
  try{ renderUpdates(await api('/api/updates','POST',{do:'check',force:!!force})); }catch(e){}
}
async function setAutoUpdates(on){
  try{ renderUpdates(await api('/api/updates','POST',{do:'auto',on:!!on})); }catch(e){}
}
async function actOnUpdate(){
  const act=$('updAct');
  if(act.dataset.do==='download') return checkUpdates(true);
  if(act.dataset.do==='restart'){
    const r=await api('/api/updates','POST',{do:'restart'});
    $('updState').textContent=r.restarting?'Restarting…':'Quitting - start MangaTCT again to run the new version.';
    act.hidden=true;
  }
}
async function getNewSetup(){
  $('updSetupBtn').disabled=true;
  try{
    const r=await api('/api/updates','POST',{do:'install'});
    if(r.error){ $('updSetupLine').textContent=r.error; $('updSetupBtn').disabled=false; return; }
    renderUpdates(r);
  }catch(e){ $('updSetupBtn').disabled=false; }
}

/* ---------------- help ---------------- */
let _support={};
function openGuide(){
  const u=(_support&&_support.guide)||'https://mangatctproject.web.app/tutorial';
  window.open(u,'_blank','noopener');
}
function _diagLines(d){
  const L=[];
  L.push('MangaTCT '+d.version+(d.channel?' ('+d.channel+')':'')+(d.launcher?'  launcher '+d.launcher:''));
  L.push('Python '+d.python+' on '+d.os);
  if(d.machine) L.push(d.machine.trim());
  const c=d.chapter||{};
  L.push('chapter: '+(c.pages||0)+' pages, '+(c.medium||'?')+' from '+(c.source||'?')
    +(c.routes&&c.routes.length?', routes '+c.routes.join('+'):'')
    +(c.ocr?', reader '+c.ocr:''));
  const m=c.models||{};
  if(Object.keys(m).length) L.push('models: '+Object.entries(m).map(([k,v])=>k.replace('_model','')+'='+v).join(', '));
  const k=d.keys_present||{};
  L.push('keys present: '+Object.entries(k).map(([n,v])=>n+(v?' yes':' no')).join(', '));
  if(d.log&&d.log.length){ L.push(''); L.push('--- last lines of the log ---'); L.push(...d.log); }
  else { L.push(''); L.push('(no log file: started by hand, not by the launcher - copy the console window instead)'); }
  return L.join('\n');
}
async function openHelp(){
  const ta=$('diagText'); if(!ta) return;
  ta.value='Gathering…';
  try{
    const d=await api('/api/diagnostics');
    _support=d.support||_support;
    ta.value=_diagLines(d);
    const e=s=>(s||'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
    const bits=[];
    if(_support.discord) bits.push('<a class="btn" target="_blank" rel="noopener" href="'+e(_support.discord)+'">Ask on Discord</a>');
    if(_support.email){
      // mailto bodies are short by nature; the first lines are the ones
      // that matter and the clipboard carries the rest.
      const body=encodeURIComponent('What I did:\n\nWhat happened:\n\n'+ta.value.slice(0,1500));
      bits.push('<a class="btn" href="mailto:'+e(_support.email)+'?subject='+encodeURIComponent('MangaTCT '+d.version+' problem')+'&body='+body+'">Email '+e(_support.email)+'</a>');
    }
    if(!bits.length) bits.push('<span class="muted">Copy the box and send it where you were told to.</span>');
    $('helpLinks').innerHTML=bits.join(' &nbsp; ');
  }catch(err){ ta.value='Could not gather the details: '+(err&&err.message||err); }
}
async function copyDiag(){
  const ta=$('diagText'); if(!ta) return;
  try{ await navigator.clipboard.writeText(ta.value); $('diagMsg').textContent='Copied.'; }
  catch(e){ ta.select(); document.execCommand&&document.execCommand('copy'); $('diagMsg').textContent='Copied.'; }
  setTimeout(()=>{ if($('diagMsg')) $('diagMsg').textContent=''; },2500);
}

async function loadProject(){
  proj=await api('/api/project');
  showVersion();
  if($('title')) $('title').value=proj.context.title||'';
  $('synopsis').value=proj.context.synopsis||''; growSynopsis();
  charSheet={...(proj.context.characters||{})};
  renderCharList();
  glossSheet={...(proj.context.glossary||{})};
  renderGlossList();
  $('minf').value=proj.settings.min_font; $('maxf').value=proj.settings.max_font;
  $('upper').checked=!!proj.settings.uppercase;
  // One default, and it lives in `Project.settings` - every project that
  // is read off disk has been through `settings.update(...)` over those
  // defaults, so the key is always there and a second default here would
  // only ever be a second place to get it wrong.
  $('substitutes').checked=!!proj.settings.substitutes;
  { const mt=$('manual_translate');
    if(mt) mt.checked=!!proj.settings.manual_translate;
    syncManualMode(); }

  // The switches that default ON. Read with `!==false` rather than `!!`,
  // because a project.json written before one of them existed has no key at
  // all - `!!undefined` would switch the story off for every chapter that
  // predates the setting.
  ON_SWITCHES.forEach(k=>{
    const el=$(k); if(el) el.checked = proj.settings[k] !== false; });
  syncStory();
  const _md=mediumDefaults($('medium').value=proj.settings.medium||'manga');
  // `auto` is what the old "Same as the source material" option saved. It only
  // ever resolved to the medium's own language, so it is shown as that.
  $('source').value=(proj.settings.source && proj.settings.source!=='auto')
                    ? proj.settings.source : _md.source;
  $('target').value=proj.settings.target||'en';
  if($('ocr_engine')) $('ocr_engine').value=proj.settings.ocr_engine||'auto';
  // `ocr_detail` is four tabs again - see `syncDetailCards`. It was taken
  // off the screen when the close-up per box won every accuracy score, and
  // came back when the ledger showed what a close-up costs: one picture per
  // BOX rather than one per page. See `ocr.DETAILS` and `coins.pictures`.
  syncReaderCards();
  syncDetailCards();
  $('direction').value=(proj.settings.direction && proj.settings.direction!=='auto')
                       ? proj.settings.direction : _md.direction;
  // The detector menu, the "Text model path" and the two wrapper divs are
  // gone -- one option in a menu is not a choice, and the second path pointed
  // at a detector nothing has called since the routes arrived. lee: *"clean
  // up the whole detecot setting page ... reeove redunced or duplicate
  // settings"*. The model file box went the same way later, and with it a
  // bug worth remembering: the save read that box, nothing ever FILLED it,
  // so every load blanked it and the next save wrote the blank over the
  // path. `saveSettings` carries the setting through now instead of reading
  // a control, which is a shape that cannot do that.
  if($('auto_kind')) $('auto_kind').checked=(proj.settings.auto_kind!==false);
  syncRoutes();
  // On unless it was turned off. Both boxes, the one in Settings and the one
  // on the File tab, are this same setting.
  // Default OFF, and read as such: `!==false` would turn it on for every
  // project.json written before it existed. See the note on `DEFAULT_ON`.
  if($('retype_kinds'))
    $('retype_kinds').checked = proj.settings.retype_kinds === true;
  // Read text also saying what KIND each box is. Default OFF and read the same
  // way, for the same reason: `!==false` would switch it on for every
  // project.json written before it existed - and this one spends a request a
  // page. lee: *"also make it off by defualt"*.
  if($('label_kinds'))
    $('label_kinds').checked = proj.settings.label_kinds === true;
  const recut=(proj.settings.restitch_strips!==false);
  if($('restitch_strips')) $('restitch_strips').checked=recut;
  if($('restitch_new')) $('restitch_new').checked=recut;
  // Multiples of the page width, not pixels. A project saved before the change
  // carries `strip_target`/`strip_max` in pixels; nothing reads them any more,
  // and the two defaults are what those two numbers were on the chapter they
  // were measured off.
  if($('strip_tall')) $('strip_tall').value=proj.settings.strip_tall||3.5;
  if($('strip_tall_max'))
    $('strip_tall_max').value=proj.settings.strip_tall_max||8.5;
  if(typeof stripSettings==='function') stripSettings();
  // An 'ai_boxes' menu stood here. The pass it drove is gone, and an old
  // project.json may still carry the key - nothing reads it.
  // A project-wide engine used to be loaded here - a "Claude model" menu and
  // a "Translation engine" menu. They are gone from the screen; what a step
  // runs on is the step's own boxes and nothing else.
  ['ocr','translate','proofread'].forEach(k=>{
    // Per-step models. The provider box used to offer "Same as the project"
    // and sit on it, which told you nothing about what the step would actually
    // call; it now shows the provider itself, pre-filled with the project's
    // own when the step has never been pointed anywhere else. What decides
    // whether a step is used at all is unchanged and is the MODEL name beside
    // it - an empty model still means "run this step on the project's engine"
    // (see `_ctx_from_settings`) - so no project behaves differently.
    const be=$(k+'_backend'), md=$(k+'_model'),
          bu=$(k+'_base_url'), ky=$(k+'_key');
    // Straight off the settings, with no second default here: the server
    // sends what every step is set to and prices the chapter off the same
    // values, so a box showing anything else would be a screen disagreeing
    // with a bill.
    if(be) be.value=proj.settings[k+'_backend']||'anthropic';
    if(md){
      md.value=proj.settings[k+'_model']||'';
      // The menu is filled from the server, and until it answers the box's
      // own value stands in - so the screen never shows a step as unset while
      // a request is in flight.
      drawModels(k, md.value ? [md.value] : [], null);
      fillModels(k);
    }
    if(bu) bu.value=proj.settings[k+'_base_url']||'';
    if(ky) ky.placeholder=proj.settings[k+'_key']==='set'
      ?'(saved)':'key for this one';
    if(typeof syncCompany==='function') syncCompany(k);
  });
  // One key per service. The boxes are masked the same way the per-step ones
  // were: the server never sends a key back, so an empty box with "(saved)"
  // in it means there is one and nothing has to be retyped to keep it.
  SERVICES.forEach(s=>{
    const el=$('key_'+s);
    if(!el) return;
    const st=proj.settings['key_'+s];
    // Three states, not two. "env" is not a saved key, it is the answer
    // coming from somewhere this box cannot reach: `editor.key_for` reads the
    // .env FIRST, so anything typed here would be saved and then ignored, and
    // a box that says "(saved)" about a value nothing uses is worse than no
    // box at all.
    el.placeholder = st==='env' ? 'from your .env file'
      : st==='set' ? '(saved)' : 'not set';
    el.disabled = st==='env';
  });
  // Keyed on the URL box and not on a method menu, because there is no method
  // menu: cleaning is the AI cleaner. `saveSettings` posts `clean_url`
  // whenever that box exists, so a box nothing fills in is a box that saves an
  // empty string over a real endpoint.
  if($('clean_url')){
    $('clean_url').value=proj.settings.clean_url||'';
    // "(saved)" for anything non-empty is what hid this for a week: the
    // CHANGE-ME example out of the deploy file is non-empty, so a token that
    // had never been filled in looked configured while the endpoint answered
    // 401 to every single call. The placeholder state says so, in the field.
    const ts=proj.settings.clean_token;
    const tf=$('clean_token');
    tf.placeholder = ts==='env' ? 'from your .env file'
      : ts==='set' ? '(saved)'
      : ts==='placeholder' ? 'still the CHANGE-ME example - paste your real token'
      : 'the token from your deploy file';
    // Not `bad` when the file is answering: the CHANGE-ME example may well
    // still be sitting in this chapter's project.json, and it is not the
    // token being sent, so lighting the box red about it points at the wrong
    // string entirely.
    tf.classList.toggle('bad', ts==='placeholder');
    tf.disabled = ts==='env';
  }
  toggleAiCfg();
  renderPages();
  if(!$('font').options.length){
    const f=await api('/api/fonts');
    takeFonts(f);
  }
  if(proj.settings.font) $('font').value=proj.settings.font;
  FONT_KINDS.forEach(k=>{
    const el=$('font_'+k);
    if(el) el.value=(proj.settings.fonts||{})[k]||'';
  });
  if(typeof renderLegend==='function') renderLegend();
  if(typeof renderCustomKinds==='function') renderCustomKinds();
}
// Selection is keyed by page NAME (stable), NOT by position - deleting or
// adding a page renumbers indices, so an index-keyed tick would jump to
// whatever page slid into that slot. A name follows its own page.
let selPages = new Set();      // page NAMES ticked for "do all"
let _seenPages = new Set();    // page NAMES seen so far - new pages start CHECKED
// Remember the ticks across a full page reload (F5), so unchecked pages stay
// unchecked. Stored locally in the browser for this editor.
//
// ...AND ONLY FOR THE CHAPTER THEY WERE MADE ON. The ticks are keyed by page
// NAME, which is stable within a chapter and says nothing whatever between
// two of them: a folder of `page001.png … page071.png` is every chapter
// anybody has ever downloaded. lee opened a new one and *"the tick boxes came
// in pre uncheesced"* - 8 ticked of 71 - because 63 of those names were
// already in `seen` from the chapter before, un-ticked there, and a name that
// has been seen does not get the new-page tick. So the memory carries the
// chapter it was made on and is dropped whole when a different one is opened,
// which puts every page of a new chapter back to CHECKED.
let _selChapter = null;        // the chapter the remembered ticks belong to
let _selStored = null;         // what localStorage had, until it is claimed
try{
  const _s=JSON.parse(localStorage.getItem('mangatl_sel')||'null');
  // Only restore the newer name-keyed form; old numeric ticks are ignored so
  // they can't mis-map onto the wrong pages.
  if(_s && Array.isArray(_s.sel) && _s.byName) _selStored=_s;
}catch(e){}
/* Which chapter this is. The folder alone used to be the answer - and every
   chapter lee makes lives in the SAME folder, because "new project" is a
   reset of it. His new chapter's pages carry the same names as the old
   ones, so the old chapter's deselections claimed them: *"the same pages
   are automaticaly unselcetd , that hsoud not happen"*. The server stamps a
   fresh `chapter_id` on every reset; a project from before the stamp sends
   "" and keys the way it always did. */
function selChapterKey(){
  if(!proj || !(proj.output_dir || proj.input_dir)) return null;
  return (proj.output_dir || proj.input_dir) + '|' + (proj.chapter_id || '');
}
/* Claim the remembered ticks, once the project is known - which is the first
   moment they can be told apart from another chapter's. */
function adoptSel(){
  const key=selChapterKey();
  if(key===null || key===_selChapter) return;
  _selChapter=key;
  if(_selStored && _selStored.chapter===key){
    selPages=new Set(_selStored.sel);
    _seenPages=new Set(_selStored.seen||_selStored.sel);
  }else{
    // A different chapter, or ticks saved before they carried one at all.
    // Forget them: `renderPages` then sees every page as new and ticks it.
    selPages=new Set(); _seenPages=new Set();
  }
  _selStored=null;
}
function saveSel(){
  try{ localStorage.setItem('mangatl_sel',
    JSON.stringify({byName:true, chapter:_selChapter,
                    sel:[...selPages], seen:[..._seenPages]})); }catch(e){}
}
function _pageName(i){ const p=(proj.pages||[]).find(p=>p.index===i); return p?p.name:null; }
function togglePageSel(i){
  const nm=_pageName(i); if(nm==null) return;
  if(selPages.has(nm)) selPages.delete(nm); else selPages.add(nm);
  saveSel(); renderPages();
}
function selectAllPages(on){
  selPages = on ? new Set(proj.pages.map(p=>p.name)) : new Set();
  saveSel(); renderPages();
}
// Pages a "do all" run targets: the checked ones, as current indices.
function scopedPages(){
  return proj.pages.filter(p=>selPages.has(p.name)).map(p=>p.index)
                   .sort((a,b)=>a-b);
}

function renderPages(){
  // Whose ticks are these? Asked here rather than at load, because `proj` is
  // what answers it and it does not exist when this file is parsed.
  adoptSel();
  // New (and first-load) pages default to CHECKED; manual deselects persist.
  let _added=false;
  proj.pages.forEach(p=>{
    if(!_seenPages.has(p.name)){ _seenPages.add(p.name); selPages.add(p.name); _added=true; }
  });
  if(_added) saveSel();
  const all=proj.pages.length;
  const selCount=proj.pages.filter(p=>selPages.has(p.name)).length;
  const allSel=selCount===all && all>0;
  // Whether Edit can be reached is a question about this list.
  if(typeof syncTabs==='function') syncTabs();
  $('pages').innerHTML =
    // Adding pages is an editing action; the Results tab is a gallery of what
    // came OUT. An "+ Add pages" there offers to change the chapter from the
    // one screen that is only ever about the finished thing.
    // lee: *"the add page shosud not be visible in teh result page"*.
    (tab==='results' ? ''
      : `<button class="addbtn" onclick="addFiles()">+ Add pages</button>`) +
    `<button class="addbtn selbtn" onclick="selectAllPages(${allSel?'false':'true'})">
       ${allSel?'Deselect all':`Select all (${selCount}/${all})`}</button>` +
    // `tall` is the red bar down the left of the row - a page Find text will
    // get wrong before it gets it right. See `isTallPage` in pipeline.js,
    // which is the one place that decides which pages those are; `typeof`
    // because this file is parsed on screens where that one is not loaded.
    proj.pages.map(p=>`
      <div class="pg ${p.index===cur?'on':''} ${selPages.has(p.name)?'sel':''}${
             (typeof isTallPage==='function' && isTallPage(p))?' tall':''
           }" draggable="true"
           data-i="${p.index}"
           onclick="showPage(${p.index})"
           oncontextmenu="pgMenu(event,${p.index});return false"
           ondragstart="pgDragStart(event,${p.index})"
           ondragover="pgDragOver(event,${p.index})"
           ondragleave="pgDragLeave(event)"
           ondragend="pgDragEnd()"
           ondrop="pgDrop(event,${p.index})"
           title="Drag to reorder">
        <input type="checkbox" class="pgchk" ${selPages.has(p.name)?'checked':''}
               onclick="event.stopPropagation();togglePageSel(${p.index})"
               title="Tick to include in ‘do all’">
        ${pageDots(p)}
        <span class="nm" title="${p.name}${
          (typeof tallWhy==='function' && tallWhy(p))
            ? ' — ' + tallWhy(p) : ''}">${p.name}</span>
        <span class="ct">${p.regions||''}</span>
        <span class="rm" title="Remove from editor"
              onclick="event.stopPropagation();removePage(${p.index})">&times;</span>
      </div>`).join('') +
    '';
  keepCurrentPageInView();
  renderSteps();
}

/* ---------------- the page rail's width ----------------
   lee: *"alwo me to resize teh side side bar with the titles and make teh
   dealt 25% bigger"*.

   The bounds are what the rail is FOR at each end: under 120px the checkbox
   and the status dots leave no room for a name at all, and past 460 it stops
   being a rail. Kept in the browser next to the ticks, because it is a fact
   about this screen on this machine and not about the chapter - open the
   same project somewhere else and it is that machine's to set. */
const RAIL_MIN = 120, RAIL_MAX = 460, RAIL_DEFAULT = 210;
function railWidth(px, remember){
  const el=$('pages'); if(!el) return;
  const w=Math.max(RAIL_MIN, Math.min(RAIL_MAX, Math.round(px)));
  el.style.width=w+'px';
  if(remember!==false){
    try{ localStorage.setItem('mangatl_rail', String(w)); }catch(e){}
  }
  return w;
}
function railGrab(e){
  e.preventDefault();
  const el=$('pages'), grip=$('pagesGrip');
  if(!el) return;
  const x0=e.clientX, w0=el.getBoundingClientRect().width;
  if(grip) grip.classList.add('on');
  document.body.classList.add('railing');
  const move=ev=>railWidth(w0 + (ev.clientX - x0), false);
  const up=ev=>{
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    if(grip) grip.classList.remove('on');
    document.body.classList.remove('railing');
    // Written once, on let go - a keystroke of localStorage per mouse move is
    // a write per frame for a number nobody reads until the next reload.
    railWidth(w0 + (ev.clientX - x0));
  };
  document.addEventListener('mousemove', move);
  document.addEventListener('mouseup', up);
}
try{
  const _rw=parseInt(localStorage.getItem('mangatl_rail')||'',10);
  if(_rw) document.addEventListener('DOMContentLoaded',()=>railWidth(_rw,false));
}catch(e){}

/* The page list follows the page you are on.

   lee: *"can you make teh side bar with th pages scroll so that teh current
   0age is alwsy in teh frame"*. On a 46-page chapter the list is far longer
   than the rail, so paging through with the arrow keys walked the highlight
   straight off the bottom and the sidebar sat on page 1 while the canvas
   showed page 30.

   `block:'nearest'` and not `'center'`: nearest does NOTHING when the row is
   already visible, so clicking a row you can see never jerks the list out
   from under the pointer, and it moves the least it can when the row is off
   the edge. The scroll is skipped entirely while a row is being renamed -
   that row holds a focused field, and scrolling the list under a caret is
   how a rename loses its place. */
function keepCurrentPageInView(){
  const list=$('pages');
  if(!list || list.querySelector('.nmedit')) return;
  const row=list.querySelector('.pg.on');
  if(!row) return;
  // After innerHTML, layout has not happened yet: measuring now gives zeroes
  // and scrolls nowhere. `soon` is core.js's, which loads first.
  //
  // Guarded, for the same reason `soon` itself is: a missing method here
  // throws inside the callback and everything after it in that frame stops.
  // jsdom has no `scrollIntoView` at all, so an unguarded call turns the
  // page list into a thrown error on every redraw under test.
  soon(()=>{
    if(typeof row.scrollIntoView==='function')
      row.scrollIntoView({block:'nearest', inline:'nearest'});
  });
}

/* One dot per STEP this view is about, filled in when that page has finished
   it. The list used to carry a single dot for the whole page, which said
   "something has happened to this one" and nothing else - so a page that had
   been read but not translated looked exactly like a page that was finished.
   lee: *"istaed of 1 green bubble it shoud be 4 for the origibla page and 2
   for the edit page, one for each step"*.

   Which steps depends on which view you are on, because that is what the view
   IS: Original is the four steps about the WORDS (find, read, translate,
   proofread) and Edit is the two about the PICTURE (clean, typeset). Export
   belongs to neither - it is the whole chapter leaving, not a state a page
   sits in. */
function stepsForView(){
  return (typeof view!=='undefined' && view==='typeset') ? [4,5] : [0,1,2,3];
}
function pageDots(p){
  if(typeof pageDoneStep!=='function')
    return `<span class="dot ${p.status}"></span>`;
  return `<span class="dots">` + stepsForView().map(i=>{
    const done=pageDoneStep(p,i);
    const s=(typeof STEPS!=='undefined' && STEPS[i]) ? STEPS[i].label : '';
    return `<i class="dot${done?' done':''}" title="${_fesc(s)}"></i>`;
  }).join('') + `</span>`;
}

/* ---- drag to reorder the page list ----
   The reorder is committed from BOTH drop and dragend: browsers are
   inconsistent about delivering drop, but dragend always arrives on the
   dragged row, so letting go over a target always works. */
let pgDragFrom=null, pgOver=null, pgDropped=false;
function pgDragStart(e,i){
  pgDragFrom=i; pgOver=null; pgDropped=false;
  e.dataTransfer.effectAllowed='move';
  try{ e.dataTransfer.setData('text/plain', String(i)); }catch(_){}
}
function pgDragOver(e,i){
  if(pgDragFrom===null) return;
  e.preventDefault();
  e.dataTransfer.dropEffect='move';
  const el=e.currentTarget, r=el.getBoundingClientRect();
  const below = e.clientY > r.top + r.height/2;
  pgOver={i, after:below};
  el.classList.toggle('ins-b', below);
  el.classList.toggle('ins-t', !below);
}
function pgDragLeave(e){ e.currentTarget.classList.remove('ins-t','ins-b'); }
function pgDragEnd(){
  const from=pgDragFrom, over=pgOver, handled=pgDropped;
  pgDragFrom=null; pgOver=null; pgDropped=false;
  document.querySelectorAll('.pg.ins-t,.pg.ins-b')
    .forEach(el=>el.classList.remove('ins-t','ins-b'));
  if(!handled && from!==null && over && over.i!==from)
    reorderPages(from, over.i, over.after);
}
function pgDrop(e,i){
  e.preventDefault();
  const el=e.currentTarget, r=el.getBoundingClientRect();
  const after = e.clientY > r.top + r.height/2;
  el.classList.remove('ins-t','ins-b');
  const from=pgDragFrom;
  pgDragFrom=null; pgOver=null; pgDropped=true;
  if(from===null || from===i) return;
  reorderPages(from, i, after);
}
async function reorderPages(from, i, after){
  const n=proj.pages.length;
  const order=[...Array(n).keys()];
  order.splice(from,1);
  let at=order.indexOf(i);
  at = at<0 ? order.length : at + (after?1:0);
  order.splice(at,0,from);
  const origCur=cur, newCur=order.indexOf(cur);
  // show the new order at once; the server confirms right behind it
  proj.pages=order.map((k,pos)=>Object.assign({},proj.pages[k],{index:pos}));
  cur=newCur;
  renderPages();
  await syncPaint();                 // strokes in flight belong to old indices
  const j=await api('/api/pages/reorder','POST',{order});
  proj=await api('/api/project');
  if(j.error){                       // server said no: put things back
    cur=origCur;
    renderPages(); showPage(cur);
    return;
  }
  renderPages();
  record('pages','Pages reordered', null);
  showPage(newCur);
  toast('Pages reordered.');
}

function addFiles(){ $('faddm').click(); }

async function addMorePages(fileList){
  await uploadFiles([...fileList], true);
}

let askResolve=null;
function ask(title, body, okLabel, danger){
  $('askTitle').textContent=title;
  $('askBody').textContent=body||'';
  const b=$('askOk');
  b.textContent=okLabel||'OK';
  b.className = danger ? 'danger' : 'pri';
  $('ask').classList.add('on');
  setTimeout(()=>b.focus(),30);
  return new Promise(res=>{askResolve=res;});
}
function askClose(v){
  $('ask').classList.remove('on');
  if(askResolve){askResolve(v);askResolve=null;}
}
window.addEventListener('keydown',e=>{
  if(!$('ask').classList.contains('on')) return;
  if(e.key==='Escape'){e.stopPropagation();askClose(false);}
  if(e.key==='Enter'){e.stopPropagation();askClose(true);}
},true);

/* ---- right-click a page ----

   lee: *"if i right clcik on one of these tabs i shou dhave the option to
   rename the file"*.

   One entry so far, built the same way the toolbox's long-press flyout is
   (see tbFlyout): a small panel pinned to the viewport at the pointer, closed
   by the next click anywhere or by Escape. */
function pgMenuClose(){ const f=$('pgmenu'); if(f) f.remove(); }
function pgMenu(ev, i){
  ev.preventDefault(); ev.stopPropagation();
  pgMenuClose();
  const f=document.createElement('div');
  f.id='pgmenu'; f.className='tbflyout';
  f.innerHTML=`<button class="tbrow" onclick="renamePage(${i})">
      <span>Rename…</span></button>`;
  document.body.appendChild(f);
  const r=f.getBoundingClientRect();
  f.style.left=Math.round(Math.max(8,
    Math.min(ev.clientX, window.innerWidth-r.width-8)))+'px';
  f.style.top=Math.round(Math.max(8,
    Math.min(ev.clientY, window.innerHeight-r.height-8)))+'px';
}
document.addEventListener('click', e=>{
  if(!e.target.closest || !e.target.closest('#pgmenu')) pgMenuClose();
});
document.addEventListener('keydown', e=>{ if(e.key==='Escape') pgMenuClose(); });

/* Renamed in place, in the row, rather than through a dialog: the name is
   already written there and this is the app's own way of editing text.

   The EXTENSION is not offered. It is not part of what the page is called, and
   a page renamed to .txt is a page nothing can open - so the field holds the
   stem and the server puts the suffix back. */
function renamePage(i){
  pgMenuClose();
  const row=$('pages').querySelector(`.pg[data-i="${i}"]`);
  const span=row && row.querySelector('.nm');
  if(!span || row.querySelector('.nmedit')) return;
  const was=(proj.pages.find(p=>p.index===i)||{}).name || '';
  const dot=was.lastIndexOf('.');
  const inp=document.createElement('input');
  inp.className='nmedit';
  inp.value = dot>0 ? was.slice(0,dot) : was;
  // The row is a click target and a drag handle; while it holds a field it is
  // neither, or selecting the text picks the page up and drops it somewhere.
  row.draggable=false;
  span.replaceWith(inp);
  inp.focus(); inp.select();
  ['click','mousedown','dblclick'].forEach(k=>
    inp.addEventListener(k, e=>e.stopPropagation()));
  let done=false;
  const finish=async (save)=>{
    if(done) return;
    done=true;
    const want=inp.value.trim();
    if(save && want && want!==(dot>0?was.slice(0,dot):was)){
      const j=await api(`/api/page/${i}/rename`,'POST',{name:want});
      if(!j.error){
        // Both of these are keyed by page NAME, so the tick has to follow the
        // page across the rename or it comes back unticked.
        if(selPages.delete(was)) selPages.add(j.name);
        _seenPages.delete(was); _seenPages.add(j.name);
        saveSel();
        proj=await api('/api/project');
      }
    }
    renderPages();
  };
  inp.addEventListener('keydown', e=>{
    e.stopPropagation();
    if(e.key==='Enter') finish(true);
    else if(e.key==='Escape') finish(false);
  });
  inp.addEventListener('blur', ()=>finish(true));
  // A press anywhere else on the screen ends it, and blur alone does not do
  // that: the canvas, the toolbox and the page strip all call preventDefault
  // on mousedown to stop a drag selecting text, and a prevented mousedown
  // never moves the focus - so the field sat there open with the click having
  // gone somewhere else entirely. lee: *"for teh rename thing if i clcik
  // anywhere on teh screen it shoud turn off"*.
  // `capture`, so it is heard before whatever swallows it.
  const away = e => {
    if(e.target===inp) return;
    document.removeEventListener('mousedown', away, true);
    finish(true);
  };
  document.addEventListener('mousedown', away, true);
}

async function removePage(i){
  const name=proj.pages[i].name;
  const yes=await ask(`Remove ${name}?`,
    'It comes out of this project. The file on your disk is not deleted.',
    'Remove page', true);
  if(!yes) return;
  await api('/api/page/'+i,'DELETE');
  proj=await api('/api/project');
  if(!proj.pages.length){showPicker(true);renderPages();return;}
  if(cur>=proj.pages.length) cur=proj.pages.length-1;
  renderPages(); showPage(cur);
}
/* The MAIN types that have their own font row in settings. `bubble` is not
   here: its row is `#font`, the one everything else falls back to. A
   sub-type's face is set beside it under Box types and travels on its own
   record - it is part of what that sub-type is. */
const FONT_KINDS=['freefloat','sfx'];
let FONTS=[];
/* Paths, most recent first. Drawn at the head of every font list. */
let RECENT_FONTS=[];
/* Paths of the faces this person uploaded - the only ones with a remove. */
let UPLOADED_FONTS=[];
/* {kind: path} - the face each kind gets when nothing has been chosen for it.
   The last link of the chain, worked out by the server, because the table it
   comes from is `typeset.DEFAULT_FONTS` and the file it names has to exist on
   this machine. See `editor.shipped_kind_fonts`. */
let KIND_DEFAULTS={};
/* {path: cap-height / point size} and the reference the server scales to.
   A POINT IS NOT A SIZE: Anton's capitals are 0.86 of its point size and Nanum
   Pen Script's are 0.56, so "30pt" in one is a third taller than in the other.
   `typeset.px_for` divides that out on the server and `emPx` does the same
   here, or the preview and the page disagree about every block.
   lee: *"teh typesetter shoud make both visulay the sam size not teh sma
   efont number"*. */
let FONT_CAPS={}, CAP_REF=0.69;
/* {css family name: the file it was loaded from}. `typesetting.fontFam` invents
   a name per face (`mlp0`, `mlp1`, ...) and hands that name to every measuring
   and drawing site, so this is how a family gets back to the path whose cap
   height the server measured. Written there, read here. */
let FAM_PATH={};
/* How tall this face's capitals are, as a fraction of the point size - the
   browser's half of `typeset.cap_ratio`. Out-of-range or unmeasured means
   DON'T SCALE THIS ONE, which is what `CAP_REF` returns. */
function capFor(path){
  const r=+FONT_CAPS[path];
  return (r>=0.30 && r<=1.20) ? r : CAP_REF;
}
/* ...the same for a CSS family name, whichever of the two kinds it is.
   `ml-<kind>` is the face a kind falls back to, and WHICH file that is
   depends on the project's settings, so it is resolved live rather than
   remembered - changing the bubble font has to change this answer. */
function capOfFam(fam){
  if(!fam) return CAP_REF;
  const name=String(fam).split(',')[0].trim().replace(/^['"]|['"]$/g,'');
  if(name.slice(0,3)==='ml-'){
    const p=(typeof fontPathFor==='function')?fontPathFor(name.slice(3)):'';
    return capFor(p);
  }
  return capFor(FAM_PATH[name]||'');
}
/* The pixel size to ASK a face for so its capitals come out the height the
   nominal size promises - the browser's copy of `typeset.px_for`.

   Only the FONT SIZE goes through here. Line pitch does not: the server sets
   `line_h = size * leading` on the nominal size, so a converted leading would
   put the browser's lines somewhere the page's lines are not. */
function emPx(size, fam){
  const s=+size;
  // NaN fails `s>0`; Infinity passes it, and a size box is a text field.
  if(!(s>0) || !isFinite(s)) return 1;
  return Math.min(4000, s*CAP_REF/capOfFam(fam));
}
/* [[group, [[character, name], ...]], ...] - the marks that can go in a line.
   Characters only; the pictures come from /marksample, because the shapes are
   in `marks.py` and a copy of them here is the mistake `DEFAULT_FONTS`
   already taught. */
let MARK_LIB=[];
/* True when the SERVER is older than this page.

   The app is a long-running Python process and these files are static. Copying
   a new version over the top replaces the pages the browser loads and leaves
   the process running the code it started with, so the two can be different
   builds until somebody restarts it.

   lee sent a screenshot of Box types with "Project default" on all twelve
   rows. That was this: his server predated `shipped_kind_fonts`, the answer
   arrived with no `defaults` in it, and the panel had nothing to name a face
   from - so it printed the one thing it says when it does not know, twelve
   times, and looked like an answer.

   Asked as "is the key THERE", not "is it empty". An empty answer is a server
   that looked and found nothing; a missing key is a server that was never
   asked the question. */
let SERVER_STALE=false;
/* One answer, four lists. Every font endpoint returns all of them so nothing
   can be redrawn from a half-updated picture. */
function takeFonts(f){
  FONTS=f.fonts||[];
  RECENT_FONTS=f.recent||[];
  UPLOADED_FONTS=f.uploaded||[];
  KIND_DEFAULTS=f.defaults||{};
  FONT_CAPS=f.caps||{};
  if(+f.cap_ref>0) CAP_REF=+f.cap_ref;
  MARK_LIB=f.marks||[];
  SERVER_STALE=!(f && Object.prototype.hasOwnProperty.call(f,'defaults'));
  if(typeof rebuildFontSelects==='function') rebuildFontSelects();
  if(typeof renderUploadedFonts==='function') renderUploadedFonts();
  if(typeof renderCustomKinds==='function') renderCustomKinds();
}
/* Is this a face that can actually be typeset with - a path naming a file that
   is on this machine right now?

   The question the panel was never asking. A saved setting is just a string,
   and lee's chapters carry `...\fonts\AnimeAce.ttf` on nine box types: a font
   this app is no longer allowed to ship, whose file is gone. `font_for` on the
   server skips a step whose file cannot be opened, and until now the browser
   did not - so the panel printed the dead name and the page came out in
   something else. */
/* Two font paths that name the same file.

   `===` was the whole of this and it is not enough. Windows paths are
   case-insensitive and mix separators, so the same file reaches the browser
   spelled two ways depending on which server call built the string - and the
   panel comparing them exactly is how twelve rows came to read "Project
   default" on lee's machine while working perfectly on Linux.

   The server-side cause is fixed (see `find_fonts`), and this stays anyway:
   the browser cannot know what filesystem it is looking at, and one honest
   comparison here is cheaper than trusting every path-building site in the
   app to agree forever. */
function samePath(a,b){
  if(!a || !b) return false;
  const norm=s=>String(s).replace(/\\/g,'/').replace(/\/+$/,'').toLowerCase();
  return norm(a)===norm(b);
}
function fontUsable(path){
  return !!path && (FONTS||[]).some(f=>samePath(f.path,path));
}
/* The pickers show comic / manga typesetting fonts only (plus everything in
   the project's fonts/ folder). A font already chosen somewhere always stays
   listed, whatever it is. */
function fontChoices(sel){
  const L=(FONTS||[]).filter(f=>f.comic||f.bundled||samePath(f.path,sel));
  return L.length ? L : (FONTS||[]);       // nothing comic installed? show all
}
/* Each font option carries the family on the option (so the custom dropdown
   can draw the word "sample" in it) plus data-name for the plain label. The
   native <select> is hidden; fontWidget() renders the visible dropdown. */
function _fesc(s){return String(s==null?'':s)
  .replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));}
function fontOptionHTML(f, sel){
  // No browser font-loading here - the preview is a server-rendered image
  // (see fontRowInner), so the option only needs its value and name.
  return `<option value="${_fesc(f.path)}"${samePath(f.path,sel)?' selected':''} `+
         `data-name="${_fesc(f.name)}">${_fesc(f.name)}</option>`;
}
function fontOptions(sel){
  return fontOptionList(fontChoices(sel), sel);
}

/* ---- the font picker ----

   A native <select>, and nothing else.

   What stood here was a custom one: the select hidden, a div mirroring it, a
   search box, a recents band, a menu positioned by hand above or below
   depending on room, and a click handler that wrote the pick back through
   whichever select was live at the time. Every one of those parts was there
   for a reason and together they did not work - lee, four times over, ending
   with *"the text drop down still dosent work re design it and remake it so
   taht it works"*.

   So it is the browser's own control. It opens where the browser decides,
   scrolls itself, filters itself when you type a few letters, and cannot be
   left open over a panel that has since been rebuilt. The two things the
   custom one had that this does not:

   * the face drawn in its own face - that went already, because a sample per
     row is an HTTP request per row and four hundred of those is what was
     jamming the sidebar; and
   * a search box - native type-ahead does the same job for a name you know,
     and the Fonts page still has a filter across all the pickers at once.

   Recents survive as an <optgroup>, which is the native way to say the same
   thing. */
function fontWidget(sel){
  if(!sel) return;
  // Anything left over from the old widget goes, including on a page that was
  // open across the change.
  if(sel._fw){ sel._fw.remove(); sel._fw=null; }
  // Three of these are not controls at all: they carry a family's font for
  // `saveSettings` to read and the row you set them from is in Box types.
  // lee: *"detete these"*.
  sel.style.display = (sel.dataset && sel.dataset.headless) ? 'none' : '';
}

/* The five faces you reached for last, then the rest - as two native groups.

   Four hundred fonts with the one you always use somewhere in the middle is a
   search every single time. lee: *"Add a recent fonts to the top of the font
   search top 5"*. A recent that is not in this list (the picker offers
   typesetting faces) is left out rather than offered and then refusing to
   load. */
function fontOptionList(list, cur){
  const recent=(RECENT_FONTS||[])
    .map(p=>list.find(f=>samePath(f.path,p))).filter(Boolean);
  const seen=new Set(recent.map(f=>f.path));
  const rest=list.filter(f=>!seen.has(f.path));
  if(!recent.length) return rest.map(f=>fontOptionHTML(f,cur)).join('');
  const g=(label,items)=>`<optgroup label="${_fesc(label)}">`+
    items.map(f=>fontOptionHTML(f,cur)).join('')+'</optgroup>';
  return g('Recent', recent)+g('All fonts', rest);
}

/* Picking one is what makes it recent, wherever it was picked from. The old
   widget did this in its own click handler; a native select has no handler of
   ours to hang it on, so it is heard once, here, for all of them. */
if(typeof document!=='undefined')
  document.addEventListener('change', e=>{
    const s=e.target;
    if(s && s.tagName==='SELECT' && s.classList &&
       s.classList.contains('fontsel') && s.value) noteFontUsed(s.value);
  });


function enhanceFontSelects(){
  document.querySelectorAll('select.fontsel').forEach(fontWidget);
}
let _fwTimer=null;
/* The inspector rebuilds its HTML on every render (region panel, typesetting
   panel, …). Whenever it does, wrap any font <select> that appeared - this
   covers the per-bubble font picker without threading a call through every
   render branch. */
document.addEventListener('DOMContentLoaded',()=>{
  const insp=$('inspector');
  if(insp && typeof MutationObserver!=='undefined'){
    new MutationObserver(()=>{
      // only wrap NEW selects - wrapping mutates the DOM, and re-wrapping an
      // already-wrapped select would loop the observer
      insp.querySelectorAll('select.fontsel').forEach(fontWidget);
    }).observe(insp,{childList:true,subtree:true});
  }
});
function rebuildFontSelects(){
  const keep=id=>{const el=$(id);return el?el.value:'';};
  const cur={font:keep('font')};
  FONT_KINDS.forEach(k=>{ cur[k]=keep('font_'+k); });
  // A BLANK FIRST, and selected when nothing is set. Without it the menu's
  // first entry - the most recent face, on lee's machine ComicNeue-Italic -
  // was what `saveSettings` read off this select the first time anything
  // was saved, and from then on the project "chose" that face for every
  // kind: the shipped defaults (Comic Neue Bold for speech, Bangers for
  // sounds...) sit after the project font on purpose, so one stray save
  // hid all of them. lee: *"we had a bunch of set defaults"*.
  const want=cur.font||proj?.settings?.font||'';
  $('font').innerHTML='<option value="">Shipped default</option>'+fontOptions(want);
  $('font').value = fontUsable(want) ? want : '';
  FONT_KINDS.forEach(k=>{
    const el=$('font_'+k);
    if(!el) return;
    el.innerHTML=`<option value="">Same as speech balloons</option>`+
      fontOptions(cur[k]);
    if(cur[k]) el.value=cur[k];
  });
  if(typeof fillCkFont==='function') fillCkFont();
  enhanceFontSelects();
}
function fontName(kind){
  const path=fontPathFor(kind);
  const hit=FONTS.find(f=>samePath(f.path,path));
  return hit?hit.name:(path.split(/[\\/]/).pop()||'default');
}
/* Which face a kind of box actually typesets in.

   The SAME chain the server walks in `typeset.font_for`, and it has to stay
   the same chain or this panel is a picture of something else. Two things were
   missing and lee's screenshot showed both.

   It stopped at the project's own font. Past that the server has
   `DEFAULT_FONTS` - a face per kind, so sound effects come out in Bangers and
   a whisper in Comic Neue Regular - and the browser had never heard of it, so
   the three family rows fell through to the first entry in the font list and
   printed `ComicNeue-Bold` as though somebody had chosen it.

   And it took a saved path at its word. `font_for` SKIPS a step whose file
   cannot be opened; this returned it. lee's chapters name
   `...\fonts\AnimeAce.ttf` on nine box types - a font this app may no longer
   ship, gone from his disk - so nine rows named a face the page would never
   come out in.

   `fontUsable` is the skip, `KIND_DEFAULTS` is the tail. */
function fontPathFor(kind){
  const st=(proj&&proj.settings)||{};
  const per=st.fonts||{};
  const sub=((st.custom_kinds)||[]).find(k=>k&&k.key===kind);
  const fam=(typeof familyOf==='function') ? familyOf(kind) : 'bubble';
  const chain=[sub&&sub.font, per[kind], fam!==kind?per[fam]:null, st.font,
               KIND_DEFAULTS[kind], KIND_DEFAULTS[fam]];
  for(const p of chain) if(fontUsable(p)) return p;
  // Nothing on the list is real. Better to name the last thing that was asked
  // for than to name nothing - the row then says what the setting SAYS, and a
  // person who has just deleted a font can see why it is not being used.
  return (sub&&sub.font)||per[kind]||per[fam]||st.font||'';
}
/* The name of the face a box would typeset in if nothing were chosen for it.

   The blank option used to read "Same as the bubble setting", which answers a
   question nobody asked - you are looking at the menu to find out WHICH FACE,
   and the one word that is not on it is the name of the face.
   lee: *"instad of saying sma as this text box it shoud just say the font, do
   that for all of the spot fonts are used"*. */
function inheritedFontLabel(kind){
  const n=fontName(kind);
  return n && n!=='default' ? n : 'Project default';
}
/* Ask the cleaner one question and print the answer here, in the settings
   screen, beside the two fields that decide it.

   This exists because "the token is the same in the app and in the code" and
   "the endpoint answers 401" were true at the same time, and there was no way to
   tell a wrong string from a deployment built before the string changed. The
   server compares the saved token against each local deploy file by hash and
   makes one real call with the cache bypassed; no token is ever sent back. */
async function testCleaner(){
  const out=$('cleanTestOut'), btn=$('cleanTestBtn');
  if(!out) return;
  if($('clean_token')&&$('clean_token').value) await saveSettings();  // test what is typed
  out.className='help'; out.textContent='Asking the cleaner…';
  if(btn){ btn.disabled=true; }
  let r;
  try{ r=await api('/api/clean_test','POST',{}); }
  catch(e){ r={error:String(e&&e.message||e), hint:''}; }
  if(btn){ btn.disabled=false; }
  const bits=[];
  if(r.ok) bits.push('The cleaner answered.');
  else if(r.error) bits.push(r.error.charAt(0).toUpperCase()+r.error.slice(1)+'.');
  if(r.hint) bits.push(r.hint);
  (r.files||[]).forEach(f=>{
    bits.push(`${f.file} → ${f.app||'?'}: token ${f.same_token?'matches':'does NOT match'}`
      + `, address ${f.url_matches?'points here':'points elsewhere'}.`);
  });
  out.textContent=bits.join(' ');
  out.className = 'help ' + (r.ok?'good':'warnbad');
}
function toggleAiCfg(){
  // Always shown. It used to be hidden until the method menu said otherwise;
  // there is no method menu and this is the cleaner's own setup.
  const c=$('aicfg'); if(c) c.style.display='block';
}
/* Which picker each refused font came from, in words. */
const FONT_SLOT={default:'speech bubbles', freefloat:'free-floating text',
                 sfx:'sound effects', narration:'narration'};
/* Put the font pickers back to what the server actually kept. It refuses a
   font that has no letters in it, so without this the dropdown goes on
   showing a choice that was never saved. */
function syncFontSelects(){
  const s=(proj&&proj.settings)||{};
  if($('font')) $('font').value=s.font||'';
  ['freefloat','sfx','narration'].forEach(k=>{
    const el=$('font_'+k); if(el) el.value=(s.fonts||{})[k]||'';
  });
  if(typeof enhanceFontSelects==='function') enhanceFontSelects();
}
async function saveSettings(){
  const fonts={};
  FONT_KINDS.forEach(k=>{ const el=$('font_'+k);
    if(el && el.value) fonts[k]=el.value; });
  (proj.settings.custom_kinds||[]).forEach(k=>{ if(k.font) fonts[k.key]=k.font; });
  const res=await api('/api/settings','POST',{settings:{
    font:$('font').value, fonts, uppercase:$('upper').checked,
    substitutes:$('substitutes').checked,
    manual_translate:($('manual_translate')
                      ? $('manual_translate').checked : false),
    min_font:+$('minf').value, max_font:+$('maxf').value,
    custom_kinds:proj.settings.custom_kinds||[],
    medium:$('medium').value, target:$('target').value,
    source:$('source').value,
    // There is no engine menu: the offline reader picks by language. 'auto'
    // rather than the 'ai' this used to write - 'ai' is not the name of an
    // engine, and `ocr.choose_engine` had to be taught to ignore it.
    ocr_engine:($('ocr_engine')?$('ocr_engine').value:'auto'),
    direction:$('direction').value,
    // Carried through untouched: neither is edited here, and leaving them
    // out of the sheet would save the project with them missing.
    // The reading detail is CARRIED, not read off a control: `pickDetail`
    // has already written it, and a save that reads the screen instead would
    // blank it on every other save - which is the exact bug the "Model file"
    // box had. See `syncDetailCards`.
    ocr_detail: proj.settings.ocr_detail || '',
    ocr_reader:(proj.settings.ocr_reader||'ai'),
    // `detector` is not read off a menu any more -- there is one detector and
    // the routes are the choice. It is still SENT, because `_detect_measured`
    // branches on it and a project.json without it would read as "no
    // detector" the next time it is opened.
    // Neither is edited on this screen any more. `weights` empty means "look
    // beside the app", which is where the download puts the file; a path put
    // in a project by hand is still obeyed, and carried through here.
    detector:'comictext', weights:(proj.settings.weights||''),
    auto_kind:($('auto_kind')?$('auto_kind').checked:true),
    // The route cards are a radio group with no radio in it, so the answer
    // lives in `proj.settings` and not in the DOM. Reading absent checkboxes
    // here is how a selection would be wiped on the next save of any other
    // setting -- `$('animetext')` is null now, and `null ? ... : false` is
    // false, every time.
    webtoon_ko:routeFlag('webtoon_ko'),
    webtoon_zh:routeFlag('webtoon_zh'),
    two_specialists:routeFlag('two_specialists'),
    manga_segmenter:routeFlag('manga_segmenter'),
    animetext:routeFlag('animetext'),
    kind_from_text:!!proj.settings.kind_from_text,
    // Either box. The Settings page may not have been built yet - the File
    // tab is where a new chapter starts - so the one that exists speaks.
    ...($('retype_kinds') ? {retype_kinds:$('retype_kinds').checked} : {}),
    // Same shape, same reason: OMITTED when the box does not exist, so saving
    // from a screen that has not been built cannot write an off - or an on -
    // that nobody asked for.
    ...($('label_kinds') ? {label_kinds:$('label_kinds').checked} : {}),
    restitch_strips:($('restitch_strips') ? $('restitch_strips').checked
                     : ($('restitch_new') ? $('restitch_new').checked : true)),
    strip_tall:(+($('strip_tall')||{}).value||3.5),
    strip_tall_max:(+($('strip_tall_max')||{}).value||8.5),

    ...ON_SWITCHES.reduce((o,k)=>{
      // Absent from the screen is not the same as off: the settings page may
      // not have been built yet. Only send what is really there.
      const el=$(k); if(el) o[k]=el.checked; return o;
    },{}),
    // No menu writes this any more and every path that reads it still works,
    // so it is stated here once: the AI cleaner, on the whole page.
    ai_clean:'all',
    clean_model:(proj.settings.clean_model||'anime-lama'),
    // Only when the box exists (it does not any more): a chapter's saved
    // address must not be wiped by a screen that has no box for it.
    ...($('clean_url')?{clean_url:$('clean_url').value}:{}),
    ...['ocr','translate','proofread'].reduce((o,k)=>{
      const v=id=>($(k+'_'+id)?$(k+'_'+id).value:'');
      o[k+'_backend']=v('backend'); o[k+'_model']=v('model');
      o[k+'_base_url']=v('base_url');
      return o;
    },{}),
    ...SERVICES.reduce((o,s)=>{
      // Masked: only ever send a key somebody has just typed. An empty box
      // means "leave the saved one alone", not "clear it".
      const el=$('key_'+s);
      if(el && el.value) o['key_'+s]=el.value;
      return o;
    },{}),
    ...(($('clean_token')&&$('clean_token').value)?{clean_token:$('clean_token').value}:{})},
    title:($('title')?$('title').value:''),
    synopsis:$('synopsis').value,
    characters:charSheet, glossary:glossSheet});
  proj=await api('/api/project');
  renderInspector();
  syncManualMode();
  const bad=(res&&res.bad_fonts)||[];
  if(bad.length){
    // A font with no alphabet in it - an icon or symbol face - cannot typeset
    // anything, and choosing one used to lay out empty bubbles. The server
    // keeps the font that was working; say which picker went back and why.
    syncFontSelects();
    const who=bad.map(k=>FONT_SLOT[k]||k).join(', ');
    if(typeof toast==='function')
      toast(`That font has no letters in it, so it cannot be typeset with -`+
            ` ${who} kept the font it had.`);
  }
  // Refresh the preview - cleaning settings really can change the plate under
  // the text. What this does NOT do is re-typeset: the layouts already laid out
  // come back untouched and stay on the page until Typeset is run again.
  if(inText()) showPage(cur);
}

/* Settings auto-save as you type; these two buttons give explicit control.
   Entering the Settings page snapshots the saved state (snapshotSettings, in
   view.js setTab) so Cancel can put it back even though edits already saved. */
async function saveSettingsClick(){
  await saveSettings();
  snapshotSettings();                        // this IS the new saved baseline
  if(typeof toast==='function') toast('Settings saved.');
  setTab('edit');
}
async function cancelSettings(){
  // Restore the values captured when the page was opened, then leave. api_key
  // and clean_token are never resent (they are masked), so secrets survive.
  if(_setSnap){
    const s={...(_setSnap.settings||{})};
    delete s.api_key; delete s.clean_token;
    ['ocr','translate','proofread'].forEach(k=>delete s[k+'_key']);
    SERVICES.forEach(x=>delete s['key_'+x]);
    try{ await api('/api/settings','POST',{settings:s,
      title:_setSnap.title||'',
      synopsis:_setSnap.synopsis||'', characters:_setSnap.characters||{},
      glossary:_setSnap.glossary||{}}); }
    catch(e){}
  }
  await loadProject();
  if(typeof toast==='function') toast('Changes discarded.');
  setTab('edit');
}
let _setSnap=null;
function snapshotSettings(){
  if(!proj) return;
  _setSnap={
    settings:JSON.parse(JSON.stringify(proj.settings||{})),
    title:(proj.context&&proj.context.title)||'',
    synopsis:(proj.context&&proj.context.synopsis)||'',
    characters:JSON.parse(JSON.stringify((proj.context&&proj.context.characters)||{})),
    glossary:JSON.parse(JSON.stringify((proj.context&&proj.context.glossary)||{})),
  };
}

async function splitRegion(id){
  const j=await api(`/api/page/${cur}/region/${id}/split`,'POST',{});
  if(j.regions){sel=null;setRegions(j.regions);refreshPages();}
  if(j.split) toast(`Split into ${j.split} bubbles`);
}

/* ---- character sheet (settings) ----
   The working copy lives here; every edit saves through saveSettings, which
   REPLACES the sheet server-side - what you write is the final word. */
let charSheet={};
function renderCharList(){
  const el=$('charList'); if(!el) return;
  const names=Object.keys(charSheet).sort((a,b)=>a.localeCompare(b));
  el.innerHTML=names.map(n=>`
    <div class="row" style="margin-top:5px;align-items:center" data-ch="${esc(n)}">
      <input value="${esc(n)}" style="flex:1"
        onchange="renameCharacter('${esc(n).replace(/'/g,"\\'")}',this.value)">
      <input value="${esc(charSheet[n])}" style="flex:2"
        placeholder="pronouns - voice note"
        onchange="updCharacter('${esc(n).replace(/'/g,"\\'")}',this.value)">
      <button class="danger" title="Remove this character"
        onclick="delCharacter('${esc(n).replace(/'/g,"\\'")}')">&times;</button>
    </div>`).join('')
    ||'<p class="help" style="margin:4px 0">No characters yet.</p>';
}
function addCharacter(){
  const n=$('chName').value.trim(), d=$('chDesc').value.trim();
  if(!n){ toast('Give the character a name.'); return; }
  charSheet[n]=d||'';
  $('chName').value=''; $('chDesc').value='';
  renderCharList(); saveSettings();
}
function updCharacter(n,d){ charSheet[n]=d.trim(); saveSettings(); }
function renameCharacter(oldName,newName){
  newName=newName.trim();
  if(!newName||newName===oldName){ renderCharList(); return; }
  charSheet[newName]=charSheet[oldName]; delete charSheet[oldName];
  renderCharList(); saveSettings();
}
function delCharacter(n){ delete charSheet[n]; renderCharList(); saveSettings(); }

/* ---- glossary: places, terms and other (manga settings) ----
   Stored as {source term: canon English rendering} - the source side is what
   the translator matches on, so it stays in the file, but it is never shown:
   you cannot proofread a language you do not read. The panel shows the English
   rendering only, and that is what you edit.

   The rendering carries its own short note in brackets - "Zaldone (the northern
   kingdom)" - so a row reads name | note, the same shape as a character row,
   and the note travels to the translator with the name.

   People do not belong here. Anything whose rendering names someone already on
   the character sheet is folded away, so a character is never listed twice; the
   AI puts every person it meets on the character sheet directly. */
let glossSheet={};

/* "Lulu (white rabbit)" -> "Lulu";  "Glow - the mercenary" -> "Glow" */
function glossName(v){
  return String(v||'').split(/\s*[（(]|\s+[—–-]\s+/)[0].trim();
}
/* ...and the other half: "Lulu (white rabbit)" -> "white rabbit". */
function glossNote(v){
  const t=String(v||'');
  const m=/[（(]([^)）]*)[)）]/.exec(t);
  if(m) return m[1].trim();
  const d=/\s+[—–-]\s+(.+)$/.exec(t);
  return d?d[1].trim():'';
}
/* Put the two halves back together the one way they are stored. */
function glossValue(name,note){
  name=String(name||'').trim(); note=String(note||'').trim();
  return note ? `${name} (${note})` : name;
}
function _charNameSet(){
  return new Set(Object.keys(charSheet).map(n=>n.trim().toLowerCase()));
}
function _isCharTerm(k){
  const cs=_charNameSet();
  if(!cs.size) return false;
  return cs.has(glossName(glossSheet[k]||k).toLowerCase())
      || cs.has(String(k).trim().toLowerCase());
}
function renderGlossList(){
  const el=$('glossList'); if(!el) return;
  const all=Object.keys(glossSheet);
  const dup=all.filter(_isCharTerm);                  // already a character
  const terms=all.filter(k=>!_isCharTerm(k))
    .sort((a,b)=>String(glossSheet[a]||a).localeCompare(String(glossSheet[b]||b)));
  const q=s=>String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  el.innerHTML=(terms.map(n=>`
    <div class="row" style="margin-top:5px;align-items:center" data-gl="${esc(n)}">
      <input value="${esc(glossName(glossSheet[n]||n))}" style="flex:1"
        placeholder="how it should be written in English"
        onchange="updGlossName('${q(esc(n))}',this.value)">
      <input value="${esc(glossNote(glossSheet[n]||n))}" style="flex:2"
        placeholder="a short note - what or where it is"
        onchange="updGlossNote('${q(esc(n))}',this.value)">
      <button class="danger" title="Remove this term"
        onclick="delGloss('${q(esc(n))}')">&times;</button>
    </div>`).join('')
    ||'<p class="help" style="margin:4px 0">Nothing yet.</p>')
  + (dup.length
     ? `<p class="help" style="margin:8px 0 0">${dup.length} entr${dup.length===1?'y is':'ies are'}
        hidden - ${dup.map(k=>esc(glossName(glossSheet[k]||k))).join(', ')}
        ${dup.length===1?'is':'are'} on the character sheet. The spelling is still
        sent to the translator; it just is not listed twice.</p>`
     : '');
}
function addGloss(){
  const n=$('glTerm').value.trim(), d=$('glDesc').value.trim();
  if(!n){ toast('Give the place or term a name.'); return; }
  // Typed by hand there is no source-side spelling, so the English doubles as
  // the key - the translator still matches it, and nothing shows twice.
  glossSheet[n]=glossValue(n,d);
  $('glTerm').value=''; $('glDesc').value='';
  renderGlossList(); saveSettings();
}
/* Editing one half leaves the other exactly where it was. */
function updGlossName(k,name){
  name=String(name).trim();
  if(!name){ renderGlossList(); return; }        // a term with no name is nothing
  glossSheet[k]=glossValue(name, glossNote(glossSheet[k]||k));
  renderGlossList(); saveSettings();
}
function updGlossNote(k,note){
  glossSheet[k]=glossValue(glossName(glossSheet[k]||k), note);
  renderGlossList(); saveSettings();
}
function delGloss(n){ delete glossSheet[n]; renderGlossList(); saveSettings(); }

/* ---- the model box suggests what the key can actually use ----

   A model name typed by hand is a chapter that dies halfway through: providers
   retire models, and nothing in the editor would tell you.
   lee: *"RuntimeError: OCR server returned 404 ... This model
   models/gemini-2.5-flash-lite is no longer available to new users"*.

   So the box asks the provider for its list the first time it is clicked into.
   Asked once per step per visit - the list does not change while you are
   looking at it, and every ask is a round trip to somebody else's server. The
   settings are saved first, or the answer would be for the provider you had
   before you changed it. */
const modelsAsked = new Set();
/* The models a step may be pointed at, as a MENU rather than a box you type a
   name into. lee: *"inatd of habving to type teh names of teh model there
   shou dbe a drop downlist of all the models"*.

   Typing was how a chapter died halfway through with a 404 - providers retire
   models and nothing here would have told you - and it was also how a step
   ended up on a model the app cannot price, which silently charges the top
   rate. The list comes from the server: the models it prices for that
   provider, or, for a local one whose range it does not price, whatever that
   provider says it has.

   There is no "Other…" row. lee: *"remove teh other from all the dropdowns"*.
   It was the way back to typing a name, and typing a name is the thing this
   menu exists to stop: every id it could produce is either one the menu
   already offers or one that cannot be run, cannot be priced, or both. A model
   that is ALREADY set and is not on the list is still kept and still
   selectable - see `drawModels` - so nobody's existing setting disappears. */

async function fillModels(step, force){
  const sel = $(step + '_model_sel');
  if(!sel) return;
  if(modelsAsked.has(step) && !force) return;
  modelsAsked.add(step);
  let names = [], priced = null;
  try{
    // The server answers off the SAVED settings, and the provider box that
    // just changed is only on screen so far - its own `onchange` starts a
    // save but does not wait for it. Waiting here is what stops the menu
    // being filled with the provider's models from a moment ago.
    if(force) await saveSettings();
    const j = await api('/api/models', 'POST', {step});
    names = j.models || [];
    priced = new Set(j.priced || []);
  }catch(e){ modelsAsked.delete(step); }
  drawModels(step, names, priced);
  // A provider change is the one time the model that was set has to go: it
  // belongs to the provider you just left and cannot run on the one you just
  // chose. Move to the first model the new provider offers, and SAVE it, so
  // the settings and the screen still say the same thing.
  //
  // There was a flag here as well, telling `drawModels` not to keep the old
  // model on the menu. It changed nothing - the move below redraws with a
  // value the new provider does offer - so it is gone.
  if(force && names.length){
    const box = $(step + '_model');
    if(box && !names.includes((box.value || '').trim())){
      box.value = names[0];
      drawModels(step, names, priced);
      await saveSettings();
    }
  }
}

/* Which maker a model comes from. `google/gemini-3.6-flash` -> `google`;
   anything with no slash in it is a direct service's own id and has no maker
   to speak of. Same cut as `coins.vendor_free` in Python, from the other
   side. */
/* The "show me all of them" row's value. Not the empty string, which is what
   an untouched <select> reads as - the two have to be told apart or choosing
   All is indistinguishable from never having chosen. */
const ALL_MAKERS = '*';

function vendorOf(m){
  const i = String(m || '').indexOf('/');
  return i < 0 ? '' : m.slice(0, i);
}

function drawModels(step, names, priced){
  const sel = $(step + '_model_sel'), box = $(step + '_model'),
        ven = $(step + '_vendor');
  if(!sel || !box) return;
  const have = (box.value || '').trim();
  // Kept on the element so choosing a maker can re-filter without asking the
  // server again - it is the same answer, shown differently.
  sel._all = names; sel._priced = priced;

  // ---- the maker menu, and only when there is more than one maker to pick
  const makers = [...new Set(names.map(vendorOf).filter(Boolean))];
  let only = '';
  if(ven){
    if(makers.length > 1){
      // What is already CHOSEN wins over what is already set: this redraws on
      // every pick, and reading the set model's maker first would drag the
      // filter back to it the moment you looked at another one.
      // Empty means never chosen - which is why "All providers" carries a
      // value of its own rather than the empty string.
      const want = ven.value || vendorOf(have) || makers[0];
      ven.innerHTML = '';
      const vadd = (value, label) => {
        const o = document.createElement('option');
        o.value = value; o.textContent = label; ven.appendChild(o);
      };
      makers.forEach(v => vadd(v, v));
      // ...and a way to see all of them at once, for somebody who does not
      // yet know which maker has the thing they want.
      vadd(ALL_MAKERS, 'All providers');
      ven.value = (want === ALL_MAKERS || makers.includes(want))
        ? want : makers[0];
      ven.style.display = ven.dataset.locked ? 'none' : '';
      only = ven.value === ALL_MAKERS ? '' : ven.value;
    }else{
      ven.style.display = 'none';
      ven.value = '';
    }
  }

  sel.innerHTML = '';
  const add = (value, label) => {
    const o = document.createElement('option');
    o.value = value; o.textContent = label;   // set, not written into markup:
    sel.appendChild(o); return o;             // a model name is somebody's string
  };
  // A model with no maker in its name sits under every maker: it is the
  // direct service's own id and hiding it behind a filter it does not answer
  // to would make it unreachable.
  // THE MAKER'S OWN TIER, ON THE ROW. lee: *"every chois that the use can
  // make like teh ai , reader, detector shoud get one of those ratings"*.
  //
  // A menu row cannot carry a coloured chip or a tooltip of its own, so the
  // word goes in the text and the explanation goes on the label above the
  // menu - see `RATE_WORDS`. It is read off the NAME and says so there: it is
  // a published fact about the model, not a measurement of this app's work.
  const tier = m => '  · ' + rateOfModel(m);
  const shown = names.filter(m => !only || !vendorOf(m) || vendorOf(m) === only);
  for(const m of shown)
    add(m, m + tier(m) + (priced && !priced.has(m) ? '  - not priced' : ''));
  // A model that is already set but not in the list - a local one, or an
  // entry a provider has retired since. It stays selectable, because taking
  // somebody's setting away without asking is worse than an odd-looking menu.
  if(have && !shown.includes(have)) add(have, have + tier(have) + '  - as set');
  // Nothing set and nothing offered - a provider that answered with an empty
  // list, or a key that has not been typed yet. Say so in the one place the
  // person is looking, rather than showing an empty menu they will click at.
  if(!sel.options.length) add('', 'No models - check the key for this service');
  sel.value = have || (shown[0] || '');
  box.style.display = 'none';
}

/* A maker was chosen. Nothing is saved by this - it narrows the menu beside
   it and that is all, so browsing the list never changes what a step runs
   on. */
function pickVendor(step){
  const sel = $(step + '_model_sel');
  if(sel) drawModels(step, sel._all || [], sel._priced);
}

/* The menu chose. The BOX is what gets saved - one value, one place - so the
   menu writes into it and everything downstream is unchanged. */
function pickModel(step){
  const sel = $(step + '_model_sel'), box = $(step + '_model');
  if(!sel || !box) return;
  if(!sel.value) return;          // the "no models" row is not a choice
  box.value = sel.value;
  box.style.display = 'none';
  saveSettings();
}

/* Changing the provider changes the answer - and the model that was chosen
   for the old one almost certainly does not exist on the new one, so the menu
   is asked again straight away rather than the next time somebody looks. */
/* The story switches, in one list so the three places that touch them -
   loading, saving, and greying the rest out - cannot fall out of step. The
   master switch is first, and the three that follow it are the ones it
   disables. */
const STORY_SWITCHES = ['story', 'learn_characters', 'learn_terms',
                        'name_speakers'];

/* Every OTHER tick that defaults ON. Being on this list buys the two things
   those four already had, and that a bare `$('x').checked` cannot give a
   default-on switch: it is READ with `!==false`, so a project.json written
   before the setting existed is not switched off by `!!undefined`; and it is
   OMITTED from the save when its box does not exist, so saving from a screen
   that has not been built yet does not write an off nobody asked for. */
/* `label_kinds` - Read text saying what KIND each box is - was on this list
   for about an hour. lee: *"also make it off by defualt"*. It is a plain
   `.checked` switch now, which is what a default-OFF setting wants: an old
   project with no key at all reads `!!undefined` and comes back off, which is
   the answer. `editor.labels_boxes` asks it the same way. */
/* `drop_empty` and `drop_read_twice` are here because they were RUNNING with
   nowhere to turn them off. Both switches came off the settings page and the
   passes behind them stayed - `editor.do_ocr` still reads both keys, both
   still default on - so Read text went on deleting boxes with no way to stop
   it. It cost a box: three readers over one chapter, and the one that gave up
   on page 005 deleted a box that plainly reads 슈, permanently, for everybody
   who read the chapter after it. A pass that removes somebody's work needs a
   tick, and it needs the tick whether or not the pass is usually right. */
/* ...and it stays on ONE line: `test_the_writing_no_mask_covered` reads this
   list by taking the text up to the first newline, so wrapping it silently
   hides everything after the wrap from that check. */
const DEFAULT_ON = ['drop_symbol_only', 'drop_empty', 'drop_read_twice', 'clean_reread', 'keep_honorifics'];
const ON_SWITCHES = [...STORY_SWITCHES, ...DEFAULT_ON];

/* The two reader cards: which is lit, what the offline one is called in this
   project's language, and whether they are shown at all.

   Picked here rather than on the Read text dialog - lee: *"no add the setting
   in the setting page not in the popup"*.

   The name matters because "On this computer" is a different program per
   language - manga-ocr reads Japanese and nothing else, easyocr reads Korean
   and Chinese and is a general engine having a go at comics. A card that says
   the same thing for both would be quietly wrong on one of them. */
function syncReaderCards(){
  const box = $('readerCards');
  if(!box) return;
  const now = (proj.settings.ocr_reader || 'ai');
  for(const c of box.querySelectorAll('.card'))
    c.classList.toggle('on', c.dataset.reader === now);
  const ja = (proj.settings.source || 'ja') === 'ja';
  const name = $('offlineName'), why = $('offlineWhy');
  if(name) name.textContent = ja ? 'manga-ocr, here' : 'easyocr, here';
  if(why) why.textContent = ja
    ? 'One box at a time. Level on dialogue and it never files a line under '
      + 'the wrong box, but it invents dialogue when handed a painted sound.'
    : 'One box at a time. A general reader rather than a comics one, so '
      + 'stylised typesetting costs it more - but nothing leaves the machine.';
  // The word, and it is a JUDGEMENT rather than a count - nobody has scored
  // the two readers against each other on a chapter. The argument for it is
  // the sentence already on the card, which is why the tooltip points at it
  // instead of quoting a number that does not exist.
  const rate = (c, word, tip) => {
    const slot = c.querySelector('.rating');
    if(!slot) return;
    slot.innerHTML = '';
    slot.appendChild(rate3(word, tip));
  };
  const ai = box.querySelector('.card[data-reader="ai"]');
  const off = box.querySelector('.card[data-reader="offline"]');
  if(ai) rate(ai, 'Great',
    'A judgement, not a count. It reads each box with the rest of the page '
    + 'behind it and it is the only one that reads painted sounds.');
  if(off) rate(off, ja ? 'Good' : 'Fair', ja
    ? 'A judgement, not a count. Level with the AI on dialogue; it invents '
      + 'dialogue when handed a painted sound, and it sees one box at a time.'
    : 'A judgement, not a count. A general reader rather than a comics one, '
      + 'so stylised typesetting costs it more - and it sees one box at a '
      + 'time. Nothing leaves the machine, which is the reason to pick it.');
}

/* WHICH ERASER: nothing to sync and nothing to pick - `editor.clean_model`
   names the measured one. Two cards stood here, from when there was a choice
   worth making; lee: *"...ad only ai and the card make this the deaflau
   clenner"*. Why it was ever a list of two and not seven is in editor.html. */

function pickReader(which){
  proj.settings.ocr_reader = which;
  syncReaderCards();
  // ...and the detail row with it: only the AI reader is shown a page, so
  // the question does not exist for the other one.
  syncDetailCards();
  saveSettings();
}

/* HOW MUCH OF THE PAGE THE READER LOOKS AT, and what each answer costs.

   Four tabs, cheapest first, drawn from `DETAIL_MODES` - which is the
   browser's copy of `ocr.DETAILS` and carries the same four keys. lee:
   *"bring back teh 1, 4 and 9 cut and make them tabs instad of drop down"*.

   The price on each card is the thing that brought the choice back. A read
   sends one picture per PIECE, except zoomed, which sends one per BOX - so a
   ten-box page reads at ten pictures instead of one, and the difference on a
   chapter is four times the bill. `coins.pictures` is where that arithmetic
   lives; this only shows it. */
const DETAIL_MODES = [
  ['page',  'Whole page', '1 picture a page',
   'The cheapest read there is, and the least able to make out small '
   + 'vertical type.'],
  ['auto',  '4 pieces', '4 pictures a page',
   'Quartered, so each piece arrives near its own resolution.'],
  ['high',  '9 pieces', '9 pictures a page',
   'Finer still. Scored no better than 4 pieces and costs over twice as '
   + 'much.'],
  ['boxes', 'Zoomed per box', 'one picture a box',
   'A close-up of every box - 96% of the dialogue agreed against 83% for '
   + 'the cut-up page, and nothing filed under the wrong box. The dearest '
   + 'by a long way.'],
];

function pickDetail(which){
  proj.settings.ocr_detail = which;
  syncDetailCards();
  saveSettings();
}

function syncDetailCards(){
  const box = $('detailCards');
  if(!box) return;
  // Only the AI reader is shown a page at all - the offline reader takes one
  // box at a time and there is nothing to choose.
  const ai = (proj.settings.ocr_reader || 'ai') === 'ai';
  const lbl = $('detailLbl');
  box.style.display = ai ? '' : 'none';
  if(lbl) lbl.style.display = ai ? '' : 'none';
  if(!ai) return;
  const now = proj.settings.ocr_detail || 'auto';     // 4 pieces: the default (lee)
  box.innerHTML = DETAIL_MODES.map(([k, name, cost, why]) =>
    `<button type="button" class="card${k === now ? ' on' : ''}"` +
    ` data-detail="${k}" onclick="pickDetail('${k}')">` +
    `<b>${esc(name)}</b><i>${esc(cost)}</i>` +
    `<span>${esc(why)}</span></button>`).join('');
  syncZoomOnly(now);
}

/* The switches that only mean anything on a close-up.

   Reading the page in pieces MISFILES text - 16 boxes of 225 at four pieces,
   20 at nine, measured against manga-ocr on lee's chapter 3 - because the
   model has to match what it read to a number drawn on the page. A close-up
   has one box in it and nothing to match.

   So a rule that changes a box's TYPE from the words read for it is only as
   good as the filing, and on the cut-up modes it is not good enough to act
   on. It greys out rather than disappearing: the setting keeps its value,
   and picking zoomed again finds it where it was. lee: *"if teh user clcik
   on 1,4,or 9 sissble teh settings that only works with zoomed in boxes"*. */
function syncZoomOnly(detail){
  const zoomed = (detail || 'auto') === 'boxes';
  ['retype_kinds'].forEach(id => {
    const el = $(id);
    if(!el) return;
    el.disabled = !zoomed;
    const row = el.closest('label');
    if(row){
      row.classList.toggle('offx', !zoomed);
      row.title = zoomed ? ''
        : 'Only on a close-up per box. Read in pieces, a line can be filed '
          + 'under the wrong box, and this changes a box\'s type from the '
          + 'words filed under it.';
    }
  });
}

/* With no story kept there is nothing for the AI to fill in, so the three
   ticks below the master switch go dead rather than staying clickable and
   doing nothing. Their own values are left alone - turning the story back on
   finds them as they were. */
function syncStory(){
  const on = !$('story') || $('story').checked;
  const box = $('storyopts');
  if(box){
    box.style.opacity = on ? '' : '.45';
    box.style.pointerEvents = on ? '' : 'none';
    box.querySelectorAll('input').forEach(i=>{ i.disabled = !on; });
  }
  // The three Story sections are about a story nobody is keeping. Say so on
  // the buttons rather than hiding them - a person who has just switched it
  // off should be able to see what they still have written down.
  document.querySelectorAll('#setNav .setnav-btn').forEach(b=>{
    if(['synopsis','characters','terms'].includes(b.dataset.sec))
      b.classList.toggle('dim', !on);
  });
}

function modelsStale(step){
  // No step named means the KEY changed, and a key is a fact about the
  // service - so every step that could be on it has to ask again. See
  // `editor.model_menu`: the menu is what the key can reach crossed with
  // what this app can price, so a new key is a different menu everywhere.
  const steps = step ? [step] : SERVICES_STEPS;
  for(const s of steps){ modelsAsked.delete(s); fillModels(s, true); }
}

/* The three services this app offers, and the three steps that can be put on
   one. This list is `project.SERVICES` and `editor.SERVICES`, and a test holds
   all three in step: a service the screen offers and the server does not know
   is a step nobody can run, and it fails at the provider rather than at the
   menu, halfway through a chapter. */
const SERVICES = ['anthropic', 'gemini', 'openrouter'];
const SERVICES_STEPS = ['ocr', 'translate', 'proofread'];

/* ------------------------------------------------- the AI company, per step
   lee: *"for te ai ... i just wan the ai compay and teh ai model"*, then
   *"for the translation sinatsd of otrher it shodu be open deepsek quwen
   etc"* - so the menu names the MAKERS. Claude and Google are their own
   services and use their own keys first; every other maker is bought through
   OpenRouter, which is why picking one saves backend=openrouter and narrows
   the model menu to that maker's models. The company menu is NOT a stored
   setting: what is saved is the same backend/model pair as always, so an old
   project reads back exactly as it was. */
const COMPANY_BACKEND = {claude: 'anthropic', google: 'gemini'};

function companyOf(step){
  const be = ($(step + '_backend') || {}).value || '';
  if(be === 'anthropic') return 'claude';
  if(be === 'gemini') return 'google';
  const v = vendorOf(($(step + '_model') || {}).value || '');
  if(v === 'anthropic') return 'claude';
  if(v === 'google') return 'google';
  const co = $(step + '_company');
  if(v && co && [...co.options].some(o => o.value === v)) return v;
  return '*';
}

function syncCompany(step){
  const co = $(step + '_company');
  if(!co) return;
  const now = companyOf(step);
  /* A PROJECT SET TO A MAKER THAT IS NOT IN THE MENU STILL SAYS SO.

     Mistral, Meta, xAI and "Any provider" came off the list - lee: *"remove
     thses from the lists"* - and a project already running one of them would
     otherwise land on a menu with nothing selected, which reads as "no model
     chosen" for a step that has one. So the maker it is really on is added
     back for as long as it is the answer, named rather than starred. Picking
     anything else replaces it and it does not come back. */
  if(![...co.options].some(o => o.value === now)){
    const o = document.createElement('option');
    o.value = now;
    o.textContent = now === '*' ? 'Whatever the model names'
                                : now + ' (set on this project)';
    co.appendChild(o);
  }
  co.value = now;

  /* READ TEXT ONLY OFFERS MAKERS THAT CAN LOOK AT A PAGE.

     lee, at this menu offering DeepSeek: *"for thsi only visin caplabel
     models hsoud show up"*. Reading text off a page hands the model a
     picture, so a maker with nothing that can be shown one has no model to
     offer here at all - picking it lands on "No models - check the key for
     this service", which reads as a broken key rather than as a maker that
     does not do this job. Translate and proofread are text jobs and keep the
     whole list.

     WHICH makers those are comes from the server - `coins.blind_makers`,
     read off the same `NO_SIGHT` that already filters the model menu. A list
     written down here would be a menu still offering DeepSeek the day that
     one changes.

     Hidden AND disabled: `hidden` alone leaves the row reachable from the
     keyboard in some browsers, and an option nobody can see is not a choice
     anybody meant to make. The one it is actually SET to is never hidden -
     taking a step's own maker off its menu is the "no model chosen" bug
     above, arriving from the other side. */
  const blind = step === 'ocr'
    ? ((typeof proj !== 'undefined' && proj && proj.blind_makers) || []) : [];
  for(const o of co.options){
    const hide = blind.includes(o.value) && o.value !== now;
    o.hidden = hide;
    o.disabled = hide;
    o.style.display = hide ? 'none' : '';   // `[hidden]` is only a UA rule
  }
}

async function pickCompany(step){
  const co = $(step + '_company'), be = $(step + '_backend');
  if(!co || !be) return;
  be.value = COMPANY_BACKEND[co.value] || 'openrouter';
  await saveSettings();
  await fillModels(step, true);
  if(be.value !== 'openrouter') return;
  // narrow the reseller's catalogue to the maker that was just named, and
  // land on one of that maker's models rather than whoever came first
  const ven = $(step + '_vendor'), sel = $(step + '_model_sel'),
        box = $(step + '_model');
  const want = co.value === '*' ? ALL_MAKERS : co.value;
  if(ven && [...ven.options].some(o => o.value === want)){
    ven.value = want;
    pickVendor(step);
  }
  if(co.value !== '*' && sel && box && vendorOf(box.value) !== co.value){
    const first = [...sel.options].map(o => o.value)
      .find(v => vendorOf(v) === co.value);
    if(first){
      box.value = first;
      drawModels(step, sel._all || [], sel._priced);
      await saveSettings();
    }
  }
}




/* ---- fonts you added yourself ----

   lee: *"Allow uploading fonts in the setting and a way to remove the fonts
   that were uploaded - the fonts should presist to new projects"*.

   They are kept beside the app rather than in the chapter, so the server owns
   the list and every one of these answers with the whole of it - there is no
   way for the three lists on screen to disagree with each other. */
async function uploadFonts(input){
  const files=[...(input.files||[])];
  input.value='';                            // so the same file can be re-picked
  if(!files.length) return;
  const msg=$('fontUpMsg');
  if(msg) msg.textContent='Adding…';
  const payload=[];
  for(const f of files){
    payload.push({name:f.name, data:await fileB64(f)});
  }
  const j=await api('/api/font','POST',{do:'add', files:payload});
  takeFonts(j);
  if(msg) msg.textContent = j.error ? j.error
    : (files.length===1 ? 'Added.' : `Added ${files.length} fonts.`);
  if(j.error && typeof toast==='function') toast(j.error);
}
/* FileReader, not fetch: the file is on this machine and never had a URL. */
function fileB64(f){
  return new Promise((ok,no)=>{
    const r=new FileReader();
    r.onerror=()=>no(new Error('could not read '+f.name));
    r.onload=()=>ok(String(r.result).split(',')[1]||'');
    r.readAsDataURL(f);
  });
}
async function removeFont(path){
  const j=await api('/api/font','POST',{do:'remove', path});
  takeFonts(j);
  // A face that was being typeset in has just gone. Whichever select was
  // pointing at it now points at nothing, which the server reads as "use the
  // default" - the same thing it will actually do.
  if(j.error && typeof toast==='function') toast(j.error);
}
/* Which face was reached for last. Not saved with the project: the point is
   that the next chapter already knows. */
async function noteFontUsed(path){
  if(!path) return;
  try{ takeFonts(await api('/api/font','POST',{do:'used', path})); }
  catch(e){}                                 // a recents list is never worth an error
}
function renderUploadedFonts(){
  const box=$('upFontList');
  if(!box) return;
  const list=UPLOADED_FONTS||[];
  box.innerHTML='';
  if(!list.length){
    const p=document.createElement('p');
    p.className='help'; p.style.margin='6px 0 0';
    p.textContent='No fonts added yet.';
    box.appendChild(p);
    return;
  }
  for(const fp of list){
    const name=String(fp).split(/[\\/]/).pop().replace(/\.(ttf|otf)$/i,'');
    const row=document.createElement('div');
    row.className='row upfont';
    const nm=document.createElement('span');
    nm.className='upfont-nm'; nm.textContent=name;   // a file name, set not written
    // No strip of the word "sample" beside it. The row is a list of what you
    // have added and a way to take one back out; the face itself is looked at
    // in the menu you typeset from, where choosing it is the next thing you do.
    // lee: *"remove teh smaple from the add fonts"*.
    const x=document.createElement('button');
    x.className='xbtn'; x.title='Remove this font'; x.textContent='×';
    x.addEventListener('click',()=>removeFont(fp));
    row.append(nm, x);
    box.appendChild(row);
  }
}


/* THE ROUTES, AS ONE GROUP YOU PICK FROM.

   lee: *"make all teh detectore selecteabe card in the setting so i can pick
   and choos and mek them nice"*.

   They were three independent ticks and independence was never true:
   `_detect_measured` asks them in order and the first one that says yes wins,
   so two ticked meant one silently ignored. One selection now, and the server
   still gets the same three booleans -- exactly one of which is true.

   A card whose weights are not on this machine is DISABLED rather than
   hidden, with the reason under the group. Hiding was right when each was a
   lone tick nobody could act on; here the cards beside it say what the
   download would buy, so the missing one is worth showing greyed.

   WHICH FORMAT EACH WAS MEASURED ON, which is not a detail. lee: *"we to
   find and use detector that are good for manwa and mnahua not the same ones
   at teh manga"*. Every route but one was swept on Japanese manga fragments
   and is guarded to them server-side (`Project.TWO_MEDIA`); the two webtoon
   models are guarded the other way (`STRIP_MEDIA`). A card offered on a
   format its route will refuse to run on is a card that silently does
   nothing, so the list below is the same set of guards said once more, on
   this side, where the buttons are.

   It lives here rather than on the buttons because `currentRoute` is asked
   with no settings page built - the File tab is where a chapter starts - and
   an answer that depends on markup that may not exist is an answer that is
   sometimes wrong. */
const ROUTE_MEDIA = {
  '':                ['manga', 'manhwa', 'manhua'],
  webtoon_ko:        ['manhwa', 'manhua'],
  webtoon_zh:        ['manhwa', 'manhua'],
  two_specialists:   ['manga'],
  manga_segmenter:   ['manga'],
  animetext:         ['manga', 'manhwa', 'manhua'],
};
const ROUTES = ['webtoon_ko', 'webtoon_zh', 'two_specialists',
                'manga_segmenter', 'animetext'];

function routeMedium(){
  return (typeof proj !== 'undefined' && proj && proj.settings
          && proj.settings.medium) || 'manga';
}

/* Is this card on screen for the format being worked on? */
function routeHere(name){
  const on = ROUTE_MEDIA[name || ''];
  return !on || on.indexOf(routeMedium()) >= 0;
}

/* THE PICKED ROUTE, OR THE FALLBACK, and a route this format does not offer
   counts as the fallback. `webtoon_ko` ships ON - it is the default a manhwa
   or a manhua should have, and there is no per-format defaults table to put
   it in - so on a manga the flag is set and the route is guarded off, and
   this is what stops the settings page lighting up a card that is not on it
   and cannot run. The server reaches the same answer by the same route:
   `webtoon_ko()` asks `why_not_webtoon_ko` asks the medium. */
function currentRoute(){
  if(typeof proj === 'undefined' || !proj || !proj.settings) return '';
  for(const k of ROUTES) if(proj.settings[k] && routeHere(k)) return k;
  return '';
}

/* What to SEND for one route key. A route this format does not offer is
   passed through untouched rather than turned off: it is the other format's
   answer, and a save on this screen is not a decision about that one. Turning
   them off here is how picking Manga109 on a manga would quietly take the
   webtoon default off a manhwa - the same project, switched over, with no
   card lit and comic-text-detector running. */
function routeFlag(k){
  return routeHere(k) ? (currentRoute() === k)
                      : !!(proj && proj.settings && proj.settings[k]);
}

function pickRoute(name){
  const st = (typeof proj !== 'undefined' && proj) ? proj[name] : null;
  if(name && (!st || !st.ready)) return;
  for(const k of ROUTES) if(routeHere(k)) proj.settings[k] = (k === name);
  syncRoutes();
  saveSettings();
  /* AND THE CHECKPOINTS START LOADING NOW.
     They used to load on whichever page a run reached first, inside a bar
     reading "1 of 30" - DB++/COO is 54s on page one of a fresh process and
     9.6s by page three, so a fifteen-second load read as a fifty-second page.
     lee drew that conclusion three times. Picking a card is the moment there
     is nothing to misread it as, and the call returns before the reading
     starts, so the settings page never waits on it. */
  api('/api/models/warm', 'POST', {}).catch(function(){});
}

function syncRoutes(){
  const wrap = $('routeCards'); if(!wrap) return;
  /* The group used to be hidden outright on anything but a manga, because
     every route in it had been measured on manga alone and offering one on a
     manhwa would have been offering a number nobody had counted. Two of them
     were counted on a webtoon since, so the group is on for every format now
     and the CARDS are what come and go. */
  wrap.style.display = '';
  const now = currentRoute();
  wrap.querySelectorAll('.card').forEach(function(c){
    const name = c.getAttribute('data-route');
    const here = routeHere(name);
    /* `style.display`, NOT the `hidden` attribute. `hidden` is a UA rule -
       `[hidden]{display:none}` - and `.cards .card{display:flex}` is a class
       selector, so the stylesheet wins and every card stays on screen. It
       showed as all six cards at once on a manhwa, with the two that need
       panels sitting there greyed and blank. */
    c.style.display = here ? '' : 'none';
    if(!here){ c.classList.remove('on'); return; }
    const st = name ? ((typeof proj !== 'undefined' && proj) ? proj[name] : null)
                    : {ready: true};
    const ready = !!(st && st.ready);
    c.disabled = !ready;
    c.classList.toggle('on', name === now);
    /* THE REASON GOES ON THE CARD THAT IS GREY.
       lee: *"also the other detector are grey out"*. It used to go in one
       shared line under all four, and that line only ever showed the FIRST
       reason - three cards greyed out, one sentence, and no way to tell which
       card it belonged to. Every reason `why_not_*` returns is a sentence
       somebody can act on ("ultralytics is not installed - run `pip install
       ultralytics`"), so it belongs against the card that cannot run. */
    let note = c.querySelector('.why');
    if(!ready && st && st.why){
      if(!note){
        note = document.createElement('em');
        note.className = 'why';
        c.appendChild(note);
      }
      note.textContent = st.why;
      c.title = st.why;
    }else if(note){
      note.remove();
      c.removeAttribute('title');
    }
  });
  const shared = $('routeWhy');
  if(shared) shared.textContent = '';
  rateRoutes();
}

/* ------------------------------ FAIR, GOOD, GREAT ------------------------

   lee: *"remove teh blue bar and the number and create a new ratting system,
   fair, good and great and every chois that the use can make like teh ai ,
   reader, detector shoud get one of those ratings"*, and *"fair beigng the
   worst and great being teh best"*.

   THREE WORDS BECAUSE THE FOURTH DIGIT WAS A LIE. The detector cards carried a
   bar and a percentage - 92, 96, 96, 95 - and a bar invites the comparison the
   numbers cannot carry: the whole spread between best and worst is a third of
   a mistake per page. A word says the size of the difference honestly.

   AND BECAUSE ONLY ONE CHOICE HAD ONE. The reader and the model are choices
   too, and they had nothing at all beside them, which reads as "nobody has an
   opinion about this" rather than "nobody has counted this". They are not the
   same kind of answer, so each word carries where it came from in its own
   tooltip, and the three sources are told apart on purpose:

   * the DETECTOR is counted - 226 hand-checked sites, missed and stray.
   * the READER is a judgement, and its argument is the sentence already on
     the card.
   * the MODEL is read off the maker's OWN tier in its name. `lite`, `mini`
     and `haiku` are what the makers call their small models and `opus` and
     `pro` what they call their large ones; that is a published fact about the
     model and not a measurement of anything this app does, and the tooltip
     says exactly that.

   A rating whose formula is a secret is a rating nobody can argue with, which
   is the opposite of useful - so none of these three is a secret. */
const RATE_WORDS = ['Fair', 'Good', 'Great'];

/* How many places on a WEBTOON somebody has to translate, hand-checked the
   same way the 226 manga ones were: every balloon and every caption on the 22
   tiles of lee's own Korean chapter, counted off the four routes' boxes drawn
   on the page.

    route                 missed  junk  s/page
    comic-text-detector        1     2     2.8
    Webtoon balloons KO        1     0     2.8
    Webtoon balloons ZH        5     1     2.8
    AnimeText YOLO12-L         1     3     4.7

   PAINTED SOUND EFFECTS ARE NOT IN IT, and that is the one thing to know
   about this number. There were nine on the chapter; AnimeText found six,
   comic-text-detector five, and the webtoon models none at all on their own.
   Folding nine into thirty-three would have rated all four Fair and hidden
   the difference that actually decides the card, so they are counted apart
   and said out loud in the tooltip instead.

   The webtoon routes borrow those boxes now - see `FILL` in detect/webtoon.py
   - which is why their seconds went up and their miss count did not: what
   they gained is a family this count never included. */
const WEBTOON_SITES = 33;

/* The chip, from a word and its reason. One place, so the three surfaces
   cannot drift into three shapes. */
function rate3(word, why){
  const w = RATE_WORDS.includes(word) ? word : 'Good';
  const s = document.createElement('b');
  s.className = 'rate3 ' + w.toLowerCase();
  s.textContent = w;
  if(why) s.title = why;
  return s;
}

/* A COUNTED score, out of 100. The thresholds are absolute rather than
   relative to the best card on screen: a rating that moves when a new model
   is added is a rating that told you something about the list rather than
   about the thing. */
function rateOfScore(pct){
  return pct >= 95 ? 'Great' : pct >= 85 ? 'Good' : 'Fair';
}

/* THE MAKER'S OWN TIER, read off the name.

   WORDS, NOT SUBSTRINGS. The first go matched `mini` anywhere in the id and
   rated every Gemini model on earth Fair, because `gemini` has `mini` in it.
   So the id is cut into words on anything that is not a letter or a digit and
   the tier is a whole word among them - which also gets `claude-haiku-4-5`
   and `anthropic/claude-haiku-4.5` to the same answer, and they are the same
   model.

   The small end is asked first, so `gemini-3.5-flash-lite` is caught by
   `lite` and never reaches the middle. A name with no tier word in it -
   `deepseek-chat`, somebody's local build - is called Good, which is the
   honest answer for "no opinion" and not a compliment; the tooltip says the
   name carries no tier. */
const RATE_SMALL = ['lite', 'mini', 'nano', 'small', 'tiny', 'haiku'];
const RATE_BIG = ['opus', 'fable', 'pro', 'max', 'ultra'];

function rateOfModel(id){
  const w = String(id || '').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  // ...and a parameter count is a tier too: `llama-3-8b` is the small one.
  if(w.some(t => RATE_SMALL.includes(t) || /^\d+b$/.test(t))) return 'Fair';
  if(w.some(t => RATE_BIG.includes(t))) return 'Great';
  return 'Good';
}

/* WHAT EACH CARD COSTS AND HOW GOOD IT IS.

   lee: *"also add time estimation and a quality rattoing on each box"*.

   The time is this chapter, not a page: seconds-per-page measured on the 23
   test pages times the number of pages actually loaded, which is the number
   somebody is deciding about. It is honest about being an estimate -- the
   measurement was one machine on one chapter -- and it is worth showing
   anyway, because the difference between the cards is 3 minutes and 11.

   The rating is `(226 - missed - junk) / 226` over the hand-checked sites,
   said out loud on the card rather than left as stars nobody can check. A
   rating whose formula is a secret is a rating nobody can argue with, which
   is the opposite of useful. */
function rateRoutes(){
  const wrap = $('routeCards'); if(!wrap) return;
  const pages = (typeof proj !== 'undefined' && proj && proj.pages)
                 ? proj.pages.length : 0;
  /* WHICH COUNT, which depends on what is being translated. The 226 sites
     are 23 pages of Japanese manga; a webtoon was counted separately, on
     lee's own Korean chapter, and the two answers are different enough that
     showing either on the other format would be a made-up number. A card
     shown on both carries both sets and picks here. */
  const strip = ROUTE_MEDIA.webtoon_ko.indexOf(routeMedium()) >= 0;
  const SITES = strip ? WEBTOON_SITES : 226;
  wrap.querySelectorAll('.card').forEach(function(c){
    const g = k => c.getAttribute((strip ? 'data-w' : 'data-') + k);
    // A card the format does not offer has no count for it either, and
    // `syncRoutes` has already taken it off the screen.
    if(g('missed') === null || g('missed') === '') return;
    const sec = parseFloat(g('sec') || '0');
    const missed = parseInt(g('missed') || '0', 10);
    const junk = parseInt(g('junk') || '0', 10);
    const score = Math.round(100 * (SITES - missed - junk) / SITES);
    const secs = sec * (pages || 0);
    const time = !pages ? sec.toFixed(1) + 's a page'
      : (secs < 90 ? Math.round(secs) + 's'
                   : Math.round(secs / 60) + ' min')
        + ' for ' + pages + ' page' + (pages === 1 ? '' : 's');
    const est = c.querySelector('.est');
    if(est) est.textContent = time;
    const slot = c.querySelector('.rating');
    if(slot){
      slot.innerHTML = '';
      slot.appendChild(rate3(rateOfScore(score),
        'Counted, not guessed: ' + (SITES - missed - junk)
        + ' of ' + SITES + ' hand-checked '
        + (strip ? 'balloons and captions on a Korean chapter'
                 : 'sites on 23 pages of manga')
        + ' right - ' + missed + ' missed, ' + junk + ' stray. '
        + (strip ? 'Painted sound effects are counted apart: 6 on those '
                 + 'pages, and no route on colour art finds them all. ' : '')
        + 'Great is 95 in a hundred or better, '
        + 'Good is 85, Fair is under that.'));
    }
  });
}


