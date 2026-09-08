# -*- coding: utf-8 -*-
"""Two things a reading is allowed to decide: how a name is addressed, and
whether a box is a noise or an aside.

## Glow-san

lee, over a bubble that reads "Mr. Glow" where the Japanese says グロウさん:
*"a swith that lets the translator keep glow-san instad of mr glow fo rthe
tranlsation it shoud keep styff like oni-chan and other stuff like that that
manga reader like and do it for mnahwa and mahua too"*, and then the limit on
it: *"it shoud only keep teh very popular managa na manhua and manhwa
honotifics"*.

**The switch was already there and only half wired.** `ctx.honorifics` has
been going into the payload as `keep_honorifics`, and the PROOFREAD prompt has
carried a rule about it, since the day it was added. The translate prompt was
never told. So the proofreader was policing a decision the translator had never
been asked to make, which is exactly how a chapter comes back saying "Mr. Glow"
with a rule about "Glow-san" sitting underneath it. And there was no control
anywhere, so nobody could have chosen either way.

**It is a list, not a policy.** "Keep the honorifics" as an instruction gets
拙者 romanised and 部長 left as "buchou". What a scanlation reader wants is the
dozen forms of address every release in the genre already keeps - and a model
given a rule instead of a list picks its own dozen, and a different dozen on
the next page. So `HONORIFIC_NOTES` names them, per source language, and says
outright that everything else is translated.

## sfx or outside text

lee: *"the tranlator or read text shoiud tun sfx into outside text or turn
outside text into sfx only those 2"*.

Those two and no others, and the "only those 2" is the safety in it. Both are
LOOSE TEXT ON THE ARTWORK with no balloon round them - the same shape - which
is precisely why Find text mixes them up: shape is all it has. The words settle
it in an instant, so the first step that can read them is the first step that
can be right about it. Every other kind says something about the PICTURE that
the words cannot overrule, and a bubble is a bubble whatever is written in it.

Off by default, because it rewrites a label the person may have set by hand.
"""
import pytest

from mangatl import translate as T


# ------------------------------------------------------------- the honorifics

def test_off_by_the_switch_and_not_by_accident():
    """The note is in the prompt when the project asks for it and absent when
    it does not - the whole point of a switch."""
    off = T.build_system("manga", "en", "ja")
    on = T.build_system("manga", "en", "ja", honorifics=True)
    assert "Glow-san" in on and "Glow-san" not in off
    assert len(on) > len(off)


def test_each_medium_gets_its_own_language(ed=None):
    """Japanese suffixes for manga, oppa and hyung for manhwa, gege and shizun
    for manhua - off the medium already set in Language & direction."""
    ja = T.build_system("manga", "en", "ja", honorifics=True)
    ko = T.build_system("manhwa", "en", "ko", honorifics=True)
    zh = T.build_system("manhua", "en", "zh", honorifics=True)
    assert "-san" in ja and "onii-chan" in ja
    assert "oppa" in ko and "hyung" in ko and "-nim" in ko
    assert "gege" in zh and "shizun" in zh
    # ...and not each other's.
    assert "oppa" not in ja and "-san" not in ko.replace("seonsaeng-nim", "")
    assert "onii-chan" not in zh


def test_it_is_a_short_list_and_says_so():
    """"Keep the honorifics" is the instruction that romanises 部長. Each note
    ends by saying that the list is the whole of it and everything else is
    translated - which is the half that stops it running away."""
    for src in ("Japanese", "Korean", "Chinese"):
        note = T.HONORIFIC_NOTES[src]
        assert "That list is the whole of it" in note, src
        assert "do not romanise a job title" in note, src
        assert "do not invent" in note, src


def test_the_japanese_list_is_the_one_the_proofreader_polices():
    """Two halves of one decision. The proofread prompt names the suffixes it
    will leave alone; the translate prompt has to name the same ones, or the
    proofreader spends the page taking off what the translator put on."""
    ja = T.HONORIFIC_NOTES["Japanese"]
    pro = T.PROOFREAD_TEMPLATE
    at = pro.index("HONORIFICS are the project's decision")
    rule = pro[at:at + 400]
    for suffix in ("-san", "-sama", "-chan", "-kun", "-dono"):
        assert suffix in ja and suffix in rule, suffix


def test_the_translator_is_actually_told():
    """The bug: `build_system` had no honorifics argument at all, so whatever
    the project decided reached the payload and the proofreader and stopped."""
    import inspect
    src = inspect.getsource(T)
    at = src.index("build_system(ctx.medium, ctx.target")
    assert "honorifics" in src[at:at + 220], \
        "the run does not pass the project's choice to the prompt"


