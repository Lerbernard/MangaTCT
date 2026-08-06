/* The show/hide switches in the Current page card.

   lee: "if i only select find speach bubble and outisde text i shoud only have
   teh option to hide tehm not option to hide sfx if i selected all 3 i shoud
   get the option to desleect all 3".

   So the switches offered are the ones there are boxes for — on THIS page
   normally, and across the chapter when "every page" is on, or a group could
   never be put away from a page that happens not to contain it. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const P0={index:0,name:'p0',status:'detected',regions:3,boxes:4,hidden_boxes:1,
          kinds:['bubble','freefloat','sfx'],hidden:['sfx']};
const P1={index:1,name:'p1',status:'detected',regions:2,boxes:2,hidden_boxes:0,
          kinds:['bubble','freefloat'],hidden:[]};
const posted=[];
let SETTINGS={hide_all_pages:false};
let PAGE={index:1,name:'p1',width:200,height:80,regions:[
    {id:0,kind:'bubble',bbox:[10,10,20,20],bubble_bbox:[10,10,20,20],order:0,
     confidence:0.9},
    {id:2,kind:'freefloat',bbox:[70,10,20,20],bubble_bbox:[70,10,20,20],order:2,
     confidence:0.9}],
  kinds:['bubble','freefloat'],hidden:[],hidden_boxes:0,custom_clean:false,
  note:'',paint_layers:[]};
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url,opt)=>{
      if(opt&&opt.body) posted.push([url,JSON.parse(opt.body)]);
      if(/^\/api\/page\/\d+$/.test(url)) return {json:async()=>PAGE};
      if(/\/hidden$/.test(url))
        return {json:async()=>({regions:PAGE.regions,hidden:PAGE.hidden,
                                kinds:PAGE.kinds,hidden_boxes:0,pages:2})};
      return {json:async()=>({pages:[P0,P1],settings:SETTINGS,context:{},
                              fonts:[]})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;
const labels=()=>[...d.querySelectorAll('#inspector .hopt')]
  .map(e=>e.textContent.trim().replace(/\s+/g,' '));

setTimeout(async ()=>{
  try{
    w.proj={pages:[P0,P1],settings:SETTINGS,context:{}};
    w.eval("cur=1; view='original'; regions="+JSON.stringify(PAGE.regions)+";"
      +"kindsHere=['bubble','freefloat']; hiddenKinds=[];");

    w.renderInspector();
    console.log('switches:', JSON.stringify(labels()));

    // all three present -> all three offered
    w.eval("kindsHere=['bubble','freefloat','sfx']; hiddenKinds=['sfx'];");
    w.renderInspector();
    console.log('with sfx:', JSON.stringify(labels()));
    const boxes=[...d.querySelectorAll('#inspector .hopt input')];
    console.log('sfx ticked:', boxes[2].checked, 'speech ticked:', boxes[0].checked);

    // "every page" off, so a page with no sound effects offers two
    w.eval("kindsHere=['bubble','freefloat']; hiddenKinds=[];");
    w.renderInspector();
    console.log('this page only:', labels().length);
    // ...and with it on the question is the chapter's
    SETTINGS.hide_all_pages=true; w.proj.settings=SETTINGS;
    w.renderInspector();
    console.log('every page:', labels().length);
    console.log('every-page box ticked:', d.getElementById('hideAllPages').checked);

    // unticking posts the group, with the every-page flag
    SETTINGS.hide_all_pages=false; w.proj.settings=SETTINGS;
    w.eval("kindsHere=['bubble','freefloat','sfx']; hiddenKinds=[];");
    w.renderInspector();
    await w.setKindShown('sfx', false);
    const p=posted.filter(x=>/\/hidden$/.test(x[0])).pop();
    console.log('posted:', JSON.stringify(p&&p[1]));

    // and the count line says how many are put away
    w.eval("cur=0; regions=[1,2,3];");
    w.renderInspector();
    console.log('count line:',
      /3 text boxes · 1 hidden/.test(d.getElementById('inspector').textContent));
    process.exit(0);
  }catch(e){ console.log('ERROR', e && e.stack || e); process.exit(1); }
}, 60);
