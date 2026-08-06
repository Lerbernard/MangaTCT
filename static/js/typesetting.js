/* typesetting.js — Per-bubble @font-face loading, drawText() canvas render, on-canvas text editing.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* Fonts picked per bubble are loaded on demand, one @font-face per file. */
let fontFams={};
/* One colour, read the way the panel reads it.

   This was `ov.x || st.x` — the SAVED override first, the live style second —
   so a colour the person had just turned off went on being drawn: `st.fg2`
   was `''`, which `||` skips straight past, and `ov.fg2` still held the old
   value until a round trip that would never carry an empty one.
   lee: *"ehen i turn off teh gradient it donts accualy turn off"*.

   `??` and the live style first, which is what `styleNow` in panels.js does.
   An empty string is an answer — it means off — and only "not set at all"
   falls through to the override. */
function pick(st, ov, key){
  const v = (st||{})[key] ?? (ov||{})[key] ?? '';
  return v || '';
}

function fontFam(path, kind){
  if(!path) return `'ml-${kind||'bubble'}'`;
  if(!fontFams[path]){
    const fam='mlp'+Object.keys(fontFams).length;
    fontFams[path]=fam;
    const url=`url("/fontfile?p=${encodeURIComponent(path)}")`;
    // once the face is available the canvas typesetting repaints in it (the
    // font DROPDOWNS use server-rendered images, so they need no refresh)
    const done=()=>{ if(typeof drawOverlay==='function') drawOverlay(); };
    // The CSS Font Loading API is the reliable way to load a font by URL and
    // KNOW when it's ready — the browser sniffs the format from the bytes, so
    // no format() hint is needed and .ttf/.otf both work. Injecting a
    // @font-face <style> rule (the old path) can silently never apply on some
    // setups; this doesn't.
    try{
      const face=new FontFace(fam, url);
      document.fonts.add(face);
      face.load().then(done).catch(()=>{});
    }catch(_){
      const st=document.createElement('style');       // very old browser
      st.textContent=`@font-face{font-family:'${fam}';`+
        `src:${url};font-display:swap}`;
      document.head.appendChild(st);
      if(document.fonts&&document.fonts.load)
        document.fonts.load(`12px '${fam}'`).then(done).catch(()=>{});
    }
  }
  return `'${fontFams[path]}'`;
}

/* Where each letter of a curved line goes — the browser's copy of
   `render.arc_places`. `curve` is the whole angle the line subtends in degrees,
   positive arching up like a rainbow. The radius comes from the arc length, and
   half the sagitta is taken back off so the bend keeps the line where the
   fitter put it instead of hanging the whole arch below it.

   Kept in step with the Python by `test_the_two_arcs_agree`, which runs both
   over the same line and compares every letter's place. */
function arcPlaces(line, fam, size, lspace, curve, x, y){
  const w=[...line].map(ch=>textW(fam,size,ch));
  const total=w.reduce((a,b)=>a+b,0)+lspace*Math.max(0,line.length-1);
  const ang=curve*Math.PI/180;
  if(total<=0 || Math.abs(ang)<1e-4) return [];
  const R=total/ang;
  const sag=R*(1-Math.cos(ang/2));
  const out=[]; let s=-total/2;
  [...line].forEach((ch,i)=>{
    const th=(s+w[i]/2)/R;
    out.push({x:x+R*Math.sin(th), y:y+R*(1-Math.cos(th))-sag/2,
              deg:th*180/Math.PI, ch:ch, adv:w[i]});
    s+=w[i]+lspace;
  });
  return out;
}

