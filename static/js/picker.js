/* picker.js — Colour picker popover, HSV conversions, eyedropper + loupe.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

async function pickColour(){
  pkTarget=null;                      // this one belongs to the brush
  // The browser's own eyedropper can sample anywhere on screen. Where it does
  // not exist, fall back to clicking a point on the page.
  if(window.EyeDropper){
    const hid=hideTextForPick();
    try{
      const res=await new EyeDropper().open();
      setPicked(res.sRGBHex); closePicker();
    }catch(_){/* cancelled */}
    hid();
    return;
  }
  picking=!picking;
  { const b=$('eyeBtn'); if(b) b.classList.toggle('pri',picking); }
  ensureLoupe();
  ensureCanvas();
  $('paint').style.pointerEvents = picking||brush ? 'auto' : 'none';
  $('paint').style.cursor = picking ? 'crosshair' : (brush ? 'none' : '');
  if(!picking){ const l=$('loupe'); if(l) l.style.display='none'; loupeCtx=null; }
}

/* ---------------- our own colour picker ----------------
   The native <input type=color> opens the operating system's dialog, which
   fights the app completely. This is a small popover: a saturation/value
   square, a hue strip, a hex field and the recent colours. */
let pkH=30, pkS=0.05, pkV=0.96, pkRecent=[];
/* Where the picked colour goes. null = the brush; anything else supplies
   its own get/set — the typesetting swatches use this. */
let pkTarget=null;
function pkGet(){
  if(pkTarget) return pkTarget.get();
  const el=$('brushCol'); return el ? el.value : brushState.col;
}
function pkSet(hex){
  if(pkTarget){ pkTarget.set(hex); return; }
  brushState.col=hex;
  const el=$('brushCol'); if(el) el.value=hex;
  const c=$('colChip'); if(c) c.style.background=hex;
  const t=$('colHex'); if(t) t.textContent=hex;
}

function hsv2hex(h,sv,v){
  const f=(n,k=(n+h/60)%6)=>v-v*sv*Math.max(Math.min(k,4-k,1),0);
  return '#'+[f(5),f(3),f(1)].map(x=>Math.round(x*255)
    .toString(16).padStart(2,'0')).join('');
}
function hex2hsv(hex){
  const m=/^#?([0-9a-f]{6})$/i.exec(hex.trim()); if(!m) return null;
  const n=parseInt(m[1],16), r=(n>>16)/255, g=((n>>8)&255)/255, b=(n&255)/255;
  const mx=Math.max(r,g,b), mn=Math.min(r,g,b), d=mx-mn;
  let h=0;
  if(d){ h= mx===r ? ((g-b)/d)%6 : mx===g ? (b-r)/d+2 : (r-g)/d+4; h*=60;
         if(h<0)h+=360; }
  return {h, s: mx?d/mx:0, v: mx};
}

function buildPicker(){
  let el=$('picker2');
  if(el) return el;
  el=document.createElement('div');
  el.id='picker2';
  el.innerHTML=`
    <canvas id="pkSV" width="194" height="130"></canvas>
    <canvas id="pkHue" width="194" height="14"></canvas>
    <div class="row2">
      <span id="pkNow"></span>
      <input id="pkHex" spellcheck="false">
      <button id="pkEye" title="Eyedropper"
              onclick="pickerEyedrop()">
        <svg viewBox="0 0 24 24" width="13" height="13">
          <path fill="currentColor" d="M19.4 2.6a3 3 0 0 0-4.2 0l-2.1 2.1-1-1a1
            1 0 1 0-1.4 1.4l.3.3-7.6 7.6a2 2 0 0 0-.5.9l-.9 3.6a1 1 0 0 0 1.2
            1.2l3.6-.9a2 2 0 0 0 .9-.5l7.6-7.6.3.3a1 1 0 0 0 1.4-1.4l-1-1
            2.1-2.1a3 3 0 0 0 0-4.2ZM6.4 16.2l6.9-6.9 1.4 1.4-6.9 6.9-1.9.5.5-1.9Z"/>
        </svg></button>
    </div>
    <div class="sw" id="pkSw"></div>
    <button class="pri" id="pkDone" onclick="closePicker()"
            style="width:100%;margin-top:9px">Done</button>`;
  document.body.appendChild(el);

  const sv=$('pkSV'), hue=$('pkHue');
  const drag=(cv,fn)=>{
    let on=false;
    cv.addEventListener('mousedown',e=>{on=true;fn(e);e.preventDefault();});
    window.addEventListener('mousemove',e=>{ if(on) fn(e); });
    window.addEventListener('mouseup',()=>{on=false;});
  };
  drag(sv,e=>{
    const b=sv.getBoundingClientRect();
    pkS=Math.min(1,Math.max(0,(e.clientX-b.left)/b.width));
    pkV=1-Math.min(1,Math.max(0,(e.clientY-b.top)/b.height));
    pickerApply();
  });
  drag(hue,e=>{
    const b=hue.getBoundingClientRect();
    pkH=360*Math.min(1,Math.max(0,(e.clientX-b.left)/b.width));
    pickerApply();
  });
  $('pkHex').addEventListener('change',()=>{
    const q=hex2hsv($('pkHex').value);
    if(q){ pkH=q.h; pkS=q.s; pkV=q.v; pickerApply(); }
  });
  document.addEventListener('mousedown',e=>{
    // An armed eyedropper owns the next click — closing the popover here
    // disarmed it a split second early, and the click painted instead.
    if(picking) return;
    if(el.style.display==='block' && !el.contains(e.target)
       && !e.target.closest('.colwell')) closePicker();
  },true);
  return el;
}

