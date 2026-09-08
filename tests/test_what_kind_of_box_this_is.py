"""Read text says what KIND each box is, and the four things it may not do.

lee: *"i want prffreader to get sent the pages and to try to accura;y lables
all the boxes with the sub types , give it all the sub tyoes and if a user
creat a sub tyoe it shoud not try to lable a bubble it and if a user deleet one
of teh originals one then teh proofreder shodu not use it, it shoud not creade
or dleet boxes just labbles them"*.

...and then, a minute later: *"alos coun;t read text do the same thing after
its done reading teh text?"*

## Why the reader and not the proofreader

He was right, and the reasons are worth keeping because they are what makes
this the correct step rather than the convenient one.

**The read step already pays for a picture.** `do_proofread` builds
`Page(image=np.zeros(...))` - the proofreader has never seen the artwork. Every
proofread would have had to start buying a page image, and proofreads are
re-run.

**These types are decided by DRAWING.** A thought balloon is a cloud outline
with a trail of circles; a burst is spiky; a whisper is broken; a caption box
is ruled; big-versus-small is size. Not one of them is a question about the
English, and the reader is the step looking at the ink.

**The proofreader cannot see half of them.** `build_proofread_payload` drops
`kind == "sfx"` deliberately, so Big / impact against Small / background was
never a label it could have applied.

## The picture is not the reader's picture

The reader's default is one crop per box, padded 25% around the WRITING - and a
balloon is drawn well outside its writing. Measured on lee's own chapter 3,
over the 141 balloons that carry a traced outline:

    the crop holds the whole outline      21 of 141   (15%)
    median share of the outline inside    0.66
    under 90% of the outline             108 of 141

So a labeller riding on the crops would be judging balloon shape from two
thirds of a balloon, and it gets its own picture instead: the whole page at
768px, which is where every red number tag is still legible and every outline
still readable, for about a third of what a full-resolution page costs.

## The four refusals

Two are lee's vocabulary rules, and they are answered in
`kinds.labelling_vocabulary`: a sub-type somebody INVENTED is never offered,
and a shipped one somebody DELETED is withdrawn. Two are about the boxes
themselves: the family cannot change, and a type a person set by hand is left
alone.

Each is asked for in the prompt AND enforced in code. That is not belt and
braces for its own sake - a prompt is a request, and this is the half that does
not depend on a model complying.
"""
import numpy as np
import pytest

from mangatl import kinds as K
from mangatl import translate as T
from mangatl.models import Page, TextRegion


# --------------------------------------------------------- the vocabulary

def _seeded():
    return K.migrate([], seed=True)


def test_every_shipped_sub_type_is_offered():
    vocab = K.labelling_vocabulary(_seeded())
    offered = {k for items in vocab.values() for k, _l in items}
    for key in K.PRELOAD_KEYS:
        assert key in offered, key


def test_and_so_is_each_family_s_own_default():
    """*"they dont all have to be difrent"* is a different question; this is
    that a box has to be able to stay PLAIN. Without the family's default in
    the list, "none of these" can only be said by silence, and silence is
    indistinguishable from a model that skipped the box."""
    vocab = K.labelling_vocabulary(_seeded())
    for fam in K.FAMILIES:
        assert vocab[fam][0][0] == fam, vocab[fam]


def test_a_sub_type_somebody_invented_is_never_offered():
    """*"if a user creat a sub tyoe it shoud not try to lable a bubble it"*.

    A person who invents "Radio" knows what they mean by it. A model would have
    the word and nothing else, and a guess dressed in somebody's private
    vocabulary looks considered while being arbitrary.
    """
    subs = _seeded() + [{"key": "radio", "label": "Radio", "family": "bubble"}]
    offered = {k for items in K.labelling_vocabulary(subs).values()
               for k, _l in items}
    assert "radio" not in offered
    assert "thought" in offered, "the shipped ones went with it"


def test_a_shipped_one_somebody_deleted_is_withdrawn():
    """*"if a user deleet one of teh originals one then teh proofreder shodu
    not use it"*. Deleting Thought bubble is an answer, and a model putting it
    back on twelve boxes is that answer being overruled by a machine."""
    subs = [s for s in _seeded() if s["key"] != "thought"]
    offered = {k for items in K.labelling_vocabulary(subs).values()
               for k, _l in items}
    assert "thought" not in offered
    assert "whisper" in offered


def test_the_label_and_the_family_come_from_the_project():
    """Only ELIGIBILITY is ours. Somebody who renamed Whisper should see their
    own word for it in the prompt, and somebody who moved a sub-type to another
    family meant that too - reading either back out of `PRELOADED` would
    quietly discard a decision they made."""
    subs = [dict(s) for s in _seeded()]
    for s in subs:
        if s["key"] == "whisper":
            s["label"], s["family"] = "Muttering", "freefloat"
    vocab = K.labelling_vocabulary(subs)
    assert ("whisper", "Muttering") in vocab["freefloat"]
    assert not any(k == "whisper" for k, _l in vocab["bubble"])


def test_the_prompt_describes_every_type_it_offers():
    """A key with no description is a word the model has to guess the meaning
    of, which is the exact failure the invented-sub-type rule exists to
    prevent - reintroduced by omission."""
    vocab = K.labelling_vocabulary(_seeded())
    sys = T.build_label_system(vocab)
    for items in vocab.values():
        for key, label in items:
            assert '"%s"' % key in sys, key
            assert label in sys, label
            assert K.PRELOAD_KEYS and (key in T.LABEL_LOOKS), key


