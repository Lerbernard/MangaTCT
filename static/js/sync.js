/* sync.js — Brush cursor + tool sliders; serialize/load paint layers and debounced sync to the server; plate upload.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* ---- persistent strokes ----
   The stroke list is saved with the project: a rendered overlay for the
   views and export, plus the editable layers, restored whenever the page is
   opened again. Changes sync on their own shortly after they happen. */
function serializeLayers(){
  return layers.map(st=> st.type==='patch'
    ? {t:'p', id:st.id, x:st.x, y:st.y, png:st.png, label:st.label||'',
       ...(st.over?{v:1}:{}),
       g:(st.group||(isRetouch(st)?'retouch':'drawing'))==='retouch'?'r':'d',
       op:st.op==null?1:st.op, visible:st.visible!==false}
    : {t:'b', id:st.id, col:st.col, sz:st.sz,
       op:st.op==null?1:st.op, hard:st.hard==null?1:st.hard,
       pts:st.pts, visible:st.visible!==false,
       // which side of the typesetting it is drawn on
       ...(st.over?{v:1}:{}),
       ...(st.type==='erase'?{e:1, clip:st.clip||''}:{}),
       // a shape keeps which shape it is and whether it is filled; its two
       // points ride along in `pts` like any other stroke's
       // ...and its angle, if it has been turned since
       ...(st.type==='shape'?{s:st.shape, f:st.fill?1:0,
                              ...(st.rot?{r:st.rot}:{})}:{})});
}
function loadLayers(list){
  layers=[]; layerSel=null;
  (list||[]).forEach(o=>{
    layerSeq=Math.max(layerSeq,(+o.id||0)+1);
    if(o.t==='p'){
      const st={id:o.id, type:'patch', col:'#57b0ff', sz:12,
                label:o.label||'', x:o.x, y:o.y, png:o.png, img:null, pts:[],
                op:o.op, visible:o.visible!==false, over:!!o.v};
      if(o.g) st.group = o.g==='r' ? 'retouch' : 'drawing';
      // saved before groups existed: unlabelled patches were heal output
      else st.group = o.label ? 'drawing' : 'retouch';
      const im=new Image();
      im.onload=()=>{ st.img=im; repaintAll(); };
      im.src=o.png;
      layers.push(st);
    }else{
      const st={id:o.id, col:o.col, sz:o.sz, op:o.op, hard:o.hard,
                pts:o.pts||[], visible:o.visible!==false, over:!!o.v};
      if(o.s){ st.type='shape'; st.shape=o.s; st.fill=!!o.f;
               if(o.r) st.rot=+o.r; }
      if(o.e){
        st.type='erase';
        if(o.clip){
          st.clip=o.clip;
          const ci=new Image();
          ci.onload=()=>{ st.clipImg=ci; repaintAll(); };
          ci.src=o.clip;
        }
      }
      layers.push(st);
    }
  });
  renderLayers();
  const ready=()=>{
    ensureCanvas(); repaintAll();
    // Rewrite the saved overlay once from the full, decoded stack.
    //
    // A page painted before this was fixed can be carrying an overlay that is
    // missing layers — written from a replay that ran a moment too early, or
    // with a family folded away — and nothing on screen says so, because the
    // screen is drawn from the editable layers and the plate is drawn from
    // the overlay. Opening the page puts it right, so the pages lee has
    // already worked on repair themselves rather than needing painting again.
    if(layers.length && loadLayers._fixed!==cur){
      loadLayers._fixed=cur;
      queueSync();
    }
  };
  const im=$('img');
  if(im && im.complete && im.naturalWidth) ready();
  else if(im) im.addEventListener('load', ready, {once:true});
}
let paintDirty=false, syncTimer=null, syncInflight=null;
function queueSync(){
  paintDirty=true;
  clearTimeout(syncTimer);
  syncTimer=setTimeout(()=>syncPaint(), 800);
}
/* Decode one layer's picture, and hand back a promise for it.

   The layer's own `onload` already fills the same field — this does not
   replace it, it waits for it. A second decode of a data URL the browser is
   already decoding is cheap, and whichever finishes first wins. */