function drawText(){
  const o=$('overlay');
  // every redraw is also the moment the page's typesetting can have appeared or
  // gone, so the switch that hides it follows along here
  if(typeof syncTextToggle==='function') syncTextToggle();
  o.innerHTML='';
  o.classList.toggle('on', inText());
  if(!inText()){ drawFrame(); return; }   // also puts the frame away
  regions.forEach(r=>{
    const L=r.layout;
    if(!L||!L.lines) return;
    if(r._hideText) return;              // its layer-eye is switched off
    if(!L.lines.length){
      // A block with nothing in it. Nothing is drawn on the exported page —
      // it is empty — but on screen it gets a dashed outline where it stands,
      // the way an empty text layer does in any editor, so it can be found,
      // clicked, typed into again or deleted.
      const [ex,ey,ew,eh]=frameOf(r);
      const ph=document.createElement('div');
      ph.className='temptyph'; ph.dataset.id=r.id;
      ph.style.cssText=`left:${ex*scale}px;top:${ey*scale}px;`+
        `width:${ew*scale}px;height:${eh*scale}px`;
      o.appendChild(ph);
      return;
    }
    const org=layoutOrigins(r,L);
    const st=r.style||{};
    const ov=r.layout_override||{};
    const fg=ov.fg||st.fg||L.fg||'#000';
    const edge=ov.edge||st.edge||L.edge||'#fff';
    const size=L.font_size*scale;
    const sv=(st.stroke??L.stroke??1);
    const sw=Math.max(0,sv)*scale;
    const fam=fontFam(ov.font||st.font||L.font, r.kind);
    const ls=(+(ov.lspace??st.lspace)||0)*scale;
    const shc=pick(st,ov,'shadow');
    const shOn=/^#[0-9a-f]{6}$/i.test(shc);
    const shD=(+(ov.sh_dist??st.sh_dist??2))*scale*0.707;
    const shB=(+(ov.sh_blur??st.sh_blur??3))*scale;
    // Outer glow. CSS blur is much weaker than a Gaussian of the same radius,
    // so the halo is stacked at three rising radii — which is also how the
    // exporter builds it (spread, blur, then composite the halo twice).
    const glc=pick(st,ov,'glow');
    const glOn=/^#[0-9a-f]{6}$/i.test(glc);
    const glS=(+(ov.glow_size??st.glow_size??6))*scale;
    // Inner glow. There is no CSS for light inside a letter, so the preview
    // shows it as a soft rim ON the edge — half of it falls where the export
    // puts all of it. It reads as the same effect at the same strength; the
    // exported page is the exact one. The only place the two deliberately part.
    const igc=pick(st,ov,'iglow');
    const igOn=/^#[0-9a-f]{6}$/i.test(igc);
    const igS=(+(ov.iglow_size??st.iglow_size??5))*scale;
    const opv=+(ov.opacity??st.opacity??100);
    const op=Math.max(0,Math.min(100,isNaN(opv)?100:opv))/100;
    const crv=+(ov.curve??st.curve??0)||0;
    if(editing===r.id) return;              // being typed into right now
    const rot=+(L.rotate||0);
    const fr=frameOf(r);
    const g2v=pick(st,ov,'fg2');
    const grad=/^#[0-9a-f]{6}$/i.test(g2v);
    const g1v=pick(st,ov,'fg1');
    const gFrom=/^#[0-9a-f]{6}$/i.test(g1v)?g1v:fg;
    const gang=+(ov.grad_angle??st.grad_angle??0)||0;
    // ...and the same three for the ring round the letters.
    const e2v=pick(st,ov,'edge2');
    const egrad=/^#[0-9a-f]{6}$/i.test(e2v) && sw>0;
    const e1v=pick(st,ov,'edge1');
    const eFrom=/^#[0-9a-f]{6}$/i.test(e1v)?e1v:edge;
    const eang=+(ov.edge_angle??st.edge_angle??0)||0;
    // One group per block, sized to the text's frame (plus slack so
    // overhanging lines keep their paint) and rotated as a whole about its
    // centre — the same thing the exporter does.
    const P=48;
    const gx=fr[0]*scale-P, gy=fr[1]*scale-P;
    const g=document.createElement('div');
    g.className='tgrp';
    g.style.cssText=`position:absolute;left:${gx}px;top:${gy}px;`+
      `width:${fr[2]*scale+2*P}px;height:${fr[3]*scale+2*P}px;`+
      (rot?`transform:rotate(${-rot}deg);`:'')+
      // Transparency belongs to the whole block, exactly as it does in the
      // export, where it scales one layer's alpha after everything is drawn.
      (op<1?`opacity:${op};`:'');
    L.lines.forEach((line,k)=>{
      const d=document.createElement('div');
      d.className='tl'+(crv?' tlcurve':'');
      d.dataset.id=r.id;
      // A curved line is not one text node: every letter has its own place on
      // the arc and its own turn, so it gets its own span. The line div stops
      // being the thing that is positioned and becomes the container the
      // letters are positioned inside — same arithmetic as `render.arc_places`.
      d.style.cssText=(crv?`left:0;top:0;transform:none;`
                          :`left:${org[k][0]*scale-gx}px;top:${org[k][1]*scale-gy}px;`)+
        `font-family:${fam},sans-serif;font-size:${size}px;`+
        (()=>{const sh=[];
          if(shOn) sh.push(`${shD.toFixed(1)}px ${shD.toFixed(1)}px `+
                           `${shB.toFixed(1)}px ${shc}`);
          if(glOn) for(const m of [0.5,1,1.7]) sh.push(`0 0 ${(glS*m).toFixed(1)}px ${glc}`);
          return sh.length?`text-shadow:${sh.join(',')};`:'';})()+
        (ls?`letter-spacing:${ls}px;`+
            // CSS adds a trailing gap after the last letter; nudge back so
            // the glyphs themselves stay centred, matching the export
            `transform:translate(calc(-50% + ${ls/2}px),-50%);`:'')+
        // The gradient is painted on the FILL span, not on the line.
        //
        // It used to be a background on the line div, clipped to its text —
        // and the outline span is a CHILD of that div, so it was painted over
        // the background and swallowed the whole gradient at any width above
        // a hairline. lee: *"the outline obsucures the gradient"*. Painting
        // the fill itself puts the colour back where it belongs: on top of
        // the outline, exactly as the exporter composites it.
        `color:${fg};`;
      if(grad) d.classList.add('grad');
      // one letter, outlined the same way a whole line is
      const inked=(host,txt)=>{
        if(sw>0){
          // A real stroke behind a clean fill: the outline only grows OUTWARD
          // from the letters, however thick it is. (text-shadow copies the
          // whole word around instead, which fell apart at large widths.)
          //
          // With an outline GRADIENT there are EDGE_BANDS of these instead of
          // one, each a solid stroke in its own step of the ramp and each
          // clipped to its own slab across the block. CSS has no gradient for
          // a text stroke — `background-clip:text` paints the fill area and
          // leaves the stroke the colour it was given, which is measurable and
          // was measured — so a stepped ramp is the honest approximation. The
          // exported page draws it as a true gradient through the ring's own
          // mask; this is the preview, and at sixteen steps the join between
          // one step and the next is under two grey levels on a full-length
          // red-to-blue ramp.
          const back=document.createElement('span');
          back.className='ts';
          back.textContent=txt;
          back.style.webkitTextStroke=`${2*sw}px ${edge}`;
          if(egrad) back.classList.add('egrad');
          const front=document.createElement('span');
          front.className='tf';
          front.textContent=txt;
          host.appendChild(back); host.appendChild(front);
        } else {
          const front=document.createElement('span');
          front.className='tf';
          front.textContent=txt;
          host.appendChild(front);
        }
      };
      if(crv){
        arcPlaces(line, fam, size, ls, crv,
                  org[k][0]*scale-gx, org[k][1]*scale-gy).forEach(p=>{
          if(!p.ch.trim()) return;
          const sp=document.createElement('span');
          sp.className='tc';
          sp.style.cssText=`left:${p.x.toFixed(1)}px;top:${p.y.toFixed(1)}px;`+
            `transform:translate(-50%,-50%) rotate(${p.deg.toFixed(2)}deg)`;
          inked(sp, p.ch);
          if(grad) sp.classList.add('grad');
          d.appendChild(sp);
        });
      } else {
        inked(d, line);
      }
      if(igOn){
        // a soft rim on the letter's edge — see the note where igc is read
        const rim=(host,txt)=>{
          const e=document.createElement('span');
          e.className='tg';
          e.textContent=txt;
          e.style.webkitTextStroke=`${Math.max(1,igS*0.5).toFixed(1)}px ${igc}`;
          e.style.webkitTextFillColor='transparent';
          e.style.filter=`blur(${Math.max(0.5,igS*0.3).toFixed(1)}px)`;
          host.appendChild(e);
        };
        if(crv) [...d.children].forEach(sp=>rim(sp, sp.textContent));
        else rim(d, line);
      }
      g.appendChild(d);
    });
    o.appendChild(g);
    if(grad){
      // Each line paints its own slice of one shared gradient. The stops
      // are given in pixels along the gradient axis, offset per line, so
      // the fade runs unbroken across the whole block. (Painting one
      // background on the group and clipping through the children sounds
      // simpler but Chromium won't clip through transformed layers.)
      const rad=gang*Math.PI/180;
      const tx=Math.sin(rad), ty=Math.cos(rad);
      // For a curved block the painted things are the letters, not the
      // lines: they are positioned the same way (centred on a point), so the
      // same arithmetic works on either.
      const cs=[...g.querySelectorAll('.tc')];
      const els=cs.length?cs:[...g.children];
      let bx0=1e9,by0=1e9,bx1=-1e9,by1=-1e9;
      els.forEach(el=>{
        const w=el.offsetWidth,h=el.offsetHeight;
        const x0=el.offsetLeft-w/2,y0=el.offsetTop-h/2;
        bx0=Math.min(bx0,x0); by0=Math.min(by0,y0);
        bx1=Math.max(bx1,x0+w); by1=Math.max(by1,y0+h);
      });
      const ps=[bx0*tx+by0*ty, bx1*tx+by0*ty, bx0*tx+by1*ty, bx1*tx+by1*ty];
      const pmin=Math.min(...ps), pmax=Math.max(...ps);
      // App angle: 0 = top to bottom, clockwise from there. CSS points the
      // other way round, hence the 180-a.
      const css=((180-gang)%360+360)%360;
      els.forEach(el=>{
        const w=el.offsetWidth,h=el.offsetHeight;
        const Lg=Math.abs(w*tx)+Math.abs(h*ty);
        const pS=el.offsetLeft*tx+el.offsetTop*ty-Lg/2;
        // measured on the placed element, painted on the fill inside it
        const paint=el.querySelector('.tf')||el;
        paint.style.backgroundImage=`linear-gradient(${css}deg,`+
          `${gFrom} ${(pmin-pS).toFixed(1)}px,`+
          `${g2v} ${(pmax-pS).toFixed(1)}px)`;
      });
    }
    if(egrad) paintEdgeGradient(g, eFrom, e2v, eang, 2*sw);
  });
  drawFrame();
}