def test_the_prompt_says_the_family_cannot_change():
    sys = T.build_label_system(K.labelling_vocabulary(_seeded()))
    assert "FAMILY CANNOT CHANGE" in sys
    assert "not deciding which boxes should exist" in sys


def test_an_unsure_answer_leaves_the_box_alone():
    """The whole population matters more than any one box. Every box already
    HAS a usable type, so an uncertain label is not an improvement on nothing -
    it is a regression somebody has to find and undo.

    It used to say *"when in doubt, answer the family's default"*, and that is
    not leaving a box alone: it is CHANGING it, to plain speech, on no
    evidence. A box the detector got right, or that somebody labelled by hand,
    was overwritten by a shrug. lee: *"if the ai is not confident of a box
    acthergory it shoud not change the type"*."""
    sys = T.build_label_system(K.labelling_vocabulary(_seeded()))
    assert "WHEN IN DOUBT" in sys
    assert '"sure"' in sys, "the reply has no way to say it is unsure"
    assert "keeps whatever type it already has" in sys
    assert "ANSWER THE FAMILY'S DEFAULT" not in sys, \
        "the old rule is still in the prompt"


def test_and_that_is_enforced_and_not_merely_asked_for(monkeypatch):
    """A prompt is a request. The same reasoning as the family rule below."""
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":0,"kind":"thought","sure":false},'
                      '{"id":1,"kind":"shout","sure":true}]}')
    assert got == {1: "shout"}, got


def test_but_a_missing_word_reads_as_sure(monkeypatch):
    """The safe direction rather than the strict one. A model that ignores the
    field would otherwise have every one of its answers thrown away and this
    step would quietly stop doing anything at all - a silent total regression,
    which is worse than the thing being fixed. Only an explicit false counts.
    """
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":0,"kind":"thought"},'
                      '{"id":1,"kind":"shout","sure":true}]}')
    assert got == {0: "thought", 1: "shout"}, got


def test_an_unsure_box_still_gives_up_its_angle(monkeypatch):
    """The two answers are about different things - what the box IS, and which
    way its writing leans - and being unsure of one says nothing about the
    other. The same reasoning that already keeps an angle when the KIND is
    rejected for its family."""
    angles = {}
    def fake(client, kind, model, system, user, image_b64,
             media_type="image/png"):
        return ('{"regions":[{"id":2,"kind":"sfx_big","sure":false,'
                '"angle":-12.5}]}')
    monkeypatch.setattr(T, "_ask_vision", fake)
    K.use(_seeded())
    got = T.label_kinds(_page(), _Ctx(), b"png",
                        K.labelling_vocabulary(_seeded()),
                        client=object(), model="m", angles=angles)
    assert got == {}, got
    assert angles == {2: -12.5}, angles


# ------------------------------------------------- a flash is not a thought

def test_a_flash_balloon_has_a_type_of_its_own():
    """lee, with a picture of one holding a line a character says out loud to
    somebody standing in front of her: *"this is calsiified as a thught
    bubble, its not , make a new clasificicaton and name it fancy bubble"*.

    It was filed under Thought on his own earlier instruction - *"flash
    bubbles shub be considered thoughts bubbles"* - and that did not merely
    mislabel it. A thought balloon is set in ITALIC to say "not said aloud",
    and a flash balloon is said aloud."""
    assert ("fancy", "Fancy bubble") in K.PRELOADED["bubble"]
    assert T.LABEL_LOOKS["fancy"], "the prompt cannot describe it"
    assert "SPOKEN" in T.LABEL_LOOKS["fancy"]


def test_what_decides_it_is_what_is_drawn_AROUND_the_balloon():
    """The first description was about the FLASH shape alone - a smooth core
    with a halo of fine radial spikes - because that was the balloon lee sent.
    His second is nothing like it: a soft LUMPY outline with little flowers
    dotted in the space around it, holding "R-Really?!". lee: *"here is
    another exmale of a happy bubble"*.

    By outline alone that one is a textbook thought balloon, and it is a
    character speaking. What the two have in common is not their edge, it is
    the DECORATION outside it - which is the artist drawing delight, and
    delight is a thing you say out loud.

    A description that only fits the example it was written from is a
    description that labels one page.
    """
    look = T.LABEL_LOOKS["fancy"]
    assert "AROUND THE BALLOON" in look, look
    for mark in ("sparkles", "stars", "flowers", "spikes"):
        assert mark in look, mark
    assert "may be anything" in look, "the outline is still doing the deciding"


def test_and_thought_says_it_has_nothing_drawn_round_it():
    """The matching half. A description two types could both be read as
    fitting is a description that decides nothing - and a lumpy outline is
    exactly what both of these have."""
    look = T.LABEL_LOOKS["thought"]
    assert "nothing drawn in the space around it" in look, look
    assert "FLASH" not in look
    assert "starburst" not in look


def test_the_pair_that_will_be_confused_is_spelled_out():
    """`LABEL_APART` is for the pairs that actually get confused, and this is
    now one of them: they can share an outline, and only one is unvoiced."""
    apart = " ".join(T.LABEL_APART)
    assert "told apart by what is drawn AROUND" in apart
    assert "even when the outline is lumpy" in apart
    # ...and the flash/burst line, which used to send a flash to thought.
    assert "answer fancy" in apart
    assert "starburst - answer thought" not in apart


