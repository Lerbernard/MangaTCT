/* Results -> Edit came back to an empty grey pane.

   The editing pane centres the page inside a wide pan border, so the middle
   of the scroll range is the only place the page is visible from. While
   another tab is up the stage is display:none, and a hidden scroll box has
   its scroll position reset to zero by the browser — on a pane like this one
   zero means the page is parked off in the corner. The hidden box also has no
   width, so a fit measured against it comes out of a zero-width container.

   So setTab('edit') has to do two things beyond unhiding the stage: measure
   the fit again now the pane has a width, and put the page back in the middle.
   Leaving for another tab must do neither — nothing is on screen to fit or to
   centre, and doing it there is what left a stale zero-width zoom behind. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const PAGE={index:0,name:'p',status:'cleaned',cleaned:true,regions:1};
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>{
      if(url==='/api/page/0')
        return {json:async()=>({index:0,name:'p',width:960,height:1365,
                                regions:[],custom_clean:false})};
      return {json:async()=>({pages:[PAGE],settings:{},context:{},fonts:[]})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;

setTimeout(async ()=>{
  try{
    w.proj={pages:[PAGE],settings:{},context:{}};
    w.regions=[]; w.cur=0; w.pageW=960; w.pageH=1365;

    // A page that has actually loaded: JSDOM images report 0 for both, and a
    // fit is deliberately not measured against a picture with no size.
    const img=d.getElementById('img');
    Object.defineProperty(img,'naturalWidth',{value:960,configurable:true});
    Object.defineProperty(img,'naturalHeight',{value:1365,configurable:true});

    // A pane with a real size, and a scroll range wider than it — the pan
    // border. JSDOM lays nothing out, so these are the numbers by hand.
    const wrap=d.getElementById('canvasWrap');
    for(const [k,v] of [['clientWidth',800],['clientHeight',600],
                        ['scrollWidth',2400],['scrollHeight',2000]])
      Object.defineProperty(wrap,k,{value:v,configurable:true});

    let refits=0, centres=0;
    const realFit=w.fitScale;
    w.fitScale=()=>{ refits++; return realFit.call(w); };
    w.centerPage=()=>{ centres++;
      wrap.scrollTop=(wrap.scrollHeight-wrap.clientHeight)/2;
      wrap.scrollLeft=(wrap.scrollWidth-wrap.clientWidth)/2; };

    // Away to Results. The browser resets a hidden box to the corner.
    // Results is shut until a chapter has been exported; this test is about
    // what coming back does, not about that gate.
    w.hasExports = true;
    w.setTab('results');
    console.log('leaving for results — refits:',refits,'recentres:',centres);
    wrap.scrollTop=0; wrap.scrollLeft=0;

    // ...and back.
    refits=0; centres=0;
    w.setTab('edit');
    const midT=(wrap.scrollHeight-wrap.clientHeight)/2;
    const midL=(wrap.scrollWidth -wrap.clientWidth )/2;
    const put=Math.abs(wrap.scrollTop-midT)<=2 && Math.abs(wrap.scrollLeft-midL)<=2;
    console.log('back on edit — refits:',refits,'recentres:',put);
    console.log('stage visible:', d.getElementById('stage').style.display);
    process.exit(0);
  }catch(e){ console.log('ERROR', e && e.stack || String(e)); process.exit(1); }
}, 60);
