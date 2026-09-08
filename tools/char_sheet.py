#!/usr/bin/env python3
"""Draw the mascot. Talks to the Modal app in `anime_char_modal.py`.

    export CHAR_URL=https://<you>--mangatl-char-artist-draw.modal.run
    export CHAR_TOKEN=<the token in the mangatl-char secret>

    python tools/char_sheet.py                    # six of her, one sheet
    python tools/char_sheet.py --pose bust -n 4
    python tools/char_sheet.py --seed 7781 -n 1   # that one again, bigger

Pictures land in `out/char/`, one PNG per generation plus a contact sheet.

## Who she is

ONE description, in one place, so every picture is the same person. The model
takes danbooru-style tags rather than sentences: comma-separated, most
important first, quality tags last.

She is deliberately NOT somebody else's character. The reference lee sent is
Zero Two, who belongs to Trigger, and a mascot on the front of a release is the
worst possible place to borrow a face from. What is copied here is the KIND of
drawing - flat cel colour, clean line, a full-length sheet on nothing - which
is a style, and styles are free.

What ties her to the app instead is the mark: gold hair off the logo's own
gradient, ink-navy coat, gold trim. The M itself is NOT prompted - an image
model cannot draw a logo the same way twice, and a wobbly one is worse than
none. It goes on afterwards, as vector, where it is exact: see `char.py`.
"""
import argparse
import base64
import json
import os
import urllib.request

WHO = (
    "1girl, solo, "
    "long straight golden blonde hair, blunt bangs, very long hair, "
    "amber eyes, pale skin, calm confident expression, "
    "dark navy military coat, double-breasted, gold trim, high collar, "
    "black belt with gold buckle, black leggings, white ankle boots"
)

POSES = {
    "sheet": "full body, standing, arms at sides, facing viewer",
    "hip": "full body, standing, one hand on hip, facing viewer",
    "bust": "upper body, facing viewer, close-up",
    "three": "full body, standing, from side, three-quarter view",
    "back": "full body, standing, from behind, back view",
    "wave": "full body, standing, waving, smiling",
}

# Flat, plain, drawn - not painted, not rendered, not a photograph. A character
# sheet is a document: one figure, no scene, no lighting.
LOOK = ("official art, character sheet, simple background, white background, "
        "flat color, clean lineart, anime style, "
        "masterpiece, high score, great score, absurdres")

OUT = os.path.join("out", "char")


def _env(name: str) -> str:
    """One environment variable, with Windows' quotes taken back off.

    `set CHAR_TOKEN="abc"` in cmd puts the QUOTES in the value, so the string
    that arrives at the endpoint is five characters where the secret is three
    - and the only thing that comes back is 401. It is the commonest way to
    get this wrong and it costs one line to survive.
    """
    v = os.environ.get(name, "").strip()
    if len(v) > 1 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


def _fp(s: str) -> str:
    """Four characters that stand for a string without being it."""
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:4] if s else "----"


def draw(url, token, prompt, n, seed, size, steps, cfg):
    body = json.dumps({
        "token": token, "prompt": prompt, "n": n, "seed": seed,
        "width": size[0], "height": size[1], "steps": steps, "cfg": cfg,
    }).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as fh:
            return json.loads(fh.read().decode())["images"]
    except urllib.error.HTTPError as e:
        # WHAT THE ENDPOINT SAID, not just the number. urlopen raises on 4xx
        # and 5xx and throws the body away with the traceback, so an endpoint
        # that carefully explains itself - see the 401 and the 503 in
        # `anime_char_modal.py` - explains itself to nobody.
        try:
            said = e.read().decode("utf-8", "replace")
        except Exception:
            said = ""
        raise SystemExit("HTTP %s from the endpoint\n%s" % (e.code, said))


def contact(paths, dest):
    """All of them side by side, so a sheet can be judged as a sheet."""
    try:
        from PIL import Image
    except ImportError:
        return None
    ims = [Image.open(p).convert("RGB") for p in paths]
    if not ims:
        return None
    w, h = ims[0].size
    k = 520.0 / h
    ims = [im.resize((int(w * k), 520)) for im in ims]
    pad = 12
    sheet = Image.new("RGB", (pad + sum(i.width + pad for i in ims),
                              520 + 2 * pad), "white")
    x = pad
    for im in ims:
        sheet.paste(im, (x, pad))
        x += im.width + pad
    sheet.save(dest)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pose", default="sheet", choices=sorted(POSES))
    ap.add_argument("-n", type=int, default=6, help="how many")
    ap.add_argument("--seed", type=int, default=0, help="0 picks one for you")
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--cfg", type=float, default=5.0)
    ap.add_argument("--extra", default="", help="tags to add, comma separated")
    ap.add_argument("--bust", action="store_true",
                    help="square-ish frame instead of full length")
    a = ap.parse_args()

    url = _env("CHAR_URL")
    token = _env("CHAR_TOKEN")
    if not url or not token:
        raise SystemExit("set CHAR_URL and CHAR_TOKEN first - see the docstring")
    # WHERE, as well as what. Both of this app's Modal siblings answer a wrong
    # token with the same words, so a 401 from the cleaner and a 401 from here
    # are the same sentence - and an hour went into one that turned out to be
    # `CHAR_URL` still holding the cleaner's address. Say the address.
    print("calling:", url)
    if "char" not in url:
        print("  ...that does not look like the character endpoint. It should "
              "end in --mangatl-char-artist-draw.modal.run")
    # The fingerprint stands for the token without being it, so it can be held
    # up against what the endpoint says it wants.
    print("token: %d chars (%s)" % (len(token), _fp(token)))

    seed = a.seed or int.from_bytes(os.urandom(3), "big")
    bits = [WHO, POSES[a.pose]]
    if a.extra:
        bits.append(a.extra.strip())
    bits.append(LOOK)
    prompt = ", ".join(bits)
    size = (1024, 1024) if a.bust else (832, 1216)

    print("seed", seed)
    print(prompt)
    got = draw(url, token, prompt, a.n, seed, size, a.steps, a.cfg)

    os.makedirs(OUT, exist_ok=True)
    paths = []
    for g in got:
        p = os.path.join(OUT, "%s_%d.png" % (a.pose, g["seed"]))
        with open(p, "wb") as fh:
            fh.write(base64.b64decode(g["png"]))
        paths.append(p)
        print("wrote", p)
    if len(paths) > 1:
        # NOT "sheet_<seed>.png". The default pose is called `sheet`, so the
        # contact sheet and the first picture of a default run were the same
        # file name and the contact sheet landed on top of it - a run of six
        # came back as five and nothing said why.
        c = contact(paths, os.path.join(OUT, "contact_%d.png" % seed))
        if c:
            print("wrote", c)


if __name__ == "__main__":
    main()