def test_it_is_set_in_the_speech_face_and_not_the_thought_one():
    """It took the thought face when the type was split off - lee: *"make it
    have teh same fonts"* - and it takes the SPEECH face now, which is his
    second answer: *"make thses teh defualts"*, with the panel in front of him
    and the Fancy bubble row reading Comic Neue Regular.

    It is also the better answer, and for the same reason the type exists at
    all. The italic was inherited from a type this one had been wrongly filed
    under, and italic in a balloon means "not said aloud" - the exact thing a
    fancy balloon is not. What makes it fancy is drawn round the balloon by
    the artist; the typesetting does not need to say it twice."""
    from mangatl.typeset import DEFAULT_FONTS
    assert DEFAULT_FONTS["fancy"] != DEFAULT_FONTS["thought"], \
        "a spoken balloon is still being set in the unvoiced face"
    assert DEFAULT_FONTS["fancy"] == "ComicNeue-Regular.ttf"


# ------------------------------------------------------------ the asking

class _Ctx:
    medium = "manga"; source = ""; target = "en"
    backend = "anthropic"; base_url = ""; model = "m"; api_key = "k"
    safety = ""; step_name = ""


def _page(kinds=("bubble", "bubble", "sfx", "freefloat")):
    pg = Page(image=np.zeros((400, 300, 3), np.uint8))
    pg.regions = []
    for n, k in enumerate(kinds):
        r = TextRegion(id=n, bbox=(10 + 20 * n, 10, 18, 18), kind=k)
        r.order = n
        pg.regions.append(r)
    return pg


def _ask(monkeypatch, reply, page=None, subs=None, ctx=None):
    seen = {}

    def fake(client, kind, model, system, user, image_b64,
             media_type="image/png"):
        seen["system"], seen["user"] = system, user
        return reply

    monkeypatch.setattr(T, "_ask_vision", fake)
    K.use(subs if subs is not None else _seeded())
    got = T.label_kinds(page or _page(), ctx or _Ctx(), b"png",
                        K.labelling_vocabulary(subs if subs is not None
                                               else _seeded()),
                        client=object(), model="m")
    return got, seen


def test_a_label_comes_back_for_each_box(monkeypatch):
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":0,"kind":"thought"},'
                      '{"id":1,"kind":"shout"},'
                      '{"id":2,"kind":"sfx_big"},'
                      '{"id":3,"kind":"sign"}]}')
    assert got == {0: "thought", 1: "shout", 2: "sfx_big", 3: "sign"}


def test_a_label_from_another_family_is_dropped(monkeypatch):
    """Enforced HERE and not only asked for in the prompt. A balloon called a
    sound effect stops being cleaned as a balloon and drops out of proofreading
    altogether, which is not a cost worth paying for a model's good intentions.
    """
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":0,"kind":"sfx_big"},'
                      '{"id":1,"kind":"thought"}]}')
    assert got == {1: "thought"}, got


def test_a_type_it_was_never_offered_is_dropped(monkeypatch):
    """Including one a person invented - the same rule the vocabulary applies,
    asked again of the reply, because the vocabulary only controls what was
    ASKED for."""
    subs = _seeded() + [{"key": "radio", "label": "Radio", "family": "bubble"}]
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":0,"kind":"radio"},'
                      '{"id":1,"kind":"whisper"}]}', subs=subs)
    assert got == {1: "whisper"}, got


def test_a_deleted_type_is_dropped_even_if_the_model_names_it(monkeypatch):
    subs = [s for s in _seeded() if s["key"] != "thought"]
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":0,"kind":"thought"},'
                      '{"id":1,"kind":"shout"}]}', subs=subs)
    assert got == {1: "shout"}, got


def test_an_id_that_is_not_on_the_page_is_dropped(monkeypatch):
    """This is the whole of *"it shoud not creade or dleet boxes"*. The
    function returns {existing id: type} and has no vocabulary for saying
    anything else - a number nobody recognises is the only way it could have
    reached for one."""
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":99,"kind":"thought"},'
                      '{"id":0,"kind":"thought"}]}')
    assert got == {0: "thought"}, got


def test_a_box_somebody_made_themselves_is_not_labelled(monkeypatch):
    """`own_text` stands for no writing in the artwork. There is nothing drawn
    round it to read a type off, because there is nothing drawn."""
    pg = _page()
    pg.regions[1].own_text = True
    got, seen = _ask(monkeypatch,
                     '{"regions":[{"id":0,"kind":"thought"},'
                     '{"id":1,"kind":"shout"}]}', page=pg)
    assert got == {0: "thought"}, got
    assert "\n1:" not in seen["user"], "it was listed after all"
    # ...and the picture still NUMBERS it, because `page_label_png` outlines
    # every region there is. Left out of the listing and told to be ignored is
    # the pair that agrees with itself; leaving it out alone would set the
    # listing against the prompt's "one entry per numbered region".
    assert "may not be in that list" in seen["user"]


def test_the_listing_says_what_each_box_already_is(monkeypatch):
    """Two facts, and both are load-bearing: the family, because it is the one
    thing that cannot change, and the current type, because the model is being
    asked to improve on it rather than to start from nothing."""
    _got, seen = _ask(monkeypatch, '{"regions":[]}')
    assert "0: family bubble, currently bubble" in seen["user"]
    assert "2: family sfx, currently sfx" in seen["user"]


