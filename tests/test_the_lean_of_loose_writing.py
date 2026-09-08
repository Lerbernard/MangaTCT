"""The angle the reading gives back, and the three rules on top of it.

lee, watching the labeller work: *"is posible while looking at the box type
with reas text ask it to give the angle of the text for the typesetter"* -
and immediately after: *"onlu for freefloat and sfx"*.

It was those two for one afternoon. He looked at outside text set on a slant
and said: *"also make all teh freefloast text be start no more angle"*.

So a freefloat block goes down level - `typeset.fit_region` says so and says
why - and the pass no longer asks about one, because an answer nothing acts on
is an answer nobody should be charged for.

What is left is the sound effects, which is where it was always going to be
used: an effect is drawn leaning on purpose, and it is laid letter by letter
along an axis of its own rather than fitted level into a box.

Asking here costs no request of its own. The pass is already holding a 768px
picture of the whole page with every box outlined and numbered on it, which is
exactly what an angle has to be read from, and the answer rides back in the
slot that was going to carry the kind anyway.

WHICH ANGLE WINS was lee's call, put to him with the trade-off:

    *Fill the gaps only.* Sound effects keep the angle measured off the
    Japanese ink at Find text, and only take the model's where that
    measurement failed or was never done.

`read_sfx_axis` sets `angle`, `sfx_vertical`, `sfx_len` and `sfx_wid` together
or none of them, so a zero length is how "never measured" shows. That is the
gap: an effect drawn by hand since detection, or one whose axis the reader
could not make out.
"""
import numpy as np
import pytest

from mangatl import editor
from mangatl import kinds as K
from mangatl import translate as T
from mangatl.models import Page, TextRegion


def _seeded():
    return K.migrate([], seed=True)


class _Ctx:
    medium = "manga"; source = ""; target = "en"
    backend = "anthropic"; base_url = ""; model = "m"; api_key = "k"
    safety = ""; step_name = ""


def _page(kinds=("bubble", "sfx", "freefloat")):
    pg = Page(image=np.zeros((400, 300, 3), np.uint8))
    pg.regions = []
    for n, k in enumerate(kinds):
        r = TextRegion(id=n, bbox=(10 + 20 * n, 10, 18, 18), kind=k)
        r.order = n
        pg.regions.append(r)
    return pg


def _ask(monkeypatch, reply, page=None, angles=None):
    seen = {}

    def fake(client, kind, model, system, user, image_b64,
             media_type="image/png"):
        seen["system"], seen["user"] = system, user
        return reply

    monkeypatch.setattr(T, "_ask_vision", fake)
    K.use(_seeded())
    got = T.label_kinds(page or _page(), _Ctx(), b"png",
                        K.labelling_vocabulary(_seeded()),
                        client=object(), model="m", angles=angles)
    return got, seen


# ------------------------------------------------------- what is asked for

def test_the_angle_is_not_asked_for_unless_somebody_wants_it():
    """`angles=None` is the old call, and it must produce the old prompt. Every
    other caller of `label_kinds` - and every test written before today - is
    that call, and a prompt that grew a section they never asked for is a
    section they pay for on every page."""
    vocab = K.labelling_vocabulary(_seeded())
    plain = T.build_label_system(vocab)
    # Not the bare word - half the balloon descriptions say "rectangle".
    assert "ANGLE OF THE WRITING" not in plain
    assert '"angle"' not in plain
    assert "angle?" not in plain


def test_only_the_sound_effects_are_marked_for_an_angle(monkeypatch):
    """The listing is where the prompt and the page agree about which boxes
    the question is about. The rule is written in the system prompt and the
    MARK is written per row, because the prompt cannot see the families.

    Outside text is not marked. Asking about it would be buying an answer
    nothing acts on."""
    _got, seen = _ask(monkeypatch, '{"regions":[]}',
                      page=_page(("bubble", "sfx", "freefloat")), angles={})
    rows = [ln for ln in seen["user"].splitlines() if ln.strip()[:2] in
            ("0:", "1:", "2:")]
    assert len(rows) == 3, rows
    assert "angle?" not in rows[0], "a balloon was asked for a lean"
    assert "angle?" in rows[1], rows
    assert "angle?" not in rows[2], ("outside text was asked for a lean it "
                                     "is no longer set at", rows)
    assert "ANGLE OF THE WRITING" in seen["system"]


def test_a_page_with_no_sound_effects_never_carries_the_rule(monkeypatch):
    """`ANGLE_RULE` is 988 characters, and on a page it cannot apply to they
    are 988 characters of a prompt somebody is charged for."""
    _got, seen = _ask(monkeypatch, '{"regions":[]}',
                      page=_page(("bubble", "freefloat")), angles={})
    assert "ANGLE OF THE WRITING" not in seen["system"]
    assert "angle?" not in seen["user"]