function paintPicker(){
  const sv=$('pkSV').getContext('2d');
  const w=194,h=130;
  const gx=sv.createLinearGradient(0,0,w,0);
  gx.addColorStop(0,'#fff'); gx.addColorStop(1,`hsl(${pkH},100%,50%)`);
  sv.fillStyle=gx; sv.fillRect(0,0,w,h);
  const gy=sv.createLinearGradient(0,0,0,h);
  gy.addColorStop(0,'#0000'); gy.addColorStop(1,'#000');
  sv.fillStyle=gy; sv.fillRect(0,0,w,h);
  sv.beginPath();
  sv.arc(pkS*w,(1-pkV)*h,5,0,7);
  sv.strokeStyle=pkV>0.5?'#000':'#fff'; sv.lineWidth=1.6; sv.stroke();

  const hu=$('pkHue').getContext('2d');
  const gh=hu.createLinearGradient(0,0,194,0);
  for(let i=0;i<=6;i++) gh.addColorStop(i/6,`hsl(${i*60},100%,50%)`);
  hu.fillStyle=gh; hu.fillRect(0,0,194,14);
  hu.fillStyle=pkV>0.5?'#000':'#fff';
  hu.fillRect(pkH/360*194-1.5,0,3,14);
}

function pickerApply(){
  const hex=hsv2hex(pkH,pkS,pkV);
  pkSet(hex);
  // The popover may not exist yet — the eyedropper also lands here.
  const now=$('pkNow'), hx=$('pkHex');
  if(now){ now.style.background=hex; hx.value=hex; paintPicker(); }
}

function openPicker(anchor, target){
  pkTarget=target||null;
  const el=buildPicker();
  const q=hex2hsv(pkGet())||{h:30,s:.05,v:.96};
  pkH=q.h; pkS=q.s; pkV=q.v;
  $('pkSw').innerHTML=[...new Set(
      [...pkRecent, '#ffffff','#f4f2ee','#e8e4dc','#bdbdbd','#6f6f6f',
       '#2b2b2b','#000000'])].slice(0,8)
    .map(c=>`<i style="background:${c}" title="${c}"
          onclick="setPicked('${c}')"></i>`).join('');
  const b=anchor.getBoundingClientRect();
  el.style.display='block';
  el.style.left=Math.min(b.left, innerWidth-240)+'px';
  el.style.top=Math.min(b.bottom+8, innerHeight-260)+'px';
  pickerApply();
}
function setPicked(hex){
  const q=hex2hsv(hex); if(!q) return;
  pkH=q.h; pkS=q.s; pkV=q.v; pickerApply();
}
function closePicker(){
  const el=$('picker2'); if(el) el.style.display='none';
  if(picking) stopPagePick();          // closing puts the eyedropper away too
  const hex=pkGet();
  pkRecent=[hex, ...pkRecent.filter(c=>c!==hex)].slice(0,7);
  // Whoever the popover was writing to gets one "finished" — the moment to
  // write a history entry and save, instead of one per pixel of the drag
  // round the wheel.
  const t=pkTarget;
  if(t && typeof t.done==='function') t.done();
}

/* The eyedropper that lives inside the popover. It lights up while armed and
   a second press disarms it. Samples anywhere on screen where the browser
   allows it; otherwise a click on the page. */
