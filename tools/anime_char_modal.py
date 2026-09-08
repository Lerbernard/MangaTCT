# anime_char_modal.py - draw the mascot with an anime-tuned image model.
#
# Same arrangement as `manga_clean_modal.py` and `sd_clean_modal.py`: a Modal
# app with a GPU behind a POST endpoint, the weights baked into the image so a
# cold start does not stall downloading seven gigabytes.
#
#     python -m modal secret create mangatl-char TOKEN=<the token you like>
#     python -m modal deploy tools/anime_char_modal.py
#
# It prints a URL. Give that to `tools/char_sheet.py` and it draws.
#
# THE MODEL is Animagine XL 4.0 - an SDXL fine-tune trained on anime art, under
# CreativeML Open RAIL++-M, which allows commercial use. It takes danbooru-style
# tag prompts rather than sentences, which is why `char_sheet.py` writes them
# that way.
#
# THE TOKEN IS NOT IN THIS FILE. The cleaner's is, and it should not be either -
# anyone with the URL and the string can spend your GPU credits. Here it comes
# out of a Modal secret, so it is on Modal's side and never in the repository.
import base64
import os

import modal

MODEL = "cagliostrolab/animagine-xl-4.0"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .env({"HF_HOME": "/cache"})              # pin it: build cache == runtime cache
    .pip_install(
        "torch", "diffusers", "transformers", "accelerate",
        "safetensors", "sentencepiece", "peft", "pillow",
        # Named on purpose. Modal used to put FastAPI in the image itself for
        # anything wearing `@modal.fastapi_endpoint` and now refuses to guess:
        # *"This used to happen automatically, but it must now be done
        # explicitly."* The cleaner's image gets it by accident, as one of
        # iopaint's dependencies; this one asks.
        "fastapi[standard]",
    )
    # ~7GB of weights, fetched once at build time.
    .run_commands(
        "python -c \"from huggingface_hub import snapshot_download; "
        f"snapshot_download('{MODEL}')\""
    )
)
app = modal.App("mangatl-char")

# What the model is told to avoid, every time. The first half is Animagine's
# own recommended negative; the rest is this job - a character sheet wants one
# figure on nothing, not a scene.
NEGATIVE = (
    "lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, "
    "fewer digits, cropped, worst quality, low quality, low score, bad score, "
    "average score, signature, watermark, username, blurry, "
    "multiple views, multiple girls, busy background, scenery, jpeg artifacts"
)


@app.cls(gpu="L4", image=image, timeout=900, scaledown_window=300,
         # The secret has to be ATTACHED, or `TOKEN` is simply absent inside
         # the container and every single request comes back 401 - which is
         # indistinguishable, from the outside, from getting the token wrong.
         # See the two answers below.
         secrets=[modal.Secret.from_name("mangatl-char")])
class Artist:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import StableDiffusionXLPipeline

        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            MODEL,
            torch_dtype=torch.float16,
            use_safetensors=True,
            # long-prompt weighting: a character sheet's tag list runs past the
            # 77-token window CLIP would otherwise cut it off at, and the tags
            # that get cut are the ones at the end - which is where the outfit
            # is.
            custom_pipeline="lpw_stable_diffusion_xl",
            add_watermarker=False,
        )
        self.pipe.to("cuda")

    @modal.fastapi_endpoint(method="POST")
    def draw(self, item: dict):
        import torch
        from fastapi import HTTPException

        # Two answers, because they are two different faults and one of them is
        # not the caller's. A missing secret is the endpoint being misconfigured
        # and no token on earth would get in; a wrong token is the caller.
        want = os.environ.get("TOKEN", "")
        if not want:
            raise HTTPException(
                status_code=503,
                detail="this endpoint has no TOKEN: the mangatl-char secret is "
                       "not attached to the function, or has no TOKEN key")
        got = item.get("token") or ""
        if got != want:
            # SAY WHICH ONE IS WRONG, without saying what either one is. Length
            # and a four-character fingerprint are enough to tell "I sent the
            # wrong string" from "I sent the right string with quotes round
            # it", which are the two ways this goes wrong on Windows and are
            # indistinguishable from a bare 401. Same trick the app already
            # uses on the cleaner's token in `editor._plate_stamp`.
            raise HTTPException(
                status_code=401,
                detail="bad token: sent %d chars (%s), expected %d chars (%s)"
                       % (len(got), _fp(got), len(want), _fp(want)))

        prompt = (item.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="no prompt")

        n = max(1, min(int(item.get("n") or 1), 6))
        seed = int(item.get("seed") or 0)
        out = []
        for k in range(n):
            # One seed per picture, derived from the one asked for, so a sheet
            # of six is repeatable and so is any single frame out of it.
            g = torch.Generator("cuda").manual_seed(seed + k)
            img = self.pipe(
                prompt,
                negative_prompt=item.get("negative") or NEGATIVE,
                width=int(item.get("width") or 832),
                height=int(item.get("height") or 1216),
                guidance_scale=float(item.get("cfg") or 5.0),
                num_inference_steps=int(item.get("steps") or 28),
                generator=g,
            ).images[0]
            buf = _png(img)
            out.append({"seed": seed + k,
                        "png": base64.b64encode(buf).decode()})
        return {"images": out}


def _fp(s: str) -> str:
    """Four characters that stand for a string without being it."""
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:4] if s else "----"


def _png(img) -> bytes:
    import io
    b = io.BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()
