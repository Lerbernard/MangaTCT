/* pipeline.js - Detect / translate / typeset steps, scoped runs, template round-trip, job polling.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* ---------------- jobs ---------------- */
let scopeEp=null;
/* Which PAID step each scoped endpoint is, for pricing it. "" is a step that
   runs on this machine and costs nothing - and it must stay "" rather than be
   left out, because a step nobody priced and a step that is free look the
   same on the button and are not the same thing. */
const SCOPE_STEP = {ocr_all:'ocr', translate_all:'translate',
                    proofread_all:'proofread', clean_all:'clean',
                    typeset_all:''};

/* The price of each choice, on the choice. lee: *"on the pop up it shoud tell
   teh price for all the pages and and this page onli on the side"* - so it
   goes beside the label rather than in it, and the two numbers are the two
   things you are actually choosing between.

   Both come from one request, priced server-side for exactly the pages each
   button would run: `prices` for the ones the button says, `one` for the page
   on screen. A free step shows nothing at all - a price of zero on a button
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
  // A read that happens on this computer is not bought from anybody, so the
  // button carries no number - the same silence every other free step gets.
  // lee: *"instaead of sayong free it shoud show nothiing"*. `run_price`
  // agrees on the server; this is that fact, said early enough to choose on.
  if(step === 'ocr' && typeof proj !== 'undefined' && proj
     && (proj.settings.ocr_reader || 'ai') === 'offline'){
    put(all, null); put(one, null); return;
  }
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
    (j.missing&&j.missing.length?` - ${j.missing.length} had no matching bubble`:'')+
    (j.typeset_started?' - laying the text out now…':'.'), 4000);
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
    : 'Downloaded - but no page has read text yet, so it only holds the prompt.');
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
    ? `Report downloaded - ${j.flags} thing${j.flags===1?'':'s'} still want a look.`
    : 'Report downloaded - nothing was left flagged.');
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

/* comic-text-detector - and the AI in "find" mode - read the whole page in one
   pass and say what kind every block is, rather than being sent looking for one
   kind at a time. The boxes below used to be greyed out for those two, on the
   grounds that they had nothing to steer; but the kind of each block IS known
   by the time the page comes back, so the choice applies perfectly well at the
   other end - see only_kinds() in project.py. They stay live for every finder.
   All the note does now is say which way round it is working. */
/* SOUND EFFECTS, on the webtoons: the tick is back, and it works.

   It was greyed out with a "Coming soon" pill for four turns of one argument,
   and all four came off ONE number: on chapter 1, 82 boxes came back as sound
   effects and of the 36 checked by hand **eighteen held no writing** - sword
   blades, a face, two buildings, a gold ornament, a leg, a bed. lee's
   *"shound affct shoud be sissable for the detector not the user"* followed
   from that and from nothing else.

   Everything built since - the character census, the art veto, the stray-mark
   sweep - was aimed at exactly those. Re-measured on all 46 pages of the new
   chapter, every box cropped and looked at: **49 sound-effect boxes, 47 hold
   real writing**. Two do not, and they are an architectural ornament and a
   gold braid: the same class, 2 instead of 18.

   So the row is a plain live tick on every format now, and it starts
   UNTICKED, exactly as it does on manga. Nothing appears on anybody's pages
   until they ask for it, and drawing one by hand (press 3) still works and
   always did. `only_kinds` in project.py is what enforces the tick, and
   always was. */
function syncDetectKinds(){
  // One detector, and no menu to read it off any more.
  const det = (typeof proj!=='undefined' && proj && proj.settings
               && proj.settings.detector) || 'comictext';
  ['kBubble','kFree','kSfx'].forEach(id=>{
    const cb=$(id); if(!cb) return;
    cb.disabled = false;
    const lab=cb.closest('label'); if(lab) lab.classList.remove('disabled');
  });
  // The three ticks are alike, on every format. Sound effects used to be
  // forced off and greyed out here on manhwa and manhua; the note above has
  // the number that said so and the number that replaced it.
  //
  // There is no longer a paragraph here explaining that one finder reads the
  // whole page and the ticks are applied at the other end. It was true and it
  // was three lines of grey nobody needed before pressing a button.
  // lee: *"remove the undeserasy tet"*.
  syncSfxOpts();
  syncTallWarning();
}

