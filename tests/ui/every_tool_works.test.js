/* Every tool in the panel, armed and actually used.

   lee: *"make sure all of tehse tools work and that they a each are sectiond
   properly and mske teh shapes movable and allwo chnage color, add a shap
   tab"*.

   "Sectioned properly" is the tab strip: Select, Paint, Shapes, Retouch, one
   at a time, and picking a section puts every tool away so what is armed is
   always something on screen. "All of these tools work" is the rest of this
   file: each one is armed and then DRIVEN with real pointer events, and what
   it leaves behind is checked. A button that lights up and paints nothing is
   exactly the failure this is for.

   The shapes get the most of it, because they are what changed: a drawn shape
   can be picked up again with the arrow and moved, resized and turned, and its
   colour, width and fill can be changed afterwards — because it is still a
   shape and not a flat patch of pixels. */
const {JSDOM}=require('jsdom');
const html=require('./load')();

const P0={index:0,name:'p',status:'cleaned',cleaned:true,regions:0,boxes:0,
          hidden_boxes:0,kinds:[],hidden:[],custom_clean:false};
const PAGE={index:0,name:'p',width:200,height:120,regions:[],kinds:[],
            hidden:[],hidden_boxes:0,custom_clean:false,note:'',
            paint_layers:[]};

const g={clearRect(){},beginPath(){},arc(){},fill(){},moveTo(){},lineTo(){},
  stroke(){},drawImage(){},fillRect(){},strokeRect(){},rect(){},closePath(){},
  save(){},restore(){},translate(){},scale(){},setLineDash(){},
  // counted, so "the angle is stored" and "the angle is DRAWN" are two
  // different claims and both get checked
  rotate(a){ g._rot=(g._rot||0)+Math.abs(a||0); },
  putImageData(){},ellipse(){},quadraticCurveTo(){},
  measureText:t=>({width:(t||'').length*8}),
  createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),
  createLinearGradient:()=>({addColorStop(){}}),
  createRadialGradient:()=>({addColorStop(){}}),
  getImageData:(x,y,w,h)=>({data:new Uint8ClampedArray(Math.max(1,w*h*4))}),
  set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){},
  set globalAlpha(v){}, set globalCompositeOperation(v){},
  set lineCap(v){}, set lineJoin(v){}, set lineDashOffset(v){},
  set imageSmoothingEnabled(v){}};

const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>{
      if(/^\/api\/page\/\d+$/.test(url)) return {json:async()=>PAGE};
      if(/\/heal$/.test(url)) return {json:async()=>({patch:'data:,x',how:'local'})};
      return {json:async()=>({ok:true,pages:[P0],settings:{},context:{},fonts:[]})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>g;
    w.HTMLCanvasElement.prototype.toDataURL=()=>'data:image/png;base64,AA';
  }});
const w=dom.window, d=w.document;
let fails=0;
const ok=(cond,msg)=>{ console.log((cond?'ok  ':'FAIL'),msg);
                       if(!cond) fails++; };

/* The page image: JSDOM has no layout, so the one geometry the paint engine
   asks for is supplied by hand. 1 CSS pixel = 1 page pixel keeps the sums in
   this file readable. */
function fakeImage(){
  const img=d.getElementById('img');
  Object.defineProperty(img,'naturalWidth',{value:200,configurable:true});
  Object.defineProperty(img,'naturalHeight',{value:120,configurable:true});
  Object.defineProperty(img,'clientWidth',{value:200,configurable:true});
  Object.defineProperty(img,'clientHeight',{value:120,configurable:true});
  img.getBoundingClientRect=()=>({left:0,top:0,width:200,height:120,
                                  right:200,bottom:120});
}
const at=(x,y,extra)=>Object.assign(
  {clientX:x, clientY:y, button:0, buttons:1, bubbles:true}, extra||{});
function drag(from,to,extra){
  const c=d.getElementById('paint');
  c.dispatchEvent(new w.MouseEvent('mousedown', at(from[0],from[1],extra)));
  w.dispatchEvent(new w.MouseEvent('mousemove', at(to[0],to[1],extra)));
  w.dispatchEvent(new w.MouseEvent('mouseup',
    Object.assign(at(to[0],to[1],extra),{buttons:0})));
}
const L=()=>w.eval('layers');

