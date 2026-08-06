/* toolbar.js — the vertical tool strip down the left of the page.

   lee: *"make a side bar lke this for all the tool and make tool folder for
   them like photoshop where you can right clcik to slected similiar tool from
   a small windown, move every too there exaxt for the main zoom an teh
   filded"*, with a picture of GIMP's toolbox.

   The tools used to live in four tabbed sections of the side panel: pick a
   section to see its buttons, and the buttons for the other three were not on
   screen at all. So reaching for the clone stamp while the brush was out meant
   changing section first, and nothing anywhere showed what was armed unless
   you happened to be looking at the right tab.

   A toolbox fixes both by being one place that is always there. Tools that do
   the same KIND of job share a slot — marquee, lasso and wand are all "choose
   part of the page" — and the slot shows whichever of them you used last, with
   a corner mark saying there are others. Right-click it (or press and hold) to
   pick another.

   What stays out of it: the zoom stepper in the top bar, which is a readout
   with two buttons rather than a tool, and every numeric field. Those are
   settings for a tool, and they belong beside the tool's own controls in the
   panel.

   Everything here DELEGATES. Arming the brush is still `toggleBrush()` and
   the panel still draws the brush's size and hardness; this file decides what
   is on screen and what is lit, and nothing else. */

/* One entry per slot, top to bottom. `k` is the tool's own key, `on` arms it,
   `lit` says whether it is armed right now. A slot with one tool has no
   flyout. */
const TOOLBOX = [
  // The transform, twice. The one on the key is the one lee asked for — every
  // corner on its own — and scale-and-rotate keeps its place underneath for
  // when a box should stay a box. He asked for Ctrl+T and then, told that
  // Chrome keeps that combination for opening a tab: *"isntead of control t
  // just make it t"*.
  {slot:'move', tools:[
    {k:'xfd',    name:'Free transform (T)', icon:'distort',
     on:()=>window.xfToggle && xfToggle('distort'),
     lit:()=>typeof xf!=='undefined' && !!(xf&&xf.quad)},
    {k:'xf',     name:'Scale and rotate', icon:'move',
     on:()=>window.xfToggle && xfToggle(),
     lit:()=>typeof xf!=='undefined' && !!xf && !xf.quad},
  ]},
  {slot:'select', tools:[
    {k:'rect',   name:'Rectangular select (M)', icon:'marquee',
     on:()=>toggleSelTool('rect'), lit:()=>selTool==='rect'},
    {k:'lasso',  name:'Lasso (L)', icon:'lasso',
     on:()=>toggleSelTool('lasso'), lit:()=>selTool==='lasso'},
    {k:'wand',   name:'Magic wand (W)', icon:'wand',
     on:()=>toggleSelTool('wand'), lit:()=>selTool==='wand'},
  ]},
  {slot:'text', tools:[
    {k:'addtext', name:'Add a text box', icon:'type',
     on:()=>window.toggleAddText && toggleAddText(),
     lit:()=>typeof addingText!=='undefined' && addingText},
  ]},
  {slot:'paint', tools:[
    {k:'brush',  name:'Brush (B)', icon:'brush',
     on:()=>toggleBrush(), lit:()=>typeof brush!=='undefined' && brush},
    {k:'eraser', name:'Eraser (E)', icon:'eraser',
     on:()=>toggleEraser(), lit:()=>typeof eraser!=='undefined' && eraser},
  ]},
  {slot:'fill', tools:[
    {k:'fill',   name:'Bucket fill (G)', icon:'bucket',
     on:()=>toggleSelTool('fill'), lit:()=>selTool==='fill'},
  ]},
  {slot:'retouch', tools:[
    {k:'stamp',  name:'Clone stamp', icon:'stamp',
     on:()=>toggleStamp(), lit:()=>typeof stamp!=='undefined' && stamp},
    // One healing brush, and it is the one that redraws. The other — the
    // local fill that copied real pixels in from nearby — is gone: lee,
    // having used it on his own pages, *"remoev teh regualr healing brush,
    // its ass"*. It could not invent artwork that was never there, which is
    // the only thing a healing brush is for once the Clean step has run.
    {k:'heal',   name:'Healing brush', icon:'healai',
     on:()=>toggleHeal(),
     lit:()=>typeof heal!=='undefined' && heal},
  ]},
  {slot:'shape', tools:[
    {k:'shrect', name:'Rectangle', icon:'square',
     on:()=>toggleShape('rect'), lit:()=>shapeKind==='rect'},
    {k:'shcirc', name:'Ellipse', icon:'circle',
     on:()=>toggleShape('circle'), lit:()=>shapeKind==='circle'},
    {k:'shline', name:'Line', icon:'line',
     on:()=>toggleShape('line'), lit:()=>shapeKind==='line'},
    // "Move a shape" used to live here. Clicking a shape on the page picks it
    // up now, the same as clicking a text box, so a tool whose whole job was
    // to make that click work is a tool that asks you to arm something before
    // you are allowed to point at what you can already see.
    // lee: *"remove teh move a shape tool its redundent"*. `toggleShapeEdit`
    // is still the arrow, still on V, and the page click turns it on itself.
  ]},
  {slot:'pick', tools:[
    {k:'eyedrop', name:'Eyedropper (I)', icon:'dropper',
     on:()=>pickColour(), lit:()=>typeof picking!=='undefined' && picking},
  ]},
  {slot:'view', tools:[
    {k:'hand',   name:'Hand (H)', icon:'hand',
     on:()=>toggleHand(), lit:()=>typeof handMode!=='undefined' && handMode,
     // 100% means ACTUAL SIZE — one page pixel to one screen pixel. It used
     // to call `fitPage`, which is what the old readout called 100%: on a
     // page already fitted that changed nothing but the scroll position.
     // lee: *"double clciking teh hadns dosnt change teh zoom it jyst centers
     // it"*.
     dbl:()=>window.zoomTo100 && zoomTo100()},
    {k:'zoomin', name:'Zoom in', icon:'zoomin',
     on:()=>toggleZoomTool('in'), lit:()=>zoomTool==='in'},
    {k:'zoomout',name:'Zoom out', icon:'zoomout',
     on:()=>toggleZoomTool('out'), lit:()=>zoomTool==='out'},
  ]},
];

