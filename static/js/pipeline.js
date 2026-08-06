/* pipeline.js — Detect / translate / typeset steps, scoped runs, template round-trip, job polling.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* ---------------- jobs ---------------- */
let scopeEp=null;
/* Which PAID step each scoped endpoint is, for pricing it. "" is a step that
   runs on this machine and costs nothing — and it must stay "" rather than be
   left out, because a step nobody priced and a step that is free look the
   same on the button and are not the same thing. */
const SCOPE_STEP = {ocr_all:'ocr', translate_all:'translate',
                    proofread_all:'proofread', clean_all:'clean',
                    typeset_all:''};

/* The price of each choice, on the choice. lee: *"on the pop up it shoud tell
   teh price for all the pages and and this page onli on the side"* — so it
   goes beside the label rather than in it, and the two numbers are the two
   things you are actually choosing between.

   Both come from one request, priced server-side for exactly the pages each
   button would run: `prices` for the ones the button says, `one` for the page
   on screen. A free step shows nothing at all — a price of zero on a button
   reads as a price nobody has worked out yet, not as free. */
let scopeQuote = null;

function priceScope(){
  const all = $('scpAll'), one = $('scpOne');
  if(!all || !one) return;
  const step = SCOPE_STEP[scopeEp] || '';
  const put = (el, n) => {
    // Always clear first. The dialog is reused for every step, so a price
    // left behind is last step's price under this step's label.
    const had = el.querySelector('.scpcoin');
    if(had) had.remove();
    // A free step has no entry in `prices`, so it arrives here as null and
    // stops on the same line an unpriced step does. There was a `!step` test
    // as well; a mutant that deleted it changed nothing, because the two
    // conditions are the same condition.
    if(n == null) return;
    el.insertAdjacentHTML('beforeend',
      `<span class="scpcoin">${n} <svg class="coinpip" width="13" height="13"` +
      ` aria-hidden="true"><use href="#tctcoin"/></svg></span>`);
  };
  if(!step || !scopeQuote){ put(all, null); put(one, null); return; }
  put(all, (scopeQuote.prices||{})[step]);
  put(one, (scopeQuote.one||{})[step]);
}

/* The pages the "every / selected" button would actually run, as the query
   the server prices. Empty means the whole chapter, which is what that button
   says when nothing is ticked. */
function scopeQuery(){
  const picked = (selPages.size && selPages.size < proj.pages.length)
    ? proj.pages.map((_pg,i)=>i).filter(i=>selPages.has(proj.pages[i].name))
    : [];
  return `?pages=${picked.join(',')}&page=${cur}`;
}

function stepScope(endpoint, verb){
  scopeEp=endpoint;
  $('scpTitle').textContent=verb+'?';
  $('scpAll').textContent = (selPages.size>=proj.pages.length)
    ? `Every page (${proj.pages.length})`
    : `Selected pages (${selPages.size})`;
  $('scpOne').textContent = 'This page only';
  scopeQuote = null;
  priceScope();
  if(typeof quoteCoins === 'function')
    quoteCoins(scopeQuery()).then(q => { scopeQuote = q; priceScope(); });
  // Translating through your own AI: the exact request is downloadable here,
  // and its reply can be pasted back.
  const own = endpoint==='translate_all';
  $('scpTpl').style.display = own ? '' : 'none';
  $('scpTplIn').style.display = own ? '' : 'none';
  if($('scpTxtOut')) $('scpTxtOut').style.display = own ? '' : 'none';
  // The proofread report is offered on the proofread step, and offered
  // BEFORE the run as well as after: re-reading the last pass is usually why
  // you opened this dialog in the first place.
  if($('scpPfOut'))
    $('scpPfOut').style.display = endpoint==='proofread_all' ? '' : 'none';
  $('scopedlg').classList.add('on');
}

