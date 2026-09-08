/* select.js - Photoshop-style selection (marquee / lasso / magic wand),
   bucket fill, free transform, and paste-as-layer for the paint engine.
   Split-file module. Classic script: shares globals with the other modules
   and must load in the order editor.html lists. No build step.

   Everything these tools produce is an ordinary 'patch' layer (an image at
   x,y) - the same shape the clone stamp and the heal tool already make - so
   undo, the layer list, hiding, deleting, and server sync all work on the
   new tools without any new plumbing. The selection itself is session-local,
   like in Photoshop: it constrains the brush, heal, clone and fill while it
   exists, and it is not saved with the project. */

/* ---- state ---- */
let selTool=null;            // null | 'rect' | 'lasso' | 'wand' | 'fill'
let selMask=null;            // page-resolution canvas; alpha>0 = selected
let selBBoxCache;            // undefined = stale, null = empty selection
/* Bumped every time the mask itself changes. The marching ants' edge ring is
   the expensive part of drawing them - four full-page composites - and it
   does NOT change between animation frames; only the stripes running through
   it do. Without this the ants cost a whole-page erosion eight times a
   second, on top of everything else, for as long as a selection exists. */
let selMaskVer=0;
let selShape=null;           // marquee / lasso being dragged right now
let selTol=32;               // wand + fill tolerance (max channel difference)
let selAnts=null, selAntsTimer=null, selPhase=0;
let xf=null;                 // free-transform session
let xfDrag=null;

/* =======================================================================
   Pure logic - no DOM. Kept separate so tests can run it in plain node.
   ======================================================================= */

/* Flood fill over RGBA pixel data from (sx,sy): every 4-connected pixel
   whose channels are all within `tol` of the START pixel joins. Returns a
   Uint8Array mask (1 = inside). The tolerance is against the seed colour,
   not the neighbour - that is what keeps a soft gradient from leaking the
   fill across the whole page. */
function floodMask(data,w,h,sx,sy,tol){
  const out=new Uint8Array(w*h);
  sx=Math.max(0,Math.min(w-1,sx|0)); sy=Math.max(0,Math.min(h-1,sy|0));
  const i0=(sy*w+sx)*4, r0=data[i0], g0=data[i0+1], b0=data[i0+2];
  const stack=[sy*w+sx];
  out[sy*w+sx]=1;
  while(stack.length){
    const p=stack.pop(), px=p%w, py=(p-px)/w;
    const cand=[p-1,p+1,p-w,p+w];
    for(let k=0;k<4;k++){
      const q=cand[k];
      if(q<0||q>=w*h) continue;
      if(k===0&&px===0) continue;          // stay on the row
      if(k===1&&px===w-1) continue;
      if(out[q]) continue;
      const j=q*4;
      if(Math.abs(data[j]-r0)<=tol && Math.abs(data[j+1]-g0)<=tol &&
         Math.abs(data[j+2]-b0)<=tol){ out[q]=1; stack.push(q); }
    }
  }
  return out;
}

/* Bounding box {x,y,w,h} of the set bytes in a mask, or null if empty. */
function maskBBox(mask,w,h){
  let x0=w,y0=h,x1=-1,y1=-1;
  for(let y=0;y<h;y++){
    const row=y*w;
    for(let x=0;x<w;x++) if(mask[row+x]){
      if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y;
    }
  }
  return x1<0 ? null : {x:x0,y:y0,w:x1-x0+1,h:y1-y0+1};
}

/* Free-transform maths. A session is {w,h,cx,cy,sx,sy,rot}: a w×h source
   image scaled by (sx,sy), rotated by rot, centred on (cx,cy). Corner order
   is TL,TR,BR,BL; edge-midpoint order is top,right,bottom,left. */
const XF_EX=[-1,1,1,-1], XF_EY=[-1,-1,1,1];
function xfCorners(t){
  // Distort: once a corner has been pulled on its own, the four corners ARE
  // the transform and there is no scale or angle left to read. Everything that
  // asks where the box is asks here, so the handles, the hit test, the dashed
  // outline and the warp all follow from this one line.
  if(t.quad) return t.quad.map(q=>({x:q.x, y:q.y}));
  const c=[],cos=Math.cos(t.rot),sin=Math.sin(t.rot);
  for(let i=0;i<4;i++){
    const lx=XF_EX[i]*t.w/2*t.sx, ly=XF_EY[i]*t.h/2*t.sy;
    c.push({x:t.cx+lx*cos-ly*sin, y:t.cy+lx*sin+ly*cos});
  }
  return c;
}

/* The box a shape actually occupies on the page: its two points, turned about
   their own middle by the shape's angle, plus half a line width all round. The
   raster paths below take a rectangle out of the page and a turned shape does
   not fit the one its two points describe. */
function xfShapeBox(l){
  const a=l.pts[0], b=l.pts[l.pts.length-1];
  const cx=(a.x+b.x)/2, cy=(a.y+b.y)/2;
  const co=Math.cos(l.rot||0), si=Math.sin(l.rot||0);
  const pad=(l.sz||1)/2+2;
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
  for(const [px,py] of [[a.x,a.y],[b.x,a.y],[b.x,b.y],[a.x,b.y]]){
    const dx=px-cx, dy=py-cy;
    const X=cx+dx*co-dy*si, Y=cy+dx*si+dy*co;
    x0=Math.min(x0,X); y0=Math.min(y0,Y);
    x1=Math.max(x1,X); y1=Math.max(y1,Y);
  }
  const cv=(typeof $==='function'&&$('paint')) ? $('paint') : {width:1e9,height:1e9};
  x0=Math.max(0,Math.floor(x0-pad)); y0=Math.max(0,Math.floor(y0-pad));
  x1=Math.min(cv.width, Math.ceil(x1+pad));
  y1=Math.min(cv.height,Math.ceil(y1+pad));
  return {x:x0, y:y0, w:Math.max(1,x1-x0), h:Math.max(1,y1-y0)};
}

/* ---- distort -----------------------------------------------------------

   Photoshop's free transform is one box with several behaviours hanging off
   modifier keys: drag a corner and it SCALES, hold Ctrl (Cmd) and that corner
   goes where you put it and the other three stay. lee: *"a trasform tool like
   photoshops cotolr + t tant allow e to move each coner of an image
   indpenedently"*.

   Freezing is the whole trick. A scale-and-rotate box cannot describe a
   quadrilateral, so the first Ctrl-drag writes down where the four corners
   are RIGHT NOW and from then on they are the state. Going back is not
   offered and should not be: there is no rotation to recover from a shape
   that no longer has one. */
function xfFreeze(t){
  if(!t.quad) t.quad = xfCorners(t);
  return t.quad;
}
/* Where a point inside the source lands, for u,v in [0,1] across the quad.
   Bilinear, which is what a free deform IS - a projective map is the other
   tool (Perspective) and would move the two corners you are not touching. */
function xfQuadPoint(q, u, v){
  const a=(1-u)*(1-v), b=u*(1-v), c=u*v, d=(1-u)*v;
  return {x:q[0].x*a+q[1].x*b+q[2].x*c+q[3].x*d,
          y:q[0].y*a+q[1].y*b+q[2].y*c+q[3].y*d};
}
/* The affine that carries source triangle s onto destination triangle d.
   Returned as canvas's [a,b,c,d,e,f]. Degenerate triangles give null - they
   have no inverse and drawing one is a divide by zero, not a thin sliver. */
function xfTriMatrix(s, d){
  const x1=s[1].x-s[0].x, y1=s[1].y-s[0].y;
  const x2=s[2].x-s[0].x, y2=s[2].y-s[0].y;
  const det=x1*y2-x2*y1;
  if(!det) return null;
  const u1=d[1].x-d[0].x, v1=d[1].y-d[0].y;
  const u2=d[2].x-d[0].x, v2=d[2].y-d[0].y;
  const a=(u1*y2-u2*y1)/det, b=(v1*y2-v2*y1)/det;
  const c=(u2*x1-u1*x2)/det, dd=(v2*x1-v1*x2)/det;
  return [a,b,c,dd, d[0].x-a*s[0].x-c*s[0].y, d[0].y-b*s[0].x-dd*s[0].y];
}
/* Push a triangle's corners out from its own middle. Neighbouring triangles
   are clipped to touching edges, and a clip is antialiased on both sides of
   that edge - so without this every seam in the mesh shows as a pale hairline
   across the picture. */