/* ---------------- editing text on the page ---------------- */
let editing=null, editBox=null;
// The wording the editor opened on. Closing only writes anything back when
// the person actually changed it — see closeCanvasEdit.
let editWas=null;

function frameOf(r){
  const f=r.layout&&r.layout.frame;
  if(f&&f.length===4) return [f[0],f[1],f[2],f[3]];
  return derivedFrame(r);
}

/* A chapter typeset before blocks carried a box of their own has origins and
   no box. Draw the box round the WORDS — where the fitter actually put them —
   rather than round the bubble or the Japanese text box: those are different
   rectangles, and adopting one of them is what threw the typesetting across the
   bubble the moment it was clicked.

   Measuring the widest line in a web font need not match the server's metrics
   to the pixel, and it doesn't have to: the width only decides where the box's
   EDGES fall, and every line is centred on the middle, which the origins give
   exactly. */
function derivedFrame(r){
  const L=r.layout, org=L&&L.origins;
  if(!L||!L.lines||!L.lines.length||!org||org.length!==L.lines.length){
    const [x,y,w,h]=r.bubble_bbox||r.bbox;
    return [x,y,w,h];
  }
  const ov=r.layout_override||{};
  const fam=fontFam(ov.font||L.font||'', r.kind);   // same face drawText uses
  const lh=L.font_size*(L.leading||1.12);
  let wid=0;
  L.lines.forEach(t=>{ wid=Math.max(wid, textW(fam, L.font_size, t)); });
  const fw=Math.max(8, Math.round(wid+2*PADL));
  const fh=Math.max(8, Math.round(L.lines.length*lh));
  const cx=org[0][0], cy=(org[0][1]+org[org.length-1][1])/2;
  return [Math.round(cx-fw/2), Math.round(cy-fh/2), fw, fh];
}

