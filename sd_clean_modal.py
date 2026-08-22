# sd_clean_modal.py - GENERATIVE "redraw" cleaner (IOPaint + PowerPaint v1).
# A drop-in alternative to manga_clean_modal.py: SAME request format (token,
# image, mask -> cleaned png), different app + URL, so you can A/B them by just
# changing the Clean URL in mangatl's settings. This one actually generates new
# line art into the gap (object-remove) instead of filling - slower, heavier.
# Deploy:  python -m modal deploy sd_clean_modal.py
import base64
import modal

CLEAN_TOKEN = "yq3tdiuwdgugqewyhduygwqdgduggeqywygywuegdhiuwgewebcwjhbxkjq"   # same token as the app setting
MODEL = "Sanster/PowerPaint-V1-stable-diffusion-inpainting"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .env({"HF_HOME": "/cache"})                 # pin the HF cache so build == runtime
    .pip_install("iopaint", "opencv-python-headless", "pillow", "numpy", "torch")
    # Bake the ~5GB PowerPaint weights into the image so cold starts don't stall
    # downloading them. Pinned HF_HOME means the runtime reads the same cache.
    .run_commands(
        "python -c \"from huggingface_hub import snapshot_download; "
        "snapshot_download('Sanster/PowerPaint-V1-stable-diffusion-inpainting')\""
    )
)
app = modal.App("mangatl-clean-sd")

@app.cls(gpu="T4", image=image, timeout=600, scaledown_window=300)
class Cleaner:
    @modal.enter()
    def load(self):
        from iopaint.model_manager import ModelManager
        # Diffusion models are always in IOPaint's available list, so unlike the
        # erase models this won't fall back to cv2. Loads PowerPaint from cache.
        self.model = ModelManager(name=MODEL, device="cuda")

    @modal.fastapi_endpoint(method="POST")
    def clean(self, item: dict):
        import cv2, numpy as np
        from fastapi import Response, HTTPException
        from iopaint.schema import InpaintRequest, HDStrategy, PowerPaintTask
        if item.get("token") != CLEAN_TOKEN:
            raise HTTPException(status_code=401, detail="bad token")
        img = cv2.imdecode(np.frombuffer(base64.b64decode(item["image"]), np.uint8), cv2.IMREAD_COLOR)
        msk = cv2.imdecode(np.frombuffer(base64.b64decode(item["mask"]), np.uint8), cv2.IMREAD_GRAYSCALE)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        cfg = InpaintRequest(
            prompt="",                                   # object-remove needs no description
            negative_prompt="text, letters, words, watermark, blurry, artifacts",
            powerpaint_task=PowerPaintTask.object_remove,
            sd_steps=20,
            sd_guidance_scale=7.5,
            sd_seed=42,
            hd_strategy=HDStrategy.CROP,                  # redraw each region at full res
            hd_strategy_crop_margin=196,
            hd_strategy_crop_trigger_size=800,
        )
        out = self.model(rgb, msk, cfg)                  # BGR result
        ok, buf = cv2.imencode(".png", out)
        return Response(content=buf.tobytes(), media_type="image/png")
