/* boot.js - Startup: install fonts, load the project, pick a page or open the chapter picker.
   Split from editor.html. Classic script: shares globals with the other
   modules and must load in the order editor.html lists. No build step. */
installFonts();

loadProject().then(()=>{
  // Whether the Results tab is pressable is a question about the export
  // folder, which is on disk and outlives this run of the app.
  if(typeof refreshExports==='function') refreshExports();
  // What is left to spend, and what this chapter would cost. Read once at
  // startup and again whenever a run ends - see poll() in pipeline.js.
  if(typeof refreshCoins==='function') refreshCoins();
  // Home first when nothing is open - lee: *"have a landing page ... like
  // Photoshop has"*. A chapter that is open comes back where it was left,
  // and Home is one click away on the mark at the top left.
  if(!proj.pages.length){ if(typeof setTab==='function') setTab('home'); }
  else {showPage(0);poll();}
});
