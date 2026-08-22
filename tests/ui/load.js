/* Rebuilds the editor page for JSDOM. The editor is served as editor.html
   plus /static/css and /static/js files; JSDOM does not fetch external
   resources, so this reads editor.html and inlines each linked stylesheet
   and script in place, in order. The result behaves exactly like the page
   a browser sees. */
const fs=require('fs'),path=require('path');
/* Two up from tests/ui is the package itself - `static/` is right there.
   This used to walk two up and then back DOWN into a folder named for the
   package, which is only true when tests/ sits beside it rather than inside
   it. Same bug the Python suite had, same fix. */
const ROOT=path.join(__dirname,'..','..','static');
module.exports=function loadEditorHtml(){
  let html=fs.readFileSync(path.join(ROOT,'editor.html'),'utf8');
  html=html.replace(/<link rel="stylesheet" href="\/static\/([^"]+)">/g,
    (_,rel)=>'<style>\n'+fs.readFileSync(path.join(ROOT,rel),'utf8')+'</style>');
  html=html.replace(/<script src="\/static\/([^"]+)"><\/script>/g,
    (_,rel)=>'<script>\n'+fs.readFileSync(path.join(ROOT,rel),'utf8')+'</script>');
  if(/<script src=/.test(html)) throw new Error('un-inlined script tag left behind');
  return html;
};