function xfGrow(tri, by){
  const cx=(tri[0].x+tri[1].x+tri[2].x)/3, cy=(tri[0].y+tri[1].y+tri[2].y)/3;
  return tri.map(p=>{
    const dx=p.x-cx, dy=p.y-cy, m=Math.hypot(dx,dy)||1;
    return {x:p.x+dx/m*by, y:p.y+dy/m*by};
  });
}
/* How finely the mesh is cut. A bilinear warp is not affine, so two triangles
   would draw a folded parallelogram rather than a deformed picture; the error
   falls off as the square of the cell size, and eight is where it stops being
   visible at any zoom the editor offers. */
const XF_MESH = 8;
function xfDrawQuad(g, t){
  const q=t.quad, src=t.src;
  if(!q || !src) return;
  const N=XF_MESH;
  for(let iy=0; iy<N; iy++){
    for(let ix=0; ix<N; ix++){
      const u0=ix/N, u1=(ix+1)/N, v0=iy/N, v1=(iy+1)/N;
      const s=[{x:u0*t.w,y:v0*t.h},{x:u1*t.w,y:v0*t.h},
               {x:u1*t.w,y:v1*t.h},{x:u0*t.w,y:v1*t.h}];
      const dq=[xfQuadPoint(q,u0,v0), xfQuadPoint(q,u1,v0),
                xfQuadPoint(q,u1,v1), xfQuadPoint(q,u0,v1)];
      for(const [i,j,k] of [[0,1,2],[0,2,3]]){
        const m=xfTriMatrix([s[i],s[j],s[k]], [dq[i],dq[j],dq[k]]);
        if(!m) continue;
        const clip=xfGrow([dq[i],dq[j],dq[k]], 0.5);
        g.save();
        g.beginPath();
        g.moveTo(clip[0].x,clip[0].y);
        g.lineTo(clip[1].x,clip[1].y);
        g.lineTo(clip[2].x,clip[2].y);
        g.closePath(); g.clip();
        g.transform(m[0],m[1],m[2],m[3],m[4],m[5]);
        g.drawImage(src,0,0);
        g.restore();
      }
    }
  }
}
function xfEdgeMids(t){
  const c=xfCorners(t);
  return [0,1,2,3].map(i=>({x:(c[i].x+c[(i+1)%4].x)/2,
                            y:(c[i].y+c[(i+1)%4].y)/2}));
}
/* Dragging corner i to page point p: the opposite corner stays anchored.
   Returns the new {sx,sy,cx,cy}. `uniform` keeps the proportions. */
function xfScaleFromCorner(t,i,p,uniform){
  const a=xfCorners(t)[(i+2)%4];
  const cos=Math.cos(-t.rot),sin=Math.sin(-t.rot);
  const dx=p.x-a.x, dy=p.y-a.y;
  const lx=dx*cos-dy*sin, ly=dx*sin+dy*cos;
  let sx=lx/(XF_EX[i]*t.w), sy=ly/(XF_EY[i]*t.h);
  if(uniform){
    const m=Math.max(Math.abs(sx),Math.abs(sy));
    sx=(sx<0?-m:m); sy=(sy<0?-m:m);
  }
  sx=clampScale(sx); sy=clampScale(sy);
  const hx=XF_EX[i]*t.w/2*sx, hy=XF_EY[i]*t.h/2*sy;
  const rcos=Math.cos(t.rot),rsin=Math.sin(t.rot);
  return {sx,sy, cx:a.x+hx*rcos-hy*rsin, cy:a.y+hx*rsin+hy*rcos};
}
/* Dragging edge-midpoint i: only that axis scales; the opposite edge stays. */
function xfScaleFromEdge(t,i,p){
  const a=xfEdgeMids(t)[(i+2)%4];
  const cos=Math.cos(-t.rot),sin=Math.sin(-t.rot);
  const dx=p.x-a.x, dy=p.y-a.y;
  const lx=dx*cos-dy*sin, ly=dx*sin+dy*cos;
  const r={sx:t.sx,sy:t.sy,cx:t.cx,cy:t.cy};
  const rcos=Math.cos(t.rot),rsin=Math.sin(t.rot);
  if(i===1||i===3){                                 // right / left edge: x axis
    const sgn=(i===1?1:-1);
    r.sx=clampScale(lx/(sgn*t.w));
    const hx=sgn*t.w/2*r.sx;
    r.cx=a.x+hx*rcos; r.cy=a.y+hx*rsin;
  }else{                                            // top / bottom edge: y axis
    const sgn=(i===2?1:-1);
    r.sy=clampScale(ly/(sgn*t.h));
    const hy=sgn*t.h/2*r.sy;
    r.cx=a.x-hy*rsin; r.cy=a.y+hy*rcos;
  }
  return r;
}
function clampScale(s){
  const m=0.02;
  return Math.abs(s)<m ? (s<0?-m:m) : s;
}
/* Is page point p inside the transformed rectangle? */
function xfInside(t,p){
  if(t.quad){
    // A distorted box is not a rotated rectangle any more, so "inside" is the
    // ordinary question about a polygon: cross the edges and count.
    const q=t.quad; let in_=false;
    for(let i=0,j=3;i<4;j=i++){
      const a=q[i], b2=q[j];
      if((a.y>p.y)!==(b2.y>p.y) &&
         p.x < (b2.x-a.x)*(p.y-a.y)/((b2.y-a.y)||1e-9)+a.x) in_=!in_;
    }
    return in_;
  }
  const cos=Math.cos(-t.rot),sin=Math.sin(-t.rot);
  const dx=p.x-t.cx, dy=p.y-t.cy;
  const lx=dx*cos-dy*sin, ly=dx*sin+dy*cos;
  return Math.abs(lx)<=Math.abs(t.sx)*t.w/2 && Math.abs(ly)<=Math.abs(t.sy)*t.h/2;
}

/* =======================================================================
   Selection mask
   ======================================================================= */
function selMaskCanvas(){
  const img=$('img');
  if(!img||!img.naturalWidth) return null;
  if(!selMask) selMask=document.createElement('canvas');
  if(selMask.width!==img.naturalWidth||selMask.height!==img.naturalHeight){
    selMask.width=img.naturalWidth; selMask.height=img.naturalHeight;
    selBBoxCache=undefined; selMaskVer++;
  }
  return selMask;
}
function selBBox(){
  if(selBBoxCache!==undefined) return selBBoxCache;
  if(!selMask||!selMask.width){ selBBoxCache=null; return null; }
  const g=selMask.getContext('2d');
  const d=g.getImageData(0,0,selMask.width,selMask.height).data;
  let x0=selMask.width,y0=selMask.height,x1=-1,y1=-1;
  for(let y=0;y<selMask.height;y++)
    for(let x=0;x<selMask.width;x++)
      if(d[(y*selMask.width+x)*4+3]>0){
        if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y;
      }
  selBBoxCache = x1<0 ? null : {x:x0,y:y0,w:x1-x0+1,h:y1-y0+1};
  return selBBoxCache;
}
function selHasMask(){ return !!selBBox(); }
function selDeselect(){
  if(selMask){ selMask.getContext('2d')
    .clearRect(0,0,selMask.width,selMask.height); }
  selBBoxCache=null; selMaskVer++; selShape=null;
  selToolUI(); selRedrawAnts();
}
/* mode: 'new' replaces, 'add' unions (Shift), 'sub' subtracts (Alt) */
function selCommitShape(shape,mode){
  const m=selMaskCanvas(); if(!m) return;
  const g=m.getContext('2d');
  if(mode==='new') g.clearRect(0,0,m.width,m.height);
  g.globalCompositeOperation = mode==='sub' ? 'destination-out' : 'source-over';
  g.fillStyle='#fff';
  g.beginPath();
  if(shape.kind==='rect'){
    const x=Math.min(shape.x0,shape.x1), y=Math.min(shape.y0,shape.y1);
    g.rect(x,y,Math.abs(shape.x1-shape.x0),Math.abs(shape.y1-shape.y0));
  }else{
    const q=shape.pts;
    g.moveTo(q[0].x,q[0].y);
    for(let i=1;i<q.length;i++) g.lineTo(q[i].x,q[i].y);
    g.closePath();
  }
  g.fill();
  g.globalCompositeOperation='source-over';
  selBBoxCache=undefined; selMaskVer++;
  selToolUI(); selAntsLoop();
}