/* The icons, as one path each on a 24-box. Line art, no fills, so they read
   the same lit and unlit — a filled glyph on the accent colour disappears. */
const TB_ICON = {
  // A quadrilateral out of true, with its corners marked — what the tool
  // does, and nothing like the four-arrow move beside it in the same slot.
  // lee: *"just cal it teh free transform tool and give it a difrent icon"*.
  distort:'M5 7.5 19 3.5V16L5 20.5Z M5 7.5v0 M19 3.5v0 M19 16v0 M5 20.5v0',
  move:'M12 2.6 15 6h-2v5h5V9l3.4 3-3.4 3v-2h-5v5h2l-3 3.4L9 18h2v-5H6v2l-3.4-3'
      +'L6 9v2h5V6H9z',
  marquee:'M3.5 6.5h4m3 0h3m3 0h4v4m0 3v3m0 3v0h-4m-3 0h-3m-3 0h-4v-4m0-3v-3m0-3v0',
  // A rope, not a speech balloon: the old one was a closed loop with a small
  // curl, which at 19px read as a chat bubble. A loop with a hanging tail and
  // a knot on the end is what the tool actually does.
  lasso:'M10.6 14.3a7 5 0 1 1 2.8.1c.3 2-1.6 2.5-1.6 4.1'
       +'M13.3 18.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 1 1 3 0',
  wand:'M4 20 15 9m0 0 2-2m-2 2-2-2m2 2 2 2m-2-2-2 2M18.4 4.2l.7 1.8 1.8.7-1.8.7'
      +'-.7 1.8-.7-1.8-1.8-.7 1.8-.7z',
  // A T, with no foot. With one it was an I-beam.
  type:'M5.4 6h13.2M12 6v12.4',
  brush:'M4.5 19.5c1.6.4 3.4-.2 4.3-1.6.8-1.3.4-2.7-.6-3.4-1-.7-2.5-.5-3.2.6'
       +'-.6 1-.4 2.6-.5 4.4zM9.6 14.2 19 4.9c.6-.6 1.5-.6 2.1 0 .6.6.6 1.5 0 2.1'
       +'L11.8 16.4',
  eraser:'M8.6 20.5h11M4.3 16.2l7.4-7.4a2 2 0 0 1 2.8 0l3.9 3.9a2 2 0 0 1 0 2.8'
        +'l-4.6 4.6H7.6l-3.3-3.3a2 2 0 0 1 0-2.8zM9.5 11.5l6 6',
  bucket:'M6.2 9.3 12 3.5l7 7a1.4 1.4 0 0 1 0 2L13 18.6a1.4 1.4 0 0 1-2 0l-5.8-5.8'
        +'a1.4 1.4 0 0 1 0-2zM9 6.3 6.6 3.9M20.4 15.4c1 1.3 1.6 2.2 1.6 3a1.6 1.6 0'
        +' 1 1-3.2 0c0-.8.6-1.7 1.6-3z',
  stamp:'M5.5 20.5h13M7 17.5h10v-2.2c0-.7-.6-1.3-1.3-1.3H8.3c-.7 0-1.3.6-1.3 1.3z'
       +'M9.2 14V9.6H7.5V7.4c0-2.2 1.9-3.9 4.5-3.9s4.5 1.7 4.5 3.9v2.2h-1.7V14',
  // A plaster, not a plus. The healing brush was a bare cross, which said
  // "add" far more than it said "repair" — lee: *"make the icon better and
  // more reconizable"*. A sticking plaster on the diagonal is what every
  // editor draws for this, with the sparkle that marks every other AI
  // control here.
  healai:'M14.3 5.3 15.6 6.5a1.6 1.6 0 0 1 0 2.2l-6.9 6.9a1.6 1.6 0 0 1-2.2 0'
        +'L5.3 14.3a1.6 1.6 0 0 1 0-2.2l6.8-6.8a1.6 1.6 0 0 1 2.2 0z'
        +'M18.8 15.2l.8 2.4 2.4.8-2.4.8-.8 2.4-.8-2.4-2.4-.8 2.4-.8z',
  square:'M4.4 5.6h15.2v12.8H4.4z',
  circle:'M12 5.4c4.2 0 7.6 2.9 7.6 6.6S16.2 18.6 12 18.6 4.4 15.7 4.4 12 7.8 5.4 12 5.4z',
  line:'M4.5 19.5 19.5 4.5',
  arrow:'M6.5 3.5v15l3.7-3.7h5.4z',
  dropper:'M4.5 19.5v-3l8.2-8.2m0 0 1.3 1.3m-1.3-1.3-1.4-1.4M14 9.6l4.3-4.3a1.9 1.9'
         +' 0 0 0 0-2.7 1.9 1.9 0 0 0-2.7 0L11.3 7',
  hand:'M8.6 12.4V5.9a1.4 1.4 0 0 1 2.8 0v5.1m0-1.4V4.4a1.4 1.4 0 0 1 2.8 0v5.2m0-.7'
      +'a1.4 1.4 0 0 1 2.8 0v2.9m0-1.3a1.4 1.4 0 0 1 2.8 0v5.1c0 3.4-2.4 6.4-6.2 6.4'
      +'-2.8 0-4.3-1.2-5.6-3l-3-4.4a1.4 1.4 0 0 1 2.1-1.8z',
  zoomin:'M10.6 4.6a6 6 0 1 1 0 12 6 6 0 0 1 0-12zM15 15l4.6 4.6M7.9 10.6h5.4M10.6 7.9v5.4',
  zoomout:'M10.6 4.6a6 6 0 1 1 0 12 6 6 0 0 1 0-12zM15 15l4.6 4.6M7.9 10.6h5.4',
};