def test_a_project_keeps_them_unless_told_otherwise(tmp_path):
    from mangatl.project import Project
    p = Project(None, str(tmp_path / "h"))
    assert p.settings["keep_honorifics"] is True


# ------------------------------------------------------------------ the kind

class _Ctx:
    def __init__(self, on):
        self.retype_kinds = on


class _Region:
    def __init__(self, kind):
        self.kind = kind
        self.flagged = ""


def test_a_sound_effect_that_reads_as_an_aside_is_relabelled():
    r = _Region("sfx")
    assert T._retype(r, {"kind": "freefloat"}, _Ctx(True)) is True
    assert r.kind == "freefloat"
    assert "read as freefloat rather than sfx" in r.flagged, \
        "the box does not say it was re-labelled"


def test_and_the_other_way_round():
    r = _Region("freefloat")
    assert T._retype(r, {"kind": "sfx"}, _Ctx(True)) is True
    assert r.kind == "sfx"


def test_only_those_two():
    """"only those 2". A bubble is a bubble whatever is written in it, and
    narration says something about the picture the words cannot overrule."""
    for now in ("bubble", "narration"):
        r = _Region(now)
        assert T._retype(r, {"kind": "sfx"}, _Ctx(True)) is False
        assert r.kind == now
    # ...and no region is ever moved INTO a third kind either.
    r = _Region("sfx")
    assert T._retype(r, {"kind": "bubble"}, _Ctx(True)) is False
    assert r.kind == "sfx"


def test_a_sub_typed_effect_can_still_be_corrected():
    """The bug the box labeller introduced, which made this whole switch a
    no-op without saying so.

    This compared `region.kind` against the pair directly, and that was right
    for exactly as long as a loose box could only ever BE `sfx` or `freefloat`.
    Read text labels sub-types now, so an effect arrives here as `sfx_big` -
    not in the pair, so the correction was refused. Measured at the time:

        plain sfx  -> freefloat :  True   -> freefloat
        sfx_big    -> freefloat :  False  -> sfx_big

    A sub-type is a kind OF its family, and nothing about `sfx_big` says the
    box cannot be outside text - it says somebody thought it was a big sound,
    which is the very reading being corrected. So the question is asked of the
    family.
    """
    from mangatl import kinds as K
    K.use(K.migrate([], seed=True))
    for now in ("sfx", "sfx_big", "sfx_small"):
        r = _Region(now)
        assert T._retype(r, {"kind": "freefloat"}, _Ctx(True)) is True, now
        assert r.kind == "freefloat"
        assert "rather than %s" % now in r.flagged, r.flagged
    for now in ("freefloat", "aside", "sign", "narration_free"):
        r = _Region(now)
        assert T._retype(r, {"kind": "sfx"}, _Ctx(True)) is True, now
        assert r.kind == "sfx"


def test_and_a_sub_typed_bubble_still_cannot_be():
    """The other half. Widening the question to families must not widen WHICH
    families - a thought balloon is a balloon, and the reason is unchanged."""
    from mangatl import kinds as K
    K.use(K.migrate([], seed=True))
    for now in ("bubble", "thought", "shout", "whisper", "narration"):
        r = _Region(now)
        assert T._retype(r, {"kind": "sfx"}, _Ctx(True)) is False, now
        assert r.kind == now


def test_the_whole_sub_type_goes_when_the_family_does():
    """`sfx_big` is not a kind of outside text and there is no honest
    translation of it into one. The box lands on the family's own default and
    can be sub-typed again from there - which it will be, on the next read."""
    from mangatl import kinds as K
    K.use(K.migrate([], seed=True))
    r = _Region("sfx_big")
    T._retype(r, {"kind": "freefloat"}, _Ctx(True))
    assert r.kind == "freefloat", "a sub-type of the old family survived"


def test_the_kind_it_already_has_is_not_a_change():
    r = _Region("sfx")
    assert T._retype(r, {"kind": "sfx"}, _Ctx(True)) is False
    assert r.flagged == "", "it noted a change that did not happen"


def test_and_neither_is_a_sub_type_of_the_family_it_is_in():
    """`sfx_big` asked to become `sfx` is not a correction, it is the
    labeller's job undone. This function is about the FAMILY; the sub-type is
    not its business in either direction."""
    from mangatl import kinds as K
    K.use(K.migrate([], seed=True))
    r = _Region("sfx_big")
    assert T._retype(r, {"kind": "sfx"}, _Ctx(True)) is False
    assert r.kind == "sfx_big"
    assert r.flagged == ""


def test_nothing_happens_unless_the_project_asked():
    r = _Region("sfx")
    assert T._retype(r, {"kind": "freefloat"}, _Ctx(False)) is False
    assert r.kind == "sfx"