function selWandAt(p,mode){
  const snap=cloneSnapshot();
  const w=snap.width,h=snap.height;
  const d=snap.getContext('2d').getImageData(0,0,w,h).data;
  const fm=floodMask(d,w,h,Math.round(p.x),Math.round(p.y),selTol);
  const t=document.createElement('canvas'); t.width=w; t.height=h;
  const g=t.getContext('2d');
  const id=g.createImageData(w,h);
  for(let i=0;i<fm.length;i++) if(fm[i]){
    id.data[i*4]=255; id.data[i*4+1]=255; id.data[i*4+2]=255; id.data[i*4+3]=255;
  }
  g.putImageData(id,0,0);
  const m=selMaskCanvas(); if(!m) return;
  const mg=m.getContext('2d');
  if(mode==='new') mg.clearRect(0,0,m.width,m.height);
  mg.globalCompositeOperation = mode==='sub' ? 'destination-out' : 'source-over';
  mg.drawImage(t,0,0);
  mg.globalCompositeOperation='source-over';
  selBBoxCache=undefined; selMaskVer++;
  selToolUI(); selAntsLoop();
}

/* =======================================================================
   Bucket fill - flood from the click, clipped to the selection if there is
   one, kept as a normal deletable layer.
   ======================================================================= */
function selFillAt(p){
  const snap=cloneSnapshot();
  const w=snap.width,h=snap.height;
  const d=snap.getContext('2d').getImageData(0,0,w,h).data;
  const fm=floodMask(d,w,h,Math.round(p.x),Math.round(p.y),selTol);
  const t=document.createElement('canvas'); t.width=w; t.height=h;
  const g=t.getContext('2d');
  const id=g.createImageData(w,h);
  const col=$('brushCol').value;
  const cr=parseInt(col.slice(1,3),16), cg=parseInt(col.slice(3,5),16),
        cb=parseInt(col.slice(5,7),16);
  for(let i=0;i<fm.length;i++) if(fm[i]){
    id.data[i*4]=cr; id.data[i*4+1]=cg; id.data[i*4+2]=cb; id.data[i*4+3]=255;
  }
  g.putImageData(id,0,0);
  if(selHasMask()){
    g.globalCompositeOperation='destination-in';
    g.drawImage(selMask,0,0);
    g.globalCompositeOperation='source-over';
  }
  let bb=maskBBox(fm,w,h); if(!bb) return;
  if(selHasMask()){
    const sb=selBBox();
    const x0=Math.max(bb.x,sb.x), y0=Math.max(bb.y,sb.y);
    const x1=Math.min(bb.x+bb.w,sb.x+sb.w), y1=Math.min(bb.y+bb.h,sb.y+sb.h);
    if(x1<=x0||y1<=y0) return;                   // fill fell entirely outside
    bb={x:x0,y:y0,w:x1-x0,h:y1-y0};
  }
  const cc=document.createElement('canvas'); cc.width=bb.w; cc.height=bb.h;
  cc.getContext('2d').drawImage(t, bb.x,bb.y,bb.w,bb.h, 0,0,bb.w,bb.h);
  const op=(+($('brushOp')&&$('brushOp').value)||100)/100;
  selPushPatch(cc, bb.x, bb.y, op, col, 'Fill');
}

/* ---- copy / paste ----
   Ctrl+C captures the selected pixels (kept here, and pushed to the system
   clipboard when the browser allows); Ctrl+V lands them as a new layer in
   the exact spot they came from, already in free transform. */
let selClipObj=null, _pasteHandled=false;
function selCopy(){
  const bb=selBBox(); if(!bb){ toast('Select something to copy first.'); return; }
  const snap=cloneSnapshot();
  const g=snap.getContext('2d');
  g.globalCompositeOperation='destination-in';
  g.drawImage(selMask,0,0);
  const cc=document.createElement('canvas'); cc.width=bb.w; cc.height=bb.h;
  cc.getContext('2d').drawImage(snap, bb.x,bb.y,bb.w,bb.h, 0,0,bb.w,bb.h);
  selClipObj={canvas:cc, x:bb.x, y:bb.y, size:0};
  cc.toBlob(async b=>{
    if(!b) return;
    selClipObj.size=b.size;
    try{ await navigator.clipboard.write([new ClipboardItem({'image/png':b})]); }
    catch(_){/* clipboard permission denied - the in-app copy still works */}
  },'image/png');
  toast('Selection copied - Ctrl+V pastes it as a new layer.');
}
/* Lift what is selected straight into its own layer - Photoshop's Ctrl+J.

   lee: *"with the select tool i shud be abke to copy a oiece o fthe image
   that i selcted and copy and paste it as a lyer that i can edit"*. Copy and
   paste already did this, but only through Ctrl+C then Ctrl+V, with nothing
   on screen to say so. This is one press: the pixels inside the selection -
   the page as it looks right now, artwork and paint together - become a layer
   sitting exactly where they came from, already picked up in the transform so
   the next thing you do is move it.

   The page underneath is untouched. It is a COPY, which is what makes it safe
   to try: hide it or delete it and the page is as it was. */
function selLift(){
  if(!selHasMask()){
    toast('Select a piece of the page first - marquee, lasso or wand.');
    return null;
  }
  const bb=selBBox();
  // EVERYTHING that is drawn there, including the band painted over the
  // typesetting - `cloneSnapshot` is the plate and the paint underneath only,
  // which is right for a clone stamp reading from beneath the text and wrong
  // here. lee, when the transform still took selections itself: *"the fre
  // tansfor too shoude be able to move everything when i slect it"*. The lift
  // is now the route that answers that, so it is the lift that has to flatten.
  const snap=flatSnapshot();
  const g=snap.getContext('2d');
  g.globalCompositeOperation='destination-in';
  g.drawImage(selMask,0,0);
  const cc=document.createElement('canvas');
  cc.width=bb.w; cc.height=bb.h;
  cc.getContext('2d').drawImage(snap, bb.x,bb.y,bb.w,bb.h, 0,0,bb.w,bb.h);
  ensureCanvas(); selEnsureHandlers();
  const st=selPushPatch(cc, bb.x, bb.y, 1, '#7fd7c4', 'Lifted piece');
  // The selection has done its job; leaving it up would fence the very tool
  // you are about to use on the new layer.
  selDeselect();
  layerSel=st.id;
  const tick=setInterval(()=>{ if(!st.img) return; clearInterval(tick);
                               xfStart(st); },60);
  setTimeout(()=>clearInterval(tick),3000);
  return st;
}

function selPasteInternal(){
  if(!selClipObj) return false;
  ensureCanvas(); selEnsureHandlers();
  const st=selPushPatch(selClipObj.canvas, selClipObj.x, selClipObj.y,
                        1, '#7fd7c4', 'Pasted selection');
  layerSel=st.id;
  selDeselect();          // the old selection is not what was just pasted
  const tick=setInterval(()=>{ if(!st.img) return; clearInterval(tick);
                               xfStart(st); },60);
  setTimeout(()=>clearInterval(tick),3000);
  return true;
}

/* Make a patch layer from a canvas and register it everywhere at once:
   layer list, history, live composite, server sync. */
function selPushPatch(cc,x,y,op,col,label){
  const png=cc.toDataURL('image/png');
  const st={id:layerSeq++, type:'patch', label, group:'drawing',
            col:col||'#8a8f98', sz:0,
            x, y, png, img:null, op, pts:[], visible:true};
  const im=new Image();
  im.onload=()=>{ st.img=im; repaintAll(); };
  im.src=png;
  // keep the screen right until the image decodes
  const L=layersBuf(), g=L.getContext('2d');
  g.globalAlpha=op==null?1:op; g.drawImage(cc,x,y); g.globalAlpha=1;
  compositeLive(null);
  layers.push(st); layerSel=st.id;
  record('paint', `${label} ${st.id}`, undoPaintLast);
  renderLayers(); queueSync();
  return st;
}

/* =======================================================================
   Hooks the paint engine calls (all optional there, all defined here)
   ======================================================================= */

