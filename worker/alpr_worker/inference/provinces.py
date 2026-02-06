from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Tuple

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
    "bangkok": "กรุงเทพมหานคร",
    "bkk": "กรุงเทพมหานคร",
    "อยุธยา": "พระนครศรีอยุธยา",
    "กรุงเก่า": "พระนครศรีอยุธยา",
    "โคราช": "นครราชสีมา",
    "พิดโลก": "พิษณุโลก",
    "ศรีสะเกษ": "ศรีสะเกษ",
    "ศรีสะเกด": "ศรีสะเกษ",
    "ชล": "ชลบุรี",
    "นน": "นนทบุรี",
    "ปากน้ำ": "สมุทรปราการ",
    "สุราษ": "สุราษฎร์ธานี",
    "สุราษฎ": "สุราษฎร์ธานี",
    "อุบล": "อุบลราชธานี",
    "อุดร": "อุดรธานี",
    "เชียงใหม่": "เชียงใหม่",
    "เชียงราย": "เชียงราย",
    "chiangmai": "เชียงใหม่",
    "chiangrai": "เชียงราย",
    "korat": "นครราชสีมา",
    "ayutthaya": "พระนครศรีอยุธยา",
    "nakhonratchasima": "นครราชสีมา",
}


def normalize_thai_text(text: str) -> str:
    txt = unicodedata.normalize("NFKC", (text or "").strip().lower())
    txt = txt.replace("ฯ", "").replace("ํ", "")
    txt = "".join(ch for ch in txt if unicodedata.category(ch) != "Mn")
    txt = re.sub(r"[\s\-_.:/\\|,;\[\](){}<>!?+*'\"`~]+", "", txt)
    txt = re.sub(r"[^a-z0-9ก-๙]", "", txt)
    return txt


_NORMALIZED_PROVINCES = {normalize_thai_text(name): name for name in THAI_PROVINCES}
_NORMALIZED_ALIASES = {normalize_thai_text(alias): target for alias, target in PROVINCE_ALIASES.items()}


def match_province(text: str, threshold: int = 70) -> Tuple[str, float]:
    cleaned = normalize_thai_text(text)
    if not cleaned:
        return "", 0.0

    if "กรุงเทพ" in cleaned or "กรงเทพ" in cleaned or "มหานคร" in cleaned:
        return "กรุงเทพมหานคร", 100.0
    if cleaned in _NORMALIZED_ALIASES:
        return _NORMALIZED_ALIASES[cleaned], 100.0
    if cleaned in _NORMALIZED_PROVINCES:
        return _NORMALIZED_PROVINCES[cleaned], 100.0

    for normalized, province in _NORMALIZED_PROVINCES.items():
        if cleaned in normalized or normalized in cleaned:
            overlap = min(len(cleaned), len(normalized)) / max(len(cleaned), len(normalized))
            score = 74.0 + overlap * 20.0
            if score >= threshold:
                return province, score

    province_hit = process.extractOne(cleaned, list(_NORMALIZED_PROVINCES.keys()), scorer=fuzz.WRatio)
    alias_hit = process.extractOne(cleaned, list(_NORMALIZED_ALIASES.keys()), scorer=fuzz.WRatio)

    candidate = ""
    score = 0.0
    is_alias = False
    if province_hit:
        candidate = province_hit[0]
        score = float(province_hit[1])
    if alias_hit and float(alias_hit[1]) > score:
        candidate = alias_hit[0]
        score = float(alias_hit[1])
        is_alias = True

    if score < float(threshold):
        return "", score

    if is_alias:
        return _NORMALIZED_ALIASES[candidate], score
    return _NORMALIZED_PROVINCES.get(candidate, ""), score


def province_candidates(text: str, limit: int = 3, threshold: int = 70) -> List[Tuple[str, float]]:
    cleaned = normalize_thai_text(text)
    if not cleaned:
        return []

    candidates: List[Tuple[str, float]] = []
    if "กรุงเทพ" in cleaned or "กรงเทพ" in cleaned or "มหานคร" in cleaned:
        return [("กรุงเทพมหานคร", 100.0)]
    if cleaned in _NORMALIZED_ALIASES:
        return [(_NORMALIZED_ALIASES[cleaned], 100.0)]
    if cleaned in _NORMALIZED_PROVINCES:
        return [(_NORMALIZED_PROVINCES[cleaned], 100.0)]

    overlap_hits: List[Tuple[str, float]] = []
    for normalized, province in _NORMALIZED_PROVINCES.items():
        if cleaned in normalized or normalized in cleaned:
            overlap = min(len(cleaned), len(normalized)) / max(len(cleaned), len(normalized))
            score = 74.0 + overlap * 20.0
            if score >= threshold:
                overlap_hits.append((province, score))
    overlap_hits.sort(key=lambda item: item[1], reverse=True)
    candidates.extend(overlap_hits[:limit])

    province_hits = process.extract(cleaned, list(_NORMALIZED_PROVINCES.keys()), scorer=fuzz.WRatio, limit=limit)
    alias_hits = process.extract(cleaned, list(_NORMALIZED_ALIASES.keys()), scorer=fuzz.WRatio, limit=limit)
    for candidate, score, _ in province_hits or []:
        if float(score) < float(threshold):
            continue
        candidates.append((_NORMALIZED_PROVINCES.get(candidate, ""), float(score)))
    for candidate, score, _ in alias_hits or []:
        if float(score) < float(threshold):
            continue
        candidates.append((_NORMALIZED_ALIASES.get(candidate, ""), float(score)))

    deduped: List[Tuple[str, float]] = []
    seen = set()
    for name, score in sorted(candidates, key=lambda item: item[1], reverse=True):
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append((name, score))
        if len(deduped) >= limit:
            break
    return deduped


def normalize_province(text: str, threshold: int = 70) -> str:
    matched, _ = match_province(text, threshold=threshold)
    return matched if matched in THAI_PROVINCES else ""
