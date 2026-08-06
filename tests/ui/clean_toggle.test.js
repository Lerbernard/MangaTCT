const {JSDOM}=require('jsdom');
const html=require('./load')();
const calls=[];
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url,opt)=>{
      calls.push({url,body:opt&&opt.body?JSON.parse(opt.body):null});
      // minimal server: project, page, region update
      const body=opt&&opt.body?JSON.parse(opt.body):{};
      if(url.startsWith('/api/page/0/region/')){
        if('skip_clean' in body) REG[0].skip_clean=body.skip_clean;   // stateful
        return {json:async()=>({region:Object.assign({},REG[0]),
                                regions:REG.map(r=>Object.assign({},r))})};
      }
      if(url==='/api/page/0')
        return {json:async()=>({index:0,name:'p',width:960,height:1365,
                                regions:REG,custom_clean:false})};
      return {json:async()=>({pages:[{index:0,name:'p',status:'detected',regions:2}],
        settings:{},context:{},fonts:[]})};
    };
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},arc(){},
      fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;
const REG=[{id:0,order:0,kind:'bubble',bbox:[10,10,100,60],bubble_bbox:[10,10,100,60],
            confidence:.9,src_text:'あ',dst_text:'A',skip_clean:false},
           {id:1,order:1,kind:'bubble',bbox:[10,90,100,60],bubble_bbox:[10,90,100,60],
            confidence:.9,src_text:'い',dst_text:'B',skip_clean:false}];
setTimeout(async ()=>{
  try{
    w.proj={pages:[{index:0,name:'p',custom_clean:false}],settings:{},context:{}};
    w.regions=REG; w.cur=0;
    w.setView('clean');
    const eyes=[...d.querySelectorAll('.lay .lx')];
    console.log('cleaning rows rendered:', d.querySelectorAll('.lay').length,
                '| eye buttons:', eyes.length);
    if(!eyes.length){
      console.log('PANEL HTML:', (d.getElementById('inspector')||{}).innerHTML
        ? d.getElementById('inspector').innerHTML.slice(0,400) : '(no inspector)');
      process.exit(1);
    }
    calls.length=0;
    eyes[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
    await new Promise(r=>setTimeout(r,80));
    console.log('click 1 posts:', calls.filter(c=>c.url.includes('/region/')).map(c=>c.body));
    console.log('row now says :', d.querySelector('.lay span').textContent.trim());
    const eye2=d.querySelector('.lay .lx');
    calls.length=0;
    eye2.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
    await new Promise(r=>setTimeout(r,80));
    console.log('click 2 posts:', calls.filter(c=>c.url.includes('/region/')).map(c=>c.body));
    console.log('row after    :', d.querySelector('.lay span').textContent.trim());
  }catch(e){ console.log('ERROR:', e.message); process.exit(1); }
  process.exit(0);
},400);