/* Live preview of a stroke being drawn inside a selection. */
let _selClipTmp=null;
function selClipLive(buf){
  if(!selHasMask()) return null;
  if(!_selClipTmp) _selClipTmp=document.createElement('canvas');
  if(_selClipTmp.width!==buf.width||_selClipTmp.height!==buf.height){
    _selClipTmp.width=buf.width; _selClipTmp.height=buf.height;
  }
  const g=_selClipTmp.getContext('2d');
  g.clearRect(0,0,buf.width,buf.height);
  g.drawImage(buf,0,0);
  g.globalCompositeOperation='destination-in';
  g.drawImage(selMask,0,0);
  g.globalCompositeOperation='source-over';
  return _selClipTmp;
}

/* A finished brush / clone stroke, clipped to the selection and frozen to a
   patch layer (strokes replay from points; the selection may be long gone by
   then, so the clip has to be baked in now). */
function selBakeStroke(st){
  const c=$('paint');
  const b=document.createElement('canvas'); b.width=c.width; b.height=c.height;
  const g=b.getContext('2d');
  g.drawImage(st.buf,0,0);
  g.globalCompositeOperation='destination-in';
  g.drawImage(selMask,0,0);
  const xs=st.pts.map(p=>p.x), ys=st.pts.map(p=>p.y);
  const pad=st.sz/2+2, sb=selBBox();
  let x0=Math.max(0,Math.floor(Math.min(...xs)-pad), sb.x);
  let y0=Math.max(0,Math.floor(Math.min(...ys)-pad), sb.y);
  let x1=Math.min(c.width, Math.ceil(Math.max(...xs)+pad), sb.x+sb.w);
  let y1=Math.min(c.height,Math.ceil(Math.max(...ys)+pad), sb.y+sb.h);
  if(x1<=x0||y1<=y0){ x0=sb.x;y0=sb.y;x1=sb.x+1;y1=sb.y+1; }
  const cc=document.createElement('canvas');
  cc.width=Math.max(1,x1-x0); cc.height=Math.max(1,y1-y0);
  cc.getContext('2d').drawImage(b, x0,y0,cc.width,cc.height,
                                   0,0,cc.width,cc.height);
  const png=cc.toDataURL('image/png');
  const rep={id:st.id, type:'patch',
             label: st.type==='clone' ? 'Clone' : 'Brush stroke',
             group: st.type==='clone' ? 'retouch' : 'drawing',
             col:st.col, sz:st.sz, x:x0, y:y0, png, img:null,
             op:st.op, pts:st.pts, visible:true};
  const im=new Image();
  im.onload=()=>{ rep.img=im; repaintAll(); };
  im.src=png;
  const L=layersBuf(), lg=L.getContext('2d');
  lg.globalAlpha = st.op==null?1:st.op;
  lg.drawImage(b,0,0);
  lg.globalAlpha=1;
  compositeLive(null);
  return rep;
}

/* The heal request's mask, cut down to the selection. */
function selClipHealMask(mc,x0,y0){
  if(!selHasMask()) return;
  const g=mc.getContext('2d');
  g.globalCompositeOperation='destination-in';
  g.drawImage(selMask, x0,y0,mc.width,mc.height, 0,0,mc.width,mc.height);
  g.globalCompositeOperation='destination-over';
  g.fillStyle='#000'; g.fillRect(0,0,mc.width,mc.height);
  g.globalCompositeOperation='source-over';
}

/* Called by the paint tools when one of them switches on, and by
   stopBrush() when the view or tab changes. The selection mask survives -
   that is the point of selecting before painting - only the tool mode and
   any half-done transform stop. */
function selToolOff(){
  if(selTool){ selTool=null; selToolUI(); }
}
function selOnStopBrush(){
  xfCancel();
  selToolOff();
  selRedrawAnts();
}
/* Called by showPage - a selection belongs to one page. */
function selClear(){
  xfCancel();
  selShape=null; selTool=null;
  if(selMask) selMask.getContext('2d').clearRect(0,0,selMask.width,selMask.height);
  selBBoxCache=null; selMaskVer++;
  selToolUI(); selRedrawAnts();
}

/* =======================================================================
   Free transform
   ======================================================================= */
/* `mode` is 'distort' when the tool should come up with its corners already
   free - Ctrl+T. Without it the box behaves as it always has: corners scale,
   edges stretch, the ring outside a corner turns. */
function xfToggle(mode){ xf ? xfApply() : xfStart(null, mode); }

/* `want` names the layer to pick up. Without it the transform guesses: a live
   selection first, otherwise whatever is highlighted in the layer list - and
   after a paste both are true at once, so it floated the OLD selection's
   pixels while the new layer sat somewhere else entirely. Two copies on
   screen from one paste. lee: *"theer a duplicate copy at teh bottom right of
   teh screen theer shud only be one copy"*. Everything that has made a layer
   and wants it in your hands now says which one. */
function xfStart(want, mode){
  if(xf) return;
  // The paint canvas only lives in the Edit (typeset) view - setView() hides
  // it everywhere else; the Cleaned view shows strokes baked in server-side.
  if(view!=='typeset'){ toast('Free transform works in the Typeset view, '+
                              'where the paint tools live.'); return; }
  // transform keeps the selection MASK but puts every other tool away
  // (selToolOff clears only the tool mode, never the marching ants)
  disarmTools('xf');
  ensureCanvas(); selEnsureHandlers();
  let src=null, x=0, y=0, op=1, replacing=null;
  {
    // A SELECTION is not something to transform.
    //
    // It used to be: with a mask down, arming the tool copied everything
    // inside it out of the page and floated that copy, so letting go left the
    // moved pixels sitting on top of the ones they came from. From the
    // outside that is the tool duplicating your artwork every time you touch
    // it. lee: *"whn i use the selcet tool and with to the move tool it shoud
    // [n]ot automaticaly make a copy of teh selected area"*, and then, asked
    // which way it should go: *"it shoud do be able to move other dhape or
    // images that are on teh page, teh select too shoud just be there and do
    // nothing  no new image shoud be made until i hit copy and past"*.
    //
    // So the transform moves LAYERS - a shape, a stroke, a pasted picture -
    // and a selection is left to the things a selection is for: fencing the
    // brush, filling, and Ctrl+J / copy-and-paste, which are the two ways a
    // new layer is deliberately made.
    const l=want || layers.find(l=>l.id===layerSel && l.visible!==false);
    if(!l){ toast('The transform moves images and shapes - pick one in the '+
                  'layer list, or press J to lift a selection into its own '+
                  'layer first.'); return; }
    // A locked layer is not picked up either.
    if(l.locked){ toast('That layer is locked.'); return; }
    layerSel=l.id;
    // A shape moved by the ordinary transform stays a shape - two points and
    // an angle, nothing baked. Pulled OUT OF TRUE it cannot: a record that
    // holds two corners cannot hold four. So distort rasterises it first, the
    // way Photoshop does when a vector layer is handed to a warp, and undo
    // puts the shape back because the patch REPLACES it rather than joining
    // it. lee: *"it shoud only work on images and shapes not text"* - shapes
    // are in, and this is the price of their being in.
    if(l.type==='shape' && mode==='distort'){
      const cv=$('paint');
      const b2=document.createElement('canvas');
      b2.width=cv.width; b2.height=cv.height;
      replayStroke(b2, {...l, op:1});
      const box=xfShapeBox(l);
      src=document.createElement('canvas');
      src.width=Math.max(1,box.w); src.height=Math.max(1,box.h);
      src.getContext('2d').drawImage(b2, box.x,box.y,box.w,box.h,
                                         0,0,box.w,box.h);
      x=box.x; y=box.y; op=l.op==null?1:l.op;
      replacing=l;
      l.visible=false; repaintAll();
      xf={src, w:src.width, h:src.height,
          cx:x+src.width/2, cy:y+src.height/2,
          sx:1, sy:1, rot:0, op, replacing};
      xfFreeze(xf);
      selTool=null;
      const cc=$('paint');
      cc.style.pointerEvents='auto'; cc.style.cursor='move';
      selToolUI(); selAntsLoop();
      return;
    }
    if(l.type==='shape'){
      // A shape is moved as a SHAPE. Everything below rasterises the layer
      // and hands the pixels to the transform, which is right for a brush
      // stroke and wrong for a rectangle: it freezes the colour, the width
      // and the fill into a flat patch, and the shape stops being editable
      // the first time you nudge it. Here the same handles drive the two
      // points and the angle instead, and nothing is ever baked.
      const a=l.pts[0], b=l.pts[l.pts.length-1];
      const w=Math.max(1,Math.abs(b.x-a.x)), h=Math.max(1,Math.abs(b.y-a.y));
      // Everything EXCEPT this shape, flattened once, so a drag repaints one
      // shape over a picture instead of replaying the whole layer stack for
      // every frame. On a page with a dozen layers that is the difference
      // between a shape that follows the pointer and one that trails it.
      const wasVis=l.visible;
      l.visible=false; repaintAll(); l.visible=wasVis;
      const rest=document.createElement('canvas');
      const lb=layersBuf();
      rest.width=lb.width; rest.height=lb.height;
      rest.getContext('2d').drawImage(lb,0,0);
      xf={vector:l, src:null, w, h, rest,
          cx:(a.x+b.x)/2, cy:(a.y+b.y)/2, sx:1, sy:1, rot:l.rot||0,
          op:l.op==null?1:l.op, replacing:null,
          // a line runs FROM its first point TO its second: keep which way
          // round it goes, or dragging it flips the arrow end over end
          sgn:{x:Math.sign(b.x-a.x)||1, y:Math.sign(b.y-a.y)||1},
          was:{pts:l.pts.map(q=>({x:q.x,y:q.y})), rot:l.rot||0}};
      selTool=null;
      // Put the shape back on screen.
      //
      // `rest` above is the stack WITHOUT this shape, and building it leaves
      // the canvas in that state - so from the moment the transform was armed
      // until the first drag frame, the shape you had just drawn was not on
      // the page at all. It came back when you clicked it, because a click is
      // a drag frame. lee: *"when i make e shape and clcik the freen transform
      // tool it dissapears aand reaapers when i clcik on it"*. One honest
      // replay costs a frame and is the difference between a tool that picks
      // a shape up and one that appears to delete it.
      repaintAll();
      const cc=$('paint');
      cc.style.pointerEvents='auto'; cc.style.cursor='move';
      selToolUI(); selAntsLoop();
      return;
    }
    if(l.type==='patch'){
      if(!l.img){ toast('That layer is still loading - try again.'); return; }
      src=document.createElement('canvas');
      src.width=l.img.naturalWidth||l.img.width;
      src.height=l.img.naturalHeight||l.img.height;
      src.getContext('2d').drawImage(l.img,0,0);
      x=l.x; y=l.y; op=l.op==null?1:l.op;
    }else{
      // a brush stroke: render it once at full strength, transform the pixels
      const c=$('paint');
      const full={...l, op:1};
      const b=document.createElement('canvas'); b.width=c.width; b.height=c.height;
      replayStroke(b, full);
      const pad=l.sz/2+2;
      const xs=l.pts.map(p=>p.x), ys=l.pts.map(p=>p.y);
      const x0=Math.max(0,Math.floor(Math.min(...xs)-pad));
      const y0=Math.max(0,Math.floor(Math.min(...ys)-pad));
      const x1=Math.min(c.width, Math.ceil(Math.max(...xs)+pad));
      const y1=Math.min(c.height,Math.ceil(Math.max(...ys)+pad));
      src=document.createElement('canvas');
      src.width=Math.max(1,x1-x0); src.height=Math.max(1,y1-y0);
      src.getContext('2d').drawImage(b, x0,y0,src.width,src.height,
                                        0,0,src.width,src.height);
      x=x0; y=y0; op=l.op==null?1:l.op;
    }
    replacing=l;
    l.visible=false; repaintAll();
  }
  xf={src, w:src.width, h:src.height,
      cx:x+src.width/2, cy:y+src.height/2,
      sx:1, sy:1, rot:0, op, replacing};
  if(mode==='distort') xfFreeze(xf);
  selTool=null;
  const c=$('paint');
  c.style.pointerEvents='auto'; c.style.cursor='move';
  selToolUI(); selAntsLoop();
}

