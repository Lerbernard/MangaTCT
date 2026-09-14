"""The tabs and the page's controls have a row of their own, under the top bar.

lee, with the top bar in a screenshot - File, Workspace, Results, Settings and
the coins on the left; the zoom, Hide boxes, Side by side, Export preview,
Translated text and Translation/Image on the right: *"mak ea new line for
these"*, then *"and kepp the other stuff on th top row"*, and then, of the
tabs: *"now file workspae etc doen to the new line"*.

So `#navrow` is a second bar between the top bar and the step bar: the four
tabs on its left and `#pageTools` on its right. The top bar keeps the wordmark,
the coins, the Results buttons and the window's own buttons. Measured in the
browser, as `test_centred_pages` measures everything: a rule that is present
and overridden is a rule that is not there.
"""
from test_centred_pages import _serve

import browserpool


_WHERE = """(()=>{
  const r = id => { const e=document.getElementById(id);
    const b=e.getBoundingClientRect();
    return {l:Math.round(b.left), r:Math.round(b.right), t:Math.round(b.top),
            b:Math.round(b.bottom), h:Math.round(b.height)}; };
  const top=document.getElementById('top'), row=document.getElementById('navrow');
  const inside = (box, ids) => ids.filter(id => box.contains(document.getElementById(id)));
  return {top:r('top'), row:r('navrow'), work:r('work'), tabs:r('tabs'),
          zoom:r('zlabel'), coins:r('coinBtn'), vw:innerWidth,
          views: (()=>{const b=row.querySelector('.views').getBoundingClientRect();
                       return {r:Math.round(b.right)};})(),
          inTop: inside(top, ['brandMark','tabs','pageTools','coinBtn',
                              'resultTools','winctl','tbDrag','zlabel','vOriginal']),
          inRow: inside(row, ['tabs','tabNew','tabEdit','tabRes','tabSet',
                              'pageTools','zlabel','hideboxes','vOriginal',
                              'vTypeset','coinBtn'])};})()"""


def test_the_tabs_and_the_page_controls_are_a_row_under_the_top_bar():
    def check(pg, p):
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        g = pg.evaluate(_WHERE)
        assert g["inRow"] == ["tabs", "tabNew", "tabEdit", "tabRes", "tabSet",
                              "pageTools", "zlabel", "hideboxes", "vOriginal",
                              "vTypeset"], g["inRow"]
        # Directly under the top bar, above the step bar, and the whole width.
        assert abs(g["row"]["t"] - g["top"]["b"]) <= 1, g
        assert g["row"]["b"] <= g["work"]["t"] + 1, g
        assert g["row"]["l"] <= 1 and g["row"]["r"] >= g["vw"] - 1, g
        # The tabs on the left of it, the view pair on the right, one line.
        assert g["tabs"]["l"] < 40, g
        assert g["views"]["r"] >= g["vw"] - 40, g
        assert abs((g["tabs"]["t"] + g["tabs"]["b"]) -
                   (g["zoom"]["t"] + g["zoom"]["b"])) <= 6, g
    _serve(check)


def test_the_top_bar_keeps_the_rest():
    def check(pg, p):
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        g = pg.evaluate(_WHERE)
        assert g["inTop"] == ["coinBtn", "resultTools", "winctl", "tbDrag"], \
            g["inTop"]
        assert g["coins"]["t"] < g["row"]["t"], g
        assert g["top"]["h"] < 60, "the top bar is taller than one row: %r" % g
    _serve(check)


def test_the_row_and_its_tabs_stay_on_every_tab_and_only_the_controls_go():
    """The tabs are how you get anywhere, so the row cannot go away with the
    Workspace the way the page's controls do."""
    def check(pg, p):
        for t, tools in (("results", False), ("settings", False),
                         ("new", False), ("edit", True)):
            pg.evaluate(f"setTab('{t}')")
            browserpool.settled(pg)
            got = pg.evaluate("""(()=>{const h=id=>document.getElementById(id)
                .getBoundingClientRect().height; return {row:h('navrow'),
                tabs:h('tabs'), tools:h('pageTools')};})()""")
            assert got["row"] > 0 and got["tabs"] > 0, (t, got)
            assert (got["tools"] > 0) is tools, (t, got)
    _serve(check, exported=1)


def test_the_file_and_home_screens_start_under_the_row_and_leave_the_tabs_usable():
    """Both are drawn over everything below a line. That line was the top
    bar's height, which is now above the tabs."""
    def check(pg, p):
        for how, screen in (("showPicker(true)", "#picker"),
                            ("setTab('home')", "#home")):
            pg.evaluate(how)
            pg.wait_for_timeout(400)
            got = pg.evaluate("""([sel])=>{
                const row=document.getElementById('navrow').getBoundingClientRect();
                const pad=parseFloat(getComputedStyle(document.querySelector(sel))
                                     .paddingTop);
                const tab=document.getElementById('tabSet');
                const r=tab.getBoundingClientRect();
                const hit=document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);
                return {pad:Math.round(pad), rowBottom:Math.round(row.bottom),
                        clickable: hit===tab || tab.contains(hit)};}""", [screen])
            assert abs(got["pad"] - got["rowBottom"]) <= 1, (how, got)
            assert got["clickable"], (how, got)
    _serve(check)
