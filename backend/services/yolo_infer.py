from ultralytics import YOLO
import numpy as np


model = YOLO("weights/best.engine")


def detect_plate(image):
result = model(image)
xyxy = result[0].boxes.xyxy.cpu().numpy()[0] # assume first box
x1, y1, x2, y2 = map(int, xyxy)
crop = np.array(image)[y1:y2, x1:x2]
return crop




# Directory: alpr_backend/services/ocr_reader.py
import easyocr
reader = easyocr.Reader(['th', 'en'], gpu=True)


def read_plate(image_np):
results = reader.readtext(image_np)
if results:
text = results[0][1]
conf = results[0][2]
return text, conf
return "", 0.0