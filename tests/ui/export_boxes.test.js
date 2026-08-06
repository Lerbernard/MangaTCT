/* The Export dialog's third choice: the page with the boxes drawn on.

   lee: "add a button n in the export that allow me to export the picture with
   the boxes".

   The two things a mode has to get right are the folder name and what gets
   posted. A box sheet is not the finished chapter, so it must not land in the
   folder the finished chapter went to — and the suffix has to come off the
   name as it was before ANY mode touched it, or clean -> boxes reads
   "chapter-cleaned-boxes". */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const PAGE={index:0,name:'p',status:'cleaned',cleaned:true,regions:1};
const posted=[];
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url,opt)=>{
      if(opt&&opt.body) posted.push([url,JSON.parse(opt.body)]);
      if(url==='/api/page/0')
        return {json:async()=>({index:0,name:'p',width:960,height:1365,
                                regions:[],custom_clean:false})};
      if(url==='/api/export') return {json:async()=>({started:1,dir:'D:\\out\\x'})};
      if(url==='/api/can_browse') return {json:async()=>({ok:false})};
      return {json:async()=>({pages:[PAGE],settings:{},context:{},fonts:[]})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;

setTimeout(async ()=>{
  try{
    w.proj={pages:[PAGE],settings:{},context:{}};
    w.eval('regions=[]; cur=0;');

    const mode=d.getElementById('expMode'), name=d.getElementById('expName');
    const opts=[...mode.options].map(o=>o.value);
    console.log('modes offered:', opts.join(','));

    name.value='chapter-12-en';
    w.eval("_expNameWas=''");
    mode.value='boxes'; w.expModeChanged();
    console.log('boxes name:', name.value);
    console.log('boxes blurb mentions boxes:',
      /boxes drawn on|with the boxes/i.test(d.getElementById('expBlurb').textContent));

    mode.value='clean'; w.expModeChanged();
    console.log('then clean name:', name.value);
    mode.value='boxes'; w.expModeChanged();
    console.log('back to boxes name:', name.value);
    mode.value='full'; w.expModeChanged();
    console.log('back to full name:', name.value);

    // and the post actually carries the mode
    mode.value='boxes';
    d.getElementById('expDir').value='D:\\out';
    d.getElementById('expScope').value='all';
    await w.doExport();
    const exp=posted.filter(p=>p[0]==='/api/export').pop();
    console.log('posted mode:', exp && exp[1].mode);
    console.log('dialog closed:',
      !d.getElementById('expdlg').classList.contains('on'));
    process.exit(0);
  }catch(e){ console.log('ERROR', e && e.stack || e); process.exit(1); }
}, 60);
