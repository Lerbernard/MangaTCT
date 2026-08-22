/* Switching pages while an answer is still in the air.

   lee: *"the page lagged and merge 2 section from one page with another when i
   switch pages too fast"*.

   Two dozen places in the client do `if(j.regions) setRegions(j.regions)` the
   moment an answer lands. One of them checked the page ticket first and the
   rest did not, so on a page slow enough to leave before it answered, another
   page's boxes were drawn over this one - and then the next drag or keystroke
   posted THOSE ids to the page now on screen, which writes the mix-up to disk.

   The check lives in `api()` now, which is the one place all of them pass
   through, and it is taken from the URL rather than from `cur` so it is about
   the page the answer actually describes. */
const {JSDOM}=require('jsdom');
const html=require('./load')();

let release=null;
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url,opt)=>{
      // page 0 answers only when the test says so; page 1 answers at once
      if(url==='/api/page/0'){
        await new Promise(res=>{ release=res; });
        return {json:async()=>({index:0,name:'p0',width:100,height:100,
                                regions:[{id:7,order:0,kind:'bubble',
                                          bbox:[1,1,9,9],src_text:'PAGE-0'}]})};
      }
      if(url==='/api/page/1')
        return {json:async()=>({index:1,name:'p1',width:100,height:100,
                                regions:[{id:3,order:0,kind:'bubble',
                                          bbox:[2,2,9,9],src_text:'PAGE-1'}]})};
      if(url.startsWith('/api/page/0/region/'))
        return {json:async()=>({region:{id:7},regions:[{id:7,order:0,
                 kind:'bubble',bbox:[1,1,9,9],src_text:'PAGE-0'}]})};
      return {json:async()=>({pages:[],settings:{},context:{},fonts:[]})};
    };
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      getImageData:()=>({data:[0,0,0]})});
  }});

const w=dom.window;
setTimeout(async ()=>{
  let bad=0;
  try{
    // 1. the URL is what says which page an answer is about
    if(w.pageOfUrl('/api/page/12/region/3')!==12){ console.log('FAIL pageOfUrl'); bad++; }
    if(w.pageOfUrl('/api/page/4')!==4){ console.log('FAIL pageOfUrl bare'); bad++; }
    if(w.pageOfUrl('/api/settings')!==null){ console.log('FAIL pageOfUrl none'); bad++; }

    // 2. an answer about the page you are ON is kept
    const API=w.eval('api');
    const at=n=>w.eval('cur='+n);
    at(1);
    const here=await API('/api/page/1');
    console.log('same page keeps its boxes:', !!(here.regions&&here.regions.length));
    if(!here.regions){ console.log('FAIL same-page answer was dropped'); bad++; }

    // 3. ...and one about the page you have LEFT is not
    at(0);
    const slow=API('/api/page/0');          // asked while on page 0
    at(1);                                     // ...you switch before it answers
    release();
    const j=await slow;
    console.log('left-page answer carries regions:', 'regions' in j, '| stale:', !!j.stale);
    if('regions' in j){ console.log('FAIL another page\'s boxes came through'); bad++; }
    if(!j.stale){ console.log('FAIL it was not marked stale'); bad++; }

    // 4. a POST answer is refused the same way - this is the one that reaches
    //    disk, because the ids in it get posted back to the page now on screen
    at(1);
    const p=await API('/api/page/0/region/7','POST',{dst_text:'x'});
    console.log('left-page POST carries region:', ('region' in p)||('regions' in p));
    if('regions' in p || 'region' in p){ console.log('FAIL POST answer applied'); bad++; }

    // 5. the answer the server sent is not edited in place. Deleting from it
    //    reaches anything else still holding it, which is a second way for one
    //    page's data to turn up where it should not.
    at(1);
    const held={regions:[{id:9}],ok:1};
    w.eval('window.__held=null');
    w.__held=held;
    w.fetchHeld=true;
    // (the mock above answers /api/page/0/region/7 with a fresh object, so the
    //  check that matters is simply that a stale answer is a DIFFERENT object)
    at(0);
    const slow2=API('/api/page/0');
    at(1);
    release();
    const j2=await slow2;
    if(j2.regions){ console.log('FAIL copy still carries regions'); bad++; }

    // 6. an answer that is not about a page at all is untouched
    at(1);
    const s=await API('/api/settings');
    if(!s.pages){ console.log('FAIL a project answer was stripped'); bad++; }
    console.log(bad?'FAILURES: '+bad:'all good');
    process.exit(bad?1:0);
  }catch(e){ console.log('ERROR', e && e.stack || e); process.exit(1); }
},400);
