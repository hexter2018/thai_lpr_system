# storage.py
from __future__ import annotations

import os
import uuid
from datetime import datetime
import cv2
import numpy as np

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def save_image_bgr(image_bgr: np.ndarray, base_dir: str, prefix: str) -> str:
    """
    Saves image as JPEG under base_dir/YYYY-MM-DD/prefix_uuid.jpg
    Returns relative path.
    """
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    folder = os.path.join(base_dir, date_str)
    ensure_dir(folder)

    filename = f"{prefix}_{uuid.uuid4().hex}.jpg"
    fullpath = os.path.join(folder, filename)

    ok = cv2.imwrite(fullpath, image_bgr)
    if not ok:
        raise RuntimeError("Failed to write image to disk")

    return os.path.relpath(fullpath, start=base_dir).replace("\\", "/")
