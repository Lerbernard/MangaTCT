"""Download pretrained bubble detectors.

    python get_models.py

Weights land in ./models. Point the editor at them under
Fonts & typesetting settings -> Bubble detector.
"""
import os
import sys
import urllib.request

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
    print("\nIn the editor: Bubble detector -> Trained model, then set the path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
