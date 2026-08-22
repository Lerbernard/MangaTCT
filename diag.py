"""mangatl detection diagnostic - run:  python diag.py
Prints what the model outputs on THIS machine and saves diag_004.png."""
import sys, os
here = os.path.dirname(os.path.abspath(__file__))     # ...\mangatl
sys.path.insert(0, os.path.dirname(here))             # so `import mangatl` works
import cv2, numpy as np
from mangatl import imgio
print("cv2   :", cv2.__version__)
print("numpy :", np.__version__)

model = os.path.join(here, "comictextdetector.pt.onnx")
page  = os.path.join(here, "out", "input", "004.jpg")
print("model exists:", os.path.isfile(model))
print("page  exists:", os.path.isfile(page))

# raw model output shapes
net = cv2.dnn.readNetFromONNX(model)
net.setInput(cv2.dnn.blobFromImage(np.zeros((1024,1024,3),'uint8'),1/255.,(1024,1024)))
outs = net.forward(net.getUnconnectedOutLayersNames())
print("raw output shapes:", [tuple(np.asarray(o).shape) for o in outs])

# full detection through the real code
from mangatl.models import Page
from mangatl.detect.comictext import detect_comictext
img = imgio.imread(page)
regs = detect_comictext(Page(image=img, source_path="004.jpg"),
                        model, split_gap=1.3, split_height=1.5)
print("DETECTED BOXES:", len(regs))
vis = img.copy()
for i, r in enumerate(regs):
    x,y,w,h = r.bbox
    cv2.rectangle(vis,(x,y),(x+w,y+h),(0,0,255),3)
    cv2.putText(vis,str(i+1),(x+2,y+26),0,0.9,(0,0,255),2)
outp = os.path.join(here, "diag_004.png")
imgio.imwrite(outp, vis)
print("SAVED:", outp)
print("--- send me everything above + the diag_004.png image ---")