/* The sub-options under Sound effects appear with it. lee: *"shoud only
   show up when sfx is clicked"*. Their VALUES are left alone, so turning
   sound effects off and on again finds the sub-tick as it was. */
function syncSfxOpts(){
  const box=$('kSfxOpts'), on=$('kSfx') && $('kSfx').checked;
  if(box) box.style.display = on ? '' : 'none';
  sayHowBig();
}

/* ...AND THE SENTENCE HAS TO SAY THE FORMAT'S OWN NUMBER.

   lee: *"can you swith teh manga version of this to be something more
   appropriate to manga"*.

   "About two fifths of the page" was measured on a webtoon, where the page IS
   the panel. A manga page holds several panels across, so the same effect is
   a much smaller share of it, and the bar was catching one sound effect in
   sixty-two. `project.BIG_SFX_BY_MEDIUM` is where the numbers live and the
   server sends the one that applies, so there is only ever one of each -- the
   same arrangement as `TALL_ASPECT` below, and for the same reason: a
   sentence with a number copied into it goes wrong quietly the first time the
   number moves. */
function sayHowBig(){
  const el=$('kSfxBigWhy'); if(!el) return;
  const share=(typeof proj!=='undefined' && proj && proj.big_sfx_share)
              || 0.435;
  el.textContent = 'Wider than about ' + Math.round(share * 100)
    + '% of the page - the cleaner makes a mess of those.';
}

/* PAGES TOO LONG TO READ PROPERLY.

   lee: *"somthing i notice is that when the pages are smaller teh issies are
   gone ... if the page exide a cerain lenght can you give a warning"*.

   He is right and the cause is arithmetic. comic-text-detector fits the page
   into a 1024 square by its LONG side, so a strip is seen at 1024/height and
   its writing arrives that many times smaller. `TALL_ASPECT` in
   detect/comictext.py is where the measurement lives; the server sends the
   number so there is only one of it.

   The warning says what was measured and not more than that. It is NOT that
   the writing goes missing - padding eleven pages out to eight times their
   width barely moved recall. It is that the box list and the LABELS go: past
   six, a page loses about a quarter of its boxes and a third of what survives
   comes back a different kind. */
/* ONE PAGE, asked on its own - because the warning is not the only place this
   has to be said.

   lee: *"can you amke it so that teh pages that are tooo long have a red
   heighlight on te side bar"*. The sheet named nine files and the rail beside
   it looked like every other page, so finding them meant reading nine names
   off one list and hunting each down another - and past six the sheet stops
   naming them at all and says "+3 more".

   The rail marks them itself now (`.pg.tall`), and it marks them by asking
   THIS rather than by a second copy of the arithmetic, which is how a mark
   and a message come to disagree about which pages they mean. */
function isTallPage(p){
  const lim = (typeof proj !== 'undefined' && proj && proj.tall_aspect) || 0;
  return !!(lim && p && p.width && p.height
            && Math.max(p.width, p.height) / Math.min(p.width, p.height) > lim);
}

function tallPages(){
  if(typeof proj === 'undefined' || !proj || !proj.pages) return [];
  return proj.pages.filter(isTallPage);
}

/* ...and why, for the rail's tooltip. A red bar with nothing behind it is a
   thing to worry about rather than a thing to act on, and the sheet that
   explains it is on another view. */
function tallWhy(p){
  if(!isTallPage(p)) return '';
  return 'more than ' + Math.round(proj.tall_aspect)
       + ' times taller than wide - Find text gets the box types wrong on '
       + 'these. Cut / join splits a strip up.';
}

