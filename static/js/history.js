/* history.js — Session history log + Ctrl/Cmd-Z undo stack.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* ---------------- painting on the cleaned plate ---------------- */
/* ---------------- history & undo ----------------
   Every meaningful change is logged, and the ones that can be undone carry a
   function that does it. Ctrl/Cmd+Z walks back through those. The log lives
   for this session — reloading starts it fresh. */
let hist=[], undoStack=[];

function record(kind, label, undoFn){
  hist.push({t:Date.now(), kind, label});
  if(hist.length>200) hist.shift();
  if(undoFn) undoStack.push({label, fn:undoFn});
  if(undoStack.length>60) undoStack.shift();
  renderHistory();
}

function renderHistory(){
  const el=$('histList'); if(!el) return;
  el.innerHTML = hist.length ? hist.slice(-40).reverse().map(h=>{
    const d=new Date(h.t);
    const hh=String(d.getHours()).padStart(2,'0');
    const mm=String(d.getMinutes()).padStart(2,'0');
    return `<div class="he"><span class="ht">${hh}:${mm}</span>${esc(h.label)}</div>`;
  }).join('') : '<p class="help" style="margin:4px 0 0">No changes yet.</p>';
}

async function undoLast(){
  const u=undoStack.pop();
  if(!u){toast('Nothing to undo.');return;}
  await u.fn();
  record('undo', `Undone: ${u.label}`, null);
  toast(`Undone: ${u.label}`);
}

window.addEventListener('keydown',e=>{
  if(!(e.key==='z'&&(e.ctrlKey||e.metaKey))) return;
  const a=document.activeElement;
  // Only a real writing surface keeps the browser's own undo. Focus left on
  // a slider, checkbox or button was why Ctrl+Z "sometimes" did nothing.
  const writing = a && (a.tagName==='TEXTAREA' || a.isContentEditable ||
    (a.tagName==='INPUT' &&
     /^(text|search|password|email|url|number)$/.test(a.type||'text')));
  if(writing) return;
  e.preventDefault(); undoLast();
});