/* Write the transform back onto the shape it belongs to. Called on every
   drag, so the shape itself is what you see moving - no ghost, no baked
   preview, and letting go is simply the last of these. */
function xfSyncVector(){
  const t=xf; if(!t||!t.vector) return;
  const l=t.vector;
  const w=Math.abs(t.w*t.sx), h=Math.abs(t.h*t.sy);
  const sx=t.sgn.x*(t.sx<0?-1:1), sy=t.sgn.y*(t.sy<0?-1:1);
  // The geometry is written straight away - everything that asks where the
  // shape is must get today's answer, not last frame's. Only the DRAWING
  // waits for a frame.
  l.pts=[{x:t.cx-sx*w/2, y:t.cy-sy*h/2},
         {x:t.cx+sx*w/2, y:t.cy+sy*h/2}];
  l.rot=t.rot||0;
  onFrame('vector', ()=>{
    // `rest` is the flattened stack as the PAGE has it. With a family folded
    // away the screen shows less than that, so the shortcut would draw the
    // hidden family back in under the pointer; do the honest replay instead.
    if(xf!==t || !t.rest || (typeof _folded==='function' && _folded())){
      repaintAll(); return;
    }
    const L=layersBuf(), g=L.getContext('2d');
    g.clearRect(0,0,L.width,L.height);
    g.drawImage(t.rest,0,0);
    if(l.visible!==false) replayStroke(L, l);
    compositeLive(null);
  });
}

function xfApply(){
  const t=xf; if(!t) return;
  if(t.vector){
    xfSyncVector();
    flushFrame();                    // the last frame of the drag, drawn now
    const l=t.vector, was=t.was;
    xf=null; xfDrag=null;
    repaintAll();                    // …and back to the honest full replay
    const moved = l.rot!==was.rot ||
      l.pts.some((q,k)=>!was.pts[k] ||
                 Math.abs(q.x-was.pts[k].x)>0.01 ||
                 Math.abs(q.y-was.pts[k].y)>0.01);
    if(moved){
      record('paint', `${layerName(l)} moved`, ()=>{
        l.pts=was.pts.map(q=>({x:q.x,y:q.y})); l.rot=was.rot;
        repaintAll(); renderLayers(); queueSync();
      });
      renderLayers(); queueSync();
    }
    selAfterXf();
    return;
  }
  const c=$('paint');
  const b=document.createElement('canvas'); b.width=c.width; b.height=c.height;
  const g=b.getContext('2d');
  if(t.quad){
    xfDrawQuad(g, t);
  }else{
    g.translate(t.cx,t.cy); g.rotate(t.rot); g.scale(t.sx,t.sy);
    g.drawImage(t.src,-t.w/2,-t.h/2);
  }
  const cs=xfCorners(t);
  const x0=Math.max(0,Math.floor(Math.min(...cs.map(p=>p.x))));
  const y0=Math.max(0,Math.floor(Math.min(...cs.map(p=>p.y))));
  const x1=Math.min(c.width, Math.ceil(Math.max(...cs.map(p=>p.x))));
  const y1=Math.min(c.height,Math.ceil(Math.max(...cs.map(p=>p.y))));
  xf=null; xfDrag=null;
  if(x1<=x0||y1<=y0){ xfRestore(t); selAfterXf(); return; }   // pushed off-page
  const cc=document.createElement('canvas'); cc.width=x1-x0; cc.height=y1-y0;
  cc.getContext('2d').drawImage(b, x0,y0,cc.width,cc.height, 0,0,cc.width,cc.height);
  const png=cc.toDataURL('image/png');
  const st={id:layerSeq++, type:'patch', label:'Transform', group:'drawing',
            col:'#c9a2ff', sz:0, x:x0, y:y0, png, img:null,
            op:t.op, pts:[], visible:true};
  const im=new Image();
  im.onload=()=>{ st.img=im; repaintAll(); };
  im.src=png;
  const repl=t.replacing;
  if(repl){
    const idx=layers.indexOf(repl);
    if(idx>=0) layers.splice(idx,1);
    layers.push(st); layerSel=st.id;
    record('paint', `Layer ${repl.id} transformed`, ()=>{
      layers=layers.filter(l=>l!==st);
      repl.visible=true;
      layers.splice(Math.min(idx<0?layers.length:idx,layers.length),0,repl);
      layerSel=repl.id;
      repaintAll(); renderLayers(); queueSync();
    });
  }else{
    layers.push(st); layerSel=st.id;
    record('paint', `Transformed selection ${st.id}`, undoPaintLast);
  }
  const L=layersBuf(), lg=L.getContext('2d');
  lg.globalAlpha=t.op==null?1:t.op; lg.drawImage(b,0,0); lg.globalAlpha=1;
  compositeLive(null);
  renderLayers(); queueSync();
  selAfterXf();
}
function xfCancel(){
  const t=xf; if(!t) return;
  xf=null; xfDrag=null;
  xfRestore(t);
  selAfterXf();
}
function xfRestore(t){
  if(t.vector){
    t.vector.pts=t.was.pts.map(q=>({x:q.x,y:q.y}));
    t.vector.rot=t.was.rot;
    repaintAll();
    return;
  }
  if(t.replacing){ t.replacing.visible=true; repaintAll(); }
}
function selAfterXf(){
  const c=$('paint');
  // `paintArmed()` and not a hand-written list: the shape arrow is a tool
  // that needs the canvas, and letting go of one shape must not take the
  // pointer away before the next one can be clicked.
  if(c && !paintArmed() && !selTool){
    c.style.pointerEvents='none'; c.style.cursor='';
  }else if(c){ c.style.cursor = selTool ? 'crosshair'
    : (typeof shapeEdit!=='undefined' && shapeEdit) ? 'default' : c.style.cursor; }
  selToolUI(); selRedrawAnts();
}

