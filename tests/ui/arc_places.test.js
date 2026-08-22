/* The browser's arc arithmetic, run against the Python's own answer.

   Two renderers draw curved typesetting - PIL for the exported page, the DOM for
   the editor - so there are two copies of the arc. The Python side writes its
   letter advances and its answer to a file; this reads the advances, feeds them
   to the browser's `arcPlaces` through a stubbed text measurer, and prints what
   it gets. `test_the_two_arcs_agree` compares them place by place. */
const {JSDOM}=require('jsdom');
const fs=require('fs');
const html=require('./load')();
const spec=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async()=>({json:async()=>({pages:[],settings:{},context:{},fonts:[]})});
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      // the real advances, measured by PIL, so both sides walk the same line
      measureText:t=>({width:spec.widths[t] !== undefined ? spec.widths[t]
                                                          : (t||'').length*8}),
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window;
setTimeout(()=>{
  try{
    const got=w.arcPlaces(spec.line, 'X', spec.size, spec.lspace, spec.curve,
                          spec.x, spec.y);
    console.log(JSON.stringify(got.map(p=>[+p.x.toFixed(3), +p.y.toFixed(3),
                                           +p.deg.toFixed(3), p.ch])));
    process.exit(0);
  }catch(e){ console.log('ERROR', e && e.stack || e); process.exit(1); }
}, 60);