function syncTallWarning(){
  const el=$('tallNote'); if(!el) return;
  const tall=tallPages();
  if(!tall.length){ el.style.display='none'; return; }
  const lim = Math.round((proj && proj.tall_aspect) || 0);
  const one = tall.length===1;
  el.style.display='';
  // Short, and the page names first-class rather than a trailing aside: this
  // is the only thing in the sheet that changes what you should DO before
  // pressing the button. lee: *"ake teh pages that too long more visible"*.
  el.innerHTML = `<b>${tall.length} page${one?' is':'s are'} very long.</b> `
    + `<span class="warnpages">${tall.slice(0,6).map(p=>esc(p.name)).join('  ')}`
    + `${tall.length>6?`  +${tall.length-6} more`:''}</span>`
    + `<span class="warnwhy">More than ${lim} times taller than wide. Find text `
    + `reads a whole page at once, so on ${one?'it':'them'} it gets the box `
    + `types wrong and misses boxes. <b>Cut / join</b>, on the Translation `
    + `view, splits a strip up.</span>`;
}

function chosenKinds(){
  const k=[];
  if($('kBubble').checked) k.push('bubble');
  if($('kFree').checked)   k.push('freefloat');
  // ...and this one is read off the tick and nothing else now. It used to
  // carry `&& sfxIsDetectable()` because the row was force-unticked on the
  // webtoons and a box ticked on a manga project before the format changed
  // would still have been ticked. There is no such force any more.
  if($('kSfx').checked)    k.push('sfx');
  return k;
}

async function runDetect(thisPageOnly){
  const kinds=chosenKinds();
  if(!kinds.length){toast('Pick at least one kind of text.');return;}
  closeModal();
  // The sub-tick under Sound effects. Sent every time rather than only when
  // it is off, because the server reads ABSENT as on - so a message that
  // forgets it and a message that means "on" have to look the same.
  const noBig = $('kSfxBig') ? $('kSfxBig').checked : true;
  if(thisPageOnly){
    // Route through the job so single-page detection shows in the progress bar
    // too, instead of running silently.
    await api('/api/detect_all','POST',{kinds, pages:[cur], no_big_sfx:noBig});
    poll();
    return;
  }
  const sel=scopedPages();
  if(!sel.length){ toast('No pages are checked.'); return; }
  await api('/api/detect_all','POST',{kinds, pages:sel, no_big_sfx:noBig});
  poll();
}

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

/* Has THIS page finished step `i`?

   One page, one step, one answer - the step bar counts these up and the page
   list draws one for each. It used to be written out only in the aggregate,
   so the list could show a page as a single green dot and say nothing about
   which of the six things had actually happened to it. lee: *"istaed of 1
   green bubble it shoud be 4 for the origibla page and 2 for the edit page,
   one for each step"*.

   A checked page with no text has nothing to do, so it PASSES every text
   step - otherwise the counts stall (e.g. 26/30) forever on empty pages. */
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
    // yourself is excluded from cleaning - both are done the moment they
    // exist, or the step never reaches the end and Typeset stays locked.
    case 4: return noText || !!p.cleaned || !!p.custom_clean;
    case 5: return passed('typeset');
    case 6: return !!p.exported;      // export writes every page for real
  }
  return false;
}

