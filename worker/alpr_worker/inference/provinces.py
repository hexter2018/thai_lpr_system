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
    "กรุงเทพ": "กรุงเทพมหานคร",
    "กรุงเทพฯ": "กรุงเทพมหานคร",
    "bangkok": "กรุงเทพมหานคร",
    "bkk": "กรุงเทพมหานคร",
    "อยุธยา": "พระนครศรีอยุธยา",
    "พระนครศรี": "พระนครศรีอยุธยา",
    "โคราช": "นครราชสีมา",
    "นครศรี": "นครศรีธรรมราช",
    "พิดโลก": "พิษณุโลก",
    "ชล": "ชลบุรี",
    "นน": "นนทบุรี",
    "สมุทรปราการ": "สมุทรปราการ",
    "chiangmai": "เชียงใหม่",
    "chiangrai": "เชียงราย",
    "nakhonratchasima": "นครราชสีมา",
    "ayutthaya": "พระนครศรีอยุธยา",
}

_EXTRA_REPLACEMENTS = {
    "ฯ": "",
    "ํ": "",
    "่": "",
    "้": "",
    "๊": "",
    "๋": "",
    "์": "",
    "ิ": "",
    "ี": "",
    "ึ": "",
    "ื": "",
    "ุ": "",
    "ู": "",
}


def _aggressive_normalize(text: str) -> str:
    txt = unicodedata.normalize("NFKC", (text or "").strip().lower())
    for src, dst in _EXTRA_REPLACEMENTS.items():
        txt = txt.replace(src, dst)
    txt = "".join(ch for ch in txt if unicodedata.category(ch) != "Mn")
    txt = re.sub(r"[\s\-_.:/\\|,;\[\](){}<>!?+*'\"`~]+", "", txt)
    txt = re.sub(r"[^a-z0-9ก-๙]", "", txt)
    return txt


_NORMALIZED_PROVINCES = {_aggressive_normalize(p): p for p in THAI_PROVINCES}
_NORMALIZED_ALIASES = {_aggressive_normalize(k): v for k, v in PROVINCE_ALIASES.items()}


def match_province(text: str, threshold: int = 62) -> Tuple[str, float]:
    cleaned = _aggressive_normalize(text)
    if not cleaned:
        return "", 0.0

    if cleaned in _NORMALIZED_ALIASES:
        return _NORMALIZED_ALIASES[cleaned], 100.0
    if cleaned in _NORMALIZED_PROVINCES:
        return _NORMALIZED_PROVINCES[cleaned], 100.0

    for n_name, province in _NORMALIZED_PROVINCES.items():
        if cleaned in n_name or n_name in cleaned:
            overlap = min(len(cleaned), len(n_name)) / max(len(cleaned), len(n_name))
            return province, 75.0 + overlap * 20.0

    province_match = process.extractOne(cleaned, list(_NORMALIZED_PROVINCES.keys()), scorer=fuzz.WRatio)
    alias_match = process.extractOne(cleaned, list(_NORMALIZED_ALIASES.keys()), scorer=fuzz.WRatio)

    best_name = ""
    best_score = 0.0
    if province_match:
        best_name = province_match[0]
        best_score = float(province_match[1])
    if alias_match and float(alias_match[1]) > best_score:
        best_name = alias_match[0]
        best_score = float(alias_match[1])

    if best_score < threshold:
        return "", best_score

    if best_name in _NORMALIZED_ALIASES:
        return _NORMALIZED_ALIASES[best_name], best_score
    return _NORMALIZED_PROVINCES.get(best_name, ""), best_score


def normalize_province(text: str, threshold: int = 62) -> str:
    matched = match_province(text, threshold=threshold)[0]
    if matched in THAI_PROVINCES:
        return matched
    return ""