async function pickerEyedrop(){
  const btn=$('pkEye');
  if(picking){ stopPagePick(); return; }        // pressed again: turn it off
  if(window.EyeDropper){
    if(btn) btn.classList.add('pri');
    // sample the page, not the typesetting drawn over it
    const hid=hideTextForPick();
    try{ const res=await new EyeDropper().open(); setPicked(res.sRGBHex); }
    catch(_){/* cancelled */}
    hid();
    if(btn) btn.classList.remove('pri');
    return;
  }
  picking=true;
  if(btn) btn.classList.add('pri');
  ensureLoupe(); ensureCanvas(); repaintAll();
  $('paint').style.pointerEvents='auto';
  $('paint').style.cursor='crosshair';
}

function stopPagePick(){
  picking=false;
  const pe=$('pkEye'); if(pe) pe.classList.remove('pri');
  const eb=$('eyeBtn'); if(eb) eb.classList.remove('pri');
  const l=$('loupe'); if(l) l.style.display='none'; loupeCtx=null;
  const pcv=$('paint');
  if(pcv){ pcv.style.pointerEvents = brush?'auto':'none';
           pcv.style.cursor = brush?'none':''; }
}

let loupeCtx=null;
function ensureLoupe(){
  let l=$('loupe');
  if(!l){
    l=document.createElement('div');
    l.id='loupe';
    l.innerHTML='<b id="loupeHex"></b>';
    document.body.appendChild(l);
    window.addEventListener('mousemove',e=>{
      if(!picking){l.style.display='none';loupeCtx=null;return;}
      const img=$('img'), b=img.getBoundingClientRect();
      const inside=e.clientX>=b.left&&e.clientX<=b.right
                 &&e.clientY>=b.top&&e.clientY<=b.bottom;
      l.style.display=inside?'block':'none';
      if(!inside) return;
      if(!loupeCtx){
        const c=document.createElement('canvas');
        c.width=img.naturalWidth; c.height=img.naturalHeight;
        loupeCtx=c.getContext('2d',{willReadFrequently:true});
        loupeCtx.drawImage(img,0,0);
      }
      const x=Math.round((e.clientX-b.left)/b.width*img.naturalWidth);
      const y=Math.round((e.clientY-b.top)/b.height*img.naturalHeight);
      const d=loupeCtx.getImageData(Math.min(x,img.naturalWidth-1),
                                    Math.min(y,img.naturalHeight-1),1,1).data;
      const hex='#'+[d[0],d[1],d[2]].map(v=>v.toString(16).padStart(2,'0')).join('');
      l.style.background=hex;
      l.style.left=e.clientX+'px'; l.style.top=e.clientY+'px';
      $('loupeHex').textContent=hex;
    });
  }
  return l;
}

function ensureCursor(){
  let c=$('brushCursor');
  if(!c){
    c=document.createElement('div');
    c.id='brushCursor';
    document.body.appendChild(c);
    window.addEventListener('mousemove',e=>{
      lastMouse={x:e.clientX,y:e.clientY};
      positionBrushCursor();
    });
  }
  return c;
}
/* Each tool shows only the settings it actually uses: the brush all of
   them, the clone stamp everything but the colour, the healing brush just
   the size. With nothing armed, everything stays reachable. */
const brushState={sz:16, op:100, hard:100, col:'#ffffff'};

