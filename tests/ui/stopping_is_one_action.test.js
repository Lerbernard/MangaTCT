/* "Stopping…" belongs to one action, not to the rest of the line.

   lee, with a screenshot of the strip reading "Detecting… 0 of 71 pages (0%)"
   beside a dead grey button still saying "Stopping…":

       when i clik cancel and it sto the ui show stopping even thiught te next
       step queue ia happening

   The button was put back by `_resetCancelBtn`, and that was only reached
   where the WHOLE queue had drained -- `poll` returns early while anything is
   running or waiting. So cancelling a Clean with a Translate queued behind it
   left the button reading "Stopping…" and disabled for the whole of the
   translation, and there was no way to stop that one either.

   The fix is to remember which action the Cancel was aimed at and put the
   button back the moment something else is running. This drives `poll`
   through a scripted sequence of `/api/job` answers and checks the button at
   each step. */
const {JSDOM} = require('jsdom');
const html = require('./load')();

// One Clean running, then the Clean gone and a Translate running in its place,
// then nothing.
const STEPS = [
  {running: true, label: 'Cleaning', done: 1, total: 9,
   queue: {count: 1, running_qid: 'q1'}},
  {running: true, label: 'Translating', done: 0, total: 9,
   queue: {count: 0, running_qid: 'q2'}},
  {running: false, label: '', done: 0, total: 0, cancelled: true,
   queue: {count: 0}},
];
let at = 0;

const dom = new JSDOM(html, {runScripts: 'dangerously',
  url: 'http://127.0.0.1:8765/',
  beforeParse(w) {
    w.fetch = async (url, opt) => {
      if (String(url).indexOf('/api/job/cancel') >= 0)
        return {json: async () => ({ok: true})};
      if (String(url).indexOf('/api/job') >= 0)
        return {json: async () => STEPS[at]};
      if (String(url).indexOf('/api/warm') >= 0)
        return {json: async () => ({running: false})};
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
const btn = () => d.getElementById('cancelJob');
const wait = ms => new Promise(r => setTimeout(r, ms));

setTimeout(async () => {
  try {
    // The Clean is running and the button offers to stop it.
    await w.poll();
    ok('a running action shows the button', btn().style.display !== 'none');
    ok('...saying Cancel', btn().textContent === 'Cancel');
    ok('...and enabled', !btn().disabled);

    await w.cancelJob();
    ok('clicking it says Stopping', btn().textContent === 'Stopping…');
    ok('...and takes the second click away', btn().disabled === true);

    // Still the same action: nothing has changed yet, so nor has the button.
    await w.poll();
    ok('while that action is still going it keeps saying Stopping',
       btn().textContent === 'Stopping…');

    // The Clean has gone and the Translate behind it is running. THIS is the
    // screenshot.
    at = 1;
    await w.poll();
    ok('once the next action starts the button says Cancel again',
       btn().textContent === 'Cancel');
    ok('...and can be clicked', btn().disabled === false);
    ok('...and is still on screen, because something IS running',
       btn().style.display !== 'none');

    // ...and it stops the new one too, rather than being a dead control.
    await w.cancelJob();
    ok('the second action can be cancelled as well',
       btn().textContent === 'Stopping…');

    at = 2;
    await w.poll();
    await wait(20);
    ok('with nothing running the button goes away',
       btn().style.display === 'none');
    ok('...reset for next time', btn().textContent === 'Cancel'
       && btn().disabled === false);

    console.log(bad ? bad + ' FAILED' : 'all good');
    process.exit(bad ? 1 : 0);
  } catch (e) { console.log('THREW', e.stack); process.exit(1); }
}, 60);