function xfHandleAt(p){
  const t=xf; if(!t) return null;
  const hs=8/Math.max(scale,0.01);                  // hit radius, page units
  const cs=xfCorners(t);
  for(let i=0;i<4;i++)
    if(Math.hypot(p.x-cs[i].x,p.y-cs[i].y)<=hs) return {type:'corner',i};
  const es=xfEdgeMids(t);
  for(let i=0;i<4;i++)
    if(Math.hypot(p.x-es[i].x,p.y-es[i].y)<=hs) return {type:'edge',i};
  for(let i=0;i<4;i++)
    if(Math.hypot(p.x-cs[i].x,p.y-cs[i].y)<=hs*3 && !xfInside(t,p))
      return {type:'rotate',i};
  if(xfInside(t,p)) return {type:'move'};
  return null;
}

/* =======================================================================
   Mouse + keyboard
   ======================================================================= */
function selEnsureHandlers(){
  if(selEnsureHandlers._done) return;
  selEnsureHandlers._done=true;
  const c=$('paint');
  c.addEventListener('mousedown',selDown);
  window.addEventListener('mousemove',selMove);
  window.addEventListener('mouseup',selUp);
}

function selDown(e){
  if(e.button!==0) return;
  if(xf){
    const p=canvasPt(e);
    const h=xfHandleAt(p);
    if(h){
      e.preventDefault(); e.stopPropagation();
      xfDrag={h, start:p, t0:{...xf},
              t0q:xf.quad?xf.quad.map(q=>({x:q.x,y:q.y})):null,
              a0:Math.atan2(p.y-xf.cy,p.x-xf.cx)};
    }
    return;
  }
  if(!selTool) return;
  e.preventDefault(); e.stopPropagation();
  const p=canvasPt(e);
  const mode=e.shiftKey?'add':(e.altKey?'sub':'new');
  if(selTool==='rect') selShape={kind:'rect',x0:p.x,y0:p.y,x1:p.x,y1:p.y,mode};
  else if(selTool==='lasso') selShape={kind:'lasso',pts:[p],mode};
  else if(selTool==='wand'){ selWandAt(p,mode); }
  else if(selTool==='fill'){ selFillAt(p); }
  if(selShape) selAntsLoop();
}
function selMove(e){
  if(xfDrag){
    const p=canvasPt(e), d=xfDrag, t0=d.t0;
    if(d.h.type==='move'){
      xf.cx=t0.cx+(p.x-d.start.x); xf.cy=t0.cy+(p.y-d.start.y);
      // A distorted box has no centre-and-scale left to move: the corners are
      // the state, so they are what travels.
      if(xf.quad && d.t0q)
        xf.quad=d.t0q.map(q=>({x:q.x+(p.x-d.start.x), y:q.y+(p.y-d.start.y)}));
    }else if(d.h.type==='corner'){
      // Ctrl (Cmd on a Mac) is Photoshop's distort modifier: this corner goes
      // where you put it and the other three stay where they are.
      // ...and only where there are pixels to bend. A shape transform moves
      // the shape's own two points and its angle; there is no rectangle of
      // pixels to pull out of true, and pretending otherwise would write a
      // quadrilateral into a record that can only hold a box.
      if((e.ctrlKey||e.metaKey||xf.quad) && xf.src){
        const q=xfFreeze(xf);
        q[d.h.i]={x:p.x, y:p.y};
      }else{
        Object.assign(xf, xfScaleFromCorner(t0,d.h.i,p,e.shiftKey));
      }
    }else if(d.h.type==='edge'){
      if(xf.quad && d.t0q){
        // The whole edge travels - its two corners keep their distance from
        // each other, which is what dragging a side does in every editor.
        const i=d.h.i, j=(d.h.i+1)%4;
        const dx=p.x-d.start.x, dy=p.y-d.start.y;
        xf.quad[i]={x:d.t0q[i].x+dx, y:d.t0q[i].y+dy};
        xf.quad[j]={x:d.t0q[j].x+dx, y:d.t0q[j].y+dy};
      }else{
        Object.assign(xf, xfScaleFromEdge(t0,d.h.i,p));
      }
    }else if(d.h.type==='rotate'){
      let r=t0.rot + Math.atan2(p.y-t0.cy,p.x-t0.cx)-d.a0;
      if(e.shiftKey) r=Math.round(r/(Math.PI/12))*(Math.PI/12);   // 15° steps
      xf.rot=r;
    }
    xfSyncVector();
    onFrame('ants', selRedrawAnts);
    return;
  }
  if(!selShape) return;
  const p=canvasPt(e);
  if(selShape.kind==='rect'){ selShape.x1=p.x; selShape.y1=p.y; }
  else{
    const q=selShape.pts, last=q[q.length-1];
    if(Math.hypot(p.x-last.x,p.y-last.y)>1.5) q.push(p);
  }
  selRedrawAnts();
}
function selUp(e){
  if(xfDrag){ xfDrag=null; return; }
  if(!selShape) return;
  const s=selShape; selShape=null;
  if(s.kind==='rect'){
    if(Math.abs(s.x1-s.x0)<2||Math.abs(s.y1-s.y0)<2){ selRedrawAnts(); return; }
  }else if(s.pts.length<3){ selRedrawAnts(); return; }
  selCommitShape(s,s.mode);
}

function toggleSelTool(t){
  selTool = (selTool===t) ? null : t;
  if(selTool){
    disarmTools('sel');
    // The export preview covers the stage and swaps the picture the ants are
    // measured against, which left a lit marquee that drew nothing after the
    // first drag. A tool in hand owns the stage - see `toolInHand`.
    if(typeof exactOff === 'function') exactOff();
    ensureCanvas(); selEnsureHandlers();
    // put any selected text region down, so the panel with the selection
    // tools stays on screen instead of swapping to the typesetting panel
    if(typeof sel!=='undefined' && sel!=null){
      sel=null; drawBoxes(); renderList();
    }
  }
  const c=$('paint');
  if(c){
    c.style.pointerEvents=(paintArmed()||selTool||xf)?'auto':'none';
    c.style.cursor = selTool||shapeKind ? 'crosshair'
      : (brush||stamp||heal||eraser ? 'none' : '');
  }
  selToolUI();
}

function selToolUI(){
  const on=(id,v)=>{ const b=$(id); if(b) b.classList.toggle('pri',!!v); };
  on('selRectBtn', selTool==='rect');
  on('selLassoBtn',selTool==='lasso');
  on('selWandBtn', selTool==='wand');
  on('selFillBtn', selTool==='fill');
  on('xfBtn', !!xf);
  const row=$('rowTol');
  if(row) row.style.display=(selTool==='wand'||selTool==='fill')?'':'none';
  if(selHasMask()) selAntsLoop();   // ants resume when the panel re-renders
  if(typeof renderToolbar==='function') renderToolbar();
}
function selTolSync(v){
  selTol=Math.max(0,Math.min(128,+v||0));
  const r=$('selTolR'), n=$('selTolN');
  if(r) r.value=selTol; if(n) n.value=selTol;
}

/* =======================================================================
   Marching ants + transform chrome, drawn on one overlay canvas
   ======================================================================= */