function openTplReply(){
  $('scopedlg').classList.remove('on');
  $('tpldlg').classList.add('on');
  setTimeout(()=>$('tplPaste').focus(),40);
}
async function tplFromFile(f){
  if(!f) return;
  $('tplPaste').value = await f.text();
}
async function applyTranslateResponse(){
  const t=$('tplPaste').value.trim();
  if(!t){toast('Paste the reply (or upload the file) first.');return;}
  const j=await api('/api/translate_response','POST',{data:t, fallback_page:cur});
  if(j.error){toast(j.error);return;}
  $('tpldlg').classList.remove('on'); $('tplPaste').value='';
  record('translate',
    `AI reply applied: ${j.regions} region${j.regions===1?'':'s'} on `+
    `${j.pages} page${j.pages===1?'':'s'}`, null);
  toast(`Replaced ${j.regions} translation${j.regions===1?'':'s'} on `+
    `${j.pages} page${j.pages===1?'':'s'}`+
    (j.missing&&j.missing.length?` — ${j.missing.length} had no matching bubble`:'')+
    (j.typeset_started?' — laying the text out now…':'.'), 4000);
  await loadProject();
  poll();                      // follows the automatic re-typeset
  showPage(cur);
}

async function downloadTranslateRequest(){
  const j=await api('/api/translate_request');
  if(j.error){toast(j.error);return;}
  const blob=new Blob([JSON.stringify(j,null,2)],{type:'application/json'});
  const u=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=u; a.download='translate-request.json'; a.click();
  URL.revokeObjectURL(u);
  toast(j.pages&&j.pages.length
    ? `Request for ${j.pages.length} page${j.pages.length>1?'s':''} downloaded.`
    : 'Downloaded — but no page has read text yet, so it only holds the prompt.');
}
/* The proofread, as something you can read on a phone or hand to somebody
   else: what still wants a human first, then the whole script with the
   Japanese beside it. Markdown rather than JSON because the point is reading
   it, not feeding it back in. */
async function downloadProofreadReport(){
  const j=await api('/api/proofread_report');
  if(j.error){toast(j.error);return;}
  const blob=new Blob([j.text],{type:'text/markdown'});
  const u=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=u; a.download=(j.name||'chapter')+'-proofread.md'; a.click();
  URL.revokeObjectURL(u);
  toast(j.flags
    ? `Report downloaded — ${j.flags} thing${j.flags===1?'':'s'} still want a look.`
    : 'Report downloaded — nothing was left flagged.');
}

async function runScoped(thisPageOnly){
  $('scopedlg').classList.remove('on');
  if(thisPageOnly){ await api('/api/'+scopeEp,'POST',{pages:[cur]}); poll(); return; }
  const sel = scopedPages();               // only the checked pages
  if(!sel.length){ toast('No pages are checked.'); return; }
  await api('/api/'+scopeEp,'POST',{pages:sel});
  poll();
}

function openDetect(){ syncDetectKinds(); $('modal').classList.add('on'); }
function closeModal(){ $('modal').classList.remove('on'); }

/* comic-text-detector — and the AI in "find" mode — read the whole page in one
   pass and say what kind every block is, rather than being sent looking for one
   kind at a time. The boxes below used to be greyed out for those two, on the
   grounds that they had nothing to steer; but the kind of each block IS known
   by the time the page comes back, so the choice applies perfectly well at the
   other end — see only_kinds() in project.py. They stay live for every finder.
   All the note does now is say which way round it is working. */
function syncDetectKinds(){
  const det = $('detector') ? $('detector').value : '';
  ['kBubble','kFree','kSfx'].forEach(id=>{
    const cb=$(id); if(!cb) return;
    cb.disabled = false;
    const lab=cb.closest('label'); if(lab) lab.classList.remove('disabled');
  });
  // One finder reads the whole page in one go and hands back every block on it
  // whatever is ticked; the ticks are applied at the other end. (An AI mode used
  // to be the other such finder. It is gone.)
  const whole = det === 'comictext';
  const n=$('ctdNote'); if(n) n.style.display = whole ? '' : 'none';
}

function chosenKinds(){
  const k=[];
  if($('kBubble').checked) k.push('bubble');
  if($('kFree').checked)   k.push('freefloat');
  if($('kSfx').checked)    k.push('sfx');
  return k;
}

async function runDetect(thisPageOnly){
  const kinds=chosenKinds();
  if(!kinds.length){toast('Pick at least one kind of text.');return;}
  closeModal();
  if(thisPageOnly){
    // Route through the job so single-page detection shows in the progress bar
    // too, instead of running silently.
    await api('/api/detect_all','POST',{kinds, pages:[cur]});
    poll();
    return;
  }
  const sel=scopedPages();
  if(!sel.length){ toast('No pages are checked.'); return; }
  await api('/api/detect_all','POST',{kinds, pages:sel});
  poll();
}

