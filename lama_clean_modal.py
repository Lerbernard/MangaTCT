# lama_clean_modal.py — the same cleaner endpoint, running LaMa instead of the
# greyscale `manga` net. Deploys ALONGSIDE manga_clean_modal.py (different app
# name), so you can A/B by pasting one URL or the other into mangatl's
# Clean settings and re-running the Clean step.
#
# Deploy:  python -m modal deploy lama_clean_modal.py
# It prints a URL; paste that + the token below into mangatl's AI-clean settings.
#
# Why bother: iopaint's `manga` model is a 2021 greyscale net — it converts the
# page to grey, runs a line-extraction pass and an inpainter, and hands back
# grey copied into three channels. That is why cleaned areas on a coloured or
# heavily toned page come back as flat grey blocks. LaMa is the standard erase
# model, works in colour, and is much stronger at reconstructing texture.
#
# MODEL picks which one this deployment serves:
#   "lama"        the standard big-lama — strongest general-purpose eraser
#   "anime-lama"  the same architecture fine-tuned on anime/manga artwork;
#                 usually better on screentone and line work, occasionally
#                 softer on photographic backgrounds
# Change the one word, deploy again, and you get a third URL to compare.
import base64
import modal

CLEAN_TOKEN = "yq3tdiuwdgugqewyhduygwqdgduggeqywygywuegdhiuwgewebcwjhbxkjq"  # must match the app setting

MODEL = "lama"           # "lama" or "anime-lama"

_CLASS = {"lama": "LaMa", "anime-lama": "AnimeLaMa"}[MODEL]

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("iopaint", "opencv-python-headless", "pillow", "numpy", "torch")
    # Bake the weights into the image using the SAME code path the runtime uses
    # (torch-hub cache), so is_downloaded() finds them. `iopaint download
    # --model-dir ...` puts them somewhere the runtime never looks.
    .run_commands(
        'python -c "from iopaint.model.lama import %s; %s(\'cpu\')"' % (_CLASS, _CLASS)
    )
)
app = modal.App("mangatl-clean-" + MODEL)


@app.cls(gpu="T4", image=image, timeout=180, scaledown_window=300)
class Cleaner:
    @modal.enter()
    def load(self):
        # Instantiate the model directly rather than through ModelManager: that
        # adds a scan gate which hides erase models unless their weights sit in
        # the exact dir it expects, and leaves you with only 'cv2'.
        import iopaint.model.lama as lama
        self.model = getattr(lama, _CLASS)("cuda")

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
        out = self.model(rgb, msk, cfg)         # returns a BGR image
        ok, buf = cv2.imencode(".png", out)
        return Response(content=buf.tobytes(), media_type="image/png")