function selAntsCanvas(){
  const img=$('img');
  if(!img||!img.naturalWidth) return null;
  let a=$('selAnts');
  if(!a){
    a=document.createElement('canvas'); a.id='selAnts';
    a.style.cssText='position:absolute;left:0;top:0;z-index:19;pointer-events:none';
    $('stage').appendChild(a);
  }
  if(a.width!==img.naturalWidth||a.height!==img.naturalHeight){
    a.width=img.naturalWidth; a.height=img.naturalHeight;
  }
  a.style.width=img.clientWidth+'px'; a.style.height=img.clientHeight+'px';
  return a;
}
function selAntsLoop(){
  if(selAntsTimer) return;
  selAntsTimer=setInterval(()=>{
    selPhase=(selPhase+1)%16;
    selRedrawAnts();
    if(!selHasMask()&&!selShape&&!xf){
      clearInterval(selAntsTimer); selAntsTimer=null;
    }
  },120);
  selRedrawAnts();
}
let _selEdgeTmp=null, _selErodeTmp=null, _selStripeTmp=null, _selAntsTmp=null;
function selRedrawAnts(){
  const a=selAntsCanvas(); if(!a) return;
  const g=a.getContext('2d');
  g.clearRect(0,0,a.width,a.height);
  if(view!=='typeset') return;      // ants only where the paint canvas lives
  const lw=Math.max(1,1/Math.max(scale,0.01));     // ≈1 screen pixel
  if(xf){ drawXfChrome(g,lw); return; }            // ants pause during transform
  if(selShape){                                     // the drag in progress
    g.setLineDash([4*lw,4*lw]); g.lineDashOffset=-selPhase*lw;
    g.lineWidth=lw; g.strokeStyle='#000';
    g.beginPath();
    if(selShape.kind==='rect'){
      const x=Math.min(selShape.x0,selShape.x1), y=Math.min(selShape.y0,selShape.y1);
      g.rect(x,y,Math.abs(selShape.x1-selShape.x0),Math.abs(selShape.y1-selShape.y0));
    }else{
      const q=selShape.pts;
      g.moveTo(q[0].x,q[0].y);
      for(let i=1;i<q.length;i++) g.lineTo(q[i].x,q[i].y);
    }
    g.stroke();
    g.strokeStyle='#fff'; g.lineDashOffset=-selPhase*lw+4*lw; g.stroke();
    g.setLineDash([]);
  }
  const bb=selBBox();
  if(!bb) return;
  // A hair over one screen pixel. A single pixel is what an image editor
  // draws on a white canvas; this one is drawn over black-and-white line art,
  // where a one-pixel dashed line disappears into the hatching.
  const d=Math.max(1,Math.round(lw*1.5));
  const ring=selEdgeRing(a.width,a.height,d);
  if(!ring) return;
  // Everything from here is redone eight times a second, for as long as a
  // selection exists, so it is done over the SELECTION and not over the page.
  // A marquee round one bubble on a 2100x2970 scan is a hundredth of the
  // pixels; striping the whole page to animate it was most of the cost of
  // having a selection at all.
  const bw=Math.min(a.width, bb.w+2*d+2), bh=Math.min(a.height, bb.h+2*d+2);
  const bx=Math.max(0,bb.x-d-1), by=Math.max(0,bb.y-d-1);
  // Animated diagonal stripes, drawn on their OWN canvas and applied to the
  // ring in one composite. Drawing them straight onto the ring with
  // 'source-in' cleared everything the stripe did not cover, so every stripe
  // erased the one before it and only the last survived - off the page.
  if(!_selStripeTmp) _selStripeTmp=document.createElement('canvas');
  const st=_selStripeTmp;
  if(st.width!==bw||st.height!==bh){ st.width=bw; st.height=bh; }
  const sg=st.getContext('2d');
  const seg=8*d, ph=(selPhase/16)*seg*2;
  sg.globalCompositeOperation='source-over';
  sg.fillStyle='#fff'; sg.fillRect(0,0,bw,bh);
  sg.fillStyle='#000';
  sg.save(); sg.translate(ph-bx,-by); sg.rotate(Math.PI/4);
  const diag=Math.hypot(bw,bh)+Math.hypot(bx,by)+seg*4;
  for(let x=-diag;x<diag;x+=seg*2) sg.fillRect(x,-diag,seg,diag*2);
  sg.restore();
  // ring ∩ stripes, on a scratch canvas so the cached ring is not consumed
  if(!_selAntsTmp) _selAntsTmp=document.createElement('canvas');
  const o=_selAntsTmp;
  if(o.width!==bw||o.height!==bh){ o.width=bw; o.height=bh; }
  const og=o.getContext('2d');
  og.globalCompositeOperation='source-over';
  og.clearRect(0,0,bw,bh);
  og.drawImage(ring, bx,by,bw,bh, 0,0,bw,bh);
  og.globalCompositeOperation='source-in';
  og.drawImage(st,0,0);
  og.globalCompositeOperation='source-over';
  g.drawImage(o,bx,by);
}

/* A one-pixel-ish outline of whatever is selected, cached until the mask
   changes.

   The ring is `mask` minus the mask ERODED by one step, and erosion is the
   INTERSECTION of the four one-pixel shifts, not their union. The original
   subtracted each shifted copy from the mask in turn, which subtracts the
   union - and the union of the four shifts covers every pixel of any solid
   shape, so the ring came out completely empty and the marching ants never
   appeared at all. lee: *"these 3 just dont work"* - the marquee, the lasso
   and the wand were all selecting correctly and showing nothing for it.

   It is also the expensive part: five full-page composites. It only changes
   when the mask does, so it is built once per selection and reused for every
   frame of the animation. */
let _selRingKey=null;
function selEdgeRing(w,h,d){
  if(!selMask) return null;
  const key=selMaskVer+'|'+w+'x'+h+'|'+d;
  if(_selEdgeTmp && _selRingKey===key) return _selEdgeTmp;
  if(!_selEdgeTmp) _selEdgeTmp=document.createElement('canvas');
  const e=_selEdgeTmp;
  if(e.width!==w||e.height!==h){ e.width=w; e.height=h; }
  if(!_selErodeTmp) _selErodeTmp=document.createElement('canvas');
  const er=_selErodeTmp;
  if(er.width!==w||er.height!==h){ er.width=w; er.height=h; }
  const rg=er.getContext('2d');
  rg.globalCompositeOperation='source-over';
  rg.clearRect(0,0,w,h);
  rg.drawImage(selMask,0,0);
  rg.globalCompositeOperation='source-in';       // keep only the overlap...
  rg.drawImage(selMask,-d,0); rg.drawImage(selMask,d,0);
  rg.drawImage(selMask,0,-d); rg.drawImage(selMask,0,d);
  rg.globalCompositeOperation='source-over';
  const eg=e.getContext('2d');
  eg.globalCompositeOperation='source-over';
  eg.clearRect(0,0,w,h);
  eg.drawImage(selMask,0,0);
  eg.globalCompositeOperation='destination-out'; // ...and take it back off
  eg.drawImage(er,0,0);
  eg.globalCompositeOperation='source-over';
  _selRingKey=key;
  return e;
}
function drawXfChrome(g,lw){
  const t=xf;
  // A pixel transform floats the pixels being moved above the page; a SHAPE
  // transform has no floating copy at all - the shape itself is what moves,
  // repainted on the paint canvas as you drag - so there is nothing to draw
  // here but the box and its handles.
  if(t.src){
    g.save();
    g.globalAlpha=t.op==null?1:t.op;
    if(t.quad){
      xfDrawQuad(g, t);
    }else{
      g.translate(t.cx,t.cy); g.rotate(t.rot); g.scale(t.sx,t.sy);
      g.drawImage(t.src,-t.w/2,-t.h/2);
    }
    g.restore();
  }
  const cs=xfCorners(t);
  g.setLineDash([4*lw,4*lw]); g.lineWidth=lw;
  g.strokeStyle='#000';
  g.beginPath();
  g.moveTo(cs[0].x,cs[0].y);
  for(let i=1;i<5;i++) g.lineTo(cs[i%4].x,cs[i%4].y);
  g.stroke();
  g.strokeStyle='#fff'; g.lineDashOffset=4*lw; g.stroke();
  g.setLineDash([]);
  const hs=4*lw;
  for(const p of [...cs,...xfEdgeMids(t)]){
    g.fillStyle='#fff'; g.strokeStyle='#000'; g.lineWidth=lw;
    g.fillRect(p.x-hs,p.y-hs,hs*2,hs*2);
    g.strokeRect(p.x-hs,p.y-hs,hs*2,hs*2);
  }
}