def test_a_reply_with_no_kind_in_it_changes_nothing():
    """Most regions arrive labelled correctly, and the prompt says to leave the
    field out for those. An absent field is not an instruction."""
    r = _Region("sfx")
    assert T._retype(r, {"translation": "BOOM"}, _Ctx(True)) is False
    assert T._retype(r, {"kind": ""}, _Ctx(True)) is False
    assert T._retype(r, {"kind": None}, _Ctx(True)) is False
    assert r.kind == "sfx"


def test_the_model_is_told_when_to_use_it():
    """A field in the schema nobody explained is a field a model fills in on a
    hunch. The rule says what each of the two IS, and to leave it out when the
    label that arrived is right."""
    sysmsg = T.build_system("manga", "en", "ja")
    assert '"kind"' in T.SCHEMA_HINT and "OPTIONAL" in T.SCHEMA_HINT
    assert "muttered aside" in sysmsg
    assert "Never propose a kind for a region that arrived as anything else" \
        in sysmsg
    assert "leave \"kind\" out entirely" in sysmsg


def test_it_is_off_until_asked_for(tmp_path):
    """It rewrites a label somebody may have set by hand."""
    from mangatl.project import Project
    p = Project(None, str(tmp_path / "k"))
    assert p.settings["retype_kinds"] is False


# ----------------------------------------------------------------- the screen

def test_both_switches_are_on_the_translation_section():
    """The switches, and their LABELS, are what this test is for.

    It used to also demand the worked example - "グロウさん comes out
    Glow-san" - stood under the switch. lee took that paragraph off the
    screen along with five others: *"remove these text form teh setting"*.
    A settings page is a place to set things, not to be taught; the reasoning
    is kept in the HTML comment beside each switch, where whoever changes it
    will read it and the person using the app will not have to.

    So the label has to say what the switch is, and nothing here may demand
    prose underneath it.
    """
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    nav = html.index('<button class="setnav-btn" data-sec="wording"')
    at = html.index('<section class="set-section" data-sec="wording">')
    sec = html[at:html.index("</section>", at)]
    assert 'id="keep_honorifics"' in sec and 'id="retype_kinds"' in sec
    assert "Keep honorifics and forms of address" in sec, \
        "the switch does not say what it is"
    assert "sound effect vs outside text" in sec, \
        "the switch does not say what it is"
    assert nav < at, "there is no nav button for it"


def test_the_default_off_one_is_loaded_as_default_off():
    """`!==false` is how the default-ON switches are read, and reading this one
    that way would turn it on for every project written before it existed."""
    from where import PKG
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "proj.settings.retype_kinds === true" in js
    assert "'retype_kinds'" not in js.split("const DEFAULT_ON")[1][:200]


def test_the_default_on_one_is_on_the_default_on_list():
    from where import PKG
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    at = js.index("const DEFAULT_ON")
    assert "'keep_honorifics'" in js[at:at + 200]


def test_both_copies_of_the_defaults_agree():
    """There USED to be two copies: `_pj.py` was an old snapshot of
    `project.py` carrying its own settings block, and a default added to one
    was a default half the app had never heard of. The snapshot went in the
    2026-09-02 dead-code sweep, so the one copy left just has to carry the
    defaults at all."""
    from where import PKG
    a = (PKG / "project.py").read_text(encoding="utf-8")
    for want in ('"keep_honorifics": True', '"retype_kinds": False'):
        assert want in a, want


def test_the_settings_reach_the_context():
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor)
    assert 's.get("keep_honorifics", True) is not False' in src
    assert 's.get("retype_kinds", False) is True' in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ------------------------------------------------- and whose dots they were

class _Linked:
    def __init__(self, rid, src, dst, link=1, kind=""):
        self.id, self.src_text, self.dst_text = rid, src, dst
        self.link, self.link_kind = link, kind


def test_the_dots_go_to_the_box_the_artist_drew_them_in():
    """lee, over a linked pair - `し` and `ん…`, one しん… drawn across a panel -
    that came back "SI..." and "LENCE": *"becasue these are linked teh ai
    messes up whickh one had the ......"*.

    The split of the WORD was right and the punctuation was on the wrong half.
    The page says which box has the dots, so this is not a judgement call."""
    a, b = _Linked(6, "し", "SI..."), _Linked(7, "ん…", "LENCE")
    assert T.fix_linked_tails([a, b]) == 2
    assert (a.dst_text, b.dst_text) == ("SI", "LENCE...")


def test_a_pair_that_was_already_right_is_left_alone():
    a, b = _Linked(1, "し", "SI"), _Linked(2, "ん…", "LENCE...")
    assert T.fix_linked_tails([a, b]) == 0
    assert (a.dst_text, b.dst_text) == ("SI", "LENCE...")