def test_the_rule_says_a_vertical_column_is_not_a_lean():
    """The failure mode worth spelling out. Japanese loose writing is often
    set in a column running straight down the page, and "which way does this
    writing run" answered about a column is 90 degrees - which would lay the
    English on its side on a page where nothing is on its side."""
    vocab = K.labelling_vocabulary(_seeded())
    s = T.build_label_system(vocab, want_angle=True)
    assert "vertical column is NOT tilted" in s
    assert "not 90" in s


# ------------------------------------------------------- what comes back

def test_the_angle_comes_back_for_the_boxes_it_was_asked_about(monkeypatch):
    angles = {}
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":0,"kind":"thought"},'
                      '{"id":1,"kind":"sfx_big","angle":-12.5},'
                      '{"id":2,"kind":"sign","angle":7}]}',
                      angles=angles)
    assert got == {0: "thought", 1: "sfx_big", 2: "sign"}
    # The effect only. Region 2 is outside text: it was never marked, so an
    # angle offered for it is not an answer to a question that was asked.
    assert angles == {1: -12.5}


def test_an_angle_on_a_balloon_is_dropped(monkeypatch):
    """It was not asked for, so it is not an answer. Enforced here as well as
    asked for in the prompt, for the same reason the family rule is."""
    angles = {}
    _got, _seen = _ask(monkeypatch,
                       '{"regions":[{"id":0,"kind":"thought","angle":30}]}',
                       angles=angles)
    assert angles == {}


def test_an_angle_that_is_not_a_number_is_dropped(monkeypatch):
    angles = {}
    _got, _seen = _ask(monkeypatch,
                       '{"regions":[{"id":1,"kind":"sfx_big","angle":"a bit"}]}',
                       angles=angles)
    assert angles == {}


def test_an_angle_past_the_limit_is_dropped_and_not_clamped(monkeypatch):
    """Clamping turns "I have misread this as sideways" into a confident
    60-degree lean, which is the wrong answer stated firmly. Dropping it
    leaves the box level, which is what the page would have had anyway."""
    angles = {}
    _got, _seen = _ask(monkeypatch,
                       '{"regions":[{"id":1,"kind":"sfx_big","angle":90}]}',
                       angles=angles)
    assert angles == {}, "an impossible angle was talked into a possible one"


def test_a_rejected_kind_still_gives_up_its_angle(monkeypatch):
    """The two answers are about different things - what the box IS, and which
    way its writing leans - and one being unusable says nothing about the
    other. A sound effect labelled with a balloon's sub-type is a rejected
    kind; the lean it reported is still a reading of the artwork."""
    angles = {}
    got, _seen = _ask(monkeypatch,
                      '{"regions":[{"id":1,"kind":"thought","angle":-20}]}',
                      angles=angles)
    assert got == {}, "the family was allowed to change"
    assert angles == {1: -20.0}


# ------------------------------------------------ and what reaches the box

class _R:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _P:
    def __init__(self, regions):
        self.regions = regions


def test_outside_text_is_left_alone_now():
    """It took the reading for one afternoon. lee: *"also make all teh
    freefloast text be start no more angle"* - and a number nothing reads is
    a number not worth storing, let alone asking for."""
    r = _R(id=1, kind="freefloat", angle=0.0)
    assert editor._apply_read_angles(_P([r]), {1: -15.0}) == 0
    assert r.angle == 0.0


def test_a_measured_sound_effect_keeps_its_measurement():
    """`read_sfx_axis` reads the lean off the Japanese ink at Find text, while
    the Japanese is still on the page. That is a better number than a model
    reading a 768px thumbnail, and lee chose to keep it."""
    r = _R(id=1, kind="sfx", angle=12.0, sfx_len=0.82, sfx_wid=0.66)
    assert editor._apply_read_angles(_P([r]), {1: 44.0}) == 0
    assert r.angle == 12.0


def test_an_unmeasured_sound_effect_takes_the_reading():
    """One drawn by hand since detection, or one whose ink the axis reader
    could not make out. `read_sfx_axis` sets all four fields together or none
    of them, so a zero length is how "never measured" shows."""
    r = _R(id=1, kind="sfx", angle=0.0, sfx_len=0.0, sfx_wid=0.0)
    assert editor._apply_read_angles(_P([r]), {1: 7.5}) == 1
    assert r.angle == 7.5


def test_an_angle_set_by_hand_is_never_touched():
    """The same rule as a type set by hand, and lee's reason for that one
    carries word for word: an answer you fixed coming back wrong on every
    re-read is worse than no reading at all."""
    r = _R(id=1, kind="sfx", angle=-30.0, sfx_len=0.0, sfx_wid=0.0,
           angle_by_hand=True)
    assert editor._apply_read_angles(_P([r]), {1: 5.0}) == 0
    assert r.angle == -30.0


def test_the_same_angle_again_is_not_a_change():
    """`label_page_kinds` throws the page's rendered cache away when something
    moved. A reading that agrees with the box did not move it."""
    r = _R(id=1, kind="sfx", angle=-15.0, sfx_len=0.0, sfx_wid=0.0)
    assert editor._apply_read_angles(_P([r]), {1: -15.0}) == 0


