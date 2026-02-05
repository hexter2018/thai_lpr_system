from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Dict, Optional, Tuple

from rapidfuzz import fuzz, process

THAI_PROVINCES = [
    "กรุงเทพมหานคร", "กระบี่", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร", "ขอนแก่น", "จันทบุรี", "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท",
    "ชัยภูมิ", "ชุมพร", "เชียงราย", "เชียงใหม่", "ตรัง", "ตราด", "ตาก", "นครนายก", "นครปฐม", "นครพนม", "นครราชสีมา", "นครศรีธรรมราช",
    "นครสวรรค์", "นนทบุรี", "นราธิวาส", "น่าน", "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์", "ปราจีนบุรี", "ปัตตานี", "พระนครศรีอยุธยา",
    "พะเยา", "พังงา", "พัทลุง", "พิจิตร", "พิษณุโลก", "เพชรบุรี", "เพชรบูรณ์", "แพร่", "ภูเก็ต", "มหาสารคาม", "มุกดาหาร", "แม่ฮ่องสอน",
    "ยะลา", "ยโสธร", "ร้อยเอ็ด", "ระนอง", "ระยอง", "ราชบุรี", "ลพบุรี", "ลำปาง", "ลำพูน", "เลย", "ศรีสะเกษ", "สกลนคร", "สงขลา", "สตูล",
    "สมุทรปราการ", "สมุทรสงคราม", "สมุทรสาคร", "สระแก้ว", "สระบุรี", "สิงห์บุรี", "สุโขทัย", "สุพรรณบุรี", "สุราษฎร์ธานี", "สุรินทร์",
    "หนองคาย", "หนองบัวลำภู", "อ่างทอง", "อำนาจเจริญ", "อุดรธานี", "อุตรดิตถ์", "อุทัยธานี", "อุบลราชธานี",
]

ALIASES: Dict[str, str] = {
    "กทม": "กรุงเทพมหานคร",
    "กทม.": "กรุงเทพมหานคร",
    "กรุงเทพ": "กรุงเทพมหานคร",
    "กรุงเทพฯ": "กรุงเทพมหานคร",
    "กรุงเทพมหานครฯ": "กรุงเทพมหานคร",
    "พระนคร": "กรุงเทพมหานคร",
    "อยุธยา": "พระนครศรีอยุธยา",
    "พระนครศรี": "พระนครศรีอยุธยา",
    "โคราช": "นครราชสีมา",
    "โคราชฯ": "นครราชสีมา",
    "นครศรี": "นครศรีธรรมราช",
    "อุบล": "อุบลราชธานี",
    "อุดร": "อุดรธานี",
    "พิษโลก": "พิษณุโลก",
    "สุราษ": "สุราษฎร์ธานี",
    "ปทุม": "ปทุมธานี",
    "สมุทรปราการฯ": "สมุทรปราการ",
}

THAI_DIACRITICS_PATTERN = re.compile(r"[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]")
NON_THAI_TEXT_PATTERN = re.compile(r"[^ก-๙]")


@lru_cache(maxsize=1)
def _normalized_province_lookup() -> Dict[str, str]:
    return {normalize_thai_text(name): name for name in THAI_PROVINCES}


def normalize_thai_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", (text or "").strip())
    value = THAI_DIACRITICS_PATTERN.sub("", value)
    value = NON_THAI_TEXT_PATTERN.sub("", value)
    return value


def _alias_lookup(text: str) -> Optional[str]:
    if not text:
        return None

    norm = normalize_thai_text(text)
    for alias, province in ALIASES.items():
        if normalize_thai_text(alias) == norm:
            return province
    return None


def normalize_province(province_text: str, min_score: int = 74) -> str:
    raw = (province_text or "").strip()
    if not raw:
        return ""

    alias_hit = _alias_lookup(raw)
    if alias_hit:
        return alias_hit

    normalized = normalize_thai_text(raw)
    if not normalized:
        return ""

    lookup = _normalized_province_lookup()
    if normalized in lookup:
        return lookup[normalized]

    for norm_name, real_name in lookup.items():
        if norm_name and norm_name in normalized:
            return real_name
        if normalized and normalized in norm_name and len(normalized) >= 4:
            return real_name

    match = process.extractOne(
        normalized,
        lookup.keys(),
        scorer=fuzz.WRatio,
    )
    if match and int(match[1]) >= min_score:
        return lookup[str(match[0])]

    return ""


def best_province_from_text(text: str, min_score: int = 72) -> Tuple[str, float]:
    raw = (text or "").strip()
    if not raw:
        return "", 0.0

    alias_hit = _alias_lookup(raw)
    if alias_hit:
        return alias_hit, 0.99

    normalized = normalize_thai_text(raw)
    if not normalized:
        return "", 0.0

    lookup = _normalized_province_lookup()

    for norm_name, real_name in lookup.items():
        if norm_name and norm_name in normalized:
            conf = min(1.0, max(0.82, len(norm_name) / max(len(normalized), 1)))
            return real_name, conf

    match = process.extractOne(normalized, lookup.keys(), scorer=fuzz.WRatio)
    if not match:
        return "", 0.0

    score = float(match[1])
    if score < min_score:
        return "", 0.0

    province = lookup[str(match[0])]
    return province, score / 100.0
