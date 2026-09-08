/* THE BOX YOU TYPE INTO, AND THE RANGES INSIDE IT.

   Everything about selecting part of a block and giving that part its own
   style used to be written by hand here: character offsets counted by
   walking the DOM, a `editSel` variable kept alive because clicking a
   colour well threw the browser's selection away, and every span's start
   and end shifted by hand whenever somebody typed in the middle. Four of
   the last five bugs lee reported lived in that machinery:

     - a colour cut two pixels into the next letter, because the cut was
       measured on a canvas and drawn by the DOM;
     - two selection highlights, because the browser painted one and we
       painted the other;
     - a size stepper that lost every other press;
     - and a box you could not select at all once part of its text wore a
       second face, because a guard asked `e.target.id === 'canvasEdit'`
       and the press landed on a run's span.

   lee: *"thats why i wanted to add an alrey made text box system because
   tgere are som many nuances that are hard to deal with"*.

   So the MODEL is ProseMirror's now (bundled in `vendor/prosemirror.js`,
   MIT, see `vendor/LICENSES.md`) and the INK is still ours. That split is
   deliberate and it is the whole design:

     ProseMirror owns   the document, the selection, the marks on a range,
                        the remapping of those marks when the text changes,
                        and undo.
     mangatl owns       every pixel: `drawText` on the page, `editInkMirror`
                        under the caret, and `render.py` on the export. No
                        editor can draw an outline, a glow, a gradient fill
                        or a hollow letterform, and those are the app.

   THE OFFSETS ARE UNCHANGED. `layout_override.spans` still indexes the flat
   text of the block's lines joined with newlines - the same numbers
   `render._spans_of` reads on the other side. This file is the only place
   that converts between those offsets and ProseMirror's positions, and it
   is about thirty lines instead of three hundred.

   ONE NORMALISATION, said out loud: our stored model allows spans to
   overlap (a colour over ten characters, a size over two of them), and a
   ProseMirror mark cannot overlap another of its own type. So a block read
   in here comes back out FLATTENED - one span per stretch of constant
   effective style, carrying the merged keys. The drawn result is identical,
   because both renderers apply overlapping spans by merging them in order
   anyway; the list is just written down the way it is drawn. */

let tbView = null;         // the live editor, or null
let tbRegion = null;       // the region it is open on
let tbOnChange = null;     // what to call when the doc or selection moves
let _tbSchema = null;

/* The keys a mark may carry - the app's own list, so adding a tool to
   `SPAN_STYLE_KEYS` adds it here too and nowhere else. */
function tbKeys(){
  return (typeof SPAN_STYLE_KEYS !== 'undefined')
    ? SPAN_STYLE_KEYS
    : ['fg','edge','stroke','fg1','fg2','grad_angle','edge1','edge2',
       'edge_angle','glow','glow_size','iglow','iglow_size','shadow',
       'sh_dist','sh_blur','font','font_size'];
}

function tbMetricKeys(){
  return (typeof SPAN_METRIC_KEYS !== 'undefined')
    ? SPAN_METRIC_KEYS : ['font','font_size'];
}

/* One paragraph per line, one mark, and the mark's attributes are the
   app's style keys. `toDOM` writes ONLY the metrics - the face and the
   size - because those change where the caret belongs and the box has to
   lay them out. Colour, outline, glow and the rest are not written here at
   all: the mirror underneath paints them, and a box that painted its own
   colours would be a second opinion about the same letters. */
