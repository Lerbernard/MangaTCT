/* toolbar.js - the vertical tool strip down the left of the page.

   lee: *"make a side bar lke this for all the tool and make tool folder for
   them like photoshop where you can right clcik to slected similiar tool from
   a small windown, move every too there exaxt for the main zoom an teh
   filded"*, with a picture of GIMP's toolbox.

   The tools used to live in four tabbed sections of the side panel: pick a
   section to see its buttons, and the buttons for the other three were not on
   screen at all. So reaching for the clone stamp while the brush was out meant
   changing section first, and nothing anywhere showed what was armed unless
   you happened to be looking at the right tab.

   A toolbox fixes both by being one place that is always there.

   EVERY TOOL IS ON IT. They used to share slots the way Photoshop and GIMP do
   - marquee, lasso and wand behind one button, the slot showing whichever you
   used last, right-click or press-and-hold for the rest - and that is one
   hidden gesture away from every tool you did not use last. lee, having lived
   with it: *"for the tools i want you to remove tye subfolder thing and make
   them all visivle and seperated bya small bar and kind make each their own
   sectiosn ianted of the subfolder"*.

   So the slots are still there and they are SECTIONS now, one under the other,
   with a hairline between them. Same grouping, no lid on it: what used to be
   the thing you had to discover is the thing you can see.

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
  // The transform, twice. The one on the key is the one lee asked for - every
  // corner on its own - and scale-and-rotate keeps its place underneath for
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
  // SELECT BOXES IS NOT HERE ANY MORE, and nothing was lost by that.
  //
  // It picks BOXES - lee: *"add annew seclet tool that alloww me to dran a
  // scquer on the boxs and all the boxesin that square sihoud be slected"* -
  // and boxes are managed on the Translation view, where this strip is not
  // even up. So the one tool on it that belonged to the other view sat there
  // being armable from the wrong screen. lee: *"i wasnt you tpo make teh
  // select tool only be usable on the translation tab"*.
  //
  // Where it lives now is where it always also lived: the legend row above the
  // page on the Translation view carries the same button, off the same
  // `boxSel` state, so the S key and the button and the mode cannot disagree.
  // See `renderLegend` in panels.js.
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
    // A sound-effect tool lived here for a turn. It is gone: 3 sets a box to
    // a sound effect on the Translation view, and a mode that makes the next
    // drag come out sfx is a second way to do that with a mode to forget
    // about. lee: *"i dont want a button i wan to be able to clcik 3"*.
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
    // One healing brush, and it is the one that redraws. The other - the
    // local fill that copied real pixels in from nearby - is gone: lee,
    // having used it on his own pages, *"remoev teh regualr healing brush,
    // its ass"*. It could not invent artwork that was never there, which is
    // the only thing a healing brush is for once the Clean step has run.
    {k:'heal',   name:'Healing brush', icon:'healai',
     on:()=>toggleHeal(),
     lit:()=>typeof heal!=='undefined' && heal},
    // The region eraser, and it sits with the retouch tools because that is
    // what it is for: the cleaner got a spot wrong and you want the page back.
    // lee: *"make a region erreser tool that allow the user to use an erraser
    // on the regions taht weere clened to revelal the original page undernea
    // it"*.
    {k:'unclean', name:'Reveal the original (R)', icon:'reveal',
     on:()=>toggleUnclean(),
     lit:()=>typeof unclean!=='undefined' && unclean},
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
     // 100% means ACTUAL SIZE - one page pixel to one screen pixel. It used
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
   the same lit and unlit - a filled glyph on the accent colour disappears. */
const TB_ICON = {
  // A quadrilateral out of true, with its corners marked - what the tool
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
  sfx:'M12 3.2l1.9 3.6 4-1.1-1.1 4 3.6 1.9-3.6 1.9 1.1 4'
     +'-4-1.1L12 20.8l-1.9-3.6-4 1.1 1.1-4L3.6 12.4l3.6-1.9'
     +'-1.1-4 4 1.1Z',
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
  // "add" far more than it said "repair" - lee: *"make the icon better and
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
  // A corner of the page peeled back, with what is under it showing through:
  // an eraser rubbing a layer away rather than adding one.
  reveal:'M4 4h9.5L20 10.5V20H4Z M13.5 4v6.5H20'
        +'M7.6 16.8l4.4-4.4a1.6 1.6 0 0 1 2.3 0l1.8 1.8a1.6 1.6 0 0 1 0 2.3'
        +'L13.9 19H9.4l-1.8-1.8a.3.3 0 0 1 0-.4z',
  zoomin:'M10.6 4.6a6 6 0 1 1 0 12 6 6 0 0 1 0-12zM15 15l4.6 4.6M7.9 10.6h5.4M10.6 7.9v5.4',
  zoomout:'M10.6 4.6a6 6 0 1 1 0 12 6 6 0 0 1 0-12zM15 15l4.6 4.6M7.9 10.6h5.4',
};

function tbSvg(name){
  return `<svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true">`
    + `<path d="${TB_ICON[name]||''}" fill="none" stroke="currentColor"`
    + ` stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

/* Which tool each slot is showing - the last one used out of that slot. */
const tbChosen = {};
function tbArm(slot, key){
  const g = TOOLBOX.find(s=>s.slot===slot); if(!g) return;
  const t = g.tools.find(x=>x.k===key) || g.tools[0];
  tbChosen[slot] = t.k;
  try{ t.on(); }catch(e){}
  renderToolbar();
}

/* Double-clicking a tool does whatever that tool's second press means. The
   hand fits the page to the window, the way it does in Photoshop - lee:
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
  // Settings screens, and the Original view is where BOXES are managed - the
  // paint canvas is not even mounted there, so every tool in the strip was a
  // button that could be pressed and could not do anything.
  // lee: *"the side bar shoud only be visible on the edit tab"*.
  const show = (typeof tab==='undefined' || tab==='edit')
            && (typeof view==='undefined' || view==='typeset');
  el.style.display = show ? '' : 'none';
  if(!show) return;
  // Every tool, in its section, with a rule between the sections. The
  // sections ARE the old slots: the grouping was right, the lid on it was not.
  el.innerHTML = TOOLBOX.map(g=>g.tools.map(t=>{
    let lit=false; try{ lit=!!t.lit(); }catch(e){}
    // ONE tool is lit, and it is the one that is armed. lee: *"only one tool
    // sjou dbeselected at once and i dont now what this haft selection thing
    // is but remove it"*. With every tool on the strip there is nothing else
    // a mark could mean, which is the other half of why the slots opened up.
    return `<button class="tbtn${lit?' on':''}"
        data-slot="${g.slot}"
        data-tool="${t.k}" title="${t.name}"
        onclick="tbArm('${g.slot}','${t.k}')"
        ondblclick="tbDbl('${g.slot}','${t.k}')">${tbSvg(t.icon)}</button>`;
  }).join('')).join('<div class="tbsep" role="separator"></div>');
}


/* THE FLYOUT IS GONE, and with it `tbClose`, `tbFlyout`, the press-and-hold
   timer and the right-click handler. There is nothing left to open: every tool
   the toolbox has is on the toolbox. The `.tbflyout` and `.tbrow` rules stay in
   the stylesheet because the page menu and the box menu are dressed with
   them. */