function _decodeInto(st, src, dst){
  return new Promise(res=>{
    const im=new Image();
    im.onload=()=>{ if(!st[dst]) st[dst]=im; res(); };
    im.onerror=()=>res();
    im.src=st[src];
  });
}
/* Every layer's picture, decoded.

   A patch is a PNG and an eraser's fence is a PNG, and a browser decodes
   those asynchronously. A replay that runs before one has landed draws one
   layer fewer — harmless on screen, where the decode fires another repaint,
   and permanent in the SAVE, which is the picture the cleaned plate and the
   exported page are built from. So the save waits. */
async function layersReady(){
  const waits=[];
  layers.forEach(st=>{
    if(st.type==='patch' && st.png && !st.img)
      waits.push(_decodeInto(st,'png','img'));
    if(st.type==='erase' && st.clip && !st.clipImg)
      waits.push(_decodeInto(st,'clip','clipImg'));
  });
  if(waits.length) await Promise.all(waits);
}
async function syncPaint(){
  clearTimeout(syncTimer);
  const prev=syncInflight;
  // Nothing new to send, but a save may still be on the wire — anyone
  // awaiting a flush must wait for THAT, or a tab/page switch reads the
  // server before the strokes arrive and "loses" them.
  if(!paintDirty) return prev;
  paintDirty=false;
  const page=cur;
  await layersReady();
  // capture everything now, before the view or page changes under us
  repaintAll();
  // A layer the replay still could not draw means this picture is not the
  // page, so the save waits and tries again rather than writing something
  // incomplete over a good overlay.
  //
  // But only a few times. A picture that is not merely slow but BROKEN never
  // decodes at all, and a save that waits for it for ever is far worse than
  // one that goes without it: every stroke made after it would be lost, with
  // nothing on screen saying so. Something undrawable is not going to appear
  // in the overlay whatever happens — after three goes, save the rest.
  if(typeof replayIncomplete!=='undefined' && replayIncomplete
     && (syncPaint._tries||0) < 3){
    syncPaint._tries=(syncPaint._tries||0)+1;
    paintDirty=true; queueSync();
    return prev;
  }
  syncPaint._tries=0;
  const L=layersBuf();
  // The layers the PAGE has — the same set `repaintAll` just drew into the
  // buffers. It used to be a different set from the one that filled them
  // (this one ignores the family master eyes, that one honoured them), so the
  // two disagreed about whether there was anything to send.
  const shown=layers.filter(l=>l.visible!==false);
  const overlay = (shown.some(l=>!isOver(l)) && L && L.width)
    ? L.toDataURL('image/png') : '';
  // ...and the band that sits ABOVE the typesetting, as its own picture: the
  // server lays that one on after the text is drawn.
  const B=(typeof overBuf==='function') ? overBuf() : null;
  const overlay_over = (shown.some(isOver) && B && B.width)
    ? B.toDataURL('image/png') : '';
  const bodyNow={overlay, overlay_over, layers:serializeLayers()};
  const run=(async()=>{
    if(prev) await prev.catch(()=>{});      // keep saves in order
    const j=await api(`/api/page/${page}/paint`,'POST',bodyNow);
    if(!j.error && proj&&proj.pages&&proj.pages[page])
      proj.pages[page].has_paint = bodyNow.layers.length>0;
  })();
  syncInflight=run;
  run.finally(()=>{ if(syncInflight===run) syncInflight=null; });
  return run;
}

async function uploadPlate(file){
  if(!file) return;
  const data=await new Promise(res=>{
    const r=new FileReader(); r.onload=()=>res(r.result); r.readAsDataURL(file);
  });
  const j=await api(`/api/page/${cur}/clean_plate`,'POST',{data});
  if(j.error){toast(j.error);return;}
  proj.pages[cur].custom_clean=true;
  record('plate', `Page ${cur+1}: your own cleaned file is now used`,
    async ()=>{ await api(`/api/page/${cur}/clean_plate`,'POST',{clear:true});
                proj.pages[cur].custom_clean=false; showPage(cur); });
  toast('This page now uses your cleaned file — Clean will skip it.');
  showPage(cur);
  if(typeof renderSteps==='function') renderSteps();
}

async function clearPlate(){
  const j=await api(`/api/page/${cur}/clean_plate`,'POST',{clear:true});
  if(j.error){toast(j.error);return;}
  proj.pages[cur].custom_clean=false;
  record('plate', `Page ${cur+1}: back to the automatic cleaning`, null);
  toast('Back to the automatic cleaning.');
  showPage(cur);
  if(typeof renderSteps==='function') renderSteps();
}
