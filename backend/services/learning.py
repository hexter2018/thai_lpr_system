import os, uuid
from database.models import PlateRecord
from database.database import SessionLocal
from PIL import Image


def store_plate_result(plate, conf, ptype, crop_np):
file_path = f"static/cropped/{uuid.uuid4()}.jpg"
Image.fromarray(crop_np).save(file_path)
db = SessionLocal()
record = PlateRecord(full_plate=plate, confidence=conf, type=ptype, image_path=file_path)
db.add(record)
db.commit()
db.refresh(record)
db.close()
return {
"plate": plate,
"confidence": conf,
"type": ptype,
"image": file_path
}