function tbSvg(name){
  return `<svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true">`
    + `<path d="${TB_ICON[name]||''}" fill="none" stroke="currentColor"`
    + ` stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

/* Which tool each slot is showing — the last one used out of that slot. */
const tbChosen = {};
function tbTool(slot){
  const g = TOOLBOX.find(s=>s.slot===slot);
  if(!g) return null;
  return g.tools.find(t=>t.k===tbChosen[slot]) || g.tools[0];
}
/* ...unless one of the slot's OTHER tools is armed, in which case the slot
   shows that one: what is lit and what is on the button are the same thing. */
function tbShown(g){
  const armed = g.tools.find(t=>{ try{ return !!t.lit(); }catch(e){ return false; } });
  return armed || tbTool(g.slot);
}
function tbArm(slot, key){
  const g = TOOLBOX.find(s=>s.slot===slot); if(!g) return;
  const t = g.tools.find(x=>x.k===key) || g.tools[0];
  tbChosen[slot] = t.k;
  tbClose();
  try{ t.on(); }catch(e){}
  renderToolbar();
}

/* Double-clicking a tool does whatever that tool's second press means. The
   hand fits the page to the window, the way it does in Photoshop — lee:
   *"make it si that dubble lciking the hand tool on the side is also make the
   page go to 100%"*. The first click of the pair already armed the tool and
   the second put it away again, so it is re-armed here: a double-click is one
   gesture, not two, and it leaves the tool in your hand. */
function tbDbl(slot, key){
  const g = TOOLBOX.find(s=>s.slot===slot); if(!g) return;
  const t = g.tools.find(x=>x.k===key); if(!t || !t.dbl) return;
  let on=false; try{ on=!!t.lit(); }catch(e){}
  if(!on){ try{ t.on(); }catch(e){} }
  try{ t.dbl(); }catch(e){}
  renderToolbar();
}

function renderToolbar(){
  const el = document.getElementById('toolbox');
  if(!el) return;
  // The toolbox is for working ON the page, and the page you work on is the
  // one under the Edit view. There is nothing to paint on the Results or
  // Settings screens, and the Original view is where BOXES are managed — the
  // paint canvas is not even mounted there, so every tool in the strip was a
  // button that could be pressed and could not do anything.
  // lee: *"the side bar shoud only be visible on the edit tab"*.
  const show = (typeof tab==='undefined' || tab==='edit')
            && (typeof view==='undefined' || view==='typeset');
  el.style.display = show ? '' : 'none';
  if(!show) return;
  el.innerHTML = TOOLBOX.map(g=>{
    const t = tbShown(g);
    let lit=false; try{ lit=!!t.lit(); }catch(e){}
    // ONE tool is lit, and it is the one that is armed.
    //
    // A slot used to also mark which of its tools it was set to, so that
    // picking one out of a flyout looked like it had done something even when
    // that tool could not arm yet. Every slot you had ever touched then kept
    // its mark, so three or four buttons sat outlined at once and none of
    // them was the tool you were using. lee: *"only one tool sjou dbeselected
    // at once and i dont now what this haft selection thing is but remove
    // it"*. The icon still changes to the tool the slot is set to; that is
    // what says which one it is.
    return `<button class="tbtn${lit?' on':''}"
        data-slot="${g.slot}"
        data-tool="${t.k}" title="${t.name}"
        onclick="tbArm('${g.slot}','${t.k}')"
        ondblclick="tbDbl('${g.slot}','${t.k}')"
        oncontextmenu="tbFlyout(event,'${g.slot}');return false">
        ${tbSvg(t.icon)}${g.tools.length>1?'<i class="tbmore"></i>':''}
      </button>`;
  }).join('');
  // Press and hold opens the flyout too — the same gesture as a right-click
  // for anybody who does not have one, and the one a trackpad makes easy.
  el.querySelectorAll('.tbtn').forEach(b=>{
    b.addEventListener('mousedown', e=>{
      if(e.button!==0) return;
      const slot=b.getAttribute('data-slot');
      const g=TOOLBOX.find(s=>s.slot===slot);
      if(!g || g.tools.length<2) return;
      b._hold=setTimeout(()=>{ b._held=true; tbFlyout(e, slot); }, 420);
    });
    const drop=()=>{ clearTimeout(b._hold); setTimeout(()=>{b._held=false;},0); };
    b.addEventListener('mouseup', drop);
    b.addEventListener('mouseleave', drop);
    b.addEventListener('click', e=>{ if(b._held){ e.stopPropagation(); } }, true);
  });
}

function tbClose(){
  const f=document.getElementById('tbflyout');
  if(f) f.remove();
}
function tbFlyout(ev, slot){
  ev.preventDefault(); ev.stopPropagation();
  tbClose();
  const g=TOOLBOX.find(s=>s.slot===slot); if(!g || g.tools.length<2) return;
  const btn=(ev.currentTarget && ev.currentTarget.closest)
    ? ev.currentTarget.closest('.tbtn')
    : document.querySelector(`.tbtn[data-slot="${slot}"]`);
  const b=btn.getBoundingClientRect();
  const f=document.createElement('div');
  f.id='tbflyout'; f.className='tbflyout';
  f.innerHTML=g.tools.map(t=>{
    let lit=false; try{ lit=!!t.lit(); }catch(e){}
    return `<button class="tbrow${lit?' on':''}"
        onclick="tbArm('${slot}','${t.k}')">${tbSvg(t.icon)}
        <span>${t.name}</span></button>`;
  }).join('');
  document.body.appendChild(f);
  // Fixed to the viewport, beside the button, and never off the bottom.
  const h=f.getBoundingClientRect().height;
  f.style.left=Math.round(b.right+6)+'px';
  f.style.top=Math.round(Math.max(8,
    Math.min(b.top, window.innerHeight-h-8)))+'px';
}
document.addEventListener('click', e=>{
  if(!e.target.closest || !e.target.closest('#tbflyout')) tbClose();
});
document.addEventListener('keydown', e=>{ if(e.key==='Escape') tbClose(); });
window.addEventListener('resize', tbClose);