function stepProgress(){
  const P=proj?proj.pages:[];
  // Progress is counted over the SELECTED pages - the ones a "do all" run
  // actually touches - so the denominator matches the ticked count, not the
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

   The first four are about the WORDS and each one needs the one before it -
   you cannot read text that has not been found, or translate what has not been
   read. The next two are about the PICTURE: cleaning can start the moment the
   boxes exist, in parallel with the whole text side, and only the typesetting
   needs both halves finished. Export needs nothing: it will write whatever
   state the chapter is in, which is the point of being able to export cleaned
   art or a box sheet. */
/* The four steps that produce the WORDS, the two that produce the picture, and
   the one that writes it out. The first group was called Text, which named the
   thing on the page rather than the work - lee: *"chnage the text on
   screenshot 4 to say translation"*. */
const STEP_GROUPS = [
  {label: 'Translation', steps: [0, 1, 2, 3]},
  {label: 'Image',       steps: [4, 5]},
  {label: 'Export',      steps: [6]},
];

/* Nothing waits its turn any more.

   The seven went unlocked for a round - lee: *"allow the user to clcik all
   the button like clean translate without any locks"* - then locked again on
   his next word, *"accualty bring ba k the locks for the 1-6 tabs but kepp the
   lock offf the edit tab"*, and now unlocked for good: *"remove the loacks on
   all the tabs"*.

   The dependencies they encoded are real - you cannot read text that has not
   been found, and typesetting onto Japanese that is still there sits on top of
   it - but they are lee's to know. The step bar still SAYS where the chapter
   is, in the count on every button and the fill under it; what it no longer
   does is decide what he is allowed to press. Running a step out of turn does
   what it always did: nothing, over nothing, and reports it.

   The three groups stay. They were never the lock - they are what the seven
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
  const on=(($('manual_translate') && $('manual_translate').checked)
           || manualMode())
           // ...and only on the translation tab - the Image tab hides the
           // whole manual-translation block (see syncViewChrome)
           && (typeof view==='undefined' || view==='original');
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
  toast('Template downloaded - type under each label and upload it back.');
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
    (j.missing&&j.missing.length?` - ${j.missing.length} label${j.missing.length===1?'':'s'} matched nothing`:'')+
    (j.typeset_started?' - laying the text out now…':'.'), 4000);
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

/* "Stopping…" belongs to ONE action, not to the rest of the line.
   lee: *"when i clik cancel and it sto the ui show stopping even thiught te
   next step queue ia happening"*. The button was put back only where the
   whole queue had drained, so cancelling a Clean with a Translate waiting
   behind it left it reading "Stopping…" and disabled for the whole of the
   translation -- and there was no way to stop THAT one either.
   So the cancel remembers which action it was aimed at, and `poll` puts the
   button back the moment something else is running. */
async function cancelJob(){
  const b=$('cancelJob');
  if(b){ b.disabled=true; b.textContent='Stopping…'; }
  cancelJob._for = (lastJob && ((lastJob.queue && lastJob.queue.running_qid)
                                || lastJob.label)) || null;
  try{ await api('/api/job/cancel','POST',{}); }catch(e){}
}
function _armCancelBtn(){
  const b=$('cancelJob');
  if(b){ b.disabled=false; b.textContent='Cancel'; }
  cancelJob._for = undefined;
}
function _resetCancelBtn(){
  const b=$('cancelJob');
  if(b){ b.style.display='none'; }
  _armCancelBtn();
}

/* The server builds every page in the background so that moving to one for
   the first time is instant. That work is silent, which made the first minute
   after opening a chapter look like nothing was happening - say so instead,
   in the same place the steps report themselves. Only runs while nothing else
   is going on, and stops the moment the pages are all made. */
/* ONE PLACE THAT DECIDES WHEN TO ASK AGAIN.

   This used to book the next look from a single line at the bottom and return
   early from three places above it - a failed fetch, the guard against
   painting over a warning, and the finish. Two of those three are states the
   bar RECOVERS from, and returning without booking another look ended the
   loop for the rest of the session.

   What lee saw: an amber "Preparing pages 23 of 23 100%" that never went
   away. The warm-up had finished; the poll that would have noticed never
   happened, because a moment earlier a step had gone busy and the guard
   returned. The bar was not stuck - it was dead, still showing its last word.

   So asking again is the default rather than a step in the happy path, and
   the only exit that stops for good is the editor going away. */
async function pollWarm(){
  clearTimeout(pollWarm._t);
  const again=ms=>{ pollWarm._t=setTimeout(pollWarm, ms); };
  let w;
  try{
    const r=await fetch(apiUrl('/api/warm'));
    w=await r.json();
  }catch(e){ again(2000); return; }      // a blip is not the end of the loop
  const job=$('job');
  if(!job) return;                       // the editor is gone; so is the bar
  if(job.className==='busy' || job.className==='err'
     || job.className==='warn'){ again(1000); return; }  // don't paint over it
  if(!w || !w.running || !w.total){
    if(pollWarm._said){ pollWarm._said=false; $('jobtxt').textContent='Ready';
                        if($('jobpct')) $('jobpct').textContent='';
                        job.classList.remove('warm');
                        $('fill').style.width='100%'; }
    // Idle, and still looking: a warm-up can START later - a project loaded,
    // pages reordered, a chapter re-cleaned - and a loop that stopped at the
    // first quiet moment would never say so again.
    again(4000);
    return;
  }
  pollWarm._said=true;
  /* Loading the models is not a job - `paintJob` never sees it, and the strip
     stays `idle`, where the fill is dimmed because idle means finished. It is
     WORK though, and it must look like work, so it gets the busy paint
     without the busy class the guard above reads. */
  job.classList.add('warm');
  const pct=Math.round(100*w.done/w.total);
  $('jobtxt').textContent=`Preparing pages ${w.done} of ${w.total}`;
  if($('jobpct')) $('jobpct').textContent=pct+'%';
  $('fill').style.width=pct+'%';
  again(1000);
}

/* THE STEP'S OWN NAME, out of whatever the run is currently saying.

   A step writes its progress into the same field the step is named by, so
   `job.label` arrives as "Reading text - AI reader, piece 17 of 23...". Two
   things went wrong with that. The bar showed the whole sentence, cut with an
   ellipsis, and lee wanted the name: *"remove the explation for the loading
   bar, it shoud just say reading tetx or finsinhg text or tralstion etc"*.
   And `renderSteps` lights a step by comparing that field to the step's job
   name, so while a run was saying anything at all, the step it was running
   went dark.

   Everything up to the dash is the name. What follows it is the run talking,
   and it has the whole of the bar's width to say it in only when it is a
   warning or an error, which is what the title and the toast are for. */
function stepName(label){
  return String(label || '').split('\u2014')[0].split(' - ')[0].trim();
}

/* What the strip says, split out of `poll` so it can be tested without a
   server that fails on cue. Everything about the bar's appearance is in here
   and nothing about timing is. */
function paintJob(j, pct){
  const job=$('job');
  if(!job) return;
  // Three states, not two. `error` stopped the run; `warn` means it finished
  // and something inside it quietly did the wrong thing - the case that had lee
  // staring at smeared pages with the bar saying "Ready".
  job.className = j.error?'err' : (j.running?'busy':(j.warn?'warn':'idle'));
  // The label is the warning's own first clause, not a fixed sentence: it used
  // to say "AI cleaning did not run" for every remark, including the ones that
  // are not faults at all.
  /* A RUN LOADING ITS MODELS IS NOT A RUN ON PAGE ONE.
     The checkpoints come off the disk before the first page - DB++/COO is 54s
     on page one of a fresh process against 9.6s by page three - and the bar
     used to spend that whole time saying "Detecting… 0 of 30". lee timed that
     on three different cards and read it as a fifty-second page every time.
     Say what is actually happening instead. */
  /* The percentage has its own slot on the right of the bar now, so it comes
     out of the sentence. That is what buys the room: the words and the number
     used to share one 250px line, and "Proofreading… 23 of 23 pages (100%)"
     only just fitted it. */
  const said = j.error ? j.error
    : (j.running
        ? (j.loading_model
            ? `Loading ${j.loading_model}…`
            : `${stepName(j.label)} ${j.done} of ${j.total}`)
        : (j.warn ? j.warn.split('—')[0].trim().replace(/[.,]$/,'')
                  : 'Ready'));
  $('jobtxt').textContent = said;
  /* ...and it is only shown while there is a run to measure. A percentage
     beside "Ready" is a number about nothing, and beside an error it is a
     number about a run that stopped. */
  const pctEl = $('jobpct');
  if(pctEl) pctEl.textContent =
    (j.running && !j.loading_model) ? pct + '%' : '';
  // The WHOLE of it, both on hover and on the click below. The strip is a
  // fixed width and cuts with an ellipsis, so a provider's four-hundred
  // character answer is readable without being allowed to resize the bar and
  // push the page tools off it. lee: *"the error moved everything out of the
  // way"*.
  const full = j.error || j.warn || '';
  job.title = full;
  job._full = full;
  /* Pacing, not measuring, while the checkpoints load: `.wait` gives the
     fill a width of its own and slides it. */
  const pacing = !!(j.running && j.loading_model);
  $('bar').classList.toggle('wait', pacing);
  $('fill').style.width =
    pacing ? '35%' : (j.running?pct:(j.error?0:100))+'%';
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
  // A NEW SERVER DESERVES A NEW PAGE. This tab's JavaScript was loaded from
  // whichever build was running when the tab opened, and a server restart
  // does not reach into an open tab - so after every ship, the "fixed" code
  // sat on disk while the old code went on running in front of lee. When
  // the server's run id moves, the page reloads itself and picks up
  // whatever is now being served. Strokes save themselves and edits are
  // debounced through the server, so the moment after a restart is as safe
  // a moment to reload as there is.
  if(j.boot){
    if(poll._boot===undefined) poll._boot=j.boot;
    else if(poll._boot!==j.boot){ location.reload(); return; }
  }
  // The queue rides down with the job, so the button is current without a
  // request of its own.
  if(j.queue) paintQueue(j.queue);
  const pct=j.total?Math.round(100*j.done/j.total):0;
  paintJob(j, pct);
  const cb=$('cancelJob'); if(cb) cb.style.display = j.running ? '' : 'none';
  // The NAME, not the sentence: `renderSteps` matches it against the step's
  // own job name, and a step in the middle of saying something matched
  // nothing and went dark.
  renderSteps(j.running?stepName(j.label):null);
  // Which action is running right now, by its queue id - the label alone
  // cannot tell two Cleans apart.
  const nowRunning = j.running
    ? ((j.queue && j.queue.running_qid) || j.label) : null;
  const changed = poll._at !== undefined && poll._at !== nowRunning;
  poll._at = nowRunning;
  // The action the Cancel was aimed at has gone, so the button is about
  // whatever is running now and says so.
  if(cancelJob._for !== undefined && nowRunning !== cancelJob._for)
    _armCancelBtn();
  // The count moves WHILE a run spends, not only when it ends.
  if(typeof coinsSpending === 'function' && j.running) coinsSpending(j.spent);
  if(j.running || (j.queue && j.queue.count)){
    // The page on screen used to be refreshed only when the WHOLE line was
    // empty, so with Clean running and Translate waiting behind it the cleaned
    // art did not appear until the translation had finished too.
    // lee: *"when the translat e finishes the cleanig aslso showed up"*.
    // One action ending is a moment worth looking at, so the page is brought
    // up to date then - once per action, not once per poll.
    if(changed){
      await refreshPages();
      if(proj.pages[cur]) showPage(cur);
    }
    setTimeout(poll,700); return; }
  _resetCancelBtn();
  poll._at = undefined;
  // A run has just ended, so the purse has changed and so has what the rest
  // of the chapter would cost - pages that are now read have text boxes the
  // translator will be charged for.
  if(typeof refreshCoins==='function') refreshCoins();
  pollWarm();
  await refreshPages();
  if(proj.pages[cur]) showPage(cur);
  if(j.cancelled){
    toast(`Stopped - ${j.done} page${j.done===1?'':'s'} done before cancelling.`);
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
