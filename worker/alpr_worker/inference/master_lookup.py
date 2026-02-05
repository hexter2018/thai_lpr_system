from rapidfuzz.distance import Levenshtein
from sqlalchemy.orm import Session
from datetime import datetime

from .textnorm import normalize_plate_text
from .provinces import normalize_province
from .. import models

def best_master_match(db: Session, plate_norm: str, max_dist: int = 1):
    # simple fuzzy match: compare against a recent subset
    # (for production, use trigram index / pg_trgm or dedicated search)
    candidates = db.query(models.MasterPlate).limit(5000).all()
    best = None
    best_d = 999
    for c in candidates:
        d = Levenshtein.distance(plate_norm, c.plate_text_norm)
        if d < best_d:
            best_d = d
            best = c
            if best_d == 0:
                break
    if best and best_d <= max_dist:
        return best, best_d
    return None, None

def assist_with_master(db: Session, plate_text: str, province: str, conf: float):
    norm = normalize_plate_text(plate_text)
    prov = normalize_province(province)
    m, d = best_master_match(db, norm, max_dist=1)
    if m:
        # If close match and master has high confidence, prefer master label.
        # Keep confidence as max(current, master.confidence*0.99) so it can pass threshold in known cases
        return {
            "plate_text": m.display_text or m.plate_text_norm,
            "plate_text_norm": m.plate_text_norm,
            "province": m.province or prov,
            "confidence": max(conf, float(m.confidence) * 0.99),
            "assisted": True,
            "dist": d,
        }
    return {
        "plate_text": plate_text,
        "plate_text_norm": norm,
        "province": prov,
        "confidence": conf,
        "assisted": False,
        "dist": None,
    }