def test_an_unlinked_line_keeps_the_ellipsis_it_chose():
    """The other end of this rule, which lee settled long ago: a standalone
    line that trails off keeps its dots whether or not the Japanese drew any.
    What is different inside a link is that the box boundary is not the
    author's - one drawn mark got cut in two, so the dots are a fact about the
    source rather than a choice about the English."""
    r = _Linked(1, "しん", "SILENCE...", link=0)
    assert T.fix_linked_tails([r]) == 0
    assert r.dst_text == "SILENCE..."


def test_a_link_of_one_is_not_a_split():
    r = _Linked(1, "しん", "SILENCE...")
    assert T.fix_linked_tails([r]) == 0
    assert r.dst_text == "SILENCE..."


def test_a_balloon_link_is_a_fact_about_the_picture_and_is_left_alone():
    """Two lobes of one balloon hold two separate sentences as often as one.
    Nothing was cut in half there, so nothing about the punctuation follows."""
    a = _Linked(1, "あ", "AH...", kind="balloon")
    b = _Linked(2, "い…", "EE", kind="balloon")
    assert T.fix_linked_tails([a, b]) == 0
    assert (a.dst_text, b.dst_text) == ("AH...", "EE")


def test_it_reads_the_ellipsis_in_either_language():
    """Japanese draws it 　…　or ‥ or ・・・; English types three periods."""
    for src, dst in (("ん…", "LENCE"), ("ん‥", "LENCE"), ("ん・・・", "LENCE")):
        a, b = _Linked(1, "し", "SI..."), _Linked(2, src, dst)
        T.fix_linked_tails([a, b])
        assert (a.dst_text, b.dst_text) == ("SI", "LENCE..."), src


def test_an_empty_translation_is_not_given_dots():
    a, b = _Linked(1, "し", ""), _Linked(2, "ん…", "LENCE")
    assert T.fix_linked_tails([a, b]) == 1
    assert a.dst_text == ""


def test_both_steps_run_it():
    """The translator splits the line and the proofreader re-reads it one box
    at a time - and will happily move an ellipsis onto the half that reads
    better. Where the author's dots live is not a copy-editing decision."""
    import inspect
    assert "fix_linked_tails(page.regions, note=True)" in inspect.getsource(
        T.proofread_page)
    src = inspect.getsource(T)
    at = src.index("low translation confidence")
    assert "fix_linked_tails(page.regions)" in src[at:at + 600]


def test_the_model_is_told_as_well():
    """The code makes it certain; the prompt makes it usually unnecessary, and
    a model that knows the rule also picks a better place to break the word."""
    sysmsg = T.build_system("manga", "en", "ja")
    assert "THE PUNCTUATION GOES WHERE THE SOURCE PUT IT" in sysmsg
    assert '"SI" and "LENCE..."' in sysmsg


def test_proofreading_says_it_moved_them():
    """lee: *"proffreading shud also catch stuff like this"*. At translation
    time this is one of a dozen things being settled and a note on each would
    be noise; at proofreading it is a correction to a finished line, which is
    what the proofread report exists to show."""
    a, b = _Linked(1, "し", "SI..."), _Linked(2, "ん…", "LENCE")
    a.flagged = b.flagged = ""
    T.fix_linked_tails([a, b], note=True)
    assert "ellipsis" in a.flagged and "ellipsis" in b.flagged
    # ...and silently at translation time.
    c, d = _Linked(1, "し", "SI..."), _Linked(2, "ん…", "LENCE")
    c.flagged = d.flagged = ""
    T.fix_linked_tails([c, d])
    assert c.flagged == "" and d.flagged == ""


def test_the_proofreader_is_told_to_look_for_it_itself():
    """The code makes it certain either way; telling the copy editor means the
    line usually arrives right, and means the report reads as one decision
    rather than a rule quietly applied afterwards."""
    assert "LINKED BOXES" in T.PROOFREAD_TEMPLATE
    at = T.PROOFREAD_TEMPLATE.index("LINKED BOXES")
    rule = T.PROOFREAD_TEMPLATE[at:at + 420]
    assert '"SI" and "LENCE..."' in rule
    assert "the page" in rule and "do not choose" in rule


def test_proofreading_notes_it_on_the_region_where_the_report_reads_it():
    """The report prints `flagged` per region and the wording it replaced, so
    a note there is a note somebody reviewing the chapter actually sees."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor.proofread_report)
    assert "flagged" in src and "proofread_was" in src
    assert "fix_linked_tails(page.regions, note=True)" in inspect.getsource(
        T.proofread_page)
