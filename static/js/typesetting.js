/* typesetting.js - Per-bubble @font-face loading, drawText() canvas render, on-canvas text editing.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */

/* Fonts picked per bubble are loaded on demand, one @font-face per file. */
let fontFams={};
/* One colour, read the way the panel reads it.

   This was `ov.x || st.x` - the SAVED override first, the live style second -
   so a colour the person had just turned off went on being drawn: `st.fg2`
   was `''`, which `||` skips straight past, and `ov.fg2` still held the old
   value until a round trip that would never carry an empty one.
   lee: *"ehen i turn off teh gradient it donts accualy turn off"*.

   `??` and the live style first, which is what `styleNow` in panels.js does.
   An empty string is an answer - it means off - and only "not set at all"
   falls through to the override. */
function pick(st, ov, key){
  const v = (st||{})[key] ?? (ov||{})[key] ?? '';
  return v || '';
}

/* The same question for a NUMBER, and it has to be asked in the same order.

   `pick` reads the live style first and the saved override second, because
   the live style is what you are editing right now. Every number on the panel
   used to be read the other way round - `ov.glow_size ?? st.glow_size` - so a
   size that had ever been saved could never be changed again: you typed 20,
   the panel said 20, the patch carried 20, the server answered 20, and the
   preview went on drawing the 6 in the saved override. Colours changed as you
   typed and numbers did not, on the same row of the same panel.

   lee: *"the outer glow is tsill not changing size in teh editor"*.

   `''` counts as "not said" and falls through, which is what an emptied field
   sends; a real 0 does not, because 0 is an answer. */
function num(st, ov, key, dflt){
  const v = (st||{})[key] ?? (ov||{})[key];
  const n = (v === '' || v === null || v === undefined) ? NaN : +v;
  return isNaN(n) ? dflt : n;
}

/* A colour that draws nothing.

   Two spellings reach this side: `rgba(...,0)`, which is what the server's
   `_css_rgba` sends the preview, and `#rrggbb00`, which is what the picker's
   "no fill" swatch writes (`render.NO_FILL`) and what `assign_colours` hands
   back for it. Both mean the same thing and both have to be recognised, or
   half the app thinks a block is empty and the other half draws it solid. */
function noInk(c){
  c=(c||'').trim();
  return /rgba\([^)]*,\s*0(\.0+)?\)\s*$/.test(c) || /^#[0-9a-f]{6}00$/i.test(c);
}

/* THE FILL AND THE RIM, WORKED OUT ONCE.

   Three places need this pair - the drawing, the box you type in, and the
   ring round the box you type in - and they each had their own copy. They
   disagreed: the drawing read `ov.fg` first and the editor read `st.fg`, so
   clicking a block whose ink was MEASURED changed its colour on the way in.
   lee: *"fix teh issue of when i clcik a box and teh text color change it
   shodu always be teh same"*.

   Same rule as `render.colours_for` + `render._hollow_colours` on the server:
   a hollow block has no fill and its rim is the ink. */
function inkPair(r, L, ss){
  const st=r.style||{}, ov=styleOf(r);
  // Level 1 alone - what a PERSON set. `render.hand_style` is the same list
  // on the other side, and hollow may overrule the automatic choice for the
  // fill and the rim but never a hand one.
  //
  // `ss` is a SPAN's style - part of the text restyled by itself - and it
  // outranks everything: within its own characters it is the hand edit.
  const hand=r.layout_override||{};
  // THE LIVE STYLE FIRST, the saved override second - `pick`'s order, and
  // for `pick`'s reason: `r.style` is the panel as it stands right now and
  // `layout_override` is the last answer the SERVER wrote. These two lines
  // were the one place that read them the other way round, so a colour
  // picked on a block that had ever been saved kept painting the old one
  // until the round trip came back and rewrote the override - measured at
  // 660ms against a 4ms redraw, and forever when the request never landed.
  // lee: *"changing the color of teh etxt take a long time now"*, *"the
  // color doesnt change until i change page and go back or reload"*.
  const inkc=(ss&&ss.fg)||pick(st,ov,'fg')||L.fg||'#000';
  const hollow=!!ov.hollow;
  const fill=hollow?'rgba(0,0,0,0)':inkc;
  // ...and an outline set by hand wins too, for on a hollow block the outline
  // is all there is. lee: *"teh outline color donet do anything even thoug
  // teh outline is what is left"*. The ink is the fallback, not the rule: an
  // AUTOMATIC edge is a halo, and a hollow letter drawn in a halo colour is
  // nothing on the page at all.
  const set=(ss&&ss.edge)||hand.edge||'';
  const rim=hollow?((set && !noInk(set))?set:inkc)
                  :((ss&&ss.edge)||pick(st,ov,'edge')||L.edge||'#fff');
  const sw=Math.max(0,((ss&&ss.stroke)??st.stroke??L.stroke??1))*scale;
  return {fill, rim, sw, hole:noInk(fill)};
}

/* The character ranges of a block that carry their own style - lee:
   *"allow teh user to modify spesifuica part of a text box"*. Offsets index
   the flat text of the laid-out lines joined with newlines, the same
   convention `render._spans_of` reads. */
function spansOf(r, L){
  const raw=(r.layout_override||{}).spans;
  if(!Array.isArray(raw) || !raw.length) return null;
  const n=(L.lines||[]).reduce((a,l)=>a+l.length,0)
        + Math.max(0,(L.lines||[]).length-1);
  const out=[];
  raw.slice(0,200).forEach(sp=>{
    if(!sp || typeof sp!=='object') return;
    const s0=Math.max(0, sp.s|0), e0=Math.min(n, sp.e|0);
    const st=sp.st;
    if(e0>s0 && st && typeof st==='object' && Object.keys(st).length)
      out.push([s0, e0, st]);
  });
  return out.length?out:null;
}

/* One line's text divided into runs of constant effective style:
   [{c0, c1, ss}] with ss null for the block's own style. `base` is the
   line's offset into the flat text. */
function lineRuns(line, base, spans){
  const runs=[];
  let runS=0, cur=null, curKey='';
  const keyAt=i=>{
    let st=null;
    for(const [s0,e0,sst] of spans)
      if(s0<=base+i && base+i<e0) st=Object.assign(st||{}, sst);
    return [st, st?JSON.stringify(st):''];
  };
  let [curSt, ck]=keyAt(0); cur=curSt; curKey=ck;
  for(let i=1;i<=line.length;i++){
    const [st2,k2]=(i<line.length)?keyAt(i):[null,'\0end'];
    if(k2===curKey) continue;
    runs.push({c0:runS, c1:i, ss:cur});
    runS=i; cur=st2; curKey=k2;
  }
  return runs;
}

/* A LETTERFORM THAT IS ONLY A LINE, drawn the way the exporter draws it.

   This is the one part of the preview that is not CSS, and the reason is
   exact: PIL's `stroke_width` grows OUTWARD from the glyph, and
   `-webkit-text-stroke` is CENTRED on it. On a block with a fill the inner
   half is covered and nobody can tell; on a block with nothing inside it the
   inner half IS the hole, and at six pixels on 54pt letters it closes the
   letter. CSS has no way to take a glyph body out of a stroke - there is no
   Porter-Duff in `mix-blend-mode` and no inner shadow for text.

   SVG has masks, so: stroke at TWICE the width, mask out the glyph body, and
   what is left is the outward half alone. That is the shape the page gets.

   The three passes, in the order they are painted:

   * the OUTER glow - the same trick, stroked wider still and masked to the
     paper outside the letters, then blurred, which is `render_page`'s "the
     ring is grown and blurred and then cut back to the paper outside";
   * the INNER glow - stroked wider and masked to the glyph body instead, so
     the light falls into the hole. This is the half the CSS preview could not
     draw at all, and the reason the note by `igc` used to say the two
     deliberately part;
   * the rim itself, on top of both.

   Sizing: the box is the text's own width and a line box's height, measured
   through the same canvas every other measurement in this file goes through,
   and the SVG is the only child of a host that is already centred on the
   line's origin - so the text's middle lands where PIL's `anchor="mm"` puts
   it. `overflow: visible` because the glow reaches past the box on purpose. */
let hollowN = 0;
const SVGNS = 'http://www.w3.org/2000/svg';