def test_a_reply_that_is_not_json_is_asked_again_then_given_up(monkeypatch):
    """A page whose types could not be improved on keeps every type it arrived
    with. Nothing about a failed label is worth failing a read over."""
    calls = {"n": 0}

    def fake(client, kind, model, system, user, image_b64,
             media_type="image/png"):
        calls["n"] += 1
        return "sorry, I cannot"

    monkeypatch.setattr(T, "_ask_vision", fake)
    K.use(_seeded())
    got = T.label_kinds(_page(), _Ctx(), b"png",
                        K.labelling_vocabulary(_seeded()),
                        client=object(), model="m")
    assert got == {}
    assert calls["n"] == 2, calls


def test_nothing_is_asked_when_there_is_nothing_to_ask(monkeypatch):
    """No picture, no vocabulary, or no boxes - each of them means the request
    is a page image bought for no possible answer."""
    def boom(*a, **k):
        raise AssertionError("asked anyway")
    monkeypatch.setattr(T, "_ask_vision", boom)
    K.use(_seeded())
    vocab = K.labelling_vocabulary(_seeded())
    assert T.label_kinds(_page(), _Ctx(), b"", vocab, client=object()) == {}
    assert T.label_kinds(_page(), _Ctx(), b"png", {}, client=object()) == {}
    empty = Page(image=np.zeros((10, 10, 3), np.uint8))
    empty.regions = []
    assert T.label_kinds(empty, _Ctx(), b"png", vocab, client=object()) == {}


# ------------------------------- the one exception: sound effect vs outside

def test_the_family_may_move_between_those_two_when_asked(monkeypatch):
    """lee: *"can read text do this before chnage teh sub type and after
    reading? or does it have to be the translation?"*

    It can and it should. His own switch says why - *"Find text tells these two
    apart by shape, and they have the same shape ... Reading the words settles
    it"* - and the reading has already happened by the time this runs. Doing it
    at Read text also means the sub-type is chosen INSIDE the corrected family,
    instead of being assigned to the wrong one and stranded there.
    """
    class Ctx(_Ctx):
        retype_kinds = True
    pg = _page(("sfx", "freefloat"))
    got, seen = _ask(monkeypatch,
                     '{"regions":[{"id":0,"kind":"aside"},'
                     '{"id":1,"kind":"sfx"}]}', page=pg, ctx=Ctx())
    assert got == {0: "aside", 1: "sfx"}, got
    assert "ONE EXCEPTION" in seen["system"]


def test_and_may_not_when_the_switch_is_off(monkeypatch):
    """It is lee's switch and it is off by default. With it off this is the
    plain rule again: the family cannot change."""
    pg = _page(("sfx", "freefloat"))
    got, seen = _ask(monkeypatch,
                     '{"regions":[{"id":0,"kind":"aside"},'
                     '{"id":1,"kind":"sfx"}]}', page=pg)
    assert got == {}, got
    assert "ONE EXCEPTION" not in seen["system"]


def test_and_never_for_a_balloon(monkeypatch):
    """*"only those 2"*, and the reason is unchanged: a bubble is a bubble
    whatever is written in it. The switch widens the question for one pair and
    not for the families either side of it."""
    class Ctx(_Ctx):
        retype_kinds = True
    pg = _page(("bubble", "sfx"))
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":0,"kind":"sfx_big"},'
                      '{"id":1,"kind":"thought"}]}', page=pg, ctx=Ctx())
    assert got == {}, got


def test_those_two_are_listed_with_what_was_read_in_them(monkeypatch):
    """The shape decides nothing for this pair, so the words have to be in the
    prompt. ONLY those two - a page of transcriptions would be a second copy of
    the reading inside a prompt that is about the drawing."""
    class Ctx(_Ctx):
        retype_kinds = True
    pg = _page(("sfx", "bubble"))
    pg.regions[0].src_text = "ドン"
    pg.regions[1].src_text = "こんにちは"
    _got, seen = _ask(monkeypatch, '{"regions":[]}', page=pg, ctx=Ctx())
    assert "reads ドン" in seen["user"], seen["user"]
    assert "こんにちは" not in seen["user"], "a balloon's words were sent too"


def test_the_words_are_not_sent_when_the_switch_is_off(monkeypatch):
    """Nothing is gained by paying for them: with the switch off no answer
    that depends on them can be accepted."""
    pg = _page(("sfx",))
    pg.regions[0].src_text = "ドン"
    _got, seen = _ask(monkeypatch, '{"regions":[]}', page=pg)
    assert "ドン" not in seen["user"]


# -------------------------------------------------------- through the step

