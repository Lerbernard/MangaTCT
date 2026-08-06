# manga_clean_modal.py — serverless manga text cleaner (IOPaint "manga" LaMa)
# Deploy:  python -m modal deploy manga_clean_modal.py
# It prints a URL; paste that + the token below into mangatl's AI-clean settings.
import base64
import modal

CLEAN_TOKEN = "yq3tdiuwdgugqewyhduygwqdgduggeqywygywuegdhiuwgewebcwjhbxkjq"   # must match the app setting

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("iopaint", "opencv-python-headless", "pillow", "numpy", "torch")
    # Bake the manga weights into the image using the SAME code path the runtime
    # uses (torch-hub cache), so is_downloaded() finds them. The earlier
    # `iopaint download --model-dir /models` put them somewhere the runtime never
    # looked, which is why only 'cv2' was available.
    .run_commands("python -c \"from iopaint.model.manga import Manga; Manga('cpu')\"")
)
app = modal.App("mangatl-clean")

@app.cls(gpu="T4", image=image, timeout=180, scaledown_window=300)
class Cleaner:
    @modal.enter()
    def load(self):
        # Instantiate Manga directly. Routing through ModelManager adds a scan
        # gate that hides erase models unless their weights sit in the exact dir
        # it expects — that gate is what left us with only 'cv2'. Direct
        # instantiation skips it and auto-downloads if the baked copy is missing.
        from iopaint.model.manga import Manga
        self.model = Manga("cuda")

    @modal.fastapi_endpoint(method="POST")
    def clean(self, item: dict):
        import cv2, numpy as np
        from fastapi import Response, HTTPException
        from iopaint.schema import InpaintRequest, HDStrategy
        if item.get("token") != CLEAN_TOKEN:
            raise HTTPException(status_code=401, detail="bad token")
        img = cv2.imdecode(np.frombuffer(base64.b64decode(item["image"]), np.uint8), cv2.IMREAD_COLOR)
        msk = cv2.imdecode(np.frombuffer(base64.b64decode(item["mask"]), np.uint8), cv2.IMREAD_GRAYSCALE)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        cfg = InpaintRequest(hd_strategy=HDStrategy.CROP,
                             hd_strategy_crop_margin=196,
                             hd_strategy_crop_trigger_size=800)
        out = self.model(rgb, msk, cfg)         # returns a BGR image
        ok, buf = cv2.imencode(".png", out)
        return Response(content=buf.tobytes(), media_type="image/png")
