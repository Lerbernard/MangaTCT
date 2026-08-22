/* Outer glow, inner glow and transparency in the browser's own preview.

   The preview and the exported page have to agree, or the panel is a guess.
   Two of the three are exact - the glow is a text-shadow stack, the fade is
   the block's opacity, both of which is what the exporter does. The inner
   glow is the one deliberate approximation: CSS cannot light the inside of a
   letter, so the preview draws a soft rim on the edge instead. */
const {JSDOM}=require('jsdom');
const html=require('./load')();
const P0={index:0,name:'p0',status:'translated',regions:1,boxes:1,hidden_boxes:0,
          kinds:['bubble'],hidden:[]};
const R={id:0,kind:'bubble',order:0,bbox:[40,40,200,80],
  bubble_bbox:[40,40,200,80],confidence:0.9,dst_text:'BOOM',
  layout:{lines:['BOOM'],font_size:30,leading:1.1,origins:[[140,80]],
          fg:'#ffffff',edge:'#000000',stroke:2,font:'',rotate:0,
          frame:[40,40,200,80],fixed:false,fit_ok:true},
  layout_override:{glow:'#ffc400',glow_size:8,iglow:'#ff3b30',iglow_size:6,
                   opacity:60,locked:true}};
const posted=[];
const PAGE={index:0,name:'p0',width:400,height:300,regions:[R],
  kinds:['bubble'],hidden:[],hidden_boxes:0,custom_clean:false,note:'',
  paint_layers:[]};
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765/',
  beforeParse(w){
    w.fetch=async(url,opt)=>{
      if(opt&&opt.body) posted.push([url,JSON.parse(opt.body)]);
      if(/^\/api\/page\/\d+$/.test(url)) return {json:async()=>PAGE};
      if(/layout_preview$/.test(url))
        return {json:async()=>Object.assign({},R.layout,
          {glow:'#ffc400',glow_size:8,iglow:'#ff3b30',iglow_size:6,opacity:60,
           kind:'bubble',lspace:0,shadow:'',sh_dist:2,sh_blur:3,
           fg1:'',fg2:'',grad_angle:0})};
      return {json:async()=>({pages:[P0],settings:{},context:{},fonts:[]})};
    };
    w.requestAnimationFrame=f=>w.setTimeout(f,0);
    w.HTMLCanvasElement.prototype.getContext=()=>({clearRect(){},beginPath(){},
      arc(){},fill(){},moveTo(){},lineTo(){},stroke(){},drawImage(){},
      // the overset check measures text through a canvas
      measureText:t=>({width:(t||'').length*8}),
      getImageData:()=>({data:[0,0,0]})});
  }});
const w=dom.window,d=w.document;

setTimeout(async ()=>{
  try{
    w.proj={pages:[P0],settings:{},context:{}};
    w.eval("cur=0; view='typeset'; sel=0; scale=1; regions="+JSON.stringify([R])+";");
    if(d.getElementById('showText')) d.getElementById('showText').checked=true;

    w.drawText();
    const grp=d.querySelector('#overlay .tgrp');
    const line=d.querySelector('#overlay .tl');
    console.log('group opacity:', grp.style.opacity);
    const sh=line.style.textShadow.replace(/\s+/g,' ');
    console.log('raw shadow:', sh);
    console.log('glow stops:', (sh.match(/rgb\(255, 196, 0\)|#ffc400/gi)||[]).length);
    console.log('glow has no offset:', /(^|,)\s*0 0 /.test(sh));
    const rim=d.querySelector('#overlay .tl .tg');
    console.log('inner rim:', !!rim, rim && /transparent/.test(rim.style.webkitTextFillColor||''),
                rim && /blur/.test(rim.style.filter||''));
    console.log('rim text matches:', rim && rim.textContent==='BOOM');

    // the panel builds, shows the stored values, and posts them back
    w.renderInspector();
    console.log('panel:', ['lyGlow','lyGlowS','lyIGlow','lyIGlowS','lyOpacity']
      .map(id=>{const e=d.getElementById(id); return id+'='+(e?e.value:'MISSING');})
      .join(' '));
    const patch=w.eval("currentPatch(regions[0])");
    console.log('patch:', JSON.stringify({glow:patch.glow,glow_size:patch.glow_size,
      iglow:patch.iglow,iglow_size:patch.iglow_size,opacity:patch.opacity}));

    // zero is a real answer: it must not turn into 100
    d.getElementById('lyOpacity').value='0';
    console.log('opacity zero:', w.eval("currentPatch(regions[0]).opacity"));

    // and the clear buttons empty the wells
    w.clearGlow(0); w.clearIGlow(0);
    console.log('cleared:', JSON.stringify({g:d.getElementById('lyGlow').value,
      i:d.getElementById('lyIGlow').value,
      gl:d.getElementById('lyGlowHex').textContent,
      il:d.getElementById('lyIGlowHex').textContent}));

    // with nothing set, nothing is added
    w.eval("regions[0].layout_override={locked:true}; regions[0].style=null;");
    w.drawText();
    const plain=d.querySelector('#overlay .tl');
    console.log('plain:', JSON.stringify({
      shadow:plain.style.textShadow||'none',
      rim:!!d.querySelector('#overlay .tl .tg'),
      op:d.querySelector('#overlay .tgrp').style.opacity||'1'}));
    process.exit(0);
  }catch(e){ console.log('ERROR', e && e.stack || e); process.exit(1); }
}, 60);