def test_a_balloon_is_left_alone_even_if_an_angle_arrives_for_it():
    r = _R(id=1, kind="bubble", angle=0.0)
    assert editor._apply_read_angles(_P([r]), {1: 30.0}) == 0
    assert r.angle == 0.0


def test_the_hand_flag_survives_a_save_and_a_load(tmp_path):
    """`region_record` and `region_from_record` are the round trip every
    region makes on every commit. A flag that dies there is a flag that
    protects one run of the reader and none of the ones after it - which is
    exactly the trap `kind_by_hand` was written to get out of."""
    import cv2
    from mangatl.project import region_record, region_from_record
    img = np.full((60, 60, 3), 240, np.uint8)
    r = TextRegion(id=1, bbox=(5, 5, 20, 20), kind="freefloat")
    r.polygon = [(5, 5), (25, 5), (25, 25), (5, 25)]
    r.angle = -22.0
    r.angle_by_hand = True
    rec = region_record(r)
    assert rec["angle_by_hand"] is True
    back = region_from_record(rec, img)
    assert getattr(back, "angle_by_hand", False) is True
    assert abs(float(back.angle) - (-22.0)) < 0.01
    assert cv2 is not None


# --------------------------------------------------- and onto the artwork

def test_outside_text_is_typeset_straight():
    """It leaned for one afternoon and lee did not like it: *"also make all
    teh freefloast text be start no more angle"*.

    An effect is drawn leaning on purpose and reaches its lean by another road
    entirely - laid letter by letter along an axis of its own. Outside text is
    a caption on the artwork, and a caption that leans is only harder to read.
    The angle is still measured and still stored; the typesetter does not act
    on it."""
    from mangatl.typeset import fit_region, TypesetConfig
    cfg = TypesetConfig()
    r = TextRegion(id=1, bbox=(20, 20, 220, 70), kind="freefloat")
    r.polygon = np.array([[20, 20], [240, 20], [240, 90], [20, 90]], np.int32)
    r.dst_text = "WELL THAT WENT WELL"
    r.angle = -14.0
    lay = fit_region(r, cfg)
    assert lay is not None
    assert not float(getattr(lay, "rotate", 0.0) or 0.0), lay.rotate


def test_a_balloon_is_not_turned_by_an_angle_on_its_record():
    """A balloon's words follow the balloon. An `angle` left on one from
    before it was relabelled must not tip its typesetting over."""
    from mangatl.typeset import fit_region, TypesetConfig
    cfg = TypesetConfig()
    r = TextRegion(id=1, bbox=(20, 20, 220, 70), kind="bubble")
    r.polygon = np.array([[20, 20], [240, 20], [240, 90], [20, 90]], np.int32)
    r.dst_text = "WELL THAT WENT WELL"
    r.angle = -14.0
    lay = fit_region(r, cfg)
    assert lay is not None
    assert not float(getattr(lay, "rotate", 0.0) or 0.0)


def test_a_turn_set_by_hand_still_wins():
    """`turn` is a decision about the BOX and `angle` is a reading of the
    artwork, which is why they are two fields - and why taking the reading off
    the typesetting leaves the handle exactly as it was."""
    from mangatl.typeset import fit_region, TypesetConfig
    cfg = TypesetConfig()
    r = TextRegion(id=1, bbox=(20, 20, 220, 70), kind="freefloat")
    r.polygon = np.array([[20, 20], [240, 20], [240, 90], [20, 90]], np.int32)
    r.dst_text = "WELL THAT WENT WELL"
    r.angle = -14.0
    r.turn = 33.0
    r.manual = True
    lay = fit_region(r, cfg)
    assert lay is not None
    assert abs(float(lay.rotate) - 33.0) < 0.01, lay.rotate


# --------------------------------------------------------- and it is paid for

def test_the_angle_is_in_the_price():
    """A prompt that grew and a price that did not is the app quoting for work
    it is not doing any more. `ANGLE_RULE` is most of a thousand characters of
    system prompt, plus a mark per row in the listing and a number back."""
    from mangatl import coins
    vocab = K.labelling_vocabulary(_seeded())
    with_angle = T.build_label_system(vocab, want_angle=True)
    sh = coins.SHAPES["label"]
    assert abs(sh.sys_in - len(with_angle) / 4) < 130, \
        (sh.sys_in, len(with_angle) / 4)
    # ...and it is still over the cache floor, which is what lets it be
    # quoted as a cache read rather than as input.
    assert T._cacheable(with_angle)
    assert coins.cached_tokens(sh, "claude-sonnet-5") == sh.sys_in


def test_the_family_lee_left_it_at_is_the_family_in_the_code():
    """He named two and then took one back. The list is what the prompt marks
    rows from, so it is also what says nobody is charged for an answer the
    typesetter will not read."""
    assert T.ANGLE_KINDS == ("sfx",)