def _drive(monkeypatch, labels, regs=None, settings=None, offline=False):
    """Run the real `editor.do_ocr` over a stub project, with the labeller's
    ANSWER scripted. What the step really did is read back off the page."""
    import types
    from mangatl import editor
    from mangatl import ocr as O
    seen = {}
    monkeypatch.setattr(O, "page_label_tiles", lambda *a, **k: [])
    monkeypatch.setattr(O, "page_label_png", lambda *a, **k: b"png")
    monkeypatch.setattr(T, "read_page_ocr",
                        lambda *a, **k: {r.id: "x" for r in regs})
    monkeypatch.setattr(T, "link_sections", lambda rs: None)
    monkeypatch.setattr(editor, "reorder", lambda p, i, **k: None)
    monkeypatch.setattr(editor, "reading_offline", lambda p: offline)
    # ...and the offline reader itself, which would otherwise go and fetch
    # manga-ocr's weights. What is under test is what happens AFTER a read,
    # and both readers leave the same thing behind: words on the regions.
    monkeypatch.setattr(editor, "_read_here",
                        lambda p, pg, say: [setattr(r, "src_text", "x")
                                            for r in pg.regions])
    monkeypatch.setattr(editor, "_ctx_from_settings", lambda p, s: None)
    def fake_label(*a, **k):
        seen["asked"] = True
        return dict(labels)

    monkeypatch.setattr(T, "label_kinds", fake_label)
    page = Page(image=np.full((80, 40, 3), 245, np.uint8), regions=list(regs))
    st = {"drop_symbol_only": False, "drop_empty": False,
          "drop_read_twice": False, "custom_kinds": _seeded(),
          # ...and the switch ON, because it is OFF by default now and every
          # test below is about what happens when somebody has turned it on.
          # The two tests about the DEFAULT say so themselves.
          "label_kinds": True}
    st.update(settings or {})
    p = types.SimpleNamespace(
        settings=st, ctx=_Ctx(), job={}, ink_seen={},
        materialize=lambda i: page,
        commit=lambda i, pg: seen.setdefault(
            "committed", {r.id: r.kind for r in pg.regions}))
    K.use(st["custom_kinds"])
    editor.do_ocr(p, 0)
    seen["kinds"] = {r.id: r.kind for r in page.regions}
    seen["ids"] = [r.id for r in page.regions]
    return seen


def _regs(*kinds):
    out = []
    for n, k in enumerate(kinds):
        r = TextRegion(id=n, bbox=(10 + 20 * n, 10, 18, 18), kind=k)
        r.order = n
        out.append(r)
    return out


def test_the_labels_reach_the_page(monkeypatch):
    got = _drive(monkeypatch, {0: "thought", 2: "sfx_big"},
                 regs=_regs("bubble", "bubble", "sfx"))
    assert got["kinds"] == {0: "thought", 1: "bubble", 2: "sfx_big"}
    assert got["committed"] == got["kinds"], "labelled and then not written"


def test_a_type_somebody_set_by_hand_is_left_alone(monkeypatch):
    """lee chose this. A type you fixed by hand coming back wrong on every
    re-read is worse than no labelling at all - it turns a correction into a
    chore you have to do again after every run.

    `kind_by_hand` is set in ONE place, the region endpoint, which is the only
    way a person can change a kind.
    """
    regs = _regs("bubble", "bubble")
    regs[0].kind_by_hand = True
    got = _drive(monkeypatch, {0: "thought", 1: "thought"}, regs=regs)
    assert got["kinds"] == {0: "bubble", 1: "thought"}, got["kinds"]


def test_a_relabelled_page_is_dropped_from_the_cache(monkeypatch):
    """`cached_page` keys on the index, the NUMBER of regions and the hidden
    families. A relabel changes none of those and changes what the page looks
    like - a box's colour comes from its kind, and a hidden kind takes its
    boxes off the page entirely. So the entry has to go by hand, which is what
    the region endpoint does on the same event."""
    from mangatl import editor
    editor._page_cache[0] = ("stale", object())
    _drive(monkeypatch, {0: "thought"}, regs=_regs("bubble"))
    assert 0 not in editor._page_cache


def test_and_not_when_nothing_moved(monkeypatch):
    """The other half: a page the labeller agreed with keeps its cache. Nothing
    changed, so rebuilding every mask would be work bought for no difference."""
    from mangatl import editor
    keep = ("key", object())
    editor._page_cache[0] = keep
    _drive(monkeypatch, {0: "bubble"}, regs=_regs("bubble"))
    assert editor._page_cache.get(0) is keep


def test_a_labelled_sound_effect_still_stays_out_of_the_proofreader():
    """`build_proofread_payload` read `r.kind != "sfx"`, which was the same
    thing as the family until Read text began labelling sub-types. A box that
    came out as `sfx_big` is not the string "sfx", so every labelled effect
    started arriving at the copy editor - paid for by the box, and handed to
    the one model most likely to turn DOOM into a sentence.

    The exclusion was always about the FAMILY. The string only worked while the
    two were the same thing, which is the shape of every bug the labeller
    caused: a field gained structure, and code that compared it for equality
    was suddenly asking a narrower question than it was written to ask.
    """
    import numpy as np
    from mangatl.models import Page, TextRegion
    K.use(_seeded())
    pg = Page(image=np.zeros((10, 10, 3), np.uint8))
    pg.regions = []
    for n, k in enumerate(("bubble", "thought", "sfx", "sfx_big", "sfx_small",
                           "aside")):
        r = TextRegion(id=n, bbox=(0, 0, 5, 5), kind=k)
        r.order, r.src_text, r.dst_text = n, "x", "WORD"
        pg.regions.append(r)

    class Ctx:
        medium, source, target, honorifics = "manga", "", "en", False
        synopsis, glossary, characters, previous_page_tail = "", {}, {}, []

    sent = {r["kind"] for r in T.build_proofread_payload(pg, Ctx())["regions"]}
    assert not (sent & {"sfx", "sfx_big", "sfx_small"}), sent
    assert {"bubble", "thought", "aside"} <= sent, sent


