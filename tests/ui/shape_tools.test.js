/* The shape tools' state machine: one tool at a time, clicking the armed one
   again puts it away, and `paintArmed()` counts a shape as a tool. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const P0={index:0,name:'p',status:'cleaned',cleaned:true,regions:0,boxes:0,
          hidden_boxes:0,kinds:[],hidden:[]};
const PAGE={index:0,name:'p',width:200,height:120,regions:[],kinds:[],hidden:[],
  hidden_boxes:0,custom_clean:false,note:'',paint_layers:[]};
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>{
      if(/^\/api\/page\/\d+$/.test(url)) return {json:async()=>PAGE};
      return {json:async()=>({pages:[P0],settings:{},context:{},fonts:[]})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      ellipse(){},rect(){},save(){},restore(){},
      measureText:t=>({width:(t||'').length*8}),getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;
setTimeout(()=>{
  try{
    w.proj={pages:[P0],settings:{},context:{}};
    w.eval("cur=0; view='typeset'; regions=[];");
    w.renderInspector();          // builds the settings panel
    w.setToolTab('shapes');
    // The tools live in the toolbox down the left of the page now — one
    // place, always on screen. They used to be in the panel as WELL, so
    // every tool was on screen twice. lee: *"the tools are duplicated it
    // shoud only be onteh side bar"*. So the lit state is read from the
    // toolbox slot, not from a button in the panel.
    const lit = k => {
      const b = d.querySelector('#toolbox .tbtn[data-slot="shape"]');
      return !!b && b.classList.contains('on') && b.dataset.tool === k;
    };

    w.toggleShape('rect');
    console.log('rect armed:', w.eval('shapeKind'), 'brush:', w.eval('brush'));
    console.log('rect button lit:', lit('shrect'));
    w.toggleBrush(true);
    console.log('brush armed:', w.eval('brush?"brush":""'),
                'shape:', JSON.stringify(w.eval('shapeKind')));
    w.toggleShape('circle'); w.toggleShape('line');
    console.log('circle then line:', w.eval('shapeKind'));
    console.log('only one lit:', ['shrect','shcirc','shline']
      .filter(lit).join(','));
    console.log('armed with a shape:', w.paintArmed());
    w.toggleShape('line');
    console.log('clicking the armed one again:', JSON.stringify(w.eval('shapeKind')));
    console.log('armed with nothing:', w.paintArmed());
    w.toggleShape('rect');
    w.stopBrush();
    console.log('after stopBrush:', JSON.stringify(w.eval('shapeKind')));
    console.log('fill toggle:', (w.setShapeFill(true), w.eval('shapeFill')),
                (w.setShapeFill(false), w.eval('shapeFill')));
    process.exit(0);
  }catch(e){ console.log('ERROR', e && e.stack || e); process.exit(1); }
}, 60);
