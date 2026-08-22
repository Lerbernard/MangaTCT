"""The clean step keeps what the cleaner said about each box.

`inpaint_page` already reports, per region. It sets `clean_route` to the path
that box took - flat fill, pattern copy, neural, telea, "fell back" - and it
appends to `flagged` when it falls back to the detector's own mask, when it
drops to the letter-like core on a dark panel, when a screentone copy is worth
a look, and when the typesetting is STILL VISIBLE after the retry.
`project.region_record` has serialised both fields all along.

**Nothing committed after cleaning**, so all of it was written onto the
materialised page and dropped with it.

Measured on lee's chapter 1, 71 pages and 134 regions: `clean_route` empty on
every one, and four flags on the whole chapter - three about speaker names and
one about punctuation. Not one from the cleaner. And that is a chapter where
three boxes came back with their Korean still on them, which took a pixel diff
against the originals to find, because the only other way to find them is to
look at 71 pages.

Committing here is the whole fix. `_commit_keep_proofread` and not `commit`,
because `commit()` rebuilds the records from the page and would drop the
editor-only proofread flag - the same reason typeset and export go through it.
"""

import numpy as np
import pytest


def _page(seed=0):
    import cv2
    img = np.full((520, 700, 3), 245, np.uint8)
    img[:] = (240 + seed % 3, 240, 240)
    cv2.ellipse(img, (230, 180), (110, 80), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (230, 180), (110, 80), 0, 0, 360, (25, 25, 25), 3)
    cv2.putText(img, "AAA", (180, 195), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (20, 20, 20), 3)
    return img


@pytest.fixture()
def proj(tmp_path, request):
    import shutil

    import cv2

    from mangatl import editor as ed
    from mangatl.project import Project
    # The plate is cached in memory under the page's box geometry and every
    # fixture here has the same boxes, so a reused plate would run no cleaner
    # and report no route - see `test_which_box_was_cleaned_how`.
    ed._plate_cache.clear()
    root = str(tmp_path / "r")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    seed = abs(hash(request.node.name)) % 97
    p.add_uploaded("p0.png", cv2.imencode(".png", _page(seed))[1].tobytes())
    p.pages[0].regions = [
        {"id": 1, "kind": "bubble", "order": 0, "bbox": [175, 165, 110, 40],
         "bubble_bbox": [175, 165, 110, 40], "polygon": [], "confidence": 0.9,
         "src_text": "a", "dst_text": "HELLO"}]
    p.pages[0].detected = True
    p.save()
    return ed, p


def test_the_route_each_box_took_is_written_down(proj):
    ed, p = proj
    ed.do_clean(p, 0)
    assert p.pages[0].regions[0].get("clean_route"), \
        "the cleaner names the path it took and nobody kept it"


def test_a_note_the_cleaner_wrote_survives_the_step(proj):
    ed, p = proj
    from mangatl import inpaint as ip
    real = ip.inpaint_page

    def loud(page, **kw):
        out = real(page, **kw)
        for r in page.regions:
            r.flagged = (r.flagged or "") + " ghost: still faintly visible"
        return out

    ed.inpaint_mod.inpaint_page = loud
    try:
        ed.do_clean(p, 0)
    finally:
        ed.inpaint_mod.inpaint_page = real
    assert "ghost" in (p.pages[0].regions[0].get("flagged") or "")


def test_and_the_page_is_still_proofread_afterwards(proj):
    """`commit()` rebuilds the records and drops the editor-only flag. Every
    other stage that re-commits goes through the same helper for this reason."""
    ed, p = proj
    p.pages[0].regions[0]["proofread"] = True
    ed.do_clean(p, 0)
    assert p.pages[0].regions[0].get("proofread")


def test_a_page_with_its_own_plate_commits_nothing(proj):
    """It is not cleaned at all - no mask, no route, nothing to report."""
    ed, p = proj
    import cv2
    own = str(p.output_dir) + "/own.png"
    cv2.imwrite(own, _page())
    p.pages[0].custom_clean = own
    ed.do_clean(p, 0)
    assert p.pages[0].cleaned
    assert not (p.pages[0].regions[0].get("clean_route") or "")


def test_the_step_still_marks_the_page_cleaned(proj):
    ed, p = proj
    ed.do_clean(p, 0)
    assert p.pages[0].cleaned


def test_the_record_has_somewhere_to_put_both(proj):
    """`region_record` has carried these two fields all along. The bug was
    never the schema."""
    from mangatl.models import TextRegion
    from mangatl.project import region_record
    r = TextRegion(id=0, bbox=(0, 0, 10, 10), text_mask=None, bubble_mask=None,
                   bubble_bbox=None, kind="bubble")
    r.clean_route, r.flagged = "neural", "ghost: still there"
    rec = region_record(r)
    assert rec["clean_route"] == "neural"
    assert rec["flagged"] == "ghost: still there"


def test_cleaning_a_page_does_not_rewrite_its_geometry(proj):
    """The first version of this called `_commit_keep_proofread`, which writes
    the whole page back - and `materialize` runs the balloon finder over
    `repaired(i)` on the way in. So cleaning rewrote every region's outline
    from a balloon found on the CLEANED plate, where the ink that defines an
    interior has just been erased, and the next clean worked from that. lee:
    *"we regreesse in a lot of ways with the clening"*.
    """
    import copy
    ed, p = proj
    p.pages[0].regions[0]["polygon"] = [[10, 10], [300, 10], [300, 200], [10, 200]]
    before = copy.deepcopy(p.pages[0].regions)
    ed.do_clean(p, 0)
    after = p.pages[0].regions
    assert len(after) == len(before)
    for a, b in zip(after, before):
        for k in ("bbox", "bubble_bbox", "polygon", "kind", "order",
                  "src_text", "dst_text", "layout", "link", "box_group"):
            assert a.get(k) == b.get(k), f"cleaning changed {k}"


def test_and_still_says_what_it_did(proj):
    ed, p = proj
    ed.do_clean(p, 0)
    assert p.pages[0].regions[0].get("clean_route")


def test_a_box_the_page_never_carried_is_left_as_it_was(proj):
    """A hidden box is not on the materialised page, so the cleaner has nothing
    to say about it - and must not blank what it already said."""
    ed, p = proj
    p.pages[0].regions[0]["clean_route"] = "flat fill"
    p.pages[0].regions[0]["flagged"] = "ghost: an old note"
    p.pages[0].hidden_ids = [p.pages[0].regions[0]["id"]]
    ed.do_clean(p, 0)
    assert p.pages[0].regions[0]["clean_route"] == "flat fill"
    assert p.pages[0].regions[0]["flagged"] == "ghost: an old note"
