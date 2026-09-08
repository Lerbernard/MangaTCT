/* The three keys in the legend are buttons, and the lit one is what you draw.

   lee, with a screenshot of the colour key: *"can you meke these 3 in the
   screenshoot buttons adn make them diactaet twhat box is beign draw by
   degault so by default the red button shoud be selected and red shopud be
   default but i i click the green button the default shoud be outside text"*.

   Drives the real page: the legend as rendered, the click handler, what the
   number keys do with nothing selected, and the body the region POST sends. */
const {JSDOM} = require('jsdom');
const html = require('./load')();

let posted = null;
const dom = new JSDOM(html, {runScripts: 'dangerously',
  url: 'http://127.0.0.1:8765/',
  beforeParse(w) {
    w.fetch = async (url, opt) => {
      const u = String(url);
      if (u.indexOf('/region') >= 0 && opt && opt.method === 'POST') {
        posted = JSON.parse(opt.body);
        return {json: async () => ({region: {id: 7}, regions: []})};
      }
      if (u.indexOf('/api/job') >= 0)
        return {json: async () => ({running: false, done: 0, total: 0})};
      return {json: async () => ({pages: [], settings: {}, context: {},
                                 fonts: []})};
    };
    w.HTMLCanvasElement.prototype.getContext = () => ({clearRect(){}, beginPath(){},
      arc(){}, fill(){}, moveTo(){}, lineTo(){}, stroke(){}, drawImage(){},
      getImageData: () => ({data: [0, 0, 0]})});
  }});

const w = dom.window, d = w.document;
let bad = 0;
const ok = (name, cond) => {
  console.log((cond ? 'ok   ' : 'FAIL ') + name);
  if (!cond) bad++;
};
// The KIND buttons only. "Select boxes" joined this row later as a TOOL
// (lee: "make teh slector tool be seprated form the other") - it wears
// .lgmain for the styling and .lgsel for what it is, and it is not a kind.
const keys = () => Array.from(d.querySelectorAll('#legend .lgmain:not(.lgsel)'));
const lit = () => keys().filter(b => b.classList.contains('on'))
                        .map(b => b.dataset.fam);

setTimeout(async () => {
  try {
    w.renderLegend();
    const ks = keys();
    ok('the three main types are buttons', ks.length === 3
       && ks.every(b => b.tagName === 'BUTTON'));
    ok('...in the order the number keys hand them out',
       ks.map(b => b.dataset.fam).join(',') === 'bubble,freefloat,sfx');
    ok('...each still saying its number and its name',
       /1 Bubble text/.test(ks[0].textContent)
       && /2 Freefloat text/.test(ks[1].textContent)
       && /3 Sound effect/.test(ks[2].textContent));

    ok('bubble text is lit to start with', lit().join() === 'bubble');
    ok('...and it is the kind a new box would be',
       w.eval('newBoxKind') === 'bubble');

    // Clicking the green one. The key is re-rendered, so the buttons are
    // looked up again rather than held onto.
    keys()[1].onclick();
    ok('clicking Freefloat text lights it', lit().join() === 'freefloat');
    ok('...and puts the red one out',
       !keys()[0].classList.contains('on'));
    ok('...and that is what a new box will be',
       w.eval('newBoxKind') === 'freefloat');

    // ...and the box that gets drawn says so. Driven through the real mouseup
    // listener, so the body this checks is the body the server would get.
    w.eval('cur=0; scale=1; drag={mode:"new",x0:10,y0:10,own:false};');
    w.document.dispatchEvent(new w.MouseEvent('mouseup',
        {clientX: 200, clientY: 120, bubbles: true}));
    await new Promise(r => setTimeout(r, 30));
    ok('the region POST carries the lit kind',
       !!posted && posted.kind === 'freefloat');

    keys()[2].onclick();
    ok('and the purple one', w.eval('newBoxKind') === 'sfx'
       && lit().join() === 'sfx');
    keys()[0].onclick();
    ok('and back to red', w.eval('newBoxKind') === 'bubble');

    // The number keys with nothing selected.
    w.eval('sel=null; if(typeof selMulti!=="undefined") selMulti.clear();');
    await w.setKindSelected('sfx');
    ok('with no box selected, 3 sets what you draw instead of scolding you',
       w.eval('newBoxKind') === 'sfx' && lit().join() === 'sfx');

    // A hidden group is brought back, or the box vanishes as it is drawn.
    w.eval('hiddenKinds=["freefloat"]');
    w.setNewBoxKind('freefloat');
    ok('choosing a kind that is hidden brings it back out',
       !(w.eval('hiddenKinds') || []).includes('freefloat')
       || w.eval('newBoxKind') === 'freefloat');

    w.setNewBoxKind('nonsense');
    ok('a kind that is not one of the three is refused',
       w.eval('newBoxKind') === 'freefloat');

    console.log(bad ? bad + ' FAILED' : 'all good');
    process.exit(bad ? 1 : 0);
  } catch (e) { console.log('THREW', e.stack); process.exit(1); }
}, 60);