function tbSchema(){
  if(_tbSchema) return _tbSchema;
  const attrs = {};
  tbKeys().forEach(k => { attrs[k] = {default: null}; });
  _tbSchema = new PM.Schema({
    nodes: {
      doc: {content: 'line+'},
      line: {content: 'inline*', group: 'block',
             parseDOM: [{tag: 'p'}],
             toDOM: () => ['p', {style: 'margin:0;white-space:pre'}, 0]},
      text: {group: 'inline'}
    },
    marks: {
      ink: {
        attrs: attrs,
        // NOT inclusive. A range is a range of CHARACTERS somebody chose,
        // so typing at its edge writes plain text - the style does not
        // reach out and swallow the next word. ProseMirror's default is
        // the opposite, which is right for bold-as-you-type and wrong for
        // "this word is red".
        inclusive: false,
        parseDOM: [{tag: 'span'}],
        toDOM(m){
          const fam = (typeof fontFam === 'function' && m.attrs.font)
            ? fontFam(m.attrs.font, tbRegion && tbRegion.kind) : '';
          const sz = m.attrs.font_size;
          let css = 'white-space:pre;';
          if(fam) css += 'font-family:' + fam + ',sans-serif;';
          if(sz && typeof emPx === 'function' && typeof scale !== 'undefined')
            css += 'font-size:' + emPx(+sz * scale, fam || 'sans-serif')
                     .toFixed(2) + 'px;';
          return ['span', {style: css, class: 'tbrun'}, 0];
        }
      }
    }
  });
  return _tbSchema;
}

/* ---- the app's offsets <-> ProseMirror's positions ----
   A line break is ONE character in the app's flat text and one paragraph
   boundary here, so the two counts agree if the boundary is counted once. */

function tbOffOf(doc, pos){
  let off = 0, out = null;
  doc.descendants((node, p) => {
    if(out !== null) return false;
    if(node.isText){
      if(pos <= p + node.text.length){ out = off + (pos - p); return false; }
      off += node.text.length;
    }else if(node.type.name === 'line'){
      if(p > 0) off += 1;                       // the newline before it
      if(pos <= p) { out = off; return false; }
    }
    return true;
  });
  return out === null ? off : out;
}

function tbPosOf(doc, want){
  let off = 0, out = null;
  doc.descendants((node, p) => {
    if(out !== null) return false;
    if(node.isText){
      if(off + node.text.length >= want){ out = p + (want - off); return false; }
      off += node.text.length;
    }else if(node.type.name === 'line'){
      if(p > 0) off += 1;
      if(off === want && !node.content.size){ out = p + 1; return false; }
      if(off > want){ out = p; return false; }
    }
    return true;
  });
  if(out === null) out = Math.max(1, doc.content.size - 1);
  return out;
}

/* ---- reading the block out ---- */

function tbLinesOf(doc){
  const out = [];
  doc.forEach(n => out.push(n.textContent));
  return out;
}

/* `layout_override.spans` as the app stores them - one entry per stretch
   of constant style, offsets over the flat text. */
function tbSpansOf(doc){
  const out = [];
  let off = 0;
  doc.descendants((node, p) => {
    if(node.type.name === 'line'){ if(p > 0) off += 1; return true; }
    if(!node.isText) return true;
    const m = node.marks.find(x => x.type === tbSchema().marks.ink);
    if(m){
      const st = {};
      tbKeys().forEach(k => {
        const v = m.attrs[k];
        if(v !== null && v !== undefined && v !== '') st[k] = v;
      });
      if(Object.keys(st).length)
        out.push({s: off, e: off + node.text.length, st: st});
    }
    off += node.text.length;
    return true;
  });
  // neighbours that ended up with the same style are one range
  const merged = [];
  out.forEach(sp => {
    const last = merged[merged.length - 1];
    if(last && last.e === sp.s
       && JSON.stringify(last.st) === JSON.stringify(sp.st)) last.e = sp.e;
    else merged.push(sp);
  });
  return merged;
}

/* ---- building the block up ---- */

function tbDocFrom(lines, spans){
  const S = tbSchema();
  const flat = (lines || ['']).join('\n');
  // the effective style of every character, spans applied IN ORDER, which
  // is exactly how `render._style_cuts` and `drawText` read them
  const at = new Array(flat.length);
  (spans || []).forEach(sp => {
    const s0 = Math.max(0, sp.s | 0), e0 = Math.min(flat.length, sp.e | 0);
    if(e0 <= s0 || !sp.st) return;
    for(let i = s0; i < e0; i++)
      at[i] = Object.assign({}, at[i], sp.st);
  });
  let off = 0;
  const paras = (lines && lines.length ? lines : ['']).map(line => {
    const kids = [];
    let i = 0;
    while(i < line.length){
      const key = JSON.stringify(at[off + i] || null);
      let j = i + 1;
      while(j < line.length && JSON.stringify(at[off + j] || null) === key) j++;
      const st = at[off + i];
      const marks = [];
      if(st){
        const attrs = {};
        tbKeys().forEach(k => {
          attrs[k] = (st[k] === undefined || st[k] === '') ? null : st[k];
        });
        marks.push(S.marks.ink.create(attrs));
      }
      kids.push(S.text(line.slice(i, j), marks));
      i = j;
    }
    off += line.length + 1;
    return S.node('line', null, kids);
  });
  return S.node('doc', null, paras);
}