def test_and_picking_a_sound_effect_sub_type_still_reads_its_axis():
    """Same class again, in the region endpoint: calling a box a sound effect
    is the moment to read the angle the artist drew it at, because the page
    still has the Japanese on it and by typeset time it will not.

    It compared the strings, so picking "Big / impact" off the menu made a box
    a sound effect without ever equalling "sfx" - the axis was never read and
    the effect came out straight on a page where it leans.
    """
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor)
    assert 'rec.get("kind") == "sfx" and was_kind != "sfx"' not in src
    assert '_kinds.family_of(rec.get("kind") or "") == "sfx"' in src


def test_a_family_move_takes_the_geometry_with_it(monkeypatch):
    """A box called outside text still carrying a balloon's polygon typesets
    into the balloon's shape - which is exactly what lee saw once before: *"i
    changed teh bubble to outside buuble an it still typeseete the same"*.

    `_kind_changed` is the endpoint's answer to that, and it works on a stored
    record; `_region_kind_changed` is the same rule for a live page on its way
    to being committed. A SUB-TYPE does not go near either of them - it changes
    no shape.
    """
    regs = _regs("sfx", "sfx")
    for r in regs:
        r.polygon = [[0, 0], [9, 0], [9, 9], [0, 9]]
    got = _drive(monkeypatch, {0: "aside", 1: "sfx_big"}, regs=regs,
                 settings={"retype_kinds": True})
    assert got["kinds"] == {0: "aside", 1: "sfx_big"}
    # the one that changed family had its balloon dropped...
    assert regs[0].polygon != [[0, 0], [9, 0], [9, 9], [0, 9]]
    assert regs[0].bubble_mask is None
    assert "read as freefloat rather than sfx" in (regs[0].flagged or "")
    # ...and the one that only gained a sub-type was left alone
    assert regs[1].polygon == [[0, 0], [9, 0], [9, 9], [0, 9]]
    assert "read as" not in (regs[1].flagged or "")


def test_and_the_box_says_it_in_the_same_words_the_translator_would(monkeypatch):
    """It is the same decision, made a step earlier. A person reading the page
    should not have to know which pass made it to recognise the note."""
    import inspect
    from mangatl import editor, translate
    a = inspect.getsource(editor.label_page_kinds)
    b = inspect.getsource(translate._retype)
    assert "kind: read as %s rather than %s" in a
    assert "kind: read as %s rather than %s" in b


def test_no_box_is_created_or_deleted(monkeypatch):
    """*"it shoud not creade or dleet boxes just labbles them"*. The three
    drops are switched off in this fixture, so anything that moved is this
    step's doing."""
    got = _drive(monkeypatch, {0: "thought", 1: "shout", 2: "sfx_small"},
                 regs=_regs("bubble", "bubble", "sfx"))
    assert got["ids"] == [0, 1, 2]
    assert sorted(got["committed"]) == [0, 1, 2]


def test_the_offline_reader_makes_no_request(monkeypatch):
    """manga-ocr's whole promise is no key, no network and no coins. Quietly
    buying a page image on its behalf would break it, so an offline chapter
    keeps the types the detector gave it."""
    got = _drive(monkeypatch, {0: "thought"}, regs=_regs("bubble"),
                 offline=True)
    assert "asked" not in got, "an offline read went to the network"
    assert got["kinds"] == {0: "bubble"}


def test_it_can_be_turned_off(monkeypatch):
    """It is a REQUEST, not a free pass over boxes already in memory - one more
    turn per page, carrying a picture. Something that costs money on every page
    has to have an off."""
    got = _drive(monkeypatch, {0: "thought"}, regs=_regs("bubble"),
                 settings={"label_kinds": False})
    assert "asked" not in got
    assert got["kinds"] == {0: "bubble"}


def test_it_is_off_until_somebody_switches_it_on(monkeypatch):
    """lee: *"also make it off by defualt"*, and it is the way round this
    belongs. Two reasons, and the second is the one that would still hold if
    the request were free:

    It SPENDS. A setting that buys a request per page without being asked for
    is a setting people find out about from their bill.

    And it CHANGES boxes. Read text was cut back to reading and two deletions
    at lee's own request - *"make it so that read text only read teh etxt and
    not modify boxes exapt for..."* - so a pass that relabels every box on the
    page belongs behind a switch somebody threw.

    Asked of a project with NO key at all, which is every chapter written
    before today: absent has to read as off, so the question is `is True` and
    not `is not False`.
    """
    got = _drive(monkeypatch, {0: "thought"}, regs=_regs("bubble"),
                 settings={"label_kinds": None})
    assert "asked" not in got, "an unasked-for request was made"
    assert got["kinds"] == {0: "bubble"}


def test_and_a_brand_new_chapter_is_off_too(tmp_path):
    """The other end of the same claim, asked of a real project rather than of
    a dict a test built - `_drive`'s fixture could agree with the code and both
    be wrong about what a new chapter gets."""
    from mangatl.project import Project
    p = Project(None, str(tmp_path / "fresh"))
    assert p.settings["label_kinds"] is False, p.settings["label_kinds"]