function hollowInk(txt, fam, size, ls, sw, colour, glow, iglow){
  const px = emPx(size, fam);
  const w = Math.max(1, textW(fam, size, txt) + ls * Math.max(0, txt.length - 1));
  const h = Math.max(1, px * 1.35);
  const pad = Math.ceil(sw * 2 + (glow ? glow.px * 2.5 : 0) + 4);
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('class', 'thollow');
  svg.setAttribute('width', w.toFixed(1));
  svg.setAttribute('height', h.toFixed(1));
  svg.style.overflow = 'visible';
  svg.style.display = 'block';
  const uid = 'hk' + (++hollowN);

  const at = (fill, stroke, width) => {
    const t = document.createElementNS(SVGNS, 'text');
    t.setAttribute('x', (w / 2).toFixed(2));
    t.setAttribute('y', (h / 2).toFixed(2));
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('dominant-baseline', 'central');
    t.setAttribute('font-family', fam + ',sans-serif');
    t.setAttribute('font-size', px.toFixed(2));
    if(ls) t.setAttribute('letter-spacing', ls.toFixed(2));
    t.setAttribute('fill', fill);
    if(stroke){
      t.setAttribute('stroke', stroke);
      t.setAttribute('stroke-width', width.toFixed(2));
      t.setAttribute('stroke-linejoin', 'round');
    }
    t.textContent = txt;
    return t;
  };
  // A mask that is the page MINUS the letters (`out`), and one that is the
  // letters alone (`in`). Every pass below is cut to one of the two.
  const defs = document.createElementNS(SVGNS, 'defs');
  const box = {x: (-pad).toFixed(1), y: (-pad).toFixed(1),
               width: (w + pad * 2).toFixed(1),
               height: (h + pad * 2).toFixed(1)};
  for(const ground of ['#fff', '#000']){
    const m = document.createElementNS(SVGNS, 'mask');
    m.setAttribute('id', uid + (ground === '#fff' ? 'out' : 'in'));
    m.setAttribute('maskUnits', 'userSpaceOnUse');
    for(const k in box) m.setAttribute(k, box[k]);
    const bg = document.createElementNS(SVGNS, 'rect');
    for(const k in box) bg.setAttribute(k, box[k]);
    bg.setAttribute('fill', ground);
    m.appendChild(bg);
    m.appendChild(at(ground === '#fff' ? '#000' : '#fff', null, 0));
    defs.appendChild(m);
  }
  svg.appendChild(defs);

  const soft = (g, mask, grow) => {
    const t = at('none', g.colour, (sw + grow) * 2);
    t.setAttribute('mask', `url(#${uid}${mask})`);
    // A CSS blur radius is about twice a Gaussian sigma, and `render_page`
    // blurs its ring by roughly half the size - so half of the size here.
    t.style.filter = `blur(${Math.max(0.4, g.px * 0.5).toFixed(1)}px)`;
    svg.appendChild(t);
  };
  if(glow) soft(glow, 'out', glow.px);
  if(iglow) soft(iglow, 'in', iglow.px);

  const rim = at('none', colour, sw * 2);
  rim.setAttribute('mask', `url(#${uid}out)`);
  svg.appendChild(rim);
  return svg;
}