/* ---- the selection, which is the whole point ----
   It lives in the editor's STATE, not in the browser, so clicking a colour
   well or a stepper cannot throw it away. That is `editSel` and its sixty
   lines of guards, deleted. */

function tbSelection(){
  if(!tbView) return null;
  const {from, to} = tbView.state.selection;
  if(from === to) return null;
  const doc = tbView.state.doc;
  const s = tbOffOf(doc, from), e = tbOffOf(doc, to);
  return (e > s) ? {s: s, e: e} : null;
}

function tbSetSelection(s, e){
  if(!tbView) return;
  const doc = tbView.state.doc;
  const from = tbPosOf(doc, s), to = tbPosOf(doc, e);
  try{
    tbView.dispatch(tbView.state.tr.setSelection(
      PM.TextSelection.create(doc, from, to)));
  }catch(err){}
}

/* What ONE key reads across a range: {mixed:true}, or {mixed:false, value}.
   `undefined` for value means "the block's own answer" - the range carries
   no opinion of its own. */
function tbFieldInfo(key, s, e){
  if(!tbView) return null;
  const doc = tbView.state.doc;
  const from = tbPosOf(doc, s), to = tbPosOf(doc, e);
  let seen, any = false, mixed = false;
  doc.nodesBetween(from, to, node => {
    if(!node.isText) return true;
    const m = node.marks.find(x => x.type === tbSchema().marks.ink);
    const v = m ? m.attrs[key] : null;
    const norm = (v === null || v === undefined || v === '') ? undefined : v;
    if(!any){ seen = norm; any = true; }
    else if(String(norm) !== String(seen)) mixed = true;
    return true;
  });
  if(!any) return null;
  return mixed ? {mixed: true} : {mixed: false, value: seen};
}

/* Put `patch` on [s, e). An empty-string value REMOVES the key, which is
   what pressing the × on a gradient means. Existing keys on the range are
   kept, so setting a colour does not wipe a size - which is the whole
   reason this walks the range instead of stamping one mark over it. */
function tbMark(s, e, patch){
  if(!tbView) return;
  const S = tbSchema();
  const state = tbView.state;
  const doc = state.doc;
  const from = tbPosOf(doc, s), to = tbPosOf(doc, e);
  if(to <= from) return;
  const tr = state.tr;
  const pieces = [];
  doc.nodesBetween(from, to, (node, p) => {
    if(!node.isText) return true;
    const a = Math.max(from, p), b = Math.min(to, p + node.text.length);
    if(b <= a) return true;
    const m = node.marks.find(x => x.type === S.marks.ink);
    pieces.push({a: a, b: b, attrs: m ? m.attrs : null});
    return true;
  });
  pieces.forEach(pc => {
    const attrs = {};
    let any = false;
    tbKeys().forEach(k => {
      let v = pc.attrs ? pc.attrs[k] : null;
      if(k in patch) v = (patch[k] === '' ? null : patch[k]);
      attrs[k] = (v === undefined || v === '') ? null : v;
      if(attrs[k] !== null) any = true;
    });
    tr.removeMark(pc.a, pc.b, S.marks.ink);
    if(any) tr.addMark(pc.a, pc.b, S.marks.ink.create(attrs));
  });
  if(tr.docChanged || tr.steps.length) tbView.dispatch(tr);
}

/* Take one key off every range in the block - what setting a MIXED field
   block-wide means: the spans' copies go and the block's own value is the
   one answer left, Photoshop-fashion. */