/* =======================================================================
   Keyboard + clipboard (registered once; inert outside the browser)
   ======================================================================= */
if(typeof window!=='undefined' && typeof document!=='undefined'){
  // Capture phase: transform's Enter/Esc and the tool keys must win over the
  // global shortcuts in region-ops.js, which listen on the bubble.
  window.addEventListener('keydown',e=>{
    const a=e.target||{};
    const writing = a.tagName==='TEXTAREA' || a.isContentEditable ||
      (a.tagName==='INPUT' &&
       /^(text|search|password|email|url|number)$/.test(a.type||'text'));
    if(xf){
      if(e.key==='Enter'){ e.preventDefault(); e.stopPropagation(); xfApply(); }
      else if(e.key==='Escape'){ e.preventDefault(); e.stopPropagation(); xfCancel(); }
      return;
    }
    if(writing) return;
    /* M MERGES IN WHATEVER VIEW YOU ARE LOOKING AT.
       lee: *"when i clcik the selct tool to slect a bunch of [boxes] and clik
       m ... nothing happens but if i manaualy do it it works"*.

       Everything below this line is the PAINT tools, and paint only exists on
       the typeset view - so the gate on the next line is right for them and
       was quietly wrong for M. Boxes are selected on every view; the select
       tool arms on every view; the right-click menu offers Merge on every
       view. The one way in that did not work was the key the menu tells you
       to press.

       The tool-toggle half of M stays below the gate, where the tool it
       toggles lives. */
    if(!(e.ctrlKey||e.metaKey||e.altKey) && (e.key==='m'||e.key==='M')
       && typeof selMulti!=='undefined' && selMulti.size>1
       && typeof mergeSelected==='function'){
      e.preventDefault(); e.stopPropagation(); mergeSelected(); return;
    }
    if(typeof view==='undefined'||view!=='typeset') return;
    if((e.ctrlKey||e.metaKey)&&(e.key==='d'||e.key==='D')){
      e.preventDefault(); e.stopPropagation(); selDeselect(); return;
    }
    if((e.ctrlKey||e.metaKey)&&(e.key==='c'||e.key==='C')&&selHasMask()){
      e.preventDefault(); e.stopPropagation(); selCopy(); return;
    }
    if((e.ctrlKey||e.metaKey)&&(e.key==='v'||e.key==='V')&&selClipObj){
      // If the browser withholds the clipboard, no paste event will follow
      // this keypress - fall back to the in-app copy after a beat.
      _pasteHandled=false;
      setTimeout(()=>{ if(!_pasteHandled) selPasteInternal(); },200);
      return;
    }
    if(e.ctrlKey||e.metaKey||e.altKey) return;
    // M MERGES WHEN THERE IS SOMETHING TO MERGE.
    //
    // lee: *"add an m shoortcut foe that"*, and M was already the pixel
    // marquee. They cannot both have it and they do not have to: with two or
    // more BOXES selected, marking an area of artwork for the brush is not
    // what anybody means by M, and with nothing selected merging is not a
    // thing that exists. So the selection decides, and neither tool loses a
    // key it was ever pressed for.
    // ...and with nothing selected to merge, M is the pixel marquee. The
    // merge half of this ran above, before the typeset gate.
    if(e.key==='m'||e.key==='M') toggleSelTool('rect');
    else if(e.key==='l'||e.key==='L') toggleSelTool('lasso');
    else if(e.key==='w'||e.key==='W') toggleSelTool('wand');
    else if(e.key==='g'||e.key==='G') toggleSelTool('fill');
    else if(e.key==='e'||e.key==='E') toggleEraser();
    // R for reveal - the region eraser, which puts the scan back where you
    // paint. E rubs out paint and stops at the plate; R goes through it.
    else if(e.key==='r'||e.key==='R') toggleUnclean();
    // T is the transform, and the transform has its corners free - lee asked
    // for Ctrl+T and then, once he heard that Chrome keeps that one for
    // opening a tab: *"isntead of control t just make it t"*. Scale and rotate
    // is still there, in the same toolbox slot, for when a box should stay a
    // box.
    else if(e.key==='t'||e.key==='T') xfToggle('distort');
    // The arrow, where an image editor keeps it. Ctrl+V is caught above, so
    // this is only ever the bare key.
    else if(e.key==='v'||e.key==='V') toggleShapeEdit();
    // Ctrl+J in every image editor there is. The plain key, because Ctrl+J is
    // the browser's downloads window.
    else if(e.key==='j'||e.key==='J') selLift();
    else if(e.key==='Escape'){
      if(selTool){ e.stopPropagation(); toggleSelTool(selTool); }
      else if(typeof shapeEdit!=='undefined' && shapeEdit){
        e.stopPropagation(); toggleShapeEdit(false); }
      else if(selHasMask()){ e.stopPropagation(); selDeselect(); }
    }
  },true);

  /* Ctrl+V an image from the clipboard: it lands as a layer in the middle of
     the current view, already in free transform so it can be nudged into
     place. Made for patches cleaned in another app and screenshots. */
  window.addEventListener('paste',e=>{
    if(typeof view==='undefined'||view!=='typeset') return;
    const a=e.target||{};
    if(a.tagName==='TEXTAREA'||a.tagName==='INPUT'||a.isContentEditable) return;
    const item=[...((e.clipboardData&&e.clipboardData.items)||[])]
      .find(i=>i.type&&i.type.startsWith('image/'));
    if(!item){
      // nothing usable on the system clipboard, but an in-app copy pastes
      if(selClipObj){ _pasteHandled=true; e.preventDefault(); selPasteInternal(); }
      return;
    }
    e.preventDefault();
    _pasteHandled=true;
    const blob=item.getAsFile(); if(!blob) return;
    const url=URL.createObjectURL(blob);
    const im=new Image();
    im.onload=()=>{
      URL.revokeObjectURL(url);
      const img=$('img'); if(!img||!img.naturalWidth){ return; }
      // Our own Ctrl+C also lands on the system clipboard, so our own copy
      // comes back here as a plain image with no idea where it came from -
      // and got dropped in the middle of the view while the original stayed
      // put. Two of everything, from one copy and one paste. Matched on the
      // SIZE OF THE IMAGE, not the size of the file: the browser re-encodes
      // on the way through the clipboard, so the bytes never matched and this
      // path was taken every single time.
      if(selClipObj && selClipObj.canvas
         && selClipObj.canvas.width===im.naturalWidth
         && selClipObj.canvas.height===im.naturalHeight){
        selPasteInternal();
        return;
      }
      ensureCanvas(); selEnsureHandlers();
      const cc=document.createElement('canvas');
      cc.width=im.naturalWidth; cc.height=im.naturalHeight;
      cc.getContext('2d').drawImage(im,0,0);
      // centre of what is on screen right now, in page coordinates
      const wrap=$('canvasWrap');
      let cx=img.naturalWidth/2, cy=img.naturalHeight/2;
      if(wrap&&scale>0){
        cx=Math.max(0,Math.min(img.naturalWidth,
          (wrap.scrollLeft+wrap.clientWidth/2)/scale));
        cy=Math.max(0,Math.min(img.naturalHeight,
          (wrap.scrollTop+wrap.clientHeight/2)/scale));
      }
      const x=Math.round(cx-cc.width/2), y=Math.round(cy-cc.height/2);
      const st=selPushPatch(cc,x,y,1,'#7fd7c4','Pasted image');
      layerSel=st.id;
      // straight into free transform to place it - as soon as the patch
      // image has decoded, which is what xfStart() needs to float it
      selDeselect();      // ditto: the selection is not the pasted image
      const tick=setInterval(()=>{
        if(!st.img) return;
        clearInterval(tick); xfStart(st);
      },60);
      setTimeout(()=>clearInterval(tick),3000);
    };
    im.onerror=()=>{ URL.revokeObjectURL(url); toast('That image would not load.'); };
    im.src=url;
  });
}

/* Pure parts exported for the node test-suite; invisible in the browser. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={floodMask,maskBBox,xfCorners,xfEdgeMids,
                  xfScaleFromCorner,xfScaleFromEdge,xfInside,clampScale,
                  xfFreeze,xfQuadPoint,xfTriMatrix,xfGrow,XF_MESH,xfShapeBox};
}
