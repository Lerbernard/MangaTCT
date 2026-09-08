/* A page Find text will get wrong is marked where the pages are.

   lee: *"can you amke it so that teh pages that are tooo long have a red
   heighlight on te side bar"*. The warning on the Original view names them
   and stops at six ("+3 more"), so on his 40-page chapter it was a count and
   not a list: nine names to read off one panel and hunt down another.

   Three things have to hold, and each is a way this goes quietly wrong:

   * the mark is on the tall pages and NOT on the rest of them;
   * it uses the same rule the warning does, so a page cannot be named in one
     and unmarked in the other;
   * it survives being the current page and being ticked, because the row
     already spends its border and its background on those two. */
const {JSDOM}=require('jsdom');
const html=require('./load')();

// 40 pages: five of them strips, the rest ordinary. 690x4830 is 7 times
// taller than wide, past the 6 the server sends; 690x2760 is 4 and is not.
const PAGES=[];
for(let i=0;i<40;i++){
  const tall = (i===4 || i===6 || i===21 || i===22 || i===39);
  PAGES.push({index:i, name:'page'+String(i+1).padStart(3,'0')+'.png',
              status:'', regions:0,
              width:690, height:tall?4830:2760});
}
const TALL=PAGES.filter((p,i)=>[4,6,21,22,39].includes(i)).map(p=>p.name);

const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>{
      if(String(url).startsWith('/api/page/'))
        return {json:async()=>({index:0,name:'page001.png',width:690,
                                height:2760,regions:[],custom_clean:false})};
      return {json:async()=>({pages:PAGES,settings:{},context:{},fonts:[],
                              tall_aspect:6.0})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLElement.prototype.scrollIntoView=function(){};
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
const names=sel=>Array.from(d.querySelectorAll(sel))
  .map(e=>e.querySelector('.nm').textContent);

setTimeout(async ()=>{
  try{
    // `proj` is a module-level binding, not a window property, so it is
    // reached the way the app reaches it. It is already loaded - the fetch
    // above is the summary - and these tests change it in place.
    w.regions=[];
    w.eval('cur=0');
    w.renderPages();
    await new Promise(r=>w.setTimeout(r,30));

    ok('every page has a row',
       d.querySelectorAll('#pages .pg').length===40,
       d.querySelectorAll('#pages .pg').length);
    ok('the tall pages are marked',
       JSON.stringify(names('#pages .pg.tall'))===JSON.stringify(TALL),
       JSON.stringify(names('#pages .pg.tall')));
    ok('...and nothing else is',
       d.querySelectorAll('#pages .pg.tall').length===TALL.length,
       d.querySelectorAll('#pages .pg.tall').length);

    // THE SAME RULE THE WARNING USES. Two copies of the arithmetic is how a
    // page comes to be named in the sheet and unmarked in the rail.
    ok('the rail and the warning agree on which pages',
       JSON.stringify(w.tallPages().map(p=>p.name))===JSON.stringify(TALL),
       JSON.stringify(w.tallPages().map(p=>p.name)));

    // The row already spends its border on `.on` and its background on
    // `.sel`, which is why the mark is drawn as its own layer.
    w.eval('cur=4');
    w.renderPages();
    await new Promise(r=>w.setTimeout(r,30));
    const on=d.querySelector('#pages .pg.on');
    ok('the page you are looking at keeps its mark',
       on && on.classList.contains('tall'), on && on.className);
    ok('...and a ticked one does too',
       on && on.classList.contains('sel'), on && on.className);

    // ...and the tooltip says why, because a red bar with nothing behind it
    // is a thing to worry about rather than a thing to act on.
    const why=on.querySelector('.nm').getAttribute('title');
    ok('the mark carries its reason', /taller than wide/.test(why||''), why);
    ok('...and an ordinary page carries only its name',
       d.querySelector('#pages .pg:not(.tall) .nm').getAttribute('title')
         === PAGES[0].name,
       d.querySelector('#pages .pg:not(.tall) .nm').getAttribute('title'));

    // A PROJECT WITH NO LIMIT marks nothing. `tall_aspect` comes off the
    // server - it is `TALL_ASPECT` in detect/comictext.py, measured next to
    // the letterbox that causes it - and a summary from before it existed,
    // or one that failed to send it, must not paint the whole rail red.
    w.eval('proj.tall_aspect=0');
    w.renderPages();
    await new Promise(r=>w.setTimeout(r,30));
    ok('no limit from the server marks nothing',
       d.querySelectorAll('#pages .pg.tall').length===0,
       d.querySelectorAll('#pages .pg.tall').length);

    // ...and neither does a page whose size is not known yet. A page added
    // this second has a name and no dimensions until the summary comes back.
    w.eval('proj.tall_aspect=6.0');
    w.eval("proj.pages=[{index:0,name:'new.png',status:'',regions:0}]");
    w.renderPages();
    await new Promise(r=>w.setTimeout(r,30));
    ok('a page with no size yet is not marked',
       d.querySelectorAll('#pages .pg.tall').length===0,
       d.querySelectorAll('#pages .pg.tall').length);

    console.log(bad?(bad+' FAILED'):'all good');
    process.exit(bad?1:0);
  }catch(e){ console.log('THREW '+(e&&e.stack||e)); process.exit(1); }
}, 400);
