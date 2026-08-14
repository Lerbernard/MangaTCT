/* The solid box on screen is the WRITING, not the balloon round it.

   lee sent two pages with rectangles the size of half a panel and said: "these
   bubbles are too big the detector shoud only try to find teh text not teh whole
   bubble". The detector was never the problem. Find text boxes the writing
   tightly and puts that in `bbox`; `attach_balloons` then works out the balloon
   the writing sits in and puts THAT in `bubble_bbox`, so the typesetter can spread
   English across the whole of the paper instead of down the narrow column the
   Japanese occupied. Two different rectangles, two different jobs — and the
   editor was drawing `bubble_bbox||bbox`, i.e. the balloon, as though it were
   the box the detector had found. A tall thin line of kana inside a wide oval
   therefore appeared as a wide oval-sized box with the writing in one corner.

   So the `.box` is `bbox`. For a while the balloon was also drawn, faint and
   dashed, as a `.bhint` behind it — a label saying "this is the room the English
   may use". lee, on meeting it around a box he was cleaning: *"there a thin
   dahed red box around the box around the text what does it do and remove it"*.
   It answered a question nobody was asking and read as a second box, so it is
   gone: `bubble_bbox` still does its job, it just does not draw itself. What is
   checked here now is that ONE rectangle is drawn per region, at the writing. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const PAGE={index:0,name:'p',status:'cleaned',cleaned:true,regions:3};
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

let bad=0;
function ok(name,cond,extra){
  console.log((cond?'ok   ':'FAIL ')+name+(extra!==undefined?'  '+extra:''));
  if(!cond) bad++;
}
const px=v=>Math.round(parseFloat(v));

setTimeout(()=>{
  try{
    // A tall column of Japanese inside a wide balloon — the shape lee
    // complained about. Region 1's balloon is the same rectangle as its
    // writing, which is what hand-typeset sound effects look like.
    const TALL={id:0,kind:'bubble',bbox:[400,200,60,300],
                bubble_bbox:[300,150,300,420],confidence:0.9};
    const SAME={id:1,kind:'sfx',bbox:[100,900,120,80],
                bubble_bbox:[100,900,120,80],confidence:0.9};
    w.eval("proj={pages:[{index:0,name:'p'}],settings:{},context:{}}");
    w.eval("view='original'; cur=0; scale=1; sel=null; selMulti=new Set()");
    d.getElementById('hideboxes').checked=false;

    const put=(rs)=>{ w.eval("regions="+JSON.stringify(rs)); w.drawBoxes(); };
    const boxes=()=>[...d.querySelectorAll('.box')];
    const hints=()=>[...d.querySelectorAll('.bhint')];

    put([TALL,SAME]);

    ok('a box is drawn for each region', boxes().length===2, boxes().length);
    const b0=boxes()[0];
    ok('the box sits at the WRITING, not the balloon',
       px(b0.style.left)===400 && px(b0.style.top)===200,
       b0.style.left+','+b0.style.top);
    ok('and is the size of the writing',
       px(b0.style.width)===60 && px(b0.style.height)===300,
       b0.style.width+'x'+b0.style.height);

    ok('nothing is drawn at the balloon rectangle', hints().length===0,
       hints().length);
    ok('and no rectangle anywhere is the balloon',
       boxes().every(b=>px(b.style.width)!==300 && px(b.style.height)!==420),
       boxes().map(b=>b.style.width+'x'+b.style.height).join(' '));

    // However much bigger the balloon is than the writing, it is not drawn.
    put([{id:0,kind:'bubble',bbox:[0,0,100,100],bubble_bbox:[0,0,110,110]}]);
    ok('a balloon barely bigger than the writing draws nothing extra',
       hints().length===0 && boxes().length===1, hints().length);
    put([{id:0,kind:'bubble',bbox:[0,0,100,100],bubble_bbox:[0,0,400,400]}]);
    ok('a balloon four times the writing draws nothing extra either',
       hints().length===0 && boxes().length===1, hints().length);
    ok('and the one box is still the writing',
       px(boxes()[0].style.width)===100, boxes()[0].style.width);

    // Scale: the box and the balloon must be drawn through the same zoom, or
    // they drift apart as you zoom in — which is exactly how the original bug
    // was hidden at small zooms and obvious at large ones.
    w.eval("scale=0.5");
    put([TALL]);
    ok('the box follows the zoom', px(boxes()[0].style.left)===200,
       boxes()[0].style.left);
    w.eval("scale=1");

    // Sections of one balloon used to get a solid frame drawn round the union
    // of them as well. lee, finding one on a burst holding two speeches:
    // *"there a big box with no label or anything"*, then *"hide teh big box
    // afterware it dosnt need to be visibel"*. It was the only thing on the
    // page with no number chip and nothing to click, and it said what the
    // sections' own dashed outlines already say. The GROUPING stays — it is
    // what dashes them — and the frame is gone, the same end the balloon
    // hint came to.
    put([{id:0,kind:'bubble',bbox:[400,200,60,120],
          bubble_bbox:[300,150,300,200],box_group:1},
         {id:1,kind:'bubble',bbox:[400,400,60,120],
          bubble_bbox:[300,380,300,200],box_group:1}]);
    ok('a two-section balloon draws no frame round the pair',
       d.querySelectorAll('.gbox').length===0,
       d.querySelectorAll('.gbox').length);
    ok('and still no balloon outlines', hints().length===0, hints().length);
    ok('each section still gets its own box', boxes().length===2, boxes().length);
    ok('and the sections are still marked as sections',
       [...boxes()].every(b=>b.classList.contains('section')),
       [...boxes()].map(b=>b.className).join(' | '));

    // Hide boxes hides the balloon outlines too. They were being left painted
    // over the page with nothing to explain them.
    put([TALL,SAME]);
    d.getElementById('hideboxes').checked=true;
    w.drawBoxes();
    ok('hiding the boxes leaves nothing painted over the page',
       boxes().length===0 && hints().length===0,
       boxes().length+'/'+hints().length);
    d.getElementById('hideboxes').checked=false;

    // Redrawing must not accumulate: every save and every zoom redraws.
    put([TALL,SAME]); put([TALL,SAME]); put([TALL,SAME]);
    ok('redrawing leaves two boxes, not a pile',
       boxes().length===2 && hints().length===0,
       boxes().length+'/'+hints().length);

    console.log(bad? bad+' FAILED' : 'all good');
    process.exit(bad?1:0);
  }catch(e){ console.log('THREW',e.stack); process.exit(1); }
},80);
