from __future__ import annotations

import re
from typing import Dict

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
    "กรุงเทพมหานคร.": "กรุงเทพมหานคร",
    "bkk": "กรุงเทพมหานคร",
    "bangkok": "กรุงเทพมหานคร",
    "phranakhonsiayutthaya": "พระนครศรีอยุธยา",
    "อยุธยา": "พระนครศรีอยุธยา",
    "นครศรี": "นครศรีธรรมราช",
    "โคราช": "นครราชสีมา",
    "chiangmai": "เชียงใหม่",
    "chiang mai": "เชียงใหม่",
    "chiangrai": "เชียงราย",
    "chiang rai": "เชียงราย",
}


def _clean_text(text: str) -> str:
    txt = (text or "").strip().lower()
    txt = re.sub(r"[\s\-_.]+", "", txt)
    return txt


def normalize_province(text: str, threshold: int = 70) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""

    if cleaned in PROVINCE_ALIASES:
        return PROVINCE_ALIASES[cleaned]

    direct = { _clean_text(p): p for p in THAI_PROVINCES }
    if cleaned in direct:
        return direct[cleaned]

    for official in THAI_PROVINCES:
        if _clean_text(official) in cleaned or cleaned in _clean_text(official):
            return official

    match = process.extractOne(cleaned, THAI_PROVINCES, scorer=fuzz.WRatio)
    if match and match[1] >= threshold:
        return str(match[0])

    alias_match = process.extractOne(cleaned, list(PROVINCE_ALIASES.keys()), scorer=fuzz.WRatio)
    if alias_match and alias_match[1] >= threshold:
        return PROVINCE_ALIASES[str(alias_match[0])]

    return ""