function tbStripKey(key){
  if(!tbView) return;
  const S = tbSchema();
  const state = tbView.state, doc = state.doc;
  const tr = state.tr;
  const pieces = [];
  doc.descendants((node, p) => {
    if(!node.isText) return true;
    const m = node.marks.find(x => x.type === S.marks.ink);
    if(m && m.attrs[key] !== null && m.attrs[key] !== undefined)
      pieces.push({a: p, b: p + node.text.length, attrs: m.attrs});
    return true;
  });
  pieces.forEach(pc => {
    const attrs = Object.assign({}, pc.attrs);
    attrs[key] = null;
    const any = tbKeys().some(k => attrs[k] !== null && attrs[k] !== undefined);
    tr.removeMark(pc.a, pc.b, S.marks.ink);
    if(any) tr.addMark(pc.a, pc.b, S.marks.ink.create(attrs));
  });
  if(tr.steps.length) tbView.dispatch(tr);
}

function tbInsertText(str){
  if(!tbView) return;
  tbView.dispatch(tbView.state.tr.insertText(str));
  tbView.focus();
}

function tbLines(){ return tbView ? tbLinesOf(tbView.state.doc) : []; }
function tbSpans(){ return tbView ? tbSpansOf(tbView.state.doc) : []; }
function tbFocus(){ if(tbView) tbView.focus(); }
function tbIsOpen(){ return !!tbView; }
/* ---- opening and closing ---- */

function tbMount(host, r, hooks){
  tbUnmount();
  tbRegion = r;
  tbOnChange = hooks || {};
  const S = tbSchema();
  const L = r.layout || {};
  const ov = r.layout_override || {};
  const doc = tbDocFrom(L.lines || [''], ov.spans || []);
  const keys = {
    'Mod-z': PM.undo, 'Mod-y': PM.redo, 'Shift-Mod-z': PM.redo,
    'Escape': () => { if(tbOnChange.escape) tbOnChange.escape(); return true; },
    'Mod-Enter': () => { if(tbOnChange.commit) tbOnChange.commit(); return true; }
  };
  // THE RANGE STAYS VISIBLE WHILE THE PANEL HAS THE FOCUS.
  //
  // The selection LIVES in the editor's state, so a colour well that
  // steals browser focus cannot take it away - but the browser only
  // PAINTS ::selection while the box is focused, so the moment a panel
  // control was clicked the highlight vanished and the range looked
  // thrown away. lee: *"the whole not unslecting text when i clcik on
  // the side bard is still not working"* - it was working underneath;
  // nobody could see it. So while the box is NOT focused, the held range
  // wears an inline decoration in the same amber the real highlight
  // paints, and the two never show together: the decoration is only
  // built when `hasFocus()` is false, and focus and blur each nudge an
  // empty transaction so it appears and disappears on time.
  const held = new PM.Plugin({
    props: {
      decorations(state){
        if(tbView && tbView.hasFocus()) return null;
        const sel = state.selection;
        if(!sel || sel.empty) return null;
        return PM.DecorationSet.create(state.doc, [
          PM.Decoration.inline(sel.from, sel.to, {class: 'tbheld'})]);
      },
      handleDOMEvents: {
        focus(view){ setTimeout(() => {
          if(tbView === view) view.dispatch(view.state.tr); }, 0);
          return false; },
        blur(view){ setTimeout(() => {
          if(tbView === view) view.dispatch(view.state.tr); }, 0);
          return false; }
      }
    }
  });
  const state = PM.EditorState.create({
    doc: doc,
    plugins: [held, PM.history(), PM.keymap(keys), PM.keymap(PM.baseKeymap)]
  });
  tbView = new PM.EditorView(host, {
    state: state,
    attributes: {
      spellcheck: 'false', autocorrect: 'off', autocapitalize: 'off',
      autocomplete: 'off', 'data-gramm': 'false'
    },
    dispatchTransaction(tr){
      const before = tbView.state;
      const next = before.apply(tr);
      tbView.updateState(next);
      if(tr.docChanged && tbOnChange.changed) tbOnChange.changed();
      else if(!tr.docChanged && tr.selectionSet && tbOnChange.selected)
        tbOnChange.selected();
    }
  });
  return tbView.dom;
}

function tbUnmount(){
  if(tbView){ try{ tbView.destroy(); }catch(e){} }
  tbView = null; tbRegion = null; tbOnChange = null;
}