/* On the Translated tab the boxes are hidden, so there is no .box element to
   click. Hit-test the text frames instead: one click selects a block and
   starts moving it, which is what clicking typesetting should do. */
function frameAt(x, y){
  let best=null;
  regions.forEach(r=>{
    // A block with nothing in it is still a block: it keeps its frame, and
    // clicking it is how you type into it again or delete it.
    // lee: *"i shoud be able to lcick on it to add text or dleete it"*.
    if(!r.layout||!r.layout.lines) return;
    if(r._hideText) return;              // hidden text is unclickable
    const [fx,fy,fw,fh]=frameOf(r);
    if(x>=fx&&x<=fx+fw&&y>=fy&&y<=fy+fh){
      const a=fw*fh;
      if(!best||a<best.a) best={id:r.id,a};       // smallest wins when nested
    }
  });
  return best?best.id:null;
}

$('stage').addEventListener('mousedown',e=>{
  if(!inText()||handMode) return;
  // ANY armed tool owns the click — while a tool is in hand, text is just
  // part of the picture and must never open its editor.
  if(paintArmed()) return;                         // painting owns the click
  if(typeof zoomTool!=='undefined' && zoomTool) return;
  // Selection / transform tools own the click too — this capture-phase
  // handler used to eat every mousedown that landed on a text frame, which
  // killed the marquee, lasso, wand and fill anywhere near typesetting.
  if(typeof selTool!=='undefined' && (selTool||xf)) return;
  if(e.target.closest('#tframe')) return;         // handles look after themselves
  if(e.target.id==='canvasEdit') return;          // already typing in it
  const p=pt(e);
  const id=frameAt(p.x/scale, p.y/scale);
  if(id===null){
    // clicked away: commit any typing and put the selection down too
    closeCanvasEdit(true);
    if(sel!=null){ sel=null; drawOverlay(); renderList(); }
    return;
  }
  e.preventDefault(); e.stopPropagation();
  if(editing===id) return;                        // clicking inside the editor
  // Press and hold to MOVE the block; let go without moving and the editor
  // opens, the way a text box in Word does. It used to open on the way DOWN,
  // so the only way to move a line was to find its frame handle first.
  // lee: *"make it so ythat i can click on te tetx and hold and move teh tetx
  // with opening up the text box"*.
  //
  // Nothing is armed until the pointer has actually travelled: a plain click
  // never touches the drag machinery, so it cannot leave a one-pixel nudge
  // saved behind it.
  textPress={id, ev:e, x:e.clientX, y:e.clientY, dragging:false};
}, true);

