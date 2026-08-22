/* history.js - Session history log + Ctrl/Cmd-Z undo stack.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* ---------------- painting on the cleaned plate ---------------- */
/* ---------------- history & undo ----------------
   Every meaningful change is logged, and the ones that can be undone carry a
   function that does it. Ctrl/Cmd+Z walks back through those. The log lives
   for this session - reloading starts it fresh.

   UNDO IS PER PAGE. lee: *"control + z shoud only work on a per pafe basix
   not a global thing"*.

   One stack across the whole chapter meant Ctrl+Z on page 12 could take back
   a merge on page 3 - and then jump you to page 3 to show you, because the
   undo of a region change ends with `showPage` on the page it belongs to. You
   press it to take back the thing you just did HERE, and there is no way to
   tell from the keyboard which page the top of the stack is on.

   So every entry is stamped with the page it was recorded on, and Ctrl+Z
   takes back the newest entry stamped with the page you are looking at. The
   others are not lost: they are still on the stack, and going back to their
   page makes them the next thing that undoes. */
let hist=[], undoStack=[];

function recordPage(){
  return (typeof cur === 'number') ? cur : null;
}

function record(kind, label, undoFn){
  const page = recordPage();
  hist.push({t:Date.now(), kind, label, page});
  if(hist.length>200) hist.shift();
  if(undoFn) undoStack.push({label, fn:undoFn, page});
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
  // The newest entry belonging to the page on screen - not the newest entry.
  const here = recordPage();
  let at = -1;
  for(let i = undoStack.length - 1; i >= 0; i--)
    if(undoStack[i].page === here){ at = i; break; }
  if(at < 0){
    toast(undoStack.length ? 'Nothing to undo on this page.'
                           : 'Nothing to undo.');
    return;
  }
  const [u] = undoStack.splice(at, 1);
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
