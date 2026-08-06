/* Pure-logic tests for the selection / transform module: flood fill,
   mask bounding boxes, and the free-transform maths. select.js exports
   these when loaded under node; no DOM required. */
const {floodMask,maskBBox,xfCorners,xfScaleFromCorner,xfScaleFromEdge,
       xfInside,clampScale}=require('../../mangatl/static/js/select.js');

let fails=0;
const ok=(cond,msg)=>{ console.log((cond?'ok  ':'FAIL'),msg);
                       if(!cond) fails++; };
const near=(a,b,eps)=>Math.abs(a-b)<=(eps==null?1e-6:eps);

/* ---- flood fill ----
   A 8x6 'page': white background, a 3x2 dark box at (2,1). */
const W=8,H=6, px=new Uint8ClampedArray(W*H*4);
for(let i=0;i<W*H;i++){ px[i*4]=px[i*4+1]=px[i*4+2]=250; px[i*4+3]=255; }
for(let y=1;y<3;y++) for(let x=2;x<5;x++){
  const i=(y*W+x)*4; px[i]=px[i+1]=px[i+2]=20;
}
const inside=floodMask(px,W,H,3,1,32);
ok(inside.reduce((a,b)=>a+b,0)===6, 'flood from the dark box selects its 6 pixels');
const bb=maskBBox(inside,W,H);
ok(bb&&bb.x===2&&bb.y===1&&bb.w===3&&bb.h===2, 'bbox of the dark box is 3x2 at (2,1)');

const bg=floodMask(px,W,H,0,0,32);
ok(bg.reduce((a,b)=>a+b,0)===W*H-6, 'flood from the corner takes everything but the box');
ok(!bg[1*W+3], 'the background flood does not leak into the box');

const all=floodMask(px,W,H,0,0,255);
ok(all.reduce((a,b)=>a+b,0)===W*H, 'max tolerance floods the whole page');
ok(maskBBox(new Uint8Array(W*H),W,H)===null, 'empty mask has no bbox');

/* row guard: two dark pixels at the ends of one row must not connect
   through the row edge */
const px2=new Uint8ClampedArray(W*H*4);
for(let i=0;i<W*H;i++){ px2[i*4]=px2[i*4+1]=px2[i*4+2]=250; px2[i*4+3]=255; }
const a1=(1*W+7)*4, a2=(2*W+0)*4;             // end of row 1, start of row 2
px2[a1]=px2[a1+1]=px2[a1+2]=20; px2[a2]=px2[a2+1]=px2[a2+2]=20;
const wrap=floodMask(px2,W,H,7,1,32);
ok(wrap.reduce((a,b)=>a+b,0)===1, 'flood does not wrap around row ends');

/* ---- transform maths ---- */
const t={w:100,h:50,cx:200,cy:100,sx:1,sy:1,rot:0};
let cs=xfCorners(t);
ok(near(cs[0].x,150)&&near(cs[0].y,75)&&near(cs[2].x,250)&&near(cs[2].y,125),
   'corners of an untransformed 100x50 box are where they should be');

/* drag BR corner to (300,160): TL stays anchored; spans 150x85 over 100x50 */
let r=xfScaleFromCorner(t,2,{x:300,y:160},false);
ok(near(r.sx,1.5)&&near(r.sy,1.7), 'corner drag scales each axis from the opposite corner');
const t2={...t,...r};
ok(near(xfCorners(t2)[0].x,150)&&near(xfCorners(t2)[0].y,75),
   'the opposite corner stays put through a corner scale');

/* uniform (Shift) keeps proportions */
r=xfScaleFromCorner(t,2,{x:300,y:150},true);
ok(near(Math.abs(r.sx),Math.abs(r.sy)), 'Shift-drag keeps the proportions');

/* dragging the right edge only changes x */
r=xfScaleFromEdge(t,1,{x:300,y:100});
ok(near(r.sx,1.5)&&near(r.sy,1), 'edge drag scales one axis only');
const t3={...t,...r};
ok(near(xfCorners(t3)[0].x,150), 'the opposite edge stays put');

/* rotation: corners still form the same rectangle, just turned */
const t4={...t,rot:Math.PI/2};
cs=xfCorners(t4);
ok(near(cs[0].x,225)&&near(cs[0].y,50), '90° rotation turns the corners correctly');

/* a corner scale under rotation still anchors the opposite corner */
const t5={...t,rot:Math.PI/6};
const anchor=xfCorners(t5)[0];
r=xfScaleFromCorner(t5,2,{x:280,y:160},false);
const t6={...t5,...r};
ok(near(xfCorners(t6)[0].x,anchor.x,1e-6)&&near(xfCorners(t6)[0].y,anchor.y,1e-6),
   'anchoring works under rotation too');

/* inside test respects rotation and flips */
ok(xfInside(t,{x:200,y:100}) && !xfInside(t,{x:200,y:130}),
   'inside test: centre in, above the box out');
ok(xfInside({...t,sx:-1},{x:200,y:100}), 'a flipped box still has an inside');

/* scale never collapses to zero */
ok(clampScale(0.001)===0.02 && clampScale(-0.001)===-0.02,
   'scale clamps away from zero, keeping the sign');

process.exit(fails?1:0);