/* How far the pointer has to travel before a press counts as a drag rather
   than a click. Small enough to feel immediate, big enough that a shaky hand
   still opens the editor. */
const TEXT_DRAG_PX=4;
let textPress=null;

window.addEventListener('mousemove',e=>{
  if(!textPress || textPress.dragging) return;
  if(Math.abs(e.clientX-textPress.x)<=TEXT_DRAG_PX
     && Math.abs(e.clientY-textPress.y)<=TEXT_DRAG_PX) return;
  textPress.dragging=true;
  // The block has to be the selected one for its frame to be on screen, and
  // the frame is what the move is drawn against.
  if(sel!==textPress.id){ sel=textPress.id; drawOverlay(); renderList(); }
  // Hand the ORIGINAL press to startFrame, so the block moves with the
  // pointer instead of jumping by however far it has already travelled.
  startFrame(textPress.ev, textPress.id, 'move');
});

window.addEventListener('mouseup',()=>{
  const t=textPress; textPress=null;
  if(t && !t.dragging) editOnCanvas(t.id);
});

$('stage').addEventListener('dblclick',e=>{
  if(!inText()||handMode) return;
  // same rule as mousedown: an armed tool means text is not clickable —
  // a double-click mid-brushstroke used to drop you into the text editor
  if(paintArmed()) return;
  if(typeof zoomTool!=='undefined' && zoomTool) return;
  if(typeof selTool!=='undefined' && (selTool||xf)) return;
  if(e.target.id==='canvasEdit') return;   // let it select a word, as Word does
  const p=pt(e);
  const id=frameAt(p.x/scale, p.y/scale);
  if(id!==null && editing!==id){
    e.preventDefault(); e.stopPropagation();
    fdrag=null;                            // a double-click is not a tiny drag
    editOnCanvas(id);
  }
});

