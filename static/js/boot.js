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
  // ...and the Account page's answer, asked while the app is starting so the
  // page is ready before anyone opens it. lee: *"the account page takes a
  // while to load, make it load as teh app is scting so there no delay"*.
  // See `acctPrefetch`.
  //
  // ONCE THE FIRST PAGE IS UP, not beside it. Asked in the same breath as the
  // page, it was one more request racing the page's own, and the box list
  // came up a beat later - measured on a clean copy, the box-types tests lost
  // a row they check at a fixed moment, and passed again with the prefetch
  // gone. Nobody can reach Settings > Account in the second this waits.
  const _prefetchAccount = () => {
    if(typeof acctPrefetch!=='function') return;
    if(typeof requestIdleCallback==='function')
      requestIdleCallback(acctPrefetch, {timeout: 4000});
    else setTimeout(acctPrefetch, 1500);
  };
  // Home first when nothing is open - lee: *"have a landing page ... like
  // Photoshop has"*. A chapter that is open comes back where it was left,
  // and Home is one click away on the mark at the top left.
  if(!proj.pages.length){ if(typeof setTab==='function') setTab('home'); }
  else {showPage(0);poll();}
  _prefetchAccount();
});