async function detectAll(){await api('/api/detect_all','POST',{force:true});poll();}
async function runAll(ep){const j=await api('/api/'+ep,'POST',{});
  toast('started on '+(j.started||0)+' pages');poll();}
const STEPS=[
  {n:1, label:'Find text',    act:()=>openDetect(),               job:'Detecting'},
  {n:2, label:'Read text',    act:()=>stepScope('ocr_all','Read the Japanese'),
                                                                  job:'Reading text'},
  {n:3, label:'Translate',    act:()=>stepScope('translate_all','Translate'),
                                                                  job:'Translating'},
  {n:4, label:'Proofread',    act:()=>stepScope('proofread_all','Proofread'),
                                                                  job:'Proofreading'},
  {n:5, label:'Clean',        act:()=>stepScope('clean_all','Clean the pages'),
                                                                  job:'Cleaning'},
  {n:6, label:'Typeset',      act:()=>stepScope('typeset_all','Lay the text out'),
                                                                  job:'Laying out text'},
  {n:7, label:'Export',       act:()=>exportDialog(),             job:'Exporting'},
];

async function typesetAll(){
  await api('/api/typeset_all','POST',{});
  setView('typeset');              // reviewing typesetting means seeing it
  toast('Laying out the typesetting — check it before exporting.');
  poll();
}

/* Has THIS page finished step `i`?

   One page, one step, one answer — the step bar counts these up and the page
   list draws one for each. It used to be written out only in the aggregate,
   so the list could show a page as a single green dot and say nothing about
   which of the six things had actually happened to it. lee: *"istaed of 1
   green bubble it shoud be 4 for the origibla page and 2 for the edit page,
   one for each step"*.

   A checked page with no text has nothing to do, so it PASSES every text
   step — otherwise the counts stall (e.g. 26/30) forever on empty pages. */
function pageDoneStep(p, i){
  if(!p) return false;
  const checked = p.status!=='pending';
  const noText = checked && (p.regions||0)===0;
  const passed = key => noText || (p.regions>0 && (p[key]||0)>=p.regions);
  switch(i){
    case 0: return checked;
    case 1: return passed('ocr');
    case 2: return passed('translated');
    case 3: return passed('proofread');
    // clean: a page with no text has nothing to erase, and a page you cleaned
    // yourself is excluded from cleaning — both are done the moment they
    // exist, or the step never reaches the end and Typeset stays locked.
    case 4: return noText || !!p.cleaned || !!p.custom_clean;
    case 5: return passed('typeset');
    case 6: return !!p.exported;      // export writes every page for real
  }
  return false;
}

function stepProgress(){
  const P=proj?proj.pages:[];
  // Progress is counted over the SELECTED pages — the ones a "do all" run
  // actually touches — so the denominator matches the ticked count, not the
  // whole chapter. Nothing selected falls back to every page.
  const selP = (typeof selPages!=='undefined')
    ? P.filter(p=>selPages.has(p.name)) : P;
  const pool = selP.length ? selP : P;
  const total=pool.length;
  return STEPS.map((_s,i)=>({
    done: pool.filter(p=>pageDoneStep(p,i)).length, total}));
}

/* The seven steps are three pieces of work, not one line of seven.

   lee: *"this shoud be split into 3 section text for the fist 4, image or
   panel fro teh next 2 and exort"*.

   The first four are about the WORDS and each one needs the one before it —
   you cannot read text that has not been found, or translate what has not been
   read. The next two are about the PICTURE: cleaning can start the moment the
   boxes exist, in parallel with the whole text side, and only the typesetting
   needs both halves finished. Export needs nothing: it will write whatever
   state the chapter is in, which is the point of being able to export cleaned
   art or a box sheet. */
/* The four steps that produce the WORDS, the two that produce the picture, and
   the one that writes it out. The first group was called Text, which named the
   thing on the page rather than the work — lee: *"chnage the text on
   screenshot 4 to say translation"*. */
const STEP_GROUPS = [
  {label: 'Translation', steps: [0, 1, 2, 3]},
  {label: 'Image',       steps: [4, 5]},
  {label: 'Export',      steps: [6]},
];

