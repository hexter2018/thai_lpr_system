from __future__ import annotations

import re
import unicodedata
from typing import Dict, Tuple

from rapidfuzz import fuzz, process

THAI_PROVINCES = [
    "กรุงเทพมหานคร", "กระบี่", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร", "ขอนแก่น", "จันทบุรี", "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท",
    "ชัยภูมิ", "ชุมพร", "เชียงราย", "เชียงใหม่", "ตรัง", "ตราด", "ตาก", "นครนายก", "นครปฐม", "นครพนม", "นครราชสีมา",
    "นครศรีธรรมราช", "นครสวรรค์", "นนทบุรี", "นราธิวาส", "น่าน", "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์",
    "ปราจีนบุรี", "ปัตตานี", "พระนครศรีอยุธยา", "พะเยา", "พังงา", "พัทลุง", "พิจิตร", "พิษณุโลก", "เพชรบุรี", "เพชรบูรณ์",
    "แพร่", "ภูเก็ต", "มหาสารคาม", "มุกดาหาร", "แม่ฮ่องสอน", "ยะลา", "ยโสธร", "ร้อยเอ็ด", "ระนอง", "ระยอง", "ราชบุรี",
    "ลพบุรี", "ลำปาง", "ลำพูน", "เลย", "ศรีสะเกษ", "สกลนคร", "สงขลา", "สตูล", "สมุทรปราการ", "สมุทรสงคราม", "สมุทรสาคร",
    "สระแก้ว", "สระบุรี", "สิงห์บุรี", "สุโขทัย", "สุพรรณบุรี", "สุราษฎร์ธานี", "สุรินทร์", "หนองคาย", "หนองบัวลำภู", "อ่างทอง",
    "อำนาจเจริญ", "อุดรธานี", "อุตรดิตถ์", "อุทัยธานี", "อุบลราชธานี",
]

PROVINCE_ALIASES: Dict[str, str] = {
    "กทม": "กรุงเทพมหานคร",
    "กทม.": "กรุงเทพมหานคร",
    "กรุงเทพ": "กรุงเทพมหานคร",
    "กรุงเทพฯ": "กรุงเทพมหานคร",
    "กรุงเทพมหานครฯ": "กรุงเทพมหานคร",
    "bkk": "กรุงเทพมหานคร",
    "bangkok": "กรุงเทพมหานคร",
    "อยุธยา": "พระนครศรีอยุธยา",
    "พระนครศรี": "พระนครศรีอยุธยา",
    "พระนครศรีอยุธยา": "พระนครศรีอยุธยา",
    "โคราช": "นครราชสีมา",
    "นครราชศรมา": "นครราชสีมา",
    "นครศรี": "นครศรีธรรมราช",
    "พิดโลก": "พิษณุโลก",
    "พิศณุโลก": "พิษณุโลก",
    "สุราษ": "สุราษฎร์ธานี",
    "สุราด": "สุราษฎร์ธานี",
    "ชล": "ชลบุรี",
    "นน": "นนทบุรี",
    "เชียงใหม่ฯ": "เชียงใหม่",
    "เชียงรายฯ": "เชียงราย",
    "chiangmai": "เชียงใหม่",
    "chiangrai": "เชียงราย",
    "ayutthaya": "พระนครศรีอยุธยา",
    "korat": "นครราชสีมา",
    "nakhonratchasima": "นครราชสีมา",
}

_COMBINING_MARKS_RE = re.compile(r"[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]")
_NOISE_RE = re.compile(r"[\s\-_.:/\\|,;\[\](){}<>!?+*'\"`~]+")
_ALLOWED_RE = re.compile(r"[^a-z0-9ก-๙]")


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", (text or "").strip().lower())
    normalized = normalized.replace("ฯ", "")
    normalized = normalized.replace("ำ", "า")
    normalized = _COMBINING_MARKS_RE.sub("", normalized)
    normalized = _NOISE_RE.sub("", normalized)
    normalized = _ALLOWED_RE.sub("", normalized)
    return normalized


_NORMALIZED_PROVINCES = {_normalize(p): p for p in THAI_PROVINCES}
_NORMALIZED_ALIASES = {_normalize(k): v for k, v in PROVINCE_ALIASES.items() if _normalize(k)}



def match_province(text: str, threshold: int = 70) -> Tuple[str, float]:
    cleaned = _normalize(text)
    if not cleaned:
        return "", 0.0

    if cleaned in _NORMALIZED_ALIASES:
        return _NORMALIZED_ALIASES[cleaned], 100.0
    if cleaned in _NORMALIZED_PROVINCES:
        return _NORMALIZED_PROVINCES[cleaned], 100.0

    for key, province in _NORMALIZED_ALIASES.items():
        if key and (cleaned in key or key in cleaned):
            overlap = min(len(cleaned), len(key)) / max(len(cleaned), len(key))
            return province, 75.0 + overlap * 20.0

    for key, province in _NORMALIZED_PROVINCES.items():
        if cleaned in key or key in cleaned:
            overlap = min(len(cleaned), len(key)) / max(len(cleaned), len(key))
            return province, 72.0 + overlap * 20.0

    province_match = process.extractOne(cleaned, list(_NORMALIZED_PROVINCES.keys()), scorer=fuzz.WRatio)
    alias_match = process.extractOne(cleaned, list(_NORMALIZED_ALIASES.keys()), scorer=fuzz.WRatio)

    best_key = ""
    best_score = 0.0
    best_is_alias = False

    if province_match:
        best_key = province_match[0]
        best_score = float(province_match[1])

    if alias_match and float(alias_match[1]) > best_score:
        best_key = alias_match[0]
        best_score = float(alias_match[1])
        best_is_alias = True

    if best_score < threshold:
        return "", best_score

    if best_is_alias or best_key in _NORMALIZED_ALIASES:
        return _NORMALIZED_ALIASES.get(best_key, ""), best_score
    return _NORMALIZED_PROVINCES.get(best_key, ""), best_score


def normalize_province(text: str, threshold: int = 70) -> str:
    return match_province(text, threshold=threshold)[0]