def test_the_browser_agrees_about_the_default():
    """Both ends have to default it the same way or the screen and the server
    disagree about what the chapter is doing. It is NOT on `DEFAULT_ON` - that
    list means "read with `!==false`", which is how you write a default-ON
    switch, and it was on it for about an hour."""
    from where import PKG
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    decl = js.split("const DEFAULT_ON = [", 1)[1].split("];", 1)[0]
    assert "'label_kinds'" not in decl, decl
    assert "$('label_kinds').checked = proj.settings.label_kinds === true" in js
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    box = html[html.index('id="label_kinds"'):][:120]
    assert "checked" not in box, box


def test_a_labeller_that_throws_does_not_fail_the_read(monkeypatch):
    """The reading is the job and a label is a nicety - the same rule
    `measure_page` sits under two lines further down. A page whose types could
    not be improved on still has every type it arrived with, and every word."""
    import types
    from mangatl import editor
    from mangatl import ocr as O
    regs = _regs("bubble")
    monkeypatch.setattr(O, "page_label_tiles", lambda *a, **k: [])
    monkeypatch.setattr(O, "page_label_png", lambda *a, **k: b"png")
    monkeypatch.setattr(T, "read_page_ocr", lambda *a, **k: {0: "hello"})
    monkeypatch.setattr(T, "link_sections", lambda rs: None)
    monkeypatch.setattr(editor, "reorder", lambda p, i, **k: None)
    monkeypatch.setattr(editor, "reading_offline", lambda p: False)
    monkeypatch.setattr(editor, "_ctx_from_settings", lambda p, s: None)

    def boom(*a, **k):
        raise RuntimeError("no key")
    monkeypatch.setattr(T, "label_kinds", boom)
    page = Page(image=np.full((80, 40, 3), 245, np.uint8), regions=regs)
    done = {}
    p = types.SimpleNamespace(
        settings={"drop_symbol_only": False, "drop_empty": False,
                  "drop_read_twice": False, "custom_kinds": _seeded()},
        ctx=_Ctx(), job={}, ink_seen={}, materialize=lambda i: page,
        commit=lambda i, pg: done.setdefault("ok", True))
    K.use(_seeded())
    editor.do_ocr(p, 0)                      # must not raise
    assert done.get("ok"), "the page was never committed"
    assert regs[0].src_text == "hello", "the reading was lost with the label"
    assert regs[0].kind == "bubble"


def test_a_hand_set_type_survives_being_saved_and_loaded():
    """The flag has to live on the MODEL, not as a key on the record.
    `commit()` rebuilds every record through `region_record()`, so an
    editor-only key dies on the first stage that re-commits the page - which is
    exactly the trap `_commit_keep_proofread` exists to work around for the
    `proofread` flag, and there is no reason to walk into it twice.
    """
    from mangatl.project import region_from_record, region_record
    from mangatl.models import TextRegion as TR
    rec = region_record(TR(id=4, bbox=(1, 2, 30, 40), kind="thought", order=0))
    rec["kind_by_hand"] = True
    r = region_from_record(rec, np.zeros((80, 60, 3), np.uint8))
    assert r.kind_by_hand is True
    assert region_record(r)["kind_by_hand"] is True


def test_the_editor_is_the_only_place_that_sets_it():
    """One writer, and it is the endpoint a person's click arrives at. If
    anything else learns to set this, a guess starts being able to declare
    itself a decision."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor)
    assert src.count('rec["kind_by_hand"] = True') == 1
    assert 'kind_by_hand' not in inspect.getsource(T)


# ------------------------------------------------------- and what it costs

def test_the_estimate_knows_this_turn_happens():
    """A second request per page the quote does not mention is a bill nobody
    agreed to - and it is checked before each page of a longer run, so a quote
    that is short is a run that stops halfway.

    Its OWN shape, not folded into "ocr". It was folded in while it was on by
    default, and that was right then; now that it is off unless somebody asks,
    quoting it inside the read would put a request most chapters never make on
    every page of every read.
    """
    from mangatl import coins
    lab = coins.SHAPES["label"]
    assert lab.fixed_in >= 553, lab
    assert lab.per_box_in > 0, "the listing is one line a box and is not free"
    assert lab.per_box_out > 0, "the reply is one entry a box"
    # ...and the read's own shape is back to describing only the read.
    ocr = coins.SHAPES["ocr"]
    assert ocr.fixed_in < lab.fixed_in + 1747, (ocr, lab)


def test_the_drift_correction_is_not_taught_to_charge_it_twice():
    """The trap that came with giving it its own shape.

    Both requests are metered onto ONE bill, under `step="ocr"` - so the meter
    line for a labelling read carries the reader's tokens plus the labeller's,
    while `predicted("ocr", ...)` describes only the reader. Drift is the ratio
    of the two, so it would settle around 1.5 and stay there; `usd_page("ocr")`
    multiplies the shape by it, and `run_price` then ADDS the labelling on top.
    The same tokens twice, charged to exactly the people who switched it on.

    So the ledger line records whether the run labelled, and `predicted` adds
    the labeller's shape when it did. A line written before any of this existed
    has no such key, comes back False, and is predicted as the read alone -
    which is what it was.
    """
    from mangatl import coins
    n = dict(boxes=40, pages=4, ctx=0, model="claude-sonnet-5")
    plain = coins.predicted("ocr", **n)
    both = coins.predicted("ocr", labelled=True, **n)
    assert both[0] + both[1] > plain[0] + plain[1], (plain, both)
    assert both[2] > plain[2], (plain, both)
    # ...and it is the labeller's shape that was added, not a guess.
    lab = coins.predicted("label", **n)
    assert both[2] == plain[2] + lab[2], (plain, both, lab)
    assert (both[0] + both[1]) == (plain[0] + plain[1]) + (lab[0] + lab[1])
    # An old line has no key at all.
    assert coins.predicted("ocr", **n) == plain


def test_and_the_ledger_line_records_which_kind_of_read_it_was():
    """`predicted` can only tell them apart if the meter line says. Written
    where the run ends, from the same `labels_boxes` the run itself asked."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor)
    assert "labelled=(step == \"ocr\" and labels_boxes(p))" in src
    assert 'bool(e.get("labelled"))' in \
        inspect.getsource(__import__("mangatl.coins", fromlist=["x"]))