function paintToolUI(){
  const shp = (typeof shapeKind!=='undefined') && shapeKind;
  const t = shp?'shape' : brush?'brush' : stamp?'stamp'
          : heal?'heal' : eraser?'erase'
          : (typeof shapeEdit!=='undefined' && shapeEdit)?'move' : null;
  // With nothing armed the SECTION on screen decides: standing in Retouch
  // with no tool picked should not be offering a brush colour, and standing
  // in Shapes should be, because the next thing drawn will use it.
  const tab = (typeof toolTab==='function') ? toolTab() : 'paint';
  // A shortcut can arm a tool whose section is not the one on screen. Redraw
  // the panel so the lit button is somewhere it can be seen. The marker moves
  // first, so this asks once and not once per call.
  if(typeof _renderedTab!=='undefined' && _renderedTab && _renderedTab!==tab){
    _renderedTab=tab;
    if(typeof soon==='function' && typeof renderInspector==='function')
      soon(renderInspector);
  }
  const show=(id,on)=>{ const el=$(id); if(el) el.style.display=on?'':'none'; };
  const idle = t===null;
  // A shape has a colour, a line width (Size) and an opacity. Hardness means
  // nothing to it: its edge is the edge of the shape. The arrow draws nothing
  // at all, so none of the three say anything about what it will do.
  show('rowSize', t!=='move');
  show('rowOp',   t==='brush' || t==='stamp' || t==='erase' || t==='shape'
                  || (idle && tab!=='select'));
  show('rowHard', t==='brush' || t==='stamp' || t==='erase'
                  || (idle && (tab==='paint' || tab==='retouch')));
  show('rowCol',  t==='brush' || t==='shape'
                  || (idle && tab!=='retouch'));
  // The old markup put the well and the eyedropper in the tool strip; the
  // strip is per-section now and they are shared, so they moved to a row of
  // their own. Keep the single-element rule working either way.
  show('brushWell', t==='brush' || t==='shape' || (idle && tab!=='retouch'));
  show('rowShapeFill', t==='shape'
       || (typeof selHasMask==='function' && selHasMask()));
  // The toolbox shows what is armed, so it is redrawn wherever the panel is.
  if(typeof renderToolbar==='function') renderToolbar();
}

/* The pointer's last position, so size changes (slider, [ ]) can redraw the
   cursor rings immediately — no need to wiggle the mouse first. */
let lastMouse=null;
/* A dialog in front of the page hides both of these — in the STYLESHEET, not
   here. They are moved on mousemove and a dialog can open without the mouse
   moving at all, so a guard on this line is a guard that fires too late; and
   with the stylesheet doing it, a guard here changes nothing a test can see.
   See the `body:has(.modal.on)` rule in editor.css. */
function positionBrushCursor(){
  const c=$('brushCursor'); if(!c||!lastMouse) return;
  // an armed colour pick is a precise point, not a brush circle
  if(picking){ c.style.display='none'; return; }
  if(!(brush||heal||eraser)||view!=='typeset'){ c.style.display='none'; return; }
  const img=$('img'), b=img.getBoundingClientRect();
  const inside=lastMouse.x>=b.left&&lastMouse.x<=b.right
             &&lastMouse.y>=b.top&&lastMouse.y<=b.bottom;
  c.style.display=inside?'block':'none';
  if(!inside) return;
  const szEl=$('brushSz');
  const d=(szEl? +szEl.value : brushState.sz)*(b.width/img.naturalWidth);
  c.style.width=d+'px'; c.style.height=d+'px';
  c.style.left=(lastMouse.x-d/2)+'px';
  c.style.top=(lastMouse.y-d/2)+'px';
}
function cursorSize(){
  // live: the rings resize the moment the value changes, no mouse wiggle
  positionBrushCursor();
  if(stamp && lastMouse)
    cloneHover({clientX:lastMouse.x, clientY:lastMouse.y});
  if(cloneSrc && $('cloneMark') && $('cloneMark').style.display!=='none')
    cloneMark(cloneSrc.x, cloneSrc.y);
}

/* Slider and number box are the same control in two shapes. */
function sliderFill(a){
  if(!a) return;
  const t=((+a.value)-(+a.min))/Math.max(1,(+a.max)-(+a.min));
  // fill ends under the knob's centre at every position (15px knob)
  a.style.setProperty('--p', `calc(${t.toFixed(4)} * (100% - 15px) + 7.5px)`);
}
function syncBrushFills(){
  ['brushSz','brushOp','brushHard'].forEach(id=>sliderFill($(id)));
}
function brushSync(which, v){
  const a=$('brush'+which), b=$('brush'+which+'N');
  if(!a) return;
  v=Math.max(+a.min, Math.min(+a.max, Math.round(+v||+a.min)));
  a.value=v; if(b) b.value=v;
  brushState[{Sz:'sz',Op:'op',Hard:'hard'}[which]]=v;
  sliderFill(a);
  cursorSize();
}

/* [ and ] step the brush size, as in Photoshop. */
function nudgeBrush(dir){
  // works with or without the panel on screen — brushState is the truth
  const v = $('brushSz') ? +$('brushSz').value : brushState.sz;
  const step = v<=10 ? 1 : v<=30 ? 2 : 4;
  const nv = Math.max(1, Math.min(60, v + dir*step));
  if($('brushSz')) brushSync('Sz', nv); else brushState.sz=nv;
  toast('Brush size '+nv, 600);
  if(typeof positionBrushCursor==='function') positionBrushCursor();
}