/* Nothing waits its turn any more.

   The seven went unlocked for a round — lee: *"allow the user to clcik all
   the button like clean translate without any locks"* — then locked again on
   his next word, *"accualty bring ba k the locks for the 1-6 tabs but kepp the
   lock offf the edit tab"*, and now unlocked for good: *"remove the loacks on
   all the tabs"*.

   The dependencies they encoded are real — you cannot read text that has not
   been found, and typesetting onto Japanese that is still there sits on top of
   it — but they are lee's to know. The step bar still SAYS where the chapter
   is, in the count on every button and the fill under it; what it no longer
   does is decide what he is allowed to press. Running a step out of turn does
   what it always did: nothing, over nothing, and reports it.

   The three groups stay. They were never the lock — they are what the seven
   are FOR: the words, the picture, and writing it out. */
function runStep(i){
  if(manualOff(i)) return;       // translating it yourself: nothing to call
  STEPS[i].act();
}

/* ---------------- translating it yourself ---------------- */

/* Read text, Translate and Proofread are the three that call a model. With
   "I'll translate it myself" on, none of them is going to, so they go grey.
   lee: *"the manual tranlat button should grey out the read text translate
   and profread"*. */
const MANUAL_GREY=[1,2,3];
function manualMode(){
  return !!(typeof proj!=='undefined' && proj && proj.settings
            && proj.settings.manual_translate);
}
function manualOff(i){ return manualMode() && MANUAL_GREY.indexOf(i)>=0; }

/* Show the template row only when it is the way you are working, and redraw
   the bar so the three change state the moment the switch does. */
function syncManualMode(){
  const on=($('manual_translate') && $('manual_translate').checked)
           || manualMode();
  const r=$('manrow'); if(r) r.style.display = on ? '' : 'none';
  if(typeof renderSteps==='function' && $('steps'))
    renderSteps((proj&&proj.job&&proj.job.running)?proj.job.label:null);
}

/* The file to type into. The browser is asked for it as a download rather
   than built here from JSON, so the labels, the Japanese and the comments
   are exactly what the importer will read back. */
function downloadManualTemplate(fmt){
  const u='/api/translation_template?fmt='+(fmt==='json'?'json':'txt');
  const a=document.createElement('a');
  a.href=u; a.download=''; a.click();
  toast('Template downloaded — type under each label and upload it back.');
}

async function uploadManualTranslation(input){
  const f=input.files && input.files[0];
  input.value='';
  if(!f) return;
  const j=await api('/api/translation_import','POST',{text:await f.text()});
  if(j.error){toast(j.error);return;}
  record('translate',
    `Translation file applied: ${j.regions} box${j.regions===1?'':'es'} on `+
    `${j.pages} page${j.pages===1?'':'s'}`, null);
  toast(`Replaced ${j.regions} translation${j.regions===1?'':'s'} on `+
    `${j.pages} page${j.pages===1?'':'s'}`+
    (j.missing&&j.missing.length?` — ${j.missing.length} label${j.missing.length===1?'':'s'} matched nothing`:'')+
    (j.typeset_started?' — laying the text out now…':'.'), 4000);
  await loadProject();
  poll();
  showPage(cur);
}

function renderSteps(runningLabel){
  const prog=stepProgress();
  let firstUnfinished=prog.findIndex(x=>x.done<x.total);
  const one = i => {
    const s = STEPS[i];
    const {done,total}=prog[i];
    const pct=total?Math.round(100*done/total):0;
    const busy = runningLabel===s.job;
    let cls = busy?'busy' : done>=total&&total?'done' : done>0?'part'
              : i===firstUnfinished?'next':'';
    if(manualOff(i)) cls += ' off';
    return `<button class="step ${cls}" onclick="runStep(${i})">
      <span class="sn">${cls.startsWith('done')?'&#10003;':s.n}</span>
      <span class="sl">${s.label}</span>
      <span class="sc">${done}/${total}</span>
      <span class="sfill" style="width:${pct}%"></span></button>`;
  };
  $('steps').innerHTML = STEP_GROUPS.map(g =>
    `<span class="stepgrp"><span class="sgl">${g.label}</span>` +
    g.steps.map(one).join('') + `</span>`).join('');
  if(typeof updateEditLock==='function') updateEditLock();
}

