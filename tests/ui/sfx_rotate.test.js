/* A sound effect arrives from the fitter already leaning, with no hand edit
   on it. Two things have to follow from that: the Rotation box has to show
   the angle the text is actually at, and the rotate buttons have to nudge
   from there rather than from zero. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>{
      if(url==='/api/page/0')
        return {json:async()=>({index:0,name:'p',width:200,height:200,
                                regions:[],custom_clean:false})};
      return {json:async()=>({pages:[{index:0,name:'p',status:'detected',
                                      regions:1}],
                              settings:{},context:{},fonts:[]})};
    };
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},save(){},
      restore(){},translate(){},rotate(){},fillText(){},strokeText(){},
      measureText:()=>({width:10}),getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;

// `regions` is a top-level `let`, which lives in the script's own scope and
// not on window - so it is set the way the page itself would set it.
const SFX={id:0,order:0,kind:'sfx',bbox:[10,10,80,140],
           bubble_bbox:[10,10,80,140],dst_text:'GRR',
           layout:{lines:['G','R','R'],font_size:30,leading:1.1,
                   origins:[[50,40],[50,80],[50,120]],rotate:22,
                   frame:[30,20,40,120],fit_ok:true}};
// A hand-set angle, the way the app actually holds one: `rotateBy` writes it
// into BOTH the override and the layout, because the layout is what gets drawn
// and what every field in the panel now reads. A fixture with the two
// disagreeing (layout 22, override -9) describes a state no code path can
// produce, and the panel used to read the override, so it hid the fact that a
// field reading the override is a field one save behind itself.
const HELD={id:1,kind:'sfx',bbox:[10,10,80,140],bubble_bbox:[10,10,80,140],
            layout:{lines:['A'],font_size:30,leading:1.1,origins:[[50,40]],
                    rotate:-9,fit_ok:true},
            layout_override:{rotate:-9,locked:true}};

setTimeout(async ()=>{
  try{
    w.eval(`regions=[${JSON.stringify(SFX)}]; cur=0;`);
    d.getElementById('inspector').innerHTML=w.typesettingPanel(SFX);
    console.log('field starts at:', d.getElementById('lyRot').value);

    // isolate the arithmetic: no canvas, no round trip
    w.drawOverlay=()=>{}; w.drawText=()=>{}; w.saveTypesetting=async()=>{};
    w.rotateBy(0,5);
    console.log('after +5:', d.getElementById('lyRot').value,
                'stored:', w.eval('regions[0].layout_override.rotate'));
    w.rotateBy(0,null);
    console.log('after reset:', d.getElementById('lyRot').value);

    // a hand-set angle still shows, and it survives the panel being rebuilt
    w.eval(`regions=[${JSON.stringify(HELD)}]; cur=0;`);
    d.getElementById('inspector').innerHTML=w.typesettingPanel(HELD);
    console.log('hand-set field:', d.getElementById('lyRot').value);
    // and setting one by hand puts it in both places, so a rebuild keeps it
    w.rotateBy(1,-3);
    d.getElementById('inspector').innerHTML=
      w.typesettingPanel(w.eval('regions[0]'));
    console.log('after -3 and a rebuild:', d.getElementById('lyRot').value,
                'stored:', w.eval('regions[0].layout_override.rotate'));
  }catch(e){ console.log('ERROR:', e.message); process.exit(1); }
  process.exit(0);
},400);