function editOnCanvas(id){
  const r=regions.find(x=>x.id===id);
  if(!r||!r.layout) return;
  // A locked block is not typed into. lee: *"the lock shoud prevent teh layer
  // form getting edited or moved"* — a lock that only stopped restacking was
  // a lock against the one thing nobody does by accident.
  if(r.locked){ toast('That text box is locked.'); return; }
  closeCanvasEdit(true);
  select(id);
  editing=id;

  const L=r.layout;
  // Open on the text's own frame, not the region box. Using the region box
  // made the text jump back into the bubble the moment you clicked it.
  const [fx,fy,fw,fh]=frameOf(r);
  const size=L.font_size*scale;
  const st=r.style||{};

  // A contenteditable rather than a textarea, because a textarea pins its
  // text to the top while the page centres it — so the words visibly jumped
  // upward as soon as the editor opened.
  const ta=document.createElement('div');
  ta.id='canvasEdit';
  ta.setAttribute('contenteditable','plaintext-only');
  if(ta.contentEditable!=='plaintext-only') ta.setAttribute('contenteditable','true');
  ta.textContent=(L.lines||[]).join('\n');
  editWas=(L.lines||[]).join('\n');
  ta.style.cssText=
    `position:absolute;text-align:center;white-space:pre;`+
    `display:flex;flex-direction:column;justify-content:center;`+
    `background:transparent;border:none;outline:none;`+
    `z-index:40;text-transform:none;overflow:visible`;
  placeEditor(ta, r);
  $('stage').appendChild(ta);
  editBox=ta;
  drawText();

  ta.focus();
  const sel2=window.getSelection(), rng=document.createRange();
  rng.selectNodeContents(ta); rng.collapse(false);      // caret at the end
  sel2.removeAllRanges(); sel2.addRange(rng);

  let t=null;
  ta.addEventListener('input',()=>{
    clearTimeout(t);
    t=setTimeout(()=>{
      const lines=editLines(ta);
      if(lines.length) livePreview(id,Object.assign(currentPatch(r),{lines}));
    },200);
  });
  ta.addEventListener('keydown',e=>{
    e.stopPropagation();                       // page shortcuts stay off
    if(e.key==='Escape'){e.preventDefault();closeCanvasEdit(false);}
    if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();closeCanvasEdit(true);}
  });
  ta.addEventListener('blur',()=>closeCanvasEdit(true));
}

/* Keeps the editor sitting exactly on the frame — at creation, and again on
   every frame change while it is open. */
function placeEditor(ta, r){
  if(!ta||!r||!r.layout) return;
  const L=r.layout, st=r.style||{};
  const [fx,fy,fw,fh]=frameOf(r);
  const size=L.font_size*scale;
  ta.style.left=(fx*scale)+'px';
  // anchored on the frame's centre line, so an added line grows it both ways
  ta.style.top=((fy+fh/2)*scale)+'px';
  ta.style.width=(fw*scale)+'px';
  ta.style.minHeight=(fh*scale)+'px';
  const ov=r.layout_override||{};
  ta.style.fontFamily=fontFam(ov.font||st.font||L.font, r.kind)+',sans-serif';
  ta.style.fontSize=size+'px';
  ta.style.lineHeight=((L.leading||1.12)*size)+'px';
  const ls=(+(ov.lspace??st.lspace)||0)*scale;
  ta.style.letterSpacing=ls?ls+'px':'';
  // centre the glyphs, not the glyphs+trailing gap — matches the render
  ta.style.paddingLeft=ls?ls+'px':'';
  ta.style.color=st.fg||L.fg||'#000';
  ta.style.caretColor=st.fg||L.fg||'#000';
  ta.style.textShadow=editShadow(r,L,size);
  // and typing into a faded block looks faded, like everything else about it
  const opv=+(ov.opacity??st.opacity??100);
  ta.style.opacity=(isNaN(opv)?100:Math.max(0,Math.min(100,opv)))/100;
  ta.style.transformOrigin='center center';
  ta.style.transform='translateY(-50%)'+
    (+(L.rotate||0) ? ` rotate(${-(+L.rotate)}deg)` : '');
}