async function cancelJob(){
  const b=$('cancelJob');
  if(b){ b.disabled=true; b.textContent='Stopping…'; }
  try{ await api('/api/job/cancel','POST',{}); }catch(e){}
}
function _resetCancelBtn(){
  const b=$('cancelJob');
  if(b){ b.style.display='none'; b.disabled=false; b.textContent='Cancel'; }
}

/* The server builds every page in the background so that moving to one for
   the first time is instant. That work is silent, which made the first minute
   after opening a chapter look like nothing was happening — say so instead,
   in the same place the steps report themselves. Only runs while nothing else
   is going on, and stops the moment the pages are all made. */
async function pollWarm(){
  clearTimeout(pollWarm._t);
  let w;
  try{
    const r=await fetch(apiUrl('/api/warm'));
    w=await r.json();
  }catch(e){ return; }
  const job=$('job');
  if(!job || job.className==='busy' || job.className==='err'
     || job.className==='warn') return;   // don't paint over the warning
  if(!w || !w.running || !w.total){
    if(pollWarm._said){ pollWarm._said=false; $('jobtxt').textContent='Ready';
                        $('fill').style.width='100%'; }
    return;
  }
  pollWarm._said=true;
  const pct=Math.round(100*w.done/w.total);
  $('jobtxt').textContent=`Preparing pages… ${w.done} of ${w.total}`;
  $('fill').style.width=pct+'%';
  pollWarm._t=setTimeout(pollWarm,1000);
}

/* What the strip says, split out of `poll` so it can be tested without a
   server that fails on cue. Everything about the bar's appearance is in here
   and nothing about timing is. */
function paintJob(j, pct){
  const job=$('job');
  if(!job) return;
  // Three states, not two. `error` stopped the run; `warn` means it finished
  // and something inside it quietly did the wrong thing — the case that had lee
  // staring at smeared pages with the bar saying "Ready".
  job.className = j.error?'err' : (j.running?'busy':(j.warn?'warn':'idle'));
  // The label is the warning's own first clause, not a fixed sentence: it used
  // to say "AI cleaning did not run" for every remark, including the ones that
  // are not faults at all.
  const said = j.error ? j.error
    : (j.running ? `${j.label}… ${j.done} of ${j.total} pages (${pct}%)`
                 : (j.warn ? j.warn.split('—')[0].trim().replace(/[.,]$/,'')
                           : 'Ready'));
  $('jobtxt').textContent = said;
  // The WHOLE of it, both on hover and on the click below. The strip is a
  // fixed width and cuts with an ellipsis, so a provider's four-hundred
  // character answer is readable without being allowed to resize the bar and
  // push the page tools off it. lee: *"the error moved everything out of the
  // way"*.
  const full = j.error || j.warn || '';
  job.title = full;
  job._full = full;
  $('fill').style.width=(j.running?pct:(j.error?0:100))+'%';
}

/* Clicking the strip says the whole thing, in a toast that wraps. Nothing
   happens when there is nothing more to see than what is already shown. */
function showJobMessage(){
  const job=$('job'), full=job && job._full;
  if(full && typeof toast === 'function') toast(full);
}

let lastJob=null;

async function poll(){
  const j=await api('/api/job');
  lastJob=j;
  // The queue rides down with the job, so the button is current without a
  // request of its own.
  if(j.queue) paintQueue(j.queue);
  const pct=j.total?Math.round(100*j.done/j.total):0;
  paintJob(j, pct);
  const cb=$('cancelJob'); if(cb) cb.style.display = j.running ? '' : 'none';
  renderSteps(j.running?j.label:null);
  // Which action is running right now, by its queue id — the label alone
  // cannot tell two Cleans apart.
  const nowRunning = j.running
    ? ((j.queue && j.queue.running_qid) || j.label) : null;
  const changed = poll._at !== undefined && poll._at !== nowRunning;
  poll._at = nowRunning;
  // The count moves WHILE a run spends, not only when it ends.
  if(typeof coinsSpending === 'function' && j.running) coinsSpending(j.spent);
  if(j.running || (j.queue && j.queue.count)){
    // The page on screen used to be refreshed only when the WHOLE line was
    // empty, so with Clean running and Translate waiting behind it the cleaned
    // art did not appear until the translation had finished too.
    // lee: *"when the translat e finishes the cleanig aslso showed up"*.
    // One action ending is a moment worth looking at, so the page is brought
    // up to date then — once per action, not once per poll.
    if(changed){
      await refreshPages();
      if(proj.pages[cur]) showPage(cur);
    }
    setTimeout(poll,700); return; }
  _resetCancelBtn();
  poll._at = undefined;
  // A run has just ended, so the purse has changed and so has what the rest
  // of the chapter would cost — pages that are now read have text boxes the
  // translator will be charged for.
  if(typeof refreshCoins==='function') refreshCoins();
  pollWarm();
  await refreshPages();
  if(proj.pages[cur]) showPage(cur);
  if(j.cancelled){
    toast(`Stopped — ${j.done} page${j.done===1?'':'s'} done before cancelling.`);
  } else if(j.info && !j.warn){
    // Who cleaned what, in the words of the person asking. The only way to
    // know the hosted model is doing the hard regions used to be to stare at
    // the page and guess.
    toast(j.info, 9000);
  } else if(j.warn){
    // Long, because it is the whole instruction: what did not happen, how many
    // spots it cost, and which setting to go and change.
    toast(j.warn, 14000);
  } else if(j.label&&j.label.startsWith('Exporting')&&!j.error){
    setTab('results');
    toast(`${j.done} page${j.done===1?'':'s'} written to ${lastExportDir||''}`);
  }
}