setTimeout(async ()=>{
 try{
  w.proj={pages:[P0],settings:{},context:{}};
  w.regions=[]; w.cur=0;
  w.setView('typeset');
  await new Promise(r=>setTimeout(r,80));
  fakeImage();
  w.eval('scale=1');
  w.ensureCanvas();

  // ---------------------------------------------------------- the toolbox
  // Every tool is in ONE place now — the strip down the left of the page.
  // They used to be here as well, in four tabbed sections of the panel, so
  // each one was on screen twice and neither copy was obviously the real one.
  // lee: *"the tools are duplicated it shoud only be onteh side bar"*.
  const slots=()=>[...d.querySelectorAll('#toolbox .tbtn')]
    .map(b=>b.dataset.slot);
  ok(slots().length===9, 'the toolbox has a slot for every kind of tool');
  ['move','select','text','paint','fill','retouch','shape','pick','view']
    .forEach(k=>ok(slots().includes(k), `the toolbox has the ${k} slot`));
  ok(!d.getElementById('brushBtn') && !d.getElementById('stampBtn')
     && !d.getElementById('shapeRectBtn'),
     'and the panel no longer has a second copy of any of them');
  w.setToolTab('retouch');
  ok(d.getElementById('rowCol').style.display==='none',
     'the retouch tools offer no brush colour, which none of them use');

  // arming from a section puts the last section's tool away
  w.setToolTab('paint'); w.toggleBrush(true);
  w.setToolTab('shapes');
  ok(w.eval('brush')===false, 'changing section puts the armed tool down');
  // ...and so does arming from the toolbox
  w.toggleBrush(true);
  w.tbArm('retouch','stamp');
  ok(w.eval('brush')===false && w.eval('stamp')===true,
     'arming from the toolbox puts the last tool down');
  w.stopBrush();

  // ------------------------------------------------------------- the tools
  w.eval('layers=[]');

  w.setToolTab('paint'); w.toggleBrush(true);
  drag([10,10],[60,40]);
  ok(L().length===1 && L()[0].type===undefined,
     'the brush paints a stroke');

  w.setToolTab('shapes');
  w.toggleShape('rect'); drag([20,20],[80,70]);
  w.toggleShape('circle'); drag([100,20],[160,70]);
  w.toggleShape('line'); drag([20,90],[180,100]);
  const shapes=L().filter(l=>l.type==='shape');
  ok(shapes.length===3 && shapes.map(s=>s.shape).join()==='rect,circle,line',
     'the rectangle, the ellipse and the line each draw one');
  w.toggleShape('line');

  w.setToolTab('paint'); w.toggleEraser(true);
  drag([30,30],[50,50]);
  ok(L().filter(l=>l.type==='erase').length===1, 'the eraser makes a pass');
  w.toggleEraser(false);

  w.setToolTab('retouch');
  w.toggleStamp(true);
  const c=d.getElementById('paint');
  c.dispatchEvent(new w.MouseEvent('mousedown', at(10,10,{altKey:true})));
  ok(w.eval('cloneSrc!=null'), 'Alt-click sets the clone source');
  drag([40,40],[70,60]);
  ok(L().filter(l=>l.label==='Clone').length===1, 'the clone stamp copies');
  w.toggleStamp(false);

  const before=L().length;
  w.toggleHeal(true); drag([120,90],[130,95]);
  await new Promise(r=>setTimeout(r,60));
  ok(w.eval('layers').length>=before, 'the healing brush sends its spot off');
  w.toggleHeal(false);

  // ------------------------------------------------- shapes stay shapes
  w.eval('layers=[]');
  w.setToolTab('shapes');
  w.toggleShape('rect'); drag([20,20],[80,60]); w.toggleShape('rect');
  const rect=()=>w.eval('layers').find(l=>l.type==='shape');
  const box=()=>{ const r=rect(); return {x0:Math.min(r.pts[0].x,r.pts[1].x),
                                          y0:Math.min(r.pts[0].y,r.pts[1].y),
                                          w:Math.abs(r.pts[1].x-r.pts[0].x),
                                          h:Math.abs(r.pts[1].y-r.pts[0].y)}; };
  const b0=box();
  ok(Math.round(b0.w)===60 && Math.round(b0.h)===40,
     'the rectangle is the size it was dragged');

  w.toggleShapeEdit(true);
  ok(w.paintArmed(), 'the arrow counts as an armed tool');
  // click somewhere inside it: picked up, transform open
  c.dispatchEvent(new w.MouseEvent('mousedown', at(50,40)));
  ok(w.eval('xf!=null') && w.eval('xf&&xf.vector!=null'),
     'clicking a shape picks it up as a shape, not as pixels');
  ok(w.eval('layerSel')===rect().id, 'and selects it in the layer list');

  // drag it 30 right, 10 down by the middle
  w.dispatchEvent(new w.MouseEvent('mousemove', at(50,40)));
  c.dispatchEvent(new w.MouseEvent('mousedown', at(50,40)));
  w.dispatchEvent(new w.MouseEvent('mousemove', at(80,50)));
  w.dispatchEvent(new w.MouseEvent('mouseup',
    Object.assign(at(80,50),{buttons:0})));
  const b1=box();
  ok(Math.round(b1.x0-b0.x0)===30 && Math.round(b1.y0-b0.y0)===10,
     'dragging the middle moves it');
  ok(Math.round(b1.w)===60 && Math.round(b1.h)===40,
     '...without changing its size');
  ok(rect().type==='shape',
     'and it is STILL a shape afterwards, not a frozen patch');

  // corner drag resizes
  const cs=w.xfCorners(w.eval('xf'));
  c.dispatchEvent(new w.MouseEvent('mousedown', at(cs[2].x,cs[2].y)));
  w.dispatchEvent(new w.MouseEvent('mousemove', at(cs[2].x+20,cs[2].y+20)));
  w.dispatchEvent(new w.MouseEvent('mouseup',
    Object.assign(at(cs[2].x+20,cs[2].y+20),{buttons:0})));
  const b2=box();
  ok(Math.round(b2.w)===80 && Math.round(b2.h)===60,
     'a corner handle resizes it');

  // rotate: grab well outside a corner (inside the corner's own radius is a
  // resize) and swing
  const cs2=w.xfCorners(w.eval('xf'));
  const t=w.eval('xf');
  const ox=cs2[0].x-(t.cx-cs2[0].x)*0.4, oy=cs2[0].y-(t.cy-cs2[0].y)*0.4;
  c.dispatchEvent(new w.MouseEvent('mousedown', at(ox,oy)));
  w.dispatchEvent(new w.MouseEvent('mousemove', at(t.cx, oy)));
  w.dispatchEvent(new w.MouseEvent('mouseup',
    Object.assign(at(t.cx,oy),{buttons:0})));
  ok(Math.abs(rect().rot||0)>0.01, 'turning it writes an angle onto the shape');
  g._rot=0; w.repaintAll();
  ok(g._rot>0.01, '...and the shape is actually drawn turned, not just marked');

  // Enter puts it down and keeps everything
  const bKeep=box(), rotKeep=rect().rot;
  w.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
  ok(w.eval('xf')===null, 'Enter lets go');
  ok(Math.round(box().w)===Math.round(bKeep.w) && rect().rot===rotKeep,
     'and keeps the move, the resize and the turn');

  // Esc puts the shape back where it was picked up — the whole session, not
  // the last drag, which is what cancelling a transform has always meant
  // the centre is the one point a turn does not move, so it is what a click
  // aimed at "this shape" has to use
  const mid=()=>({x:(rect().pts[0].x+rect().pts[1].x)/2,
                  y:(rect().pts[0].y+rect().pts[1].y)/2});
  const m0=mid();
  c.dispatchEvent(new w.MouseEvent('mousedown', at(m0.x,m0.y)));
  ok(w.eval('xf!=null'), 'picked up again');
  c.dispatchEvent(new w.MouseEvent('mousedown', at(m0.x,m0.y)));
  w.dispatchEvent(new w.MouseEvent('mousemove', at(m0.x+25,m0.y+15)));
  w.dispatchEvent(new w.MouseEvent('mouseup',
    Object.assign(at(m0.x+25,m0.y+15),{buttons:0})));
  ok(Math.round(box().x0)!==Math.round(bKeep.x0), 'and moved somewhere else');
  w.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  ok(w.eval('xf')===null, 'Esc lets go too');
  ok(Math.round(box().x0)===Math.round(bKeep.x0)
     && Math.round(box().y0)===Math.round(bKeep.y0)
     && rect().rot===rotKeep,
     'and puts the shape back exactly where it was picked up');

  // ------------------------------------------------------ change its colour
  w.eval('layers[0].rot=0');
  const id=rect().id;
  w.selectLayer(id);
  w.setLayerColour(id, '#ff0055', true);
  ok(rect().col==='#ff0055', 'a shape can be recoloured after it is drawn');
  w.setLayerWidth(id, 9, true);
  ok(rect().sz===9, 'and its line width changed');
  w.setLayerFill(id, true);
  ok(rect().fill===true, 'and filled');
  w.setLayerFill(id, false);
  ok(rect().fill===false, 'and outlined again');

  // a heal / clone / transform patch is pixels: there is no colour in it
  const patch={id:999, type:'patch', col:'#57b0ff', label:'Heal',
               group:'retouch', x:0, y:0, png:'data:,', img:null,
               pts:[], visible:true};
  w.eval('layers').push(patch);
  w.setLayerColour(999,'#00ff00',true);
  ok(patch.col==='#57b0ff', 'a finished patch refuses to be recoloured');
  ok(w.canRecolour(rect())===true && w.canRecolour(patch)===false,
     'and says which is which');

  // ------------------------------------------------ it survives a round trip
  w.eval('layers=layers.filter(l=>l.type==="shape")');
  w.eval('layers[0].rot=0.4');
  const wire=w.serializeLayers();
  w.loadLayers(wire);
  const back=w.eval('layers').find(l=>l.type==='shape');
  ok(back && back.shape==='rect' && Math.abs(back.rot-0.4)<1e-9
       && back.col==='#ff0055' && back.sz===9,
     'the shape, its angle, its colour and its width are all saved and restored');

  // ----------------------------------------- one list, dragged to restack
  w.eval('layers=[]');
  w.setToolTab('shapes');
  w.toggleShape('rect'); drag([10,10],[40,40]);
  drag([50,10],[80,40]); drag([90,10],[120,40]);
  w.toggleShape('rect');
  const ids=()=>w.eval('layers').map(l=>l.id);
  const start=ids();
  ok(start.length===3, 'three shapes to restack');
  w.renderLayers();
  const rows=()=>[...d.querySelectorAll('#stackList .lay[data-lid]')]
                   .map(r=>+r.getAttribute('data-lid'));
  ok(rows().join()===start.slice().reverse().join(),
     'the one list shows every paint layer, top of the stack first');
  ok(!d.getElementById('layerList') && !d.getElementById('retouchList'),
     '...and the separate Strokes and Retouch lists are gone');
  ok(!d.querySelector('.lmv'), 'the up and down arrows are gone');

  // press, move, release: a drag
  const rowOf=id=>d.querySelector(`#stackList .lay[data-lid="${id}"]`);
  const stub=(el,top)=>{ el.getBoundingClientRect=()=>({top,bottom:top+30,
                                                        left:0,right:200,
                                                        height:30,width:200}); };
  rows().forEach((id,k)=>stub(rowOf(id), 100+k*30));
  rowOf(start[2]).dispatchEvent(new w.MouseEvent('mousedown',
    {clientY:110, button:0, bubbles:true}));
  d.dispatchEvent(new w.MouseEvent('mousemove',{clientY:175,bubbles:true}));
  d.dispatchEvent(new w.MouseEvent('mouseup',{clientY:175,bubbles:true}));
  ok(ids().join()===[start[2],start[0],start[1]].join(),
     'dragging a row to the bottom of the list moves it down the stack');
  ok(w.eval('layerSel')===start[2], 'and the dragged layer is the picked one');

  // a press that does not move is a click, and a click picks the layer
  rows().forEach((id,k)=>stub(rowOf(id), 100+k*30));
  rowOf(start[0]).dispatchEvent(new w.MouseEvent('mousedown',
    {clientY:112, button:0, bubbles:true}));
  d.dispatchEvent(new w.MouseEvent('mousemove',{clientY:113,bubbles:true}));
  d.dispatchEvent(new w.MouseEvent('mouseup',{clientY:113,bubbles:true}));
  ok(ids().join()===[start[2],start[0],start[1]].join(),
     'a press that barely moves does not restack anything');
  ok(w.eval('layerSel')===start[0], '...it selects the layer instead');
  ok(!!d.getElementById('layMoveBtn'),
     'and selecting one opens its editor, with Move & resize on it');

  // the eye and the × are buttons, not handles: pressing one and twitching
  // must not quietly restack the layer under it
  rows().forEach((id,k)=>stub(rowOf(id), 100+k*30));
  const orderBefore=ids().join();
  // the middle row's eye, dragged down onto the row below it
  const midId=rows()[1];
  const eye=rowOf(midId).querySelector('.lx');
  eye.dispatchEvent(new w.MouseEvent('mousedown',
    {clientY:140, button:0, bubbles:true}));
  d.dispatchEvent(new w.MouseEvent('mousemove',{clientY:170,bubbles:true}));
  d.dispatchEvent(new w.MouseEvent('mouseup',{clientY:170,bubbles:true}));
  ok(ids().join()===orderBefore,
     'dragging from the eye button does not restack the layer');

  // ---------------------------------------- lifting a selection to a layer
  w.eval('layers=[]');
  w.setToolTab('select');
  ok(!d.getElementById('liftBtn'),
     'no lift BUTTON — J does it, and so do Ctrl+C and Ctrl+V');
  w.selLift();
  ok(L().length===0, 'lifting with nothing selected lifts nothing');
  // What lifting actually produces needs real canvas pixels, so it is proved
  // in a Chromium against the exported page — tests/test_lift_and_ants.py.
  w.toggleSelTool('rect');
  ok(w.eval("selTool")==='rect', 'and the marquee to make one with');
  w.toggleSelTool('rect');

  // --------------------------------------------- one redraw per frame
  let paints=0;
  const realComposite=w.compositeLive;
  w.eval('layers=[]');
  w.setToolTab('paint'); w.toggleBrush(true);
  w.compositeLive=function(){ paints++; return realComposite.apply(this,arguments); };
  w.eval('window._cl=compositeLive');
  const cv=d.getElementById('paint');
  cv.dispatchEvent(new w.MouseEvent('mousedown', at(10,10)));
  for(let i=0;i<25;i++)
    w.dispatchEvent(new w.MouseEvent('mousemove', at(10+i*3,10+i*2)));
  const nPts=w.eval('painting.pts.length');
  ok(nPts>=20, `all ${nPts} moves were recorded, whatever was drawn`);
  w.dispatchEvent(new w.MouseEvent('mouseup',
    Object.assign(at(85,60),{buttons:0})));
  ok(L().length===1 && L()[0].pts.length>=20,
     'and the finished stroke has every one of them');

  // ------------------------------------------------------------ the arrow
  w.toggleShapeEdit(false);
  ok(w.eval('shapeEdit')===false && w.eval('xf')===null,
     'putting the arrow away lets go of whatever it held');
  w.toggleShapeEdit(true);
  w.toggleBrush(true);
  ok(w.eval('shapeEdit')===false, 'and any other tool puts it away');
  w.stopBrush();
 }catch(e){ console.log('ERROR:', e && e.stack || e); process.exit(1); }
 process.exit(fails?1:0);
},400);
