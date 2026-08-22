"""Translating by hand: a template out, a filled-in file back.

The AI route already had both halves - `/api/translate_request` writes the
exact prompt, `/api/translate_response` takes the model's JSON. This is the
same shape for a person: a plain text file with one block per box, the
Japanese beside its label, and room to type the English underneath.

    # mangatl - manual translation
    #
    # Type the English under each label. A block you leave empty is left
    # alone, so you can do a few boxes now and the rest later.
    # Do not change the [p001.png #3] labels: they are how a line finds its
    # box. The number is the one drawn on the box sheet.

    [p001.png #1]  テスト
    HELLO THERE

    [p001.png #2]  こんにちは

Two lines of a block are two lines of dialogue, kept as typed - the typesetter
honours a break somebody put in by hand.

The JSON form is the same information for anything that would rather read
JSON, and both are accepted on the way back in. **Whatever comes in wins**:
lee asked for a file that *"should override current text"*, so a block with
words in it replaces what the box says now, whoever wrote it.
"""
from __future__ import annotations

import json
import re

# `[name #n]`, with the rest of the line - the Japanese - ignored on the way
# back in. Tolerant of stray spaces: this is a file people edit by hand.
LABEL = re.compile(r"^\s*\[\s*(?P<page>[^\]#]+?)\s*#\s*(?P<n>\d+)\s*\]"
                   r"(?P<tail>.*)$")

HEAD = """# mangatl — manual translation
#
# Type the English under each label. A block you leave empty is left alone,
# so you can do a few boxes now and the rest later.
#
# Do not change the labels: they are how a line finds its box, and the number
# is the one drawn on the box sheet (Export ▸ boxes). Everything after the
# label on the same line is the Japanese, and is ignored when this comes back.
#
# Two lines under a label are two lines of dialogue and are kept as typed.
"""


def _boxes(st):
    """Every box on a page, in reading order, numbered as the box sheet is."""
    recs = sorted(st.regions, key=lambda r: r.get("order", 0))
    return [(n + 1, r) for n, r in enumerate(recs)]


def template(p, idxs=None) -> str:
    """The file to fill in, with whatever is already translated pre-filled."""
    out = [HEAD]
    for i in (range(len(p.pages)) if idxs is None else idxs):
        if not 0 <= i < len(p.pages):
            continue
        st = p.pages[i]
        rows = _boxes(st)
        if not rows:
            continue
        out.append(f"\n# ── {st.name} " + "─" * max(0, 46 - len(st.name)))
        for n, r in rows:
            src = " ".join(str(r.get("src_text") or "").split())
            out.append(f"\n[{st.name} #{n}]  {src}".rstrip())
            dst = str(r.get("dst_text") or "").strip()
            out.append(dst if dst else "")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def template_json(p, idxs=None) -> dict:
    pages = []
    for i in (range(len(p.pages)) if idxs is None else idxs):
        if not 0 <= i < len(p.pages):
            continue
        st = p.pages[i]
        rows = _boxes(st)
        if not rows:
            continue
        pages.append({
            "page": st.name,
            "boxes": [{"n": n, "kind": r.get("kind") or "",
                       "japanese": str(r.get("src_text") or ""),
                       "english": str(r.get("dst_text") or "")}
                      for n, r in rows]})
    return {"how_to_use": (
        "Put your translation in each box's 'english'. A box left empty is "
        "left alone. 'page' and 'n' are how a line finds its box — the "
        "number is the one drawn on the box sheet."), "pages": pages}


def parse(text: str) -> list[tuple[str, int, str]]:
    """(page, number, english) for every block that has words in it.

    A block runs from its label to the next label or the end. Comment lines
    are dropped; blank lines inside a block are kept as blank lines, which is
    how somebody writes a paragraph break, but a block that is nothing but
    blanks counts as untouched.
    """
    out: list[tuple[str, int, str]] = []
    cur: tuple[str, int] | None = None
    buf: list[str] = []

    def flush():
        if cur is None:
            return
        body = "\n".join(buf).strip("\n")
        if body.strip():
            out.append((cur[0], cur[1], body.strip()))

    for raw in (text or "").splitlines():
        m = LABEL.match(raw)
        if m:
            flush()
            cur, buf = (m.group("page").strip(), int(m.group("n"))), []
            continue
        if raw.lstrip().startswith("#"):
            continue                       # a comment, at any indent
        if cur is not None:
            buf.append(raw.rstrip())
    flush()
    return out


def parse_json(data) -> list[tuple[str, int, str]]:
    """The same triples out of the JSON form, or out of a flat mapping like
    `{"p001.png #2": "HELLO"}` - which is what somebody writing one by hand
    tends to produce."""
    out: list[tuple[str, int, str]] = []
    if isinstance(data, dict) and isinstance(data.get("pages"), list):
        for pg in data["pages"]:
            if not isinstance(pg, dict):
                continue
            name = str(pg.get("page") or pg.get("name") or "")
            for b in (pg.get("boxes") or []):
                if not isinstance(b, dict):
                    continue
                try:
                    n = int(b.get("n"))
                except (TypeError, ValueError):
                    continue
                eng = str(b.get("english") or b.get("dst") or "").strip()
                if eng:
                    out.append((name, n, eng))
        return out
    if isinstance(data, dict):
        for k, v in data.items():
            m = LABEL.match(str(k) if str(k).startswith("[") else f"[{k}]")
            if m and str(v).strip():
                out.append((m.group("page").strip(), int(m.group("n")),
                            str(v).strip()))
    return out


def read(text: str) -> list[tuple[str, int, str]]:
    """Whichever of the two this is. JSON is tried first and only when the
    file actually looks like it - a template starts with a comment."""
    t = (text or "").lstrip()
    if t[:1] in "[{":
        try:
            return parse_json(json.loads(text))
        except Exception:
            pass                       # a .txt whose first block is at the top
    return parse(text)
