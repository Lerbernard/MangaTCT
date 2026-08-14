/* Turning to a smaller page left it stuck at the top of the workspace.

   lee, third report and the one that named it:

     wheni swith to the next page its still keeping the old pages size,
     meanin that if the next page is smaller it gts stuck on top

   Two things decided how big the page is drawn, and both asked the <img>
   element:

     fitScale   const ph = d.naturalHeight || pageH
     applyZoom  const w  = img.naturalWidth * fitZoom * zoom

   `pageW`/`pageH` are what the SERVER said about the page that is open NOW,
   set the moment its record arrives. The element is a rendering of that page
   and lags behind it: while the next picture is still on the wire it still
   reports the LAST page's size. So every fit computed in that window is a fit
   for the page you just left, and on a shorter page the stage stays as tall as
   the old one — which puts the middle of the scroll range below the picture,
   and the picture at the top.

   Worse, and invisible: `applyZoom` took the width from the element and then
   divided it by `pageW` to get `scale`. Between pages those two describe
   different pictures, and `scale` is what every box is drawn with.

   The element is the fallback now. The server is the authority. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const dom=new JSDOM(html,{runScripts:'dangerously',
  url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async()=>({json:async()=>({pages:[],settings:{},context:{},
                                        fonts:[]})});
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;

function sizeWrap(cw,ch){
  const wrap=d.getElementById('canvasWrap');
  Object.defineProperty(wrap,'clientWidth',{value:cw,configurable:true});
  Object.defineProperty(wrap,'clientHeight',{value:ch,configurable:true});
}
function elementStillShows(nw,nh){
  const img=d.getElementById('img');
  Object.defineProperty(img,'naturalWidth',{value:nw,configurable:true});
  Object.defineProperty(img,'naturalHeight',{value:nh,configurable:true});
}

setTimeout(()=>{
  try{
    sizeWrap(1000,1000);
    /* `zoom`, `fitZoom`, `pageW` and `pageH` are `let` at the top level of a
       classic script, so they are NOT window properties -- `w.zoom = 1` makes
       an unrelated property and the real binding never moves. Direct eval in
       the global scope does reach them. Same trap as `let proj`. */
    const set=src=>w.eval(src);
    const get=src=>w.eval(src);
    set('zoom=1');

    /* The page we just left: 900 x 4000. Still the picture in the element.
       Different in WIDTH as well as height on purpose -- with the two pages
       the same width, reading the width off the element gives the same answer
       as reading it off the server and the mistake hides. */
    elementStillShows(900,4000);

    /* The page we just turned TO: 720 x 800, straight from the server. */
    set('pageW=720; pageH=800');

    const fit=get('fitScale()');
    const tall=Math.min((1000-28)/900,(1000-28)/4000,1);
    const shortPage=Math.min((1000-28)/720,(1000-28)/800,1);
    if(Math.abs(fit-tall)<1e-9)
      throw new Error('fitScale used the page we LEFT ('+fit+')');
    if(Math.abs(fit-shortPage)>1e-9)
      throw new Error('expected '+shortPage+', got '+fit);

    /* ...and the width actually applied, and the scale the boxes use. */
    set('fitZoom='+fit); set('applyZoom()');
    const img=d.getElementById('img');
    const want=Math.round(720*fit);
    if(Math.abs(parseFloat(img.style.width)-want)>0.5)
      throw new Error('drew it '+img.style.width+', wanted '+want+'px');
    /* scale is width-on-screen over page pixels. Taking the width from the
       element and dividing by pageW mixed two different pictures. */
    const sc=get('scale');
    if(Math.abs(sc-fit)>1e-9)
      throw new Error('scale is '+sc+', wanted '+fit);

    /* With nothing from the server yet, the element is still the fallback --
       a page opened before its record arrives must still draw. */
    set('pageW=0; pageH=0');
    elementStillShows(600,600);
    const fallback=get('fitScale()');
    if(Math.abs(fallback-Math.min((1000-28)/600,(1000-28)/600,1))>1e-9)
      throw new Error('the element should still stand in: '+fallback);

    /* ...and `scale` has to survive it. It used to be `w / pageW`, and with
       nothing from the server yet that is a divide by zero -- Infinity, which
       is then the number every box on the page is positioned with. Dividing
       by the width actually DRAWN cannot do that. */
    set('fitZoom='+fallback); set('applyZoom()');
    const sc2=get('scale');
    if(!isFinite(sc2)) throw new Error('scale came out '+sc2);
    if(Math.abs(sc2-fallback)>1e-9)
      throw new Error('fallback scale is '+sc2+', wanted '+fallback);

    console.log('ok'); process.exit(0);
  }catch(e){ console.error(String(e && e.message || e)); process.exit(1); }
},0);