function fontFam(path, kind){
  if(!path) return `'ml-${kind||'bubble'}'`;
  if(!fontFams[path]){
    const fam='mlp'+Object.keys(fontFams).length;
    fontFams[path]=fam;
    // ...and the way back. A measuring site carries a family name and nothing
    // else, and `capOfFam` needs the FILE to look up the cap height the server
    // measured. See `project.FAM_PATH`.
    if(typeof FAM_PATH==='object' && FAM_PATH) FAM_PATH[fam]=path;
    const url=`url("/fontfile?p=${encodeURIComponent(path)}")`;
    // once the face is available the canvas typesetting repaints in it (the
    // font DROPDOWNS use server-rendered images, so they need no refresh)
    const done=()=>{ if(typeof drawOverlay==='function') drawOverlay(); };
    // The CSS Font Loading API is the reliable way to load a font by URL and
    // KNOW when it's ready - the browser sniffs the format from the bytes, so
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

/* Where each letter of a curved line goes - the browser's copy of
   `render.arc_places`. `curve` is the whole angle the line subtends in degrees,
   positive arching up like a rainbow. The radius comes from the arc length, and
   half the sagitta is taken back off so the bend keeps the line where the
   fitter put it instead of hanging the whole arch below it.

   Kept in step with the Python by `test_the_two_arcs_agree`, which runs both
   over the same line and compares every letter's place. */
function arcPlaces(line, fam, size, lspace, curve, x, y, kind){
  const w=[...line].map(ch=>textW(fam,size,ch));
  const total=w.reduce((a,b)=>a+b,0)+lspace*Math.max(0,line.length-1);
  kind=kind||'arch';
  if(kind==='wave'||kind==='rise'){
    // `curve` is the STEEPEST slope in degrees (capped short of vertical);
    // a wave is one S along the line, a rise is a straight slant with the
    // letters kept upright. The same arithmetic is in `render.arc_places`,
    // and a test compares the two, kind by kind.
    const dg=Math.max(-75,Math.min(75,+curve||0));
    if(total<=0 || Math.abs(dg)<1e-4) return [];
    const slope0=Math.tan(dg*Math.PI/180);
    const out=[]; let s=-total/2;
    [...line].forEach((ch,i)=>{
      const u=s+w[i]/2, t=(u+total/2)/total;
      let cy=y, deg=0;
      if(kind==='wave'){
        const A=total*slope0/(2*Math.PI);
        cy=y-A*Math.sin(2*Math.PI*t);
        deg=Math.atan(-slope0*Math.cos(2*Math.PI*t))*180/Math.PI;
      } else {
        cy=y-u*slope0;
      }
      out.push({x:x+u, y:cy, deg:deg, ch:ch, adv:w[i]});
      s+=w[i]+lspace;
    });
    return out;
  }
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

/* ONE STYLE, WORKED OUT ONCE - the block's own, or the block's with a
   SPAN's overlay on top, which is how part of the text wears its own
   colours and effects (lee: *"allow teh user to modify spesifuica part of
   a text box"*). A span's value wins over everything, exactly as
   `render._ink_layer` reads it. Used by `drawText` and by the box you
   type into, so the two can never disagree about what a run wears. */
function runStyle(r, L, ss){
      const st=r.style||{}, ov=styleOf(r);
      const pk=(key)=>{const v=ss?ss[key]:undefined;
        return (v===undefined||v===null||v==='')?pick(st,ov,key):String(v);};
      const nm=(key,dflt)=>{const v=ss?ss[key]:undefined;
        const n=(v===''||v===null||v===undefined)?NaN:+v;
        return isNaN(n)?num(st,ov,key,dflt):n;};
      const {fill:fg, rim:edge, sw, hole}=inkPair(r,L,ss);
      const shc=pk('shadow');
      const shOn=/^#[0-9a-f]{6}$/i.test(shc);
      const shD=nm('sh_dist',2)*scale*0.707;
      const shB=nm('sh_blur',3)*scale;
      // the layout as the last word for the glows, which is where an
      // AUTOMATIC halo arrives (`render.auto_glow`) - a glow somebody chose,
      // or turned off, wins above; eight digits count (an automatic halo has
      // an alpha under full) and `noInk` is where "off" is asked.
      const glc=pk('glow') || (L.glow||'');
      const glOn=/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(glc) && !noInk(glc);
      const glS=nm('glow_size',(+L.glow_size||6))*scale;
      const igc=pk('iglow') || (L.iglow||'');
      const igOn=/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(igc) && !noInk(igc);
      const igS=nm('iglow_size',(+L.iglow_size||5))*scale;
      // EVERY SHADOW AND GLOW ON SPANS OF THEIR OWN, at the bottom of the
      // stack, drawn the way the EXPORT draws them: the letters STROKED FAT
      // (`-webkit-text-stroke` = PIL `stroke_width`) and GAUSSIAN BLURRED
      // (`filter: blur()`, whose length is a standard deviation, PIL's own
      // unit). `text-shadow` is inherited and rings of copies are
      // uncalibratable - both designs died measured. Bottom-up, in the
      // export's compositing order: the shadow, then the glow over it.
      const fx=[];
      if(shOn){
        // `render_page`: `draw_line(..., fill=shcol, stroke_width=stroke,
        // stroke_fill=shcol)` then `GaussianBlur(blur)`.
        fx.push({cls:'tshadow', colour:shc, strokePx:2*sw,
                 dx:shD, dy:shD, blur:shB, passes:1});
      }
      if(glOn && !hole){
        // the silhouette grown by `stroke + spread`, blurred by 0.55 of the
        // size - a CHOSEN glow composited twice, an AUTOMATIC one once.
        const spread=Math.max(1, Math.round(glS));
        const ga=(glc.length===9)?parseInt(glc.slice(7,9),16):255;
        fx.push({cls:'tglow', colour:glc, strokePx:2*(sw+spread),
                 dx:0, dy:0, blur:glS*0.55, passes:(ga>=255)?2:1});
      }
      const g2v=pk('fg2');
      const grad=/^#[0-9a-f]{6}$/i.test(g2v);
      const g1v=pk('fg1');
      const gFrom=/^#[0-9a-f]{6}$/i.test(g1v)?g1v:fg;
      const gang=nm('grad_angle',0);
      // ...and the same three for the ring round the letters.
      const e2v=pk('edge2');
      const egrad=/^#[0-9a-f]{6}$/i.test(e2v) && sw>0;
      const e1v=pk('edge1');
      const eFrom=/^#[0-9a-f]{6}$/i.test(e1v)?e1v:edge;
      const eang=nm('edge_angle',0);
      // THE METRICS OF THIS RUN - the face it is set in and how big.
      //
      // A span may now carry these, which is the one thing that makes a run
      // take up a different amount of room from its neighbours. lee: *"the
      // changing size and fonts happens to teh whole etxt box instead fo
      // just the selevcted text"*. `font_size` is the NOMINAL size, the
      // number the panel shows and the server stores; `emPx` turns it into
      // the pixel size the face is asked for.
      const fam=fontFam((ss&&ss.font)||ov.font||st.font||L.font, r.kind);
      const fsz=((ss&&ss.font_size)?+ss.font_size:0)
                || num(st,ov,'font_size',L.font_size||14);
      const size=fsz*scale;
      // THE RUN'S OWN TRANSPARENCY - a range may carry one, and its value
      // REPLACES the block's for its own characters, exactly as every
      // other range key does. 0-100, the number the panel's slider shows.
      const op=Math.max(0,Math.min(100,nm('opacity',100)));
      return {fg,edge,sw,hole,fx,glOn,glc,glS,igOn,igc,igS,
              grad,gFrom,g2v,gang,egrad,eFrom,e2v,eang,fam,size,op};
}

/* THERE ARE NO BANDS.

   Three functions used to live here - `mixedMetrics`, `inkReach` and
   `styleCuts` - and between them they implemented the other way of drawing
   a line that carries spans: paint the WHOLE line once per style, then cut
   the copies into vertical bands at the glyph boundaries so that each copy
   shows only over the characters that wear its style.

   The cut was taken off the browser's own typesetting (a `Range` over an
   invisible sizer span) rather than off a canvas, and that fixed a real
   two-pixel error; but the model itself is wrong at any precision. A
   letter's ink is not inside its advance box - the diagonal of an A
   overhangs both ways, and a heavy sound-effect face overhangs a long way -
   so a vertical cut ANYWHERE near the boundary slices through the ink of
   the glyph beside it, and the letter comes out with a hard seam down it,
   half in one colour and half in the other. lee photographed it twice and
   then named the whole thing in one line: *"it shoud apply to the letter it
   self and not a box behiod teh letter"*. A band IS a box behind the
   letter.

   So every span goes down the flow path now - run after run, each drawn as
   its own letters, sharing one baseline - which is what `drawText`,
   `editInkMirror` and `render.flow_runs` all do, and the only thing they
   do. Nothing is clipped, so a colour can only ever land on the characters
   that carry it. */

/* ONE RUN OF TEXT, INKED. The five layers, in the order the exporter
   composites them: the shadow and glow passes underneath, then the
   outline, then the fill, then the inner glow.

   This was written TWICE - `inked` inside `drawText` for the page, and
   `stack` inside `editInkMirror` for the box you type into - 146 lines
   saying one thing in two spellings, with the positioning expressed as
   classes on one side and inline styles on the other. Every change to how
   ink is drawn had to be made in both, and the times it was only made in
   one are exactly the times the page and the box disagreed. lee has
   reported that disagreement in four different shapes.

   `ctx` is the little the two callers really differ by:
     fam, size, ls   the block's face and metrics, for the hollow rim
     fill            whether to paint the fill at all. The mirror leaves it
                     to the box's own text when the block has no ranges -
                     the box is only transparent once a range takes over.

   The host needs the `ink` class; the CSS for these five lives there. */
function inkRun(host, txt, S, ctx){
  const fam=ctx.fam, size=ctx.size, ls=ctx.ls;
  // the shadow and glow spans, FIRST, so everything else paints over
  // them - and never by inheritance, which is what once repainted a
  // red shadow on every span above them
  S.fx.forEach(f=>{
    for(let pass=0; pass<f.passes; pass++){
      const e=document.createElement('span');
      // a hollow block's letters are drawn centred in their SVG, so
      // its effects are centred the same way or they fall off the glyphs
      const centred=(S.hole && S.sw>0);
      e.className='tsh '+f.cls+(centred?' tshc':'');
      e.textContent=txt;
      e.style.cssText=
        (f.strokePx>0?`-webkit-text-stroke:${f.strokePx.toFixed(1)}px `+
                      `${f.colour};`:'')+
        `-webkit-text-fill-color:${f.colour};color:${f.colour};`+
        (f.blur>0?`filter:blur(${f.blur.toFixed(1)}px);`:'')+
        (centred
          ?`transform:translate(calc(-50% + ${f.dx.toFixed(1)}px),`+
           `calc(-50% + ${f.dy.toFixed(1)}px));`
          :((f.dx||f.dy)
            ?`transform:translate(${f.dx.toFixed(1)}px,`+
             `${f.dy.toFixed(1)}px);`:''));
      host.appendChild(e);
    }
  });
  if(S.hole && S.sw>0){
    // NOTHING INSIDE, SO THE RIM IS DRAWN IN SVG AND NOT IN CSS. PIL
    // grows `stroke_width` OUTWARD; a CSS stroke is CENTRED, and with
    // nothing behind it the inward half closes the letter. SVG has
    // masks: stroke at TWICE the width, take the glyph body out, and the
    // outward half alone remains - the shape PIL draws. See `hollowInk`,
    // and the glow/inner glow ride its masks too.
    host.appendChild(hollowInk(txt, fam, size, ls, S.sw, S.edge,
                               S.glOn?{colour:S.glc, px:S.glS}:null,
                               S.igOn?{colour:S.igc, px:S.igS}:null));
    return;
  }
  let front=null;
  if(S.sw>0){
    // A real stroke behind a clean fill: the outline only grows OUTWARD
    // from the letters. With an outline GRADIENT there are EDGE_BANDS of
    // these, each a solid stroke in its own step of the ramp - CSS has no
    // gradient for a text stroke, and sixteen steps join under two grey
    // levels on a full-length ramp. See `paintEdgeGradient`.
    const back=document.createElement('span');
    back.className='ts';
    back.textContent=txt;
    back.style.webkitTextStroke=`${2*S.sw}px ${S.edge}`;
    if(S.egrad){
      back.classList.add('egrad');
      back.dataset.e1=S.eFrom; back.dataset.e2=S.e2v;
      back.dataset.eang=S.eang; back.dataset.esw=(2*S.sw).toFixed(1);
    }
    host.appendChild(back);
  }
  if(ctx.fill!==false){
    front=document.createElement('span');
    front.className='tf';
    front.textContent=txt;
    host.appendChild(front);
    // the fill's own colour or its gradient - painted ON the fill span,
    // over the outline, exactly as the exporter composites it. An inline
    // colour would beat the gradient class's transparent fill, so a
    // gradient-wearing span gets no inline colour at all.
    if(S.grad){
      front.classList.add('grad');
      front.dataset.g1=S.gFrom; front.dataset.g2=S.g2v;
      front.dataset.gang=S.gang;
    }else{
      front.style.color=S.fg;
      front.style.webkitTextFillColor=S.fg;
    }
  }
  if(S.igOn && !S.hole){
    // Inner glow: no CSS for light inside a letter, so a soft rim ON the
    // edge - the one place the preview and the page deliberately part. A
    // hollow block's is already inside `hollowInk`'s masks.
    const e=document.createElement('span');
    e.className='tg';
    e.textContent=txt;
    e.style.webkitTextStroke=
      `${Math.max(1,S.igS*0.5).toFixed(1)}px ${S.igc}`;
    e.style.webkitTextFillColor='transparent';
    e.style.filter=`blur(${Math.max(0.5,S.igS*0.3).toFixed(1)}px)`;
    host.appendChild(e);
  }
}

/* THE RAMPS - a fill gradient and an outline gradient, painted across the
   WHOLE BLOCK rather than per letter, so the fade runs unbroken from one
   side of the words to the other.

   Pulled out of `drawText` so the mirror under the caret can call it too.
   It could not before: the box's own copy of the ink wrote a per-run
   `linear-gradient` inline, which is a different fade from the block-wide
   one the page and the export draw - so a gradient looked one way while
   you typed and another the moment you clicked away, and an OUTLINE
   gradient did not show in the box at all. One function, both places. */
/* WHERE AN ELEMENT SITS INSIDE THE BLOCK, as a centre point.

   Two shapes have to answer this: a line on the page, which is pulled back
   by half its own size (`translate(-50%,-50%)`), so its `offsetLeft` IS its
   centre; and a row in the mirror, which is an ordinary flow box whose
   offset is its top left. The offsets are accumulated up to the group
   either way, because a RUN's are measured from its line and not from the
   block - which is what made the ramp on a resized word start from the
   line's left edge and jump at the word. */
function centreIn(g, el, centred){
  let x=0, y=0, n=el;
  while(n && n!==g){ x+=n.offsetLeft; y+=n.offsetTop; n=n.offsetParent; }
  x+=el.offsetWidth/2; y+=el.offsetHeight/2;
  const tl=centred && el.closest && el.closest('.tl');
  if(tl){ x-=tl.offsetWidth/2; y-=tl.offsetHeight/2; }
  return {x:x, y:y};
}

/* THE RAMPS - a fill gradient and an outline gradient, painted across the
   WHOLE BLOCK rather than per letter, so the fade runs unbroken from one
   side of the words to the other.

   Pulled out of `drawText` so the mirror under the caret can call it too.
   It could not before: the box's own copy of the ink wrote a per-run
   `linear-gradient` inline, which is a different fade from the block-wide
   one the page and the export draw - so a gradient looked one way while
   you typed and another the moment you clicked away, and an OUTLINE
   gradient did not show in the box at all. One function, both places.

   `centred` says which of the two shapes the caller has: the page's lines
   are centred on their origins, the mirror's rows are not. */
function paintRamps(g, size, fam, centred){
  // Each gradient-wearing fill span carries its colours and angle in data
  // attributes; the ramp spans the union of the block's lines, offset per
  // element so the fade runs unbroken - and padded past the em box,
  // because ink overhangs it and a background stops at the element's box
  // (lee's "!", *"the gradient is still broke at teh corner"*).
  const gtfs=[...g.querySelectorAll('.tf.grad')];
  if(gtfs.length){
    const gpad=Math.ceil(emPx(size,fam)*0.6);
    const hostOf=(tf)=>tf.closest('.tc')||tf.closest('.trunf')
      ||tf.closest('.trun')||tf.closest('.tl')||tf.closest('.ink')
      ||tf.parentElement;
    // ONE RAMP PER STYLE, spanning that style's OWN letters - which is
    // exactly what the export does (`render._ink_layer` fades over the
    // bbox of the style's own mask). A block-wide gradient still fades
    // block-wide: every line carries the same colours, so the group is
    // the whole block. A RANGE's gradient fades across the RANGE: its
    // group is its own runs. It used to fade across the whole block
    // whoever carried it, so a selected middle word showed only the
    // middle blend of the ramp - lee: *"gradient ... still universal"* -
    // while the exported page faded it edge to edge across the word.
    const groups=new Map();
    gtfs.forEach(tf=>{
      const k=(tf.dataset.g1||'')+'|'+(tf.dataset.g2||'')+'|'
              +(tf.dataset.gang||0);
      if(!groups.has(k)) groups.set(k, []);
      groups.get(k).push(tf);
    });
    groups.forEach(list=>{
      let bx0=1e9,by0=1e9,bx1=-1e9,by1=-1e9;
      list.forEach(tf=>{
        const el=hostOf(tf);
        const c=centreIn(g, el, centred);
        const w=el.offsetWidth,h=el.offsetHeight;
        bx0=Math.min(bx0,c.x-w/2); by0=Math.min(by0,c.y-h/2);
        bx1=Math.max(bx1,c.x+w/2); by1=Math.max(by1,c.y+h/2);
      });
      list.forEach(tf=>{
        const ga=+tf.dataset.gang||0;
        const rad=ga*Math.PI/180;
        const tx=Math.sin(rad), ty=Math.cos(rad);
        const ps=[bx0*tx+by0*ty, bx1*tx+by0*ty, bx0*tx+by1*ty, bx1*tx+by1*ty];
        const pmin=Math.min(...ps), pmax=Math.max(...ps);
        // App angle: 0 = top to bottom, clockwise. CSS points the other way
        // round, hence the 180-a.
        const css=((180-ga)%360+360)%360;
        const padj=gpad*(Math.abs(tx)+Math.abs(ty));
        const el=hostOf(tf);
        const w=el.offsetWidth,h=el.offsetHeight;
        const Lg=Math.abs(w*tx)+Math.abs(h*ty);
        const c=centreIn(g, el, centred);
        const pS=c.x*tx+c.y*ty-Lg/2;
        tf.style.padding=`${gpad}px`;
        tf.style.margin=`0 -${gpad}px`;
        tf.style.backgroundImage=`linear-gradient(${css}deg,`+
          `${tf.dataset.g1} ${(pmin-pS+padj).toFixed(1)}px,`+
          `${tf.dataset.g2} ${(pmax-pS+padj).toFixed(1)}px)`;
      });
    });
  }
  paintEdgeGradient(g);
}

function drawText(){
  const o=$('overlay');
  // THE ONE CHOKE POINT. Every redraw of the typesetting is a moment the page
  // may have changed - an edit, a zoom, a selection, a page turn - so the
  // exported page goes off the screen here and is asked for again a moment
  // later, once. Guarded because this file loads before that one.
  if(typeof exactOff === 'function') exactOff();
  // every redraw is also the moment the page's typesetting can have appeared or
  // gone, so the switch that hides it follows along here
  if(typeof syncTextToggle==='function') syncTextToggle();
  o.innerHTML='';
  o.classList.toggle('on', inText());
  if(!inText()){
    drawFrame();
    if(typeof exactSoon === 'function') exactSoon();
    return;                              // also puts the frame away
  }
  regions.forEach(r=>{
    const L=r.layout;
    if(!L||!L.lines) return;
    if(r._hideText) return;              // its layer-eye is switched off
    if(!L.lines.length){
      // A block with nothing in it. Nothing is drawn on the exported page -
      // it is empty - but on screen it gets a dashed outline where it stands,
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
    // `styleOf`, not the override alone: the MEASURED style lives in its own
    // field now (`layout_measured`) and the preview has to read the same two
    // in the same order the exporter does. See `render.style_of`.
    const ov=styleOf(r);
    // WRITING DRAWN AS AN OUTLINE has no fill, and the line is the ink.
    //
    // `inkstyle` measures both off the original page and leaves `hollow` and
    // the ink colour in `layout_measured`; the exporter reads them in
    // `render._hollow_colours`. This is the same rule on this side, and it
    // has to be here rather than left to the colours the server sends: the
    // fill below prefers `ov.fg`, which IS that measured ink colour, so a
    // hollow block would have come out solid in the preview and outlined on
    // the exported page.
    const size=L.font_size*scale;
    const fam=fontFam(ov.font||st.font||L.font, r.kind);
    const ls=num(st,ov,'lspace',0)*scale;
    const opv=num(st,ov,'opacity',100);
    const op=Math.max(0,Math.min(100,isNaN(opv)?100:opv))/100;
    const crv=num(st,ov,'curve',0);
    const ckd=pick(st,ov,'curve_kind')||'arch';
    if(editing===r.id) return;              // being typed into right now
    const rot=+(L.rotate||0);
    const fr=frameOf(r);
    const styFor=(ss)=>runStyle(r, L, ss);
    const bs=styFor(null);
    const spans=spansOf(r,L);
    const flatBase=[]; {let fo=0; L.lines.forEach(l=>{flatBase.push(fo); fo+=l.length+1;});}
    // One group per block, sized to the text's frame (plus slack so
    // overhanging lines keep their paint) and rotated as a whole about its
    // centre - the same thing the exporter does.
    const P=48;
    const gx=fr[0]*scale-P, gy=fr[1]*scale-P;
    const g=document.createElement('div');
    g.className='tgrp';
    g.style.cssText=`position:absolute;left:${gx}px;top:${gy}px;`+
      `width:${fr[2]*scale+2*P}px;height:${fr[3]*scale+2*P}px;`+
      (rot?`transform:rotate(${-rot}deg);`:'')+
      // Transparency belongs to the whole block, exactly as it does in the
      // export, where it scales one layer's alpha after everything is
      // drawn - UNLESS the block carries spans, because a range may have a
      // transparency of its own that REPLACES the block's over its own
      // characters. Then every run wears its own effective number (the
      // range's, or the block's where no range says otherwise) and the
      // group stays opaque, exactly as the export fades style by style.
      (op<1 && !spans?`opacity:${op};`:'');
    // one letter (or one run's copy of the line), inked in one style
    // one run, inked - the same function the mirror under the caret
    // draws with, so the page and the box cannot drift apart
    const inked=(host,txt,S)=>inkRun(host, txt, S,
                                     {fam:fam, size:size, ls:ls});
    L.lines.forEach((line,k)=>{
      const d=document.createElement('div');
      d.className='tl ink'+(crv?' tlcurve':'');
      d.dataset.id=r.id;
      // A curved line is not one text node: every letter has its own place
      // on the arc and its own turn, so it gets its own span - which is
      // also how part of a curved line wears a span's style: letter by
      // letter, no clipping needed.
      d.style.cssText=(crv?`left:0;top:0;transform:none;`
                          :`left:${org[k][0]*scale-gx}px;top:${org[k][1]*scale-gy}px;`)+
        `font-family:${fam},sans-serif;font-size:${emPx(size,fam).toFixed(2)}px;`+
        (ls?`letter-spacing:${ls}px;`+
            // CSS adds a trailing gap after the last letter; nudge back so
            // the glyphs themselves stay centred, matching the export
            `transform:translate(calc(-50% + ${ls/2}px),-50%);`:'')+
        `color:${bs.fg};`;
      const styCache={};
      const styOfChar=(i)=>{
        if(!spans) return bs;
        let sst=null;
        for(const [s0,e0,x] of spans)
          if(s0<=flatBase[k]+i && flatBase[k]+i<e0)
            sst=Object.assign(sst||{}, x);
        if(!sst) return bs;
        const kk=JSON.stringify(sst);
        return styCache[kk]||(styCache[kk]=styFor(sst));
      };
      if(crv){
        arcPlaces(line, fam, size, ls, crv,
                  org[k][0]*scale-gx, org[k][1]*scale-gy, ckd).forEach((p,idx)=>{
          if(!p.ch.trim()) return;
          const sp=document.createElement('span');
          sp.className='tc';
          const Sc=styOfChar(idx);
          sp.style.cssText=`left:${p.x.toFixed(1)}px;top:${p.y.toFixed(1)}px;`+
            (spans && Sc.op<100?`opacity:${(Sc.op/100).toFixed(3)};`:'')+
            `transform:translate(-50%,-50%) rotate(${p.deg.toFixed(2)}deg)`;
          inked(sp, p.ch, Sc);
          d.appendChild(sp);
        });
      } else {
        const runs=spans?lineRuns(line, flatBase[k], spans):null;
        const rsty=runs?runs.map(run=>run.ss?styFor(run.ss):bs):[];
        if(!runs || (runs.length===1 && !runs[0].ss)){
          if(spans && bs.op<100) d.style.opacity=(bs.op/100).toFixed(3);
          inked(d, line, bs);
        } else {
          // PART OF THE LINE IN ITS OWN STYLE, SET RUN BY RUN.
          //
          // There used to be a second way of drawing this - paint the WHOLE
          // line once per style and cut the copies into vertical bands at
          // the glyph ADVANCES - and it was used for every span that did
          // not change the metrics.
          //
          // It cannot work. A letter's ink is not inside its advance box:
          // the diagonal of an A overhangs both ways and a heavy
          // sound-effect face overhangs a long way, so a vertical cut at
          // the advance boundary slices through the neighbouring glyph.
          // The letter comes out with a hard seam down it, half in one
          // colour and half in the other. lee photographed it twice and
          // then named it: *"it shoud apply to the letter it self and not
          // a box behiod teh letter"*. A band IS a box behind the letter.
          //
          // So: run after run, each drawn as its own letters, sharing one
          // baseline. `align-items:baseline` is the whole rule on this
          // side; the exporter accumulates the same x for the same runs
          // (`render.flow_runs`). Nothing is clipped, so a colour can only
          // land on the characters that carry it.
          d.style.display='flex';
          d.style.alignItems='baseline';
          d.style.justifyContent='center';
          d.dataset.flow='1';
          runs.forEach((run,i)=>{
            const S=rsty[i];
            const w=document.createElement('span');
            w.className='trunf';
            w.dataset.c0=run.c0; w.dataset.c1=run.c1;
            w.style.cssText='position:relative;display:inline-block;'+
              'white-space:pre;line-height:1;overflow:visible;'+
              `font-family:${S.fam},sans-serif;`+
              `font-size:${emPx(S.size,S.fam).toFixed(2)}px;`+
              (S.op<100?`opacity:${(S.op/100).toFixed(3)};`:'')+
              `color:${S.fg};`;
            inked(w, line.slice(run.c0, run.c1), S);
            d.appendChild(w);
          });
        }
      }
      g.appendChild(d);
    });
    o.appendChild(g);
    paintRamps(g, size, fam, true);
  });
  drawFrame();
  if(typeof exactSoon === 'function') exactSoon();
}

/* ---------------- editing text on the page ---------------- */
let editing=null, editBox=null;
// The wording the editor opened on. Closing only writes anything back when
// the person actually changed it - see closeCanvasEdit.
let editWas=null;
// ...and the whole hand-edit state as it stood when the box was OPENED.
// The editor writes the wording into `layout_override` on every keystroke
// (`syncFromTextbox`) - that is what keeps the mirror and the ranges live -
// so by the time the box closes, the region carries the edit already, and a
// snapshot taken at close is a snapshot OF the edit. Which is exactly the
// bug lee reported once before: *"its not in the history so i cant undo the
// delete"*. What undo must put back is captured here, at the open.
let editBefore=null;
// When the side panel or the marks dialog was last pressed. The box closes
// on losing focus, and every control over there steals focus when it is
// really clicked - so a press that landed on the panel is not a click-out.
let panelDownAt=0;

function frameOf(r){
  const f=r.layout&&r.layout.frame;
  if(f&&f.length===4) return [f[0],f[1],f[2],f[3]];
  return derivedFrame(r);
}

/* A chapter typeset before blocks carried a box of their own has origins and
   no box. Draw the box round the WORDS - where the fitter actually put them -
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
  const ov=styleOf(r);
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
  // ANY armed tool owns the click - while a tool is in hand, text is just
  // part of the picture and must never open its editor.
  if(paintArmed()) return;                         // painting owns the click
  if(typeof zoomTool!=='undefined' && zoomTool) return;
  // Selection / transform tools own the click too - this capture-phase
  // handler used to eat every mousedown that landed on a text frame, which
  // killed the marquee, lasso, wand and fill anywhere near typesetting.
  if(typeof selTool!=='undefined' && (selTool||xf)) return;
  if(e.target.closest('#tframe')) return;         // handles look after themselves
  // ...and INSIDE it, not just ON it. A box laid out in runs - part of
  // its text in another face or another size - has the press land on a
  // run's span, not on the box; an identity check missed that, so the
  // stage took the click, called `preventDefault`, and the browser never
  // started a selection. lee: *"when theere 2 tetx with difent font in a
  // box i cant select any part of teh text aymore and none of teh edit
  // lick chnaging size works on that box"* - the second half follows from
  // the first, because every range tool needs a range. `closest`, the way
  // the `#tframe` guard two lines up has always done it.
  if(e.target.closest && e.target.closest('#canvasEdit')) return;
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
  // same rule as mousedown: an armed tool means text is not clickable -
  // a double-click mid-brushstroke used to drop you into the text editor
  if(paintArmed()) return;
  if(typeof zoomTool!=='undefined' && zoomTool) return;
  if(typeof selTool!=='undefined' && (selTool||xf)) return;
  // inside it, not just on it - see the mousedown guard. A double-click
  // on a run's span must still select that word rather than reopen the
  // editor on the block.
  if(e.target.closest && e.target.closest('#canvasEdit')) return;
  const p=pt(e);
  const id=frameAt(p.x/scale, p.y/scale);
  if(id!==null && editing!==id){
    e.preventDefault(); e.stopPropagation();
    fdrag=null;                            // a double-click is not a tiny drag
    editOnCanvas(id);
  }
});

/* WHICH CHARACTERS ARE SELECTED in the box you type into.

   All of this used to be written by hand: offsets counted by walking the
   contenteditable, an `editSel` variable kept alive across panel clicks
   because the browser throws its own selection away when focus moves, and
   a `selectionchange` listener with two guards deciding whether a collapse
   was a real click-out or a colour well stealing focus.

   The editor keeps its selection in its own state now, so none of that is
   needed: clicking a well cannot lose a range that was never the
   browser's to lose. `textbox.js` converts between the editor's positions
   and the app's flat offsets, and this is the whole of what is left. */
function editRange(){
  if(editing===null || typeof tbSelection!=='function') return null;
  return tbSelection();
}

/* The panel turns to face whatever is selected - span-capable fields show
   the range's values, blank where the range disagrees with itself. Called
   by the editor when its selection moves. */
function editSelectionMoved(){
  const r=regions.find(x=>x.id===editing);
  if(r && typeof editInkMirror==='function') editInkMirror(editBox, r);
  if(typeof renderInspector==='function') renderInspector();
  if(typeof snapshotTypesetPanel==='function') snapshotTypesetPanel();
  if(typeof gradientOwnsTheWell==='function') gradientOwnsTheWell();
}

document.addEventListener('pointerdown',(ev)=>{
  const t=ev.target;
  panelDownAt = (t && t.closest && (t.closest('#side')||t.closest('#markdlg')))
                ? performance.now() : 0;
},true);

function editOnCanvas(id){
  const r=regions.find(x=>x.id===id);
  if(!r||!r.layout) return;
  // A locked block is not typed into. lee: *"the lock shoud prevent teh layer
  // form getting edited or moved"* - a lock that only stopped restacking was
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

  // A DIV that the editor mounts into, rather than a contenteditable we
  // drive ourselves. It keeps the id, the geometry and the class every
  // other part of the app already looks for; what changed is who owns the
  // document and the selection inside it. See `textbox.js`.
  const ta=document.createElement('div');
  ta.id='canvasEdit';
  ta.style.cssText=
    `position:absolute;text-align:center;white-space:pre;`+
    `display:flex;flex-direction:column;justify-content:center;`+
    `background:transparent;border:none;outline:none;`+
    `z-index:40;text-transform:none;overflow:visible`;
  editWas=(L.lines||[]).join('\n');
  editBefore={ov:JSON.parse(JSON.stringify(r.layout_override||{})),
              text:r.dst_text,
              lines:(L.lines||[]).slice(),
              frame:(L.frame||[]).slice()};
  $('stage').appendChild(ta);

  let t=null;
  // NO RED SQUIGGLE UNDER THE TYPESETTING - every word in here is a sound
  // effect, a name or a line the copy editor has been over, and the
  // browser's dictionary knows none of them. lee: *"remove teh red
  // spellcheck on teh box"*. The attributes go on the editor's own element
  // (see `tbMount`), together with the three that stop a phone keyboard
  // rewriting anything on the way in.
  tbMount(ta, r, {
    changed(){
      // The wording moved. The RANGES move with it by themselves now -
      // that is the editor's job and `remapSpans` is gone - so all that is
      // left here is to write the block down and redraw it.
      syncFromTextbox(r);
      editInkMirror(ta, r);
      placeEditor(ta, r);
      clearTimeout(t);
      t=setTimeout(()=>{
        const lines=tbLines();
        if(lines.length) livePreview(id,Object.assign(currentPatch(r),{lines}));
      },200);
    },
    selected(){ editSelectionMoved(); },
    escape(){ closeCanvasEdit(false); },
    commit(){ closeCanvasEdit(true); }
  });
  placeEditor(ta, r);
  // ...and again now it is on the page, because a box laid out in runs is
  // widened to fit them and that can only be measured once it has a layout
  placeEditor(ta, r);
  editBox=ta;
  drawText();
  tbFocus();

  // Page shortcuts stay off while somebody is typing. Escape and
  // Ctrl+Enter are the editor's own keymap (`tbMount`), so they are not
  // repeated here.
  ta.addEventListener('keydown',e=>{ e.stopPropagation(); });
  // Blur closes the editor - EXCEPT when the focus went to the side panel
  // or the special-characters dialog. Every control there steals focus when
  // really clicked (a colour well, a stepper, a mark tile), so "click
  // anything on the side bar" would close the box mid-edit - the synthetic
  // tests never caught it because a dispatched event moves no focus. Two
  // signs are checked because neither alone covers it: where the focus
  // LANDED (relatedTarget - null for the native colour dialog and for
  // clicks on non-focusable labels) and where the last pointer went DOWN.
  //
  // The RANGE no longer needs protecting here. It lives in the editor's
  // state, not in the browser's selection, so a well that steals focus
  // cannot take it away.
  ta.addEventListener('focusout',(e)=>{
    const to=e.relatedTarget;
    if(to && to.closest && (to.closest('#side')||to.closest('#markdlg')))
      return;
    if(to && ta.contains(to)) return;
    if(typeof panelDownAt!=='undefined'
       && performance.now()-panelDownAt < 700) return;
    closeCanvasEdit(true);
  });
}

/* The block, written down from the editor: the lines it holds and the
   ranges inside it, in the app's own shape and the app's own offsets.
   Called on every change, so `r.layout` and `r.layout_override` are never
   more than one keystroke behind what is on screen - which is what the
   overlay, the mirror and the save all read. */
function syncFromTextbox(r){
  if(!r || typeof tbLines!=='function' || !tbIsOpen()) return;
  const lines=tbLines();
  const spans=tbSpans();
  if(r.layout) r.layout.lines=lines;
  const ov=Object.assign({}, r.layout_override||{}, {lines:lines,
                                                     locked:true});
  if(spans.length) ov.spans=spans; else delete ov.spans;
  r.layout_override=ov;
}


/* How wide the widest line in the box actually is, when the box is laid
   out in runs. Measured off the ROW ELEMENTS the browser has already laid
   out - `scrollWidth` is their content, overflow included - so no font
   measuring is repeated and no canvas can disagree with it. 0 for a plain
   box, which is every box that has not had a size or a face put on part of
   its text. */
function runWidthOf(ta, r){
  if(!ta) return 0;
  // The editor mounts its own element inside the box, so the ROWS are the
  // paragraphs wherever they are - one level down when the editor is
  // there, at the top when it is not.
  const rows=[...ta.querySelectorAll('p')];
  const list=rows.length?rows:[...ta.children];
  let w=0;
  list.forEach(d=>{
    // the RUNS, added up - not the row's own width, which is whatever the
    // box is and would make this measurement chase its own tail
    const kids=[...d.children];
    let s=0;
    if(kids.length) kids.forEach(c=>{ s+=c.getBoundingClientRect().width; });
    else {
      const rg=document.createRange();
      rg.selectNodeContents(d);
      s=rg.getBoundingClientRect().width;
    }
    w=Math.max(w, s);
  });
  return w;
}

/* Keeps the editor sitting exactly on the frame - at creation, and again on
   every frame change while it is open. */
function placeEditor(ta, r){
  if(!ta||!r||!r.layout) return;
  const L=r.layout, st=r.style||{};
  const [fx,fy,fw,fh]=frameOf(r);
  const size=L.font_size*scale;
  // A BLOCK WITH RUNS IN IT CAN BE WIDER THAN ITS FRAME. The frame was
  // fitted at the block's own size, and one word made bigger runs past it.
  // A `pre` line that overflows its block is laid out from the LEFT EDGE
  // rather than centred - the browser will not start an overflowing line
  // outside its container - so the box's letters, and the caret with them,
  // sat to the right of the ink. Widening the box round the same centre
  // line is the fix, and the mirror takes its geometry from the box, so
  // both move together. lee's rule is that the box no longer resizes the
  // TEXT (`resizeFlags`); this is the box making room for it.
  let bw=fw*scale;
  const wide=runWidthOf(ta, r);
  const cx=(fx+fw/2)*scale;
  if(wide>bw) bw=Math.ceil(wide)+2;
  ta.style.left=(cx-bw/2)+'px';
  // anchored on the frame's centre line, so an added line grows it both ways
  ta.style.top=((fy+fh/2)*scale)+'px';
  ta.style.width=bw+'px';
  ta.style.minHeight=(fh*scale)+'px';
  const ov=styleOf(r);
  const efam=fontFam(ov.font||st.font||L.font, r.kind);
  ta.style.fontFamily=efam+',sans-serif';
  // The size the FACE is asked for is converted; the line pitch is not. The
  // server's `line_h` is the nominal size times the leading, so converting
  // both would have opened the editor with its lines off the page's lines.
  ta.style.fontSize=emPx(size, efam).toFixed(2)+'px';
  ta.style.lineHeight=((L.leading||1.12)*size)+'px';
  const ls=num(st,ov,'lspace',0)*scale;
  ta.style.letterSpacing=ls?ls+'px':'';
  // centre the glyphs, not the glyphs+trailing gap - matches the render
  ta.style.paddingLeft=ls?ls+'px':'';
  // THE COLOUR THE PAGE IS DRAWN IN, WHATEVER THAT IS.
  //
  // It used to borrow: with no fill it typed in the RIM's colour instead, so
  // that there was something to see. That made a block you had emptied on
  // purpose turn solid the moment you clicked it and hollow again the moment
  // you clicked away - and worse, it read `st.fg` while the drawing reads
  // `ov.fg` first, so a block whose ink was MEASURED changed colour on the
  // way in even when it had a fill.
  // lee: *"fix teh issue of when i clcik a box and teh text color change it
  // shodu always be teh same"*.
  //
  // `inkPair` is the one rule now. Where there is nothing inside the letters
  // the editor draws them the way the page does - a real stroke on the
  // outline with the artwork showing through - which `-webkit-text-stroke`
  // does correctly for exactly this case: there is no fill for it to eat.
  // The caret takes the rim's colour so it can still be found.
  const {fill, rim, sw, hole}=inkPair(r,L);
  // NOT a centred stroke any more. `-webkit-text-stroke` grows half of its
  // width INWARD, and with nothing behind it that half is the letter's own
  // see-through middle - so clicking a hollow block filled its letters with
  // the rim's colour, usually white. lee: *"when i clcik a transparent box,
  // it ussly get a white fill"*. The rim is drawn by `editInkMirror` now -
  // the same masked SVG the page itself uses - and the box keeps only the
  // caret.
  ta.style.webkitTextStroke='';
  ta.style.color=hole?'transparent':fill;
  ta.style.caretColor=hole?rim:fill;
  // A FILL GRADIENT STAYS WHEN YOU CLICK. The box used to type in the flat
  // base colour, so the gradient vanished the moment the block was clicked
  // and came back on click-out. lee: *"some of teh affcets dont stay when i
  // clcik on it"*. One ramp across the whole box - the page runs its ramp
  // over the ink's box, so the two agree to within the em slack.
  const g2v=pick(st,ov,'fg2');
  const grad=!hole && /^#[0-9a-f]{6}$/i.test(g2v);
  if(grad){
    const g1v=pick(st,ov,'fg1');
    const gFrom=/^#[0-9a-f]{6}$/i.test(g1v)?g1v:fill;
    const css=((180-num(st,ov,'grad_angle',0))%360+360)%360;
    ta.style.backgroundImage=`linear-gradient(${css}deg, ${gFrom}, ${g2v})`;
    ta.style.webkitBackgroundClip='text';
    ta.style.backgroundClip='text';
  }else{
    ta.style.backgroundImage='';
    ta.style.webkitBackgroundClip='';
    ta.style.backgroundClip='';
  }
  // ...and when PART of the text wears its own style, the box shows
  // nothing at all: one plaintext contenteditable cannot wear two colours,
  // so the mirror under it draws the fill run by run and the box keeps
  // only the caret.
  const rspans=(r.layout_override||{}).spans;
  const wys=Array.isArray(rspans)&&rspans.length>0;
  if(wys){
    ta.style.color='transparent';
    ta.style.backgroundImage='';
    ta.style.webkitBackgroundClip='';
    ta.style.backgroundClip='';
  }
  ta.style.webkitTextFillColor=(hole||grad||wys)?'transparent':'';
  // no text-shadow on the box at all: every effect lives in the mirror
  // under it, where the layering is the page's own
  ta.style.textShadow='';
  // and typing into a faded block looks faded, like everything else about it
  const opv=num(st,ov,'opacity',100);
  ta.style.opacity=(isNaN(opv)?100:Math.max(0,Math.min(100,opv)))/100;
  ta.style.transformOrigin='center center';
  ta.style.transform='translateY(-50%)'+
    (+(L.rotate||0) ? ` rotate(${-(+L.rotate)}deg)` : '');
  // LAST, once every property it copies is in place - called earlier it
  // mirrored a box that had no transform yet and sat half a frame low
  editInkMirror(ta, r);
}

/* EVERYTHING BUT THE FILL, UNDER THE BOX YOU TYPE IN - and, when part of
   the text wears its own style, THE FILL AS WELL.

   The box you type in is ONE element, and one element cannot layer: its
   text-shadows paint OVER its background, a centred stroke on a hollow
   block filled the letters with the rim's colour, and one plaintext
   contenteditable cannot show two colours at once. So the editor is
   layered the way the page is: a non-editable MIRROR sits right under the
   box - same frame, same face, same line pitch - and carries everything
   that paints around or under the letters, built by the same `runStyle`
   the page itself draws with. On a block whose text carries SPANS the
   mirror draws the fill too, run by run, and the box above goes fully
   transparent: what you see while typing is the page, with a caret on it.
   The selected range wears a soft band, so it survives the panel taking
   the browser's own selection away. Rebuilt on every keystroke, locally:
   no server round-trip, no lag. */
function editInkMirror(ta, r){
  const L=r&&r.layout;
  const m0=ta._rim;
  if(!L){ if(m0){m0.remove(); ta._rim=null;} return; }
  const st=r.style||{}, ov=styleOf(r);
  const lines=editLines(ta);
  const flat=lines.join('\n');
  let spans=null;
  const rawSp=(r.layout_override||{}).spans;
  if(Array.isArray(rawSp)&&rawSp.length){
    spans=[];
    rawSp.forEach(sp=>{
      const s0=Math.max(0,sp.s|0), e0=Math.min(flat.length,sp.e|0);
      if(e0>s0&&sp.st&&Object.keys(sp.st).length) spans.push([s0,e0,sp.st]);
    });
    if(!spans.length) spans=null;
  }
  const bs=runStyle(r, L, null);
  const wys=!!spans;                 // the mirror draws the fill too
  const _rng=(typeof editRange==='function') ? editRange() : null;
  const hasSel=!!_rng;
  const bare=!wys && !hasSel && !bs.fx.length && !(bs.sw>0) && !bs.igOn;
  if(bare){ if(m0){m0.remove(); ta._rim=null;} return; }
  let m=m0;
  if(!m){
    m=document.createElement('div');
    m.id='canvasEditRim';
    $('stage').appendChild(m);
    ta._rim=m;
  }
  const size=L.font_size*scale;
  const fam=fontFam(ov.font||st.font||L.font, r.kind);
  const ls=num(st,ov,'lspace',0)*scale;
  const lh=((L.leading||1.12)*size);
  // the box's own geometry, one property at a time - the mirror must sit
  // exactly under it or the ink parts from the caret
  m.style.cssText='position:absolute;text-align:center;white-space:pre;'+
    'display:flex;flex-direction:column;justify-content:center;'+
    'pointer-events:none;z-index:39;'+
    `left:${ta.style.left};top:${ta.style.top};width:${ta.style.width};`+
    `min-height:${ta.style.minHeight};opacity:${ta.style.opacity||1};`+
    `font-family:${fam},sans-serif;`+
    `font-size:${emPx(size,fam).toFixed(2)}px;`+
    (ls?`letter-spacing:${ls}px;padding-left:${ls}px;`:'')+
    `transform:${ta.style.transform||'none'};`+
    'transform-origin:center center';
  m.textContent='';
  /* One run, inked - by the SAME function the page draws with. This used
     to be a second implementation called `stack`, with the positioning
     written inline instead of in classes: five layers, two spellings, and
     every divergence between the page and the box came out of the gap.

     `fill` is the one real difference. With no ranges on the block the
     box's own text is still showing through, so the mirror must not paint
     a second copy of the fill over it; the moment a range takes over, the
     box goes transparent and the mirror owns the fill too. */
  const stack=(holder, line, S)=>inkRun(holder, line, S,
    {fam:fam, size:size, ls:ls, fill:wys});
  let off=0;
  lines.forEach((line,k)=>{
    const d=document.createElement('div');
    // `ink`, because the five layers under it are the page's own and their
    // CSS is scoped to that class - see `inkRun`
    d.className='ink';
    d.style.cssText=`height:${lh}px;display:flex;align-items:center;`+
      'justify-content:center;overflow:visible';
    if(!line.length){ m.appendChild(d); off+=1; return; }
    const w=document.createElement('span');
    w.style.cssText='position:relative;display:inline-block;'+
      'white-space:pre;overflow:visible';
    // THE IN-FLOW SIZER: real metrics, no ink. It gives the wrapper the
    // width and height of the line, so that the absolutely-positioned ink
    // of an UNSPANNED line has something to sit on top of. A spanned line
    // removes it: those runs are in flow themselves and size the wrapper
    // between them, and a sizer left in front of them would push every one
    // of them a whole run to the right.
    const base=document.createElement('span');
    base.className='tz';
    base.textContent=line;
    base.style.cssText='position:relative;color:transparent;'+
      '-webkit-text-fill-color:transparent';
    w.appendChild(base);
    // THE SELECTION IS THE BROWSER'S TO DRAW.
    //
    // A band used to be drawn here, by hand. It existed because clicking a
    // colour well threw the browser's own selection away and something had
    // to show what was still selected - and the editor holds the selection
    // in its own state now, so that reason is gone.
    //
    // It was never right either. Placed by measurement, and standing as
    // tall as the tallest RUN rather than as tall as the letters, it came
    // out as an amber slab across the middle of a sound effect. lee sent a
    // picture of it: *"this is still hapeening use any mean to fix it i
    // want it GONE"*.
    //
    // The browser puts a highlight exactly on the glyphs it is
    // highlighting, for nothing, and cannot be off by a pixel. See
    // `#canvasEdit::selection`.
    const runs=spans?lineRuns(line, off, spans)
                    :[{c0:0, c1:line.length, ss:null}];
    const rsty=runs.map(run=>run.ss?runStyle(r, L, run.ss):bs);
    if(runs.length>1 || (runs[0] && runs[0].ss)){
      // RUN BY RUN, always - the same flow `drawText` lays out and the
      // exporter paints. There are no bands any more: a band is a box
      // behind the letter, and a vertical cut at a glyph advance slices
      // through the ink of the letter beside it. The transparent sizer
      // goes with them; nothing is clipped, so nothing needs measuring.
      base.remove();
      d.dataset.flow='1';
      runs.forEach((run,i)=>{
        const S=rsty[i];
        const holder=document.createElement('span');
        holder.className='trunf';
        holder.dataset.c0=run.c0; holder.dataset.c1=run.c1;
        holder.style.cssText='position:relative;display:inline-block;'+
          'white-space:pre;line-height:1;overflow:visible;'+
          `font-family:${S.fam},sans-serif;`+
          `font-size:${emPx(S.size,S.fam).toFixed(2)}px;`+
          // the run's own transparency, as the page draws it
          (S.op<100?`opacity:${(S.op/100).toFixed(3)};`:'');
        // NO SIZER HERE. The fill span is an IN-FLOW element - that is
        // how a run comes to be the width of its own letters - so a sizer
        // in front of it pushes it one whole run to the right, and what
        // you see is the outline in the right place with the colour on
        // the next letter along. lee: *"the color sliping to other
        // letter"*, and his own reading of it was right: *"the letter
        // themselft are not getting coloed ... teh text is going out of
        // teh bound"*. The ink sizes the run, exactly as it does on the
        // page (`drawText`'s flow branch has never had a sizer either).
        stack(holder, line.slice(run.c0, run.c1), S);
        w.appendChild(holder);
      });
    } else {
      runs.forEach((run,i)=>{
        const S=rsty[i];
        // ALWAYS a holder of its own, even for a single run. `w` already
        // carries the invisible sizer in flow, and the fill span is an
        // in-flow element too - dropped straight into `w` it lands AFTER
        // the sizer instead of on top of it, and every letter is drawn
        // twice, side by side. That is what lee photographed: *"the color
        // sliping to other letter"* - a second copy of the words, offset
        // by the width of the first.
        const holder=document.createElement('span');
        holder.className='trun';
        holder.style.cssText='position:absolute;inset:0;overflow:visible';
        w.appendChild(holder);
        stack(holder, line, S);
      });
    }
    d.appendChild(w);
    m.appendChild(d);
    off+=line.length+1;
  });
  // the gradients are the block's, not each run's - the same ramp
  // the page paints, so a fade cannot look one way while you type and
  // another the moment you click away. `false`: the mirror's rows are
  // ordinary flow boxes, not lines centred on their origins.
  paintRamps(m, size, fam, false);
}

/* The lines in the box, as the app counts them. Asked of the EDITOR when
   one is open - it holds the document, and reading `innerText` back out of
   the DOM it rendered is asking the picture what the words were. The DOM
   path is kept for the moment before the editor is mounted and for any
   caller that still has only an element. */
function editLines(el){
  if(typeof tbIsOpen==='function' && tbIsOpen()
     && (!el || el===editBox)){
    const ls=tbLines().slice();
    while(ls.length && !ls[ls.length-1].trim()) ls.pop();
    return ls;
  }
  const ls=((el&&el.innerText)||'').replace(/\u00a0/g,' ').split('\n');
  while(ls.length && !ls[ls.length-1].trim()) ls.pop();
  return ls;
}

function closeCanvasEdit(commit){
  if(!editBox) return;
  const id=editing, ta=editBox, lines=editLines(ta);
  const spans=(typeof tbSpans==='function' && tbIsOpen()) ? tbSpans() : null;
  const was=editWas, before0=editBefore;
  editing=null; editBox=null; editWas=null; editBefore=null;
  if(typeof tbUnmount==='function') tbUnmount();
  if(typeof renderInspector==='function') renderInspector();
  if(typeof snapshotTypesetPanel==='function') snapshotTypesetPanel();
  ta.remove();
  if(ta._rim){ try{ ta._rim.remove(); }catch(e){} ta._rim=null; }
  const r=regions.find(x=>x.id===id);
  // Clicking a block and clicking away is not an edit. It used to save
  // anyway, and saving locks the block onto the hand-edit path - which
  // places lines by a different rule than the fitter does - so the typesetting
  // visibly moved on a click that changed nothing. Only a real change to the
  // wording is a change.
  if(was!==null && lines.join('\n')===was) commit=false;
  // …and an EMPTY edit is an edit. `lines.length` was a guard here, so
  // selecting everything in a block and pressing delete committed nothing at
  // all: the words came straight back the moment the editor closed. Deleting
  // all of it is the most deliberate edit there is.
  // lee: *"deleeting all teh etxt from a text box still dont just leave it"*.
  if(r&&commit){
    // What to put back: the words, ranges, frame and translation as they
    // stood when the box was OPENED - captured then, because the editor
    // writes every keystroke into the region as it goes (`syncFromTextbox`),
    // so by now the region holds the edit itself. Snapshotting here is how
    // the undo came to restore the edit and do nothing (lee: *"its not in
    // the history so i cant undo the delete"*). `saveTypesetting` builds
    // the undo from these plus its own save body, so everything else on
    // the panel - a size set moments before the box opened, still saving
    // when it did - survives the undo untouched.
    const before=before0||{ov:JSON.parse(JSON.stringify(r.layout_override||{})),
                           text:r.dst_text,
                           lines:(r.layout&&r.layout.lines||[]).slice(),
                           frame:(r.layout&&r.layout.frame||[]).slice()};
    r.layout.lines=lines;
    const ov=Object.assign({},r.layout_override,{lines,locked:true});
    // ...and the ranges as the editor last held them. They moved with the
    // words while it was open, so this is the answer, not the copy the
    // region was carrying before the edit.
    if(spans){ if(spans.length) ov.spans=spans; else delete ov.spans; }
    r.layout_override=ov;
    const f=$('lyLines'); if(f) f.value=lines.join('\n');
    // Send the lines explicitly. currentPatch reads the side panel, which
    // still held the old wording - that is why typed changes sometimes
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
   ring's own mask - see `edge2` in render.py.

   The slabs run across the WHOLE block, not per line, so a two-line shout
   fades once from top to bottom rather than twice. */
const EDGE_BANDS = 16;
function _mixHex(a, b, t){
  const p=h=>[1,3,5].map(i=>parseInt(h.substr(i,2),16));
  const A=p(a), B=p(b);
  return '#'+A.map((v,i)=>Math.round(v+(B[i]-v)*t)
    .toString(16).padStart(2,'0')).join('');
}
function paintEdgeGradient(g){
  const rings=[...g.querySelectorAll('.ts.egrad')];
  if(!rings.length) return;
  // Every ring's own box, in the group's coordinates. The positioned thing
  // is the line div (or the arc letter) the ring sits inside - a ring in a
  // run wrapper is one level deeper, so climb.
  const boxOf=el=>{
    const h=el.closest('.tc')||el.closest('.tl')||el.parentElement;
    // A ring with no positioned host has no box to contribute. It happens
    // while a block is being rebuilt - `drawText` replaces the group, and a
    // repaint queued against the old one finds its rings detached - and it
    // used to throw here, which killed the whole ramp and left the outline
    // painted in one flat colour.
    if(!h) return null;
    const w=h.offsetWidth, ht=h.offsetHeight;
    return {x:h.offsetLeft-w/2, y:h.offsetTop-ht/2, w, h:ht};
  };
  // the ramp spans the union of ALL the block's rings, per angle - the
  // export's `_gradient_image` runs across the whole ring bbox the same way
  const boundsFor=(tx,ty)=>{
    let pmin=1e9, pmax=-1e9;
    rings.forEach(el=>{
      const b=boxOf(el);
      if(!b) return;
      [[b.x,b.y],[b.x+b.w,b.y],[b.x,b.y+b.h],[b.x+b.w,b.y+b.h]]
        .forEach(([x,y])=>{ const p=x*tx+y*ty;
          pmin=Math.min(pmin,p); pmax=Math.max(pmax,p); });
    });
    return [pmin, pmax];
  };
  rings.forEach(el=>{
    const from=el.dataset.e1, to=el.dataset.e2;
    const angle=+el.dataset.eang||0;
    const strokePx=parseFloat(el.dataset.esw)||2;
    const rad=angle*Math.PI/180;
    const tx=Math.sin(rad), ty=Math.cos(rad);
    const [pmin,pmax]=boundsFor(tx,ty);
    const span=Math.max(1e-6, pmax-pmin);
    const b=boxOf(el);
    if(!b) return;                     // detached mid-rebuild - see boxOf
    const base=b.x*tx+b.y*ty;          // projection of the ring's own origin
    const BIG=(b.w+b.h)*2+200;
    const parent=el.parentElement;
    const frag=document.createDocumentFragment();
    for(let k=0;k<EDGE_BANDS;k++){
      // The first and last slab run on to infinity, because the ink runs on
      // past the box (the leaning "!" that lost its outline at the corner);
      // and every slab starts half a pixel inside its neighbour, or the
      // antialiased seam between two clip paths shows the page through the
      // outline once per band.
      const lo=pmin+span*k/EDGE_BANDS-base-(k===0?BIG:0.5);
      const hi=pmin+span*(k+1)/EDGE_BANDS-base+(k===EDGE_BANDS-1?BIG:0);
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
