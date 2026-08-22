/* Where the Side-by-side switch lives, and when.

   It sat out in the open beside "Snap boxes", on every tab and in every
   view - including the Original view, where the reference pane it opens is
   the same picture twice, and the Results and Settings tabs, where there is
   no page on screen at all. lee asked for it beside the "Translated text"
   switch and only where it does something. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const PAGE={index:0,name:'p',status:'cleaned',cleaned:true,regions:1};
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url)=>{
      if(url==='/api/page/0')
        return {json:async()=>({index:0,name:'p',width:960,height:1365,
                                regions:[],custom_clean:false})};
      return {json:async()=>({pages:[PAGE],settings:{},context:{},fonts:[]})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;
const shown=id=>{const e=d.getElementById(id);
  return !!e && e.style.display!=='none';};

setTimeout(async ()=>{
  try{
    w.proj={pages:[PAGE],settings:{},context:{}};
    w.regions=[]; w.cur=0;

    const sbs=d.getElementById('sbsWrap'), txt=d.getElementById('showTextWrap');
    if(!sbs||!txt) throw new Error('the switches are not both on the page');
    // DOCUMENT_POSITION_FOLLOWING === 4: txt comes after sbs
    const order=sbs.compareDocumentPosition(txt)&4 ? 'before' : 'after';
    console.log('side by side sits:', order, 'the translated-text switch');

    w.setTab('edit'); w.setView('original');
    console.log('edit tab, original view:', shown('sbsWrap'));
    w.setView('typeset');
    console.log('edit tab, edit view:', shown('sbsWrap'));

    w.toggleSideBySide(true);
    console.log('pane with it on, edit view:', shown('refWrap'));
    // Results is shut until a chapter has been exported; this test is about
    // the side-by-side switch, not about that gate.
    w.hasExports = true;
    w.setTab('results');
    console.log('results tab:', shown('sbsWrap'), 'pane:', shown('refWrap'));
    w.setTab('edit');
    console.log('back on edit:', shown('sbsWrap'), 'pane:', shown('refWrap'));
    process.exit(0);
  }catch(e){ console.log('ERROR', e && e.stack || e); process.exit(1); }
}, 60);
