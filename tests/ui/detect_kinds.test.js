/* The three boxes in "What should I look for?".

   lee sent a screenshot of this dialog with two of them greyed out and a note
   saying the choice "doesn't apply". That was true of the search and never of
   the result: comic-text-detector hands back every block on the page and says
   what kind each one is, so the kinds are known by the time the page comes back
   and the choice bites there - only_kinds() in project.py. These pin that the
   boxes stay live whichever finder is picked.

   There was a paragraph in the dialog saying so, and there was a second
   whole-page finder once, an AI mode. Both are gone - the finder with its
   setting, the paragraph because lee asked for the dialog to stop being a wall
   of grey. What it explained is still true and is still asserted here, on the
   boxes themselves. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>({json:async()=>(
      url==='/api/job' ? {running:false,done:0,total:0} :
      {pages:[],settings:{},context:{},fonts:[]})});
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;

let bad=0;
function ok(name,cond){ console.log((cond?'ok   ':'FAIL ')+name); if(!cond) bad++; }

setTimeout(()=>{
  try{
    const ids=['kBubble','kFree','kSfx'];
    const live=()=>ids.every(i=>{
      const cb=d.getElementById(i);
      return cb && !cb.disabled && !cb.closest('label').classList.contains('disabled');
    });

    // `proj` is a top-level `let` in core.js, so it lives in the global
    // lexical scope and is not a property of window - assigning w.proj would
    // quietly make a second, unread variable. eval reaches the real one.
    const set=(det)=>{
      d.getElementById('detector').value=det;
      w.syncDetectKinds();
    };

    set('classical');
    ok('classical: all three boxes are live', live());

    set('comictext');
    ok('comic-text-detector: all three boxes stay live', live());

    // No stale setting from an older project may reach in and grey one out.
    w.eval("proj={settings:{ai_boxes:'find'}}");
    set('classical');
    ok('a stale ai_boxes in an old project changes nothing', live());

    // The dialog no longer carries the paragraph that explained the above.
    ok('the explaining paragraph is gone', !d.getElementById('ctdNote'));

    // And greying one out again must be caught: nothing in the page may
    // disable them behind syncDetectKinds' back.
    d.getElementById('kSfx').disabled=true;
    set('comictext');
    ok('a box left disabled is turned back on', live());

    // The dialog opens through openDetect(), which is what actually runs it.
    d.getElementById('kFree').disabled=true;
    w.openDetect();
    ok('opening the dialog syncs the boxes', live());
    ok('opening the dialog shows it', d.getElementById('modal').classList.contains('on'));

    console.log(bad? bad+' FAILED' : 'all good');
    process.exit(bad?1:0);
  }catch(e){ console.log('THREW',e.stack); process.exit(1); }
},60);
