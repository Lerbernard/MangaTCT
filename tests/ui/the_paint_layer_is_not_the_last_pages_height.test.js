/* The page sat 613 pixels above the top of the workspace, and the reason was
   an invisible canvas.

   lee, on the framing for the fourth time: *"try to fi the issue of teh image
   not being centered"*.

   Measured in a real browser rather than reasoned about. Every state was
   centred to the pixel — first paint, turning back to a page already seen, the
   Find text dialog open, Fit page, 2x, hiding the side panel, a page wider
   than the pane — except one:

     turned to the SHORT page   top −599  bottom 627   img 629x821 in 1002x849

   The paint layer is a <canvas> inside the stage, and `applyZoom` sized it
   with a CSS width and `height:auto`. `auto` takes the height from the
   canvas's own BITMAP aspect, and that bitmap is only resized when somebody
   paints. So on the page after a tall one it was still 690 by 3000, and 629
   CSS pixels wide at that aspect is 2735 tall — a 2735-tall invisible column
   in the stage behind an 821-tall picture.

   `centerPage` centres the STAGE. So it put the middle of that empty column in
   front of you, with the page scrolled off the top.

   Both dimensions come from the same authority the rest of `applyZoom` uses:
   `pageW`/`pageH`, what the SERVER said about the page open now, with the
   element as the fallback. */
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
function paintLayer(){
  let c=d.getElementById('paint');
  if(!c){
    c=d.createElement('canvas');
    c.id='paint';
    d.getElementById('stage').appendChild(c);
  }
  return c;
}

setTimeout(()=>{
  try{
    const set=src=>w.eval(src);
    const get=src=>w.eval(src);
    sizeWrap(1000,1000);
    set('zoom=1');

    /* The paint layer still carries the tall page's bitmap. This is the whole
       fixture: it is what `height:auto` would read. */
    const pc=paintLayer();
    pc.width=690; pc.height=3000;

    /* ...and we have turned to a short one. */
    elementStillShows(690,3000);          // the element lags too
    set('pageW=690; pageH=900');
    set('fitZoom='+get('fitScale()'));
    set('applyZoom()');

    const img=d.getElementById('img');
    const drawnW=parseFloat(img.style.width);
    const wantH=drawnW*900/690;

    if(pc.style.height==='auto'||!pc.style.height)
      throw new Error('the paint layer is still height:auto, so the stage '+
                      'keeps the last page’s height');
    const gotH=parseFloat(pc.style.height);
    if(Math.abs(gotH-wantH)>1)
      throw new Error('paint layer drawn '+gotH+'px tall, wanted '+
                      Math.round(wantH)+' — the picture is '+drawnW+
                      ' by '+Math.round(wantH));
    if(Math.abs(parseFloat(pc.style.width)-drawnW)>1)
      throw new Error('paint layer is '+pc.style.width+' wide, picture is '+
                      drawnW);

    /* It has to keep tracking the zoom, not just the first fit. */
    set('zoom=2; applyZoom()');
    const w2=parseFloat(img.style.width);
    if(Math.abs(parseFloat(pc.style.height)-w2*900/690)>1)
      throw new Error('the paint layer did not follow the zoom');

    /* And with nothing from the server yet, the element is still the
       fallback — a page opened before its record arrives must still draw. */
    set('zoom=1; pageW=0; pageH=0');
    elementStillShows(600,1200);
    set('fitZoom='+get('fitScale()'));
    set('applyZoom()');
    const w3=parseFloat(img.style.width);
    if(Math.abs(parseFloat(pc.style.height)-w3*1200/600)>1)
      throw new Error('the element should still stand in: '+pc.style.height);

    console.log('ok'); process.exit(0);
  }catch(e){ console.error(String(e && e.message || e)); process.exit(1); }
},0);