function editShadow(r,L,sizePx){
  // the same outline AND drop shadow the page is typeset with, so typing
  // looks like the result — the shadow used to be left out here, which made
  // it vanish the moment the text box opened and pop back on click-out
  const st=r.style||{}, ov=r.layout_override||{};
  const edge=ov.edge||st.edge||L.edge||'#fff';
  const sv=(st.stroke??L.stroke??1);
  const sw=Math.max(0,sv)*scale;
  const parts=[];
  if(sw>0)
    parts.push(...[[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]]
      .map(([a,b])=>`${a*sw}px ${b*sw}px 0 ${edge}`));
  const shc=pick(st,ov,'shadow');
  if(/^#[0-9a-f]{6}$/i.test(shc)){
    const shD=(+(ov.sh_dist??st.sh_dist??2))*scale*0.707;
    const shB=(+(ov.sh_blur??st.sh_blur??3))*scale;
    // listed last so it paints BEHIND the outline, matching the page
    parts.push(`${shD.toFixed(1)}px ${shD.toFixed(1)}px ${shB.toFixed(1)}px ${shc}`);
  }
  const glc=pick(st,ov,'glow');
  if(/^#[0-9a-f]{6}$/i.test(glc)){
    const glS=(+(ov.glow_size??st.glow_size??6))*scale;
    for(const m of [0.5,1,1.7]) parts.push(`0 0 ${(glS*m).toFixed(1)}px ${glc}`);
  }
  return parts.length ? parts.join(',') : 'none';
}

/* What is in the on-page editor right now, line for line.

   It used to trim every line and drop the empty ones, which threw away a
   blank line typed between two paragraphs and an indent typed at the front —
   the same rule the panel's line box abandoned rounds ago. Trailing blanks go,
   because those are only where the cursor was left. */
function editLines(el){
  const ls=(el.innerText||'').replace(/\u00a0/g,' ').split('\n');
  while(ls.length && !ls[ls.length-1].trim()) ls.pop();
  return ls;
}

function closeCanvasEdit(commit){
  if(!editBox) return;
  const id=editing, ta=editBox, lines=editLines(ta);
  const was=editWas;
  editing=null; editBox=null; editWas=null;
  ta.remove();
  const r=regions.find(x=>x.id===id);
  // Clicking a block and clicking away is not an edit. It used to save
  // anyway, and saving locks the block onto the hand-edit path — which
  // places lines by a different rule than the fitter does — so the typesetting
  // visibly moved on a click that changed nothing. Only a real change to the
  // wording is a change.
  if(was!==null && lines.join('\n')===was) commit=false;
  // …and an EMPTY edit is an edit. `lines.length` was a guard here, so
  // selecting everything in a block and pressing delete committed nothing at
  // all: the words came straight back the moment the editor closed. Deleting
  // all of it is the most deliberate edit there is.
  // lee: *"deleeting all teh etxt from a text box still dont just leave it"*.
  if(r&&commit){
    // What to put back, captured BEFORE the edit is written into the region.
    // `saveTypesetting` snapshots `r.layout_override` for its undo, and by the
    // time it reads it the next two lines have already replaced it — so the
    // undo restored the edit and pressing it did nothing.
    // lee: *"the text is deleting and teh empty box stay but its not in the
    // history so i cant undo the delete"*.
    const before={ov:JSON.parse(JSON.stringify(r.layout_override||{})),
                  text:r.dst_text};
    r.layout.lines=lines;
    r.layout_override=Object.assign({},r.layout_override,{lines,locked:true});
    const f=$('lyLines'); if(f) f.value=lines.join('\n');
    // Send the lines explicitly. currentPatch reads the side panel, which
    // still held the old wording — that is why typed changes sometimes
    // vanished the moment you clicked away.
    // And no panel rebuild: closing often happens because a panel control
    // was just clicked, and rebuilding it mid-click swallowed that click.
    saveTypesetting(id, true, {lines}, true, before);
  }
  drawText();
}