def test_and_the_quote_only_adds_it_when_it_will_happen():
    """The same question `do_ocr` asks, asked by `run_price` - and asked
    through the same function, so the two cannot drift into charging for a
    request that is not made."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor.run_price)
    assert 'coins.quote("label"' in src
    assert "labels_boxes(p)" in src


def test_the_two_labelling_switches_do_not_say_the_same_thing():
    """There are two settings in Detection & OCR about box types and they are
    different passes:

        auto_kind    FIND TEXT. Is there a balloon drawn round this writing?
                     Geometry, from the detector, free.
        label_kinds  READ TEXT. Given that it is a balloon, what KIND? The
                     drawing, from the AI, one request a page.

    `auto_kind` was labelled "Label box types" on its own, and for a few
    minutes after `label_kinds` arrived this section held two switches saying
    the same words about different things, with the whole detector block
    between them. lee, looking at it: *"also make teh automated box labbling
    finding a setting in te setting"*, then *"no like teh chnahing teh boxes
    with teh read text"* - he had found the wrong one.

    So they sit together, and each names the step it runs in.
    """
    import re
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    body = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    def caption(box_id):
        i = body.index('id="%s"' % box_id)
        seg = body[i:body.index("</label>", i)]
        return " ".join(re.sub(r"<[^>]+>", " ", seg).split())

    a, b = caption("auto_kind"), caption("label_kinds")
    assert a != b, a
    assert "Read text" in b, b
    assert "Read text" not in a, a
    # ...and they are next to each other, under one heading.
    assert 0 < body.index('id="label_kinds"') - body.index('id="auto_kind"') < 1200
    assert ">Box types</label>" in body


def test_the_switch_exists_on_the_screen_and_is_saved():
    """A setting the server honours and the screen cannot show is a setting
    nobody can turn on; a box the screen shows and never writes back is worse -
    it looks like it worked and does nothing."""
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert 'id="label_kinds"' in html
    assert "label_kinds:$('label_kinds').checked" in js, \
        "the tick is never written back"


def test_one_function_decides_whether_the_labelling_happens():
    """`editor.labels_boxes`. Two places ask - `do_ocr`, which does it, and
    `run_price`, which charges for it - and they have to give the same answer
    or a page is billed for a request it never makes, or makes one it was not
    billed for.

    Both halves live in there: the switch, and the reader being the AI. It is
    the offline half that would have been missed - an offline read makes no
    labelling request, and a quote that forgot would have charged for one.
    """
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor)
    assert src.count("labels_boxes(p)") >= 2, "somebody is asking their own way"
    body = inspect.getsource(editor.labels_boxes)
    assert "label_kinds" in body and "reading_offline" in body, body


def test_the_quote_prices_the_cache_the_way_the_code_asks_for_one():
    """`sys_in` is the CACHEABLE part, and Read text sends two prompts on two
    turns - the reader's and the labeller's. Only one of them clears
    `_cacheable`'s threshold, and `sys_in` has to be that one.

    Pinned against the prompts themselves rather than against the numbers,
    because this is a THRESHOLD the prompt can cross by being edited. It has
    already crossed once: the labeller's prompt was under the floor when it was
    written and went over it when lee's reference charts turned four
    descriptions into eleven. A comment saying which is cacheable is a comment
    that goes quietly wrong; this goes red.
    """
    from mangatl import coins
    from mangatl import kinds as K
    # Each turn's prompt against its OWN shape, and the cache treatment asked
    # of `_cacheable` rather than assumed. Both of these have crossed the floor
    # once already - the labeller upward when lee's reference charts turned
    # four descriptions into eleven, the reader upward a few hours later when
    # it was taught to keep the marks a line carries. An earlier version of
    # this test asserted the reader's prompt was NOT cacheable, which was true
    # when it was written and false by the end of the day.
    # The labeller's prompt is priced WITH the angle rule on it, because that
    # is the page this step is for: one with loose writing, which is where a
    # sub-type and a lean are both worth asking about. A page of nothing but
    # balloons never carries the rule and is quoted a little over - the right
    # way round for a quote given before the button is pressed.
    for step, prompt in (("label",
                          T.build_label_system(K.labelling_vocabulary(_seeded()),
                                               want_angle=True)),
                         ("ocr", T.build_ocr_system()),
                         ("proofread", T.build_proofread_system())):
        sh = coins.SHAPES[step]
        assert abs(sh.sys_in - len(prompt) / 4) < 130, \
            (step, sh.sys_in, len(prompt) / 4)
        want = sh.sys_in if T._cacheable(prompt) else 0
        assert coins.cached_tokens(sh, "claude-sonnet-5") == want, \
            (step, T._cacheable(prompt), coins.cached_tokens(sh,
                                                             "claude-sonnet-5"))
