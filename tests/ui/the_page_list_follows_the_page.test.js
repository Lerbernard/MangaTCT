/* The page list follows the page you are on.

   lee: *"can you make teh side bar with th pages scroll so that teh current
   0age is alwsy in teh frame"*. On a 46-page chapter the list is far longer
   than the rail, so paging through walked the highlight off the bottom and
   the sidebar sat on page 1 while the canvas showed page 30.

   Two things are asserted here and they are different: that the CURRENT row
   is the one asked for, and that the ask is `block:'nearest'`. Nearest does
   nothing when the row is already visible — which is what stops a click on a
   row you can see from jerking the list out from under the pointer — and
   moves the least it can when the row is off the edge. `center` would scroll
   on every single redraw. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const PAGES=[];
for(let i=0;i<40;i++) PAGES.push({index:i,name:'p'+i,status:'',regions:0});

const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>{
      if(String(url).startsWith('/api/page/'))
        return {json:async()=>({index:0,name:'p0',width:100,height:100,
                                regions:[],custom_clean:false})};
      return {json:async()=>({pages:PAGES,settings:{},context:{},fonts:[]})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;
let bad=0;
const ok=(what,cond,got)=>{
  if(cond) console.log('ok   '+what);
  else { bad++; console.log('FAIL '+what+'  '+(got===undefined?'':got)); }
};

setTimeout(async ()=>{
  try{
    w.proj={pages:PAGES,settings:{},context:{}};
    w.regions=[];

    // jsdom has no scrollIntoView at all, so this doubles as the guard's
    // fixture: the calls are recorded, and an unguarded one would have
    // thrown inside the frame callback and stopped everything after it.
    const asked=[];
    w.HTMLElement.prototype.scrollIntoView=function(o){
      asked.push({el:this,opt:o}); };

    // `cur` is a module-level binding, not a window property — so the page
    // is changed the way the app changes it.
    w.eval('cur=30');
    w.renderPages();
    await new Promise(r=>w.setTimeout(r,30));

    const on=d.querySelector('#pages .pg.on');
    ok('the current page has a row', !!on, on&&on.dataset.i);
    ok('...and it is the page the canvas is on',
       on && on.dataset.i==='30', on&&on.dataset.i);
    ok('the list scrolled to exactly one row', asked.length===1, asked.length);
    ok('...and it was the current one', asked[0] && asked[0].el===on);
    ok('...asked for as nearest, not centred',
       asked[0] && asked[0].opt && asked[0].opt.block==='nearest',
       asked[0] && JSON.stringify(asked[0].opt));

    // Following the page means following it on every change, not once.
    asked.length=0;
    w.eval('cur=7');
    w.renderPages();
    await new Promise(r=>w.setTimeout(r,30));
    const on7=d.querySelector('#pages .pg.on');
    ok('a new page scrolls the list again',
       asked.length===1 && asked[0].el===on7 && on7.dataset.i==='7',
       asked.length+'/'+(on7&&on7.dataset.i));

    // A row being renamed holds a focused field. Scrolling the list under a
    // caret is how a rename loses its place, so the follow stands down.
    asked.length=0;
    const row=d.querySelector('#pages .pg.on');
    const inp=d.createElement('input');
    inp.className='nmedit';
    row.appendChild(inp);
    w.keepCurrentPageInView();
    await new Promise(r=>w.setTimeout(r,30));
    ok('a rename in progress is not scrolled away from',
       asked.length===0, asked.length);
    inp.remove();

    // No current page: nothing to follow, and nothing thrown either.
    asked.length=0;
    w.eval('cur=-1');
    w.renderPages();
    await new Promise(r=>w.setTimeout(r,30));
    ok('no current page scrolls nothing', asked.length===0, asked.length);

    // A browser without `scrollIntoView` — which is every jsdom, and the
    // reason `soon` exists in core.js. An unguarded call throws INSIDE the
    // frame callback, and everything after it in that frame never happens.
    // The list must still be drawn and the error must never be raised.
    const threw=[];
    w.addEventListener('error', e=>threw.push(String(e.message||e)));
    delete w.HTMLElement.prototype.scrollIntoView;
    w.eval('cur=12');
    w.renderPages();
    await new Promise(r=>w.setTimeout(r,30));
    ok('a browser with no scrollIntoView is not an error',
       threw.length===0, threw.join(' | '));
    ok('...and the list is drawn anyway',
       d.querySelectorAll('#pages .pg').length===40,
       d.querySelectorAll('#pages .pg').length);

    console.log(bad?(bad+' FAILED'):'all good');
    process.exit(bad?1:0);
  }catch(e){ console.log('THREW '+e); process.exit(1); }
}, 400);