/* ---- the outline's own gradient, in the preview ----

   CSS will not put a gradient on a text stroke: `background-clip:text` paints
   the FILL area and leaves `-webkit-text-stroke` exactly the colour it was
   given (measured in Chromium, not assumed). So the ring is drawn as a stack
   of solid-coloured copies, each clipped to one slab across the block, and the
   steps read as a ramp. The exported page draws the real thing through the
   ring's own mask — see `edge2` in render.py.

   The slabs run across the WHOLE block, not per line, so a two-line shout
   fades once from top to bottom rather than twice. */
const EDGE_BANDS = 16;
function _mixHex(a, b, t){
  const p=h=>[1,3,5].map(i=>parseInt(h.substr(i,2),16));
  const A=p(a), B=p(b);
  return '#'+A.map((v,i)=>Math.round(v+(B[i]-v)*t)
    .toString(16).padStart(2,'0')).join('');
}
function paintEdgeGradient(g, from, to, angle, strokePx){
  const rings=[...g.querySelectorAll('.ts.egrad')];
  if(!rings.length) return;
  const rad=angle*Math.PI/180;
  const tx=Math.sin(rad), ty=Math.cos(rad);
  // Every ring's own box, in the group's coordinates. `.ts` sits at the top
  // left of its host, and the host is what is centred — so the host is what
  // carries the position.
  const boxOf=el=>{
    const h=el.parentElement;
    const w=h.offsetWidth, ht=h.offsetHeight;
    return {x:h.offsetLeft-w/2, y:h.offsetTop-ht/2, w, h:ht};
  };
  let pmin=1e9, pmax=-1e9;
  rings.forEach(el=>{
    const b=boxOf(el);
    [[b.x,b.y],[b.x+b.w,b.y],[b.x,b.y+b.h],[b.x+b.w,b.y+b.h]]
      .forEach(([x,y])=>{ const p=x*tx+y*ty;
        pmin=Math.min(pmin,p); pmax=Math.max(pmax,p); });
  });
  const span=Math.max(1e-6, pmax-pmin);
  rings.forEach(el=>{
    const b=boxOf(el);
    const base=b.x*tx+b.y*ty;          // projection of the ring's own origin
    const BIG=(b.w+b.h)*2+200;
    const parent=el.parentElement;
    const frag=document.createDocumentFragment();
    for(let k=0;k<EDGE_BANDS;k++){
      const lo=pmin+span*k/EDGE_BANDS-base;
      const hi=pmin+span*(k+1)/EDGE_BANDS-base;
      // A slab is a quad: its centre line, pushed out sideways far enough to
      // cover the box whichever way the ramp runs.
      const mid=(lo+hi)/2, half=(hi-lo)/2;
      const cx=mid*tx, cy=mid*ty;            // a point with this projection
      const ax=tx*half, ay=ty*half;          // along the ramp
      const px=-ty*BIG, py=tx*BIG;           // across it
      const pts=[[cx-ax+px,cy-ay+py],[cx+ax+px,cy+ay+py],
                 [cx+ax-px,cy+ay-py],[cx-ax-px,cy-ay-py]];
      const band=el.cloneNode(true);
      band.classList.remove('egrad');
      band.classList.add('eband');
      band.style.webkitTextStroke=
        `${strokePx}px ${_mixHex(from, to, (k+0.5)/EDGE_BANDS)}`;
      band.style.clipPath='polygon('+
        pts.map(([x,y])=>`${x.toFixed(1)}px ${y.toFixed(1)}px`).join(',')+')';
      frag.appendChild(band);
    }
    parent.replaceChild(frag, el);
  });
}
