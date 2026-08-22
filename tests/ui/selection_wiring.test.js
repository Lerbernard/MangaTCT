/* Wiring test: the selection tools render in their own section of the tool
   panel, toggle like the paint tools do (mutually exclusive with them), the
   keyboard shortcuts land, and deselect clears. Canvas 2d is stubbed -
   pixel work is covered by select_logic.test.js and the browser e2e.

   The tools are in tabbed sections now, so only one section's buttons are in
   the DOM at a time: anything about a tool from ANOTHER section is asked of
   the state, not of a button that is not on screen. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>{
      if(url.startsWith('/api/page/0'))
        return {json:async()=>({index:0,name:'p',width:960,height:1365,
                                regions:[],custom_clean:false})};
      return {json:async()=>({pages:[{index:0,name:'p',status:'detected',regions:0}],
        settings:{},context:{},fonts:[]})};
    };
    const g={clearRect(){},beginPath(){},arc(){},fill(){},moveTo(){},lineTo(){},
      stroke(){},drawImage(){},fillRect(){},strokeRect(){},rect(){},closePath(){},
      save(){},restore(){},translate(){},rotate(){},scale(){},setLineDash(){},
      putImageData(){},
      createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),
      createLinearGradient:()=>({addColorStop(){}}),
      createRadialGradient:()=>({addColorStop(){}}),
      getImageData:(x,y,w,h)=>({data:new Uint8ClampedArray(w*h*4)}),
      set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){},
      set globalAlpha(v){}, set globalCompositeOperation(v){},
      set lineCap(v){}, set lineJoin(v){}, set lineDashOffset(v){},
      set imageSmoothingEnabled(v){}};
    w.HTMLCanvasElement.prototype.getContext=()=>g;
  }});
const w=dom.window,d=w.document;
let fails=0;
const ok=(cond,msg)=>{ console.log((cond?'ok  ':'FAIL'),msg);
                       if(!cond) fails++; };
setTimeout(async ()=>{
  try{
    w.proj={pages:[{index:0,name:'p',custom_clean:false}],settings:{},context:{}};
    w.regions=[]; w.cur=0;
    w.setView('typeset');
    await new Promise(r=>setTimeout(r,80));
    w.setToolTab('select');
    ok(d.getElementById('selRectBtn')&&d.getElementById('selLassoBtn')&&
       d.getElementById('selWandBtn')&&d.getElementById('selFillBtn')&&
       d.getElementById('xfBtn')&&d.getElementById('deselBtn'),
       'the Select & transform card renders all six buttons');
    // The hint line under these tools is gone - lee: *"remove all the pop up
    // explaiantion / tips, make teh sorfware clean and prfesioanal"*.
    ok(d.getElementById('selTolR'), 'the tolerance slider is there');
    ok(!d.getElementById('selHint'), 'the hint line is gone');

    // Top-level `let` state lives in the shared global lexical scope, not on
    // window - so every assertion here reads the DOM the tools drive.
    const lit=id=>d.getElementById(id).classList.contains('pri');

    w.toggleSelTool('rect');
    ok(lit('selRectBtn'), 'clicking the marquee arms it and lights it up');
    ok(d.getElementById('paint').style.pointerEvents==='auto',
       'the paint canvas takes the mouse while a selection tool is armed');
    ok(d.getElementById('paint').style.cursor==='crosshair',
       'selection tools use a crosshair cursor');

    w.toggleBrush(true);
    ok(w.eval('selTool')===null && w.eval('brush')===true,
       'arming the brush disarms the selection tool');
    ok(w.toolTab()==='paint',
       'and the panel follows it into the Paint section');
    w.toggleSelTool('wand');
    ok(w.eval('brush')===false && w.eval("selTool")==='wand',
       'arming a selection tool disarms the brush');
    ok(w.toolTab()==='select', 'and the panel comes back to Select');
    w.setToolTab('select');
    ok(d.getElementById('rowTol').style.display!=='none',
       'the wand shows the tolerance row');

    // keyboard: L switches to the lasso, Esc drops the tool
    w.dispatchEvent(new w.KeyboardEvent('keydown',{key:'l',bubbles:true}));
    ok(lit('selLassoBtn') && !lit('selWandBtn'), 'L arms the lasso');
    w.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    w.setToolTab('select');
    w.toggleSelTool('lasso');
    w.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    ok(!lit('selLassoBtn'), 'Esc puts the tool down');

    // tolerance sync keeps slider and number together, and clamps
    w.selTolSync(64);
    ok(d.getElementById('selTolR').value==='64'
       && d.getElementById('selTolN').value==='64',
       'tolerance stays in sync across the slider and the number box');
    w.selTolSync(999);
    ok(d.getElementById('selTolR').value==='128', 'tolerance clamps to its range');

    // a transform without a selection or picked layer politely refuses
    w.xfToggle();
    ok(!lit('xfBtn'), 'transform without anything to transform does not start');
  }catch(e){ console.log('ERROR:',e.message); process.exit(1); }
  process.exit(fails?1:0);
},400);
