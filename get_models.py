"""Download pretrained bubble detectors.

    python get_models.py

Weights land in ./models. Point the editor at them under
Fonts & typesetting settings -> Bubble detector.

The two WEBTOON balloon models are different: they arrive as zips, and the
app looks for them BESIDE itself under a fixed name rather than by a path
somebody types (`Project.webtoon_ko_weights`). So they are unzipped into this
folder, under the names that function looks for, and there is nothing to set
afterwards. Off manhwa and manhua they are ignored either way.
"""
import io
import os
import sys
import urllib.request
import zipfile

#: (url of the zip, file inside it, what to call it here). Published with
#: ImageTrans; see NOTICE - the licence is not stated on either of them.
WEBTOON = [
    ("https://github.com/xulihang/balloon-dataset/releases/download/models/"
     "korean_webtoon.zip", "model.onnx", "webtoon-ko.onnx",
     "webtoon balloons, Korean (~12MB)"),
    ("https://github.com/xulihang/balloon-dataset/releases/download/models/"
     "chinese_webtoon.zip", "model.onnx", "webtoon-zh.onnx",
     "webtoon balloons, Chinese (~12MB)"),
]

MODELS = {
    "comic-speech-bubble-detector-yolov8m.pt": (
        "https://huggingface.co/ogkalu/comic-speech-bubble-detector-yolov8m/"
        "resolve/main/comic-speech-bubble-detector.pt",
        "bubble detector, boxes (~50MB)"),
    "comic-text-segmenter-yolov8m.pt": (
        "https://huggingface.co/ogkalu/comic-text-segmenter-yolov8m/"
        "resolve/main/comic-text-segmenter.pt",
        "text segmenter, finds text outside bubbles (~50MB)"),
}


def progress(done, block, total):
    if total > 0:
        pct = min(100, done * block * 100 // total)
        sys.stdout.write(f"\r  {pct}%")
        sys.stdout.flush()


def main() -> int:
    os.makedirs("models", exist_ok=True)
    for name, (url, what) in MODELS.items():
        dest = os.path.join("models", name)
        if os.path.exists(dest):
            print(f"already have {name}")
            continue
        print(f"downloading {name} - {what}")
        try:
            urllib.request.urlretrieve(url, dest, progress)
            print(f"\r  saved to {dest}")
        except Exception as e:
            print(f"\r  FAILED: {e}")
            print("  Download it by hand from the model page instead; file "
                  "names on Hugging Face change occasionally.")
    here = os.path.dirname(os.path.abspath(__file__))
    for url, inside, name, what in WEBTOON:
        dest = os.path.join(here, name)
        if os.path.exists(dest):
            print(f"already have {name}")
            continue
        print(f"downloading {name} - {what}")
        try:
            with urllib.request.urlopen(url, timeout=120) as fh:
                blob = fh.read()
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                # the zip holds `model.onnx` and a `model.json`; the json only
                # ever says 640/640/20, which is what `detect/webtoon.py`
                # defaults to, so the graph alone is enough.
                with open(dest, "wb") as out:
                    out.write(z.read(inside))
            print(f"  saved to {dest}")
        except Exception as e:
            print(f"  FAILED: {e}")
            print(f"  Download {url} by hand and unzip its {inside} to "
                  f"{dest}.")
    print("\nIn the editor: Bubble detector -> Trained model, then set the path.")
    print("The webtoon models need nothing set - pick their card under "
          "Detector on a manhwa or manhua.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