/* --- the queue -------------------------------------------------------------
   lee: *"if somethin gis happening fro exmaple cleeening and i click typeseete
   it shod be added to teh queue ... allow me to move the iteme sin teh queue
   and cancek them"*.

   The count comes down with the job poll, so the button is up to date without
   a request of its own. The panel is only redrawn while it is open. */
let queueState = {waiting:[], count:0, running_qid:0};

function paintQueue(q){
  if(q) queueState = q;
  const n = (queueState.waiting||[]).length;
  const btn = $('queueBtn'), lbl = $('queueN');
  if(!btn || !lbl) return;
  lbl.textContent = n;
  btn.classList.toggle('has', n > 0);
  btn.title = n ? `${n} action${n===1?'':'s'} waiting their turn`
                : 'Nothing waiting';
  const pop = $('queuePop');
  if(pop && pop.classList.contains('open')) drawQueuePop();
}

function drawQueuePop(){
  const pop = $('queuePop'); if(!pop) return;
  const w = queueState.waiting || [];
  const running = (typeof lastJob!=='undefined' && lastJob && lastJob.running)
    ? lastJob : null;
  const rows = [];
  if(running){
    rows.push(`<div class="qrow now"><span class="qlbl">${esc(running.label||'Working')}</span>
      <span class="qpg">now</span>
      <button onclick="cancelJob()" title="Stop this">Stop</button></div>`);
  }
  w.forEach((it,k)=>{
    rows.push(`<div class="qrow">
      <span class="qlbl">${esc(it.label)}</span>
      <span class="qpg">${it.pages} pg</span>
      <button onclick="queueMove(${it.qid},-1)" ${k===0?'disabled':''}
              title="Do this sooner">&#9650;</button>
      <button onclick="queueMove(${it.qid},1)" ${k===w.length-1?'disabled':''}
              title="Do this later">&#9660;</button>
      <button class="qx" onclick="queueDrop(${it.qid})"
              title="Take it out of the queue">&times;</button></div>`);
  });
  pop.innerHTML = `<h4>Queue</h4>` + (rows.join('') ||
    `<p class="help" style="margin:2px 6px 4px">Nothing waiting. Start
     something while another action is running and it lines up here.</p>`);
}

function toggleQueue(ev){
  if(ev) ev.stopPropagation();
  const pop = $('queuePop'); if(!pop) return;
  const opening = !pop.classList.contains('open');
  pop.classList.toggle('open', opening);
  if(opening){ refreshQueue(); drawQueuePop(); }
}

document.addEventListener('click', e=>{
  const pop = $('queuePop');
  if(pop && pop.classList.contains('open') && !e.target.closest('#queuewrap'))
    pop.classList.remove('open');
});

async function refreshQueue(){
  try{ paintQueue(await api('/api/queue')); }catch(e){}
}

async function queueMove(qid, dir){
  paintQueue(await api('/api/queue','POST',{move:{qid, dir}}));
  drawQueuePop();
}

async function queueDrop(qid){
  paintQueue(await api('/api/queue','POST',{cancel:qid}));
  drawQueuePop();
}
