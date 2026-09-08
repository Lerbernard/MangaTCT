# lama_clean_modal.py - the same cleaner endpoint, running LaMa instead of the
# greyscale `manga` net. Deploys ALONGSIDE manga_clean_modal.py (different app
# name), so you can A/B by pasting one URL or the other into mangatl's
# Clean settings and re-running the Clean step.
#
# Deploy:  python -m modal deploy lama_clean_modal.py
# It prints a URL; paste that + the token below into mangatl's AI-clean settings.
#
# Why bother: iopaint's `manga` model is a 2021 greyscale net - it converts the
# page to grey, runs a line-extraction pass and an inpainter, and hands back
# grey copied into three channels. That is why cleaned areas on a coloured or
# heavily toned page come back as flat grey blocks. LaMa is the standard erase
# model, works in colour, and is much stronger at reconstructing texture.
#
# ONE DEPLOY SERVES BOTH MODELS NOW.
#
#   "lama"        the standard big-lama - strongest general-purpose eraser
#   "anime-lama"  the same architecture fine-tuned on anime/manga artwork;
#                 better on screentone and line work
#
# It used to serve whichever one `MODEL` named, so comparing them meant editing
# this file, deploying again, and pasting a second URL into the app. They are
# 200MB each and the container holds both without noticing, so the app names
# the one it wants per request and the picker is in Settings where it belongs.
# lee, after seven erasers were measured on his own chapter: *"anime lama is
# the shout, add it in the list"*.
#
# MODEL is the DEFAULT - what an old copy of the app, which sends no name at
# all, gets served.
import base64
import modal

CLEAN_TOKEN = "yq3tdiuwdgugqewyhduygwqdgduggeqywygywuegdhiuwgewebcwjhbxkjq"  # must match the app setting

MODEL = "anime-lama"     # the default; the app may ask for either

_CLASS = {"lama": "LaMa", "anime-lama": "AnimeLaMa"}

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("iopaint", "opencv-python-headless", "pillow", "numpy", "torch")
    # Bake the weights into the image using the SAME code path the runtime uses
    # (torch-hub cache), so is_downloaded() finds them. `iopaint download
    # --model-dir ...` puts them somewhere the runtime never looks.
    # Both sets of weights baked in, through the SAME code path the runtime
    # uses (torch-hub cache), so `is_downloaded()` finds them.
    .run_commands(*[
        'python -c "from iopaint.model.lama import %s; %s(\'cpu\')"' % (c, c)
        for c in _CLASS.values()
    ])
)
# ONE app for both models, and it keeps the name the lama deploy already had -
# so the URL somebody has already pasted into Settings goes on working and a
# redeploy is all this costs. NOT the bare "mangatl-clean": that is
# manga_clean_modal.py's app, and taking it would replace that deploy with this
# one. The name no longer carries the model, because the request does.
app = modal.App("mangatl-clean-lama")


@app.cls(gpu="T4", image=image, timeout=180, scaledown_window=300)
class Cleaner:
    @modal.enter()
    def load(self):
        # Instantiate the model directly rather than through ModelManager: that
        # adds a scan gate which hides erase models unless their weights sit in
        # the exact dir it expects, and leaves you with only 'cv2'.
        import iopaint.model.lama as lama
        # Both, held for the life of the container. Loading on demand would put
        # a cold model load in front of somebody's first hard box.
        self.models = {k: getattr(lama, c)("cuda") for k, c in _CLASS.items()}

    @modal.fastapi_endpoint(method="POST")
    def clean(self, item: dict):
        import cv2, numpy as np
        from fastapi import Response, HTTPException
        from iopaint.schema import InpaintRequest, HDStrategy
        if item.get("token") != CLEAN_TOKEN:
            raise HTTPException(status_code=401, detail="bad token")
        img = cv2.imdecode(np.frombuffer(base64.b64decode(item["image"]), np.uint8),
                           cv2.IMREAD_COLOR)
        msk = cv2.imdecode(np.frombuffer(base64.b64decode(item["mask"]), np.uint8),
                           cv2.IMREAD_GRAYSCALE)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # mangatl now sends ONE CROP PER BUBBLE with ~96px of surrounding page,
        # so what arrives here is a few hundred pixels square and goes through
        # the model in a single pass. HDStrategy.CROP is left in only as a
        # backstop for an unusually large region: when it does trigger it splits
        # the mask into connected pieces and runs once per piece, which on a page
        # of text means once per glyph, each seeing too little to match.
        cfg = InpaintRequest(hd_strategy=HDStrategy.CROP,
                             hd_strategy_crop_margin=196,
                             hd_strategy_crop_trigger_size=1600)
        # Which eraser. An app that does not send one - or sends a name this
        # deploy has never heard of - gets MODEL, so an older client keeps
        # working and a typo in a settings box cleans the page instead of
        # failing it.
        want = str(item.get("model") or "").strip().lower()
        model = self.models.get(want) or self.models[MODEL]
        out = model(rgb, msk, cfg)              # returns a BGR image
        ok, buf = cv2.imencode(".png", out)
        return Response(content=buf.tobytes(), media_type="image/png")
