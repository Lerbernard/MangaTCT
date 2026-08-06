
const {JSDOM}=require('jsdom');
const html=require('./load')();
const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://x/',
  beforeParse(w){
    w.fetch=async()=>({json:async()=>({pages:[],settings:{},context:{},fonts:[]})});
    const g={clearRect(){},beginPath(){},arc(){},fill(){},moveTo(){},lineTo(){},
      stroke(){},drawImage(){},fillRect(){},
      createLinearGradient:()=>({addColorStop(){}}),
      getImageData:()=>({data:[0,0,0]}), set fillStyle(v){}, set strokeStyle(v){},
      set lineWidth(v){}};
    w.HTMLCanvasElement.prototype.getContext=()=>g;
  }});
const w=dom.window,d=w.document;
setTimeout(()=>{
  try{
    // fake the toolbar bits the picker reads
    d.body.insertAdjacentHTML('beforeend',
      '<span class="colwell"><i id="colChip"></i>'+
      '<input id="brushCol" type="hidden" value="#f4f2ee">'+
      '<b id="colHex">#f4f2ee</b></span>');
    w.openPicker(d.querySelector('.colwell'));
    console.log('popover shown:', d.getElementById('picker2').style.display);
    // type a hex
    const hx=d.getElementById('pkHex');
    hx.value='#3366cc';
    hx.dispatchEvent(new w.Event('change'));
    console.log('hex typed -> brush colour:', d.getElementById('brushCol').value);
    // round trip sanity
    console.log('hsv round trip:', w.hsv2hex(220,0.5,0.8),
      JSON.stringify(w.hex2hsv(w.hsv2hex(220,0.5,0.8))));
    // eyedropper path with the popover closed
    w.closePicker();
    w.setPicked('#a1b2c3');
    console.log('eyedropper with popover closed:',
      d.getElementById('brushCol').value,
      d.getElementById('colHex').textContent);
  }catch(e){ console.log('ERR', e.message); process.exit(1); }
  process.exit(0);
},300);
