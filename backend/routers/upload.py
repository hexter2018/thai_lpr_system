from fastapi import APIRouter, UploadFile, File
from services.yolo_infer import detect_plate
from services.ocr_reader import read_plate
from services.learning import store_plate_result
from PIL import Image
import uuid, os


router = APIRouter()


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
filename = f"{uuid.uuid4()}.jpg"
image_path = f"static/uploads/{filename}"
with open(image_path, "wb") as buffer:
buffer.write(await file.read())


image = Image.open(image_path)
crop_img = detect_plate(image)
plate_text, confidence = read_plate(crop_img)


plate_type = "ALPR" if confidence > 0.95 else "MLPR"
plate_record = store_plate_result(plate_text, confidence, plate_type, crop_img)


return plate_record