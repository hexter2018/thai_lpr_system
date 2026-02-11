"""
validate.py — Thai License Plate Format Validation (CORRECTED)
===============================================================

รองรับทะเบียนรถไทยทุกรูปแบบ:

1. ป้ายส่วนบุคคล / แท็กซี่ (Personal / Taxi):
   - กก 1234        → [ก-ฮ]{2}[0-9]{1,4}
   - ก 1234         → [ก-ฮ]{1}[0-9]{1,4}     (จักรยานยนต์)
   - 1กก 1234       → [0-9][ก-ฮ]{2}[0-9]{1,4} (รวมแท็กซี่ เช่น 1ฆข 1234)
   - 1กก 1234       → [0-9][ก-ฮ]{1,2}[0-9]{1,4}
   - 12กก 1234      → [0-9]{2}[ก-ฮ]{1,2}[0-9]{1,4}  (rare)

2. ป้ายเหลือง — รถสาธารณะ/รถบรรทุก (Commercial/Truck):
   - 32-0394         → [0-9]{2}-[0-9]{4}  (NN-NNNN ตัวเลขล้วน)
   - 65-0282         → [0-9]{2}-[0-9]{4}
   - ท.99-1234       → [ก-ฮ].[0-9]{1,2}-[0-9]{3,4}

3. ป้ายน้ำเงิน — ราชการ/ทูต (Government/Diplomatic):
   - 36-1777         → [0-9]{2}-[0-9]{4}

หมายเหตุ:
- "THAILAND XX" ด้านบนคือ header ไม่ใช่เลขทะเบียน
- ป้ายเหลือง/น้ำเงินที่เป็นตัวเลขล้วน มี "ชส" "ชน" etc. เป็นประเภทรถ
- ป้ายแท็กซี่ เช่น "1ฆข 1234" ใช้ format เดียวกับรถส่วนบุคคลที่มี digit prefix
- "1ฆ 4048" เป็น OCR อ่านขาด — จริงๆ ต้องเป็น "1ฆ[ก-ฮ] 4048"
"""

import re

# === Plate format patterns (normalized — no spaces, no dashes, no dots) ===

PATTERNS = [
    # --- ป้ายมีตัวอักษรไทย (Standard / Taxi / Personal) ---
    re.compile(r"^[ก-ฮ]{2}\d{1,4}$"),          # กก1234, กต8076
    re.compile(r"^[ก-ฮ]\d{1,4}$"),              # ก1234 (ป้ายแดง)
    re.compile(r"^\d[ก-ฮ]{2}\d{1,4}$"),         # 1กก1234, 1ฆข1234 (taxi!)
    re.compile(r"^\d[ก-ฮ]\d{1,4}$"),            # 1ก1234 (จักรยานยนต์ บางจังหวัด)
    re.compile(r"^\d{2}[ก-ฮ]{1,2}\d{1,4}$"),   # 12กก1234 (rare)

    # --- ป้ายตัวเลขล้วน (Commercial/Truck/Government/Diplomatic) ---
    re.compile(r"^\d{2}\d{4}$"),                 # 320394 (= 32-0394)
    re.compile(r"^\d{2}\d{3}$"),                 # 36177 (= 36-177)

    # --- ป้ายรถบรรทุก (Thai char + digits) ---
    re.compile(r"^[ก-ฮ]\d{5,6}$"),              # ท991234 (= ท.99-1234)
]

# === Patterns ที่เก็บ dash (สำหรับ raw input ก่อน normalize) ===
PATTERNS_WITH_DASH = [
    re.compile(r"^\d{1,2}-\d{1,4}$"),           # 32-0394, 1-1234
    re.compile(r"^[ก-ฮ]\.?\d{1,2}-\d{3,4}$"),  # ท.99-1234, ข12-3456
    re.compile(r"^\d{2,3}-\d{3,4}$"),           # 01-1234, 123-4567 (diplomatic)
]


def is_valid_plate(norm: str) -> bool:
    """
    ตรวจสอบว่าข้อความเป็นรูปแบบทะเบียนรถไทยที่ถูกต้องหรือไม่

    Args:
        norm: ข้อความทะเบียนที่ normalize แล้ว (ไม่มี space, อาจมีหรือไม่มี dash/dot)

    Returns:
        True ถ้าตรงกับรูปแบบทะเบียนไทย
    """
    if not norm:
        return False

    # Check with-dash patterns first (before stripping)
    for p in PATTERNS_WITH_DASH:
        if p.match(norm):
            return True

    # Strip dash and dot for normalized patterns
    clean = norm.replace("-", "").replace(".", "")

    for p in PATTERNS:
        if p.match(clean):
            return True

    return False


def is_possibly_truncated(norm: str) -> bool:
    """
    ตรวจว่าทะเบียนอาจถูก OCR ตัดตัวอักษรหายไป

    ตัวอย่าง:
    - "1ฆ4048" → น่าจะเป็น "1ฆ[ก-ฮ]4048" (ขาดตัวอักษรไทย 1 ตัว)
    - "กก12"   → น่าจะเป็น "กก1234"  (ขาดตัวเลข)

    Returns:
        True ถ้าอาจถูกตัด
    """
    if not norm:
        return False

    clean = norm.replace("-", "").replace(".", "").replace(" ", "")

    # Pattern: digit + 1 Thai char + 3-4 digits → likely missing 2nd Thai char
    # เช่น 1ฆ4048 → should be 1ฆข4048
    if re.match(r"^\d[ก-ฮ]\d{3,4}$", clean):
        return True

    # Very short text that partially matches plate patterns
    if len(clean) <= 3 and re.match(r"^[ก-ฮ0-9]+$", clean):
        return True

    return False


def classify_plate_type(norm: str) -> str:
    """
    จำแนกประเภทป้ายทะเบียน

    Returns:
        "personal"    — ป้ายส่วนบุคคล/แท็กซี่ (มีตัวอักษรไทย ≥ 2 ตัว)
        "motorcycle"  — ป้ายจักรยานยนต์ (มีตัวอักษรไทย 1 ตัว + digits สั้น)
        "commercial"  — ป้ายรถสาธารณะ/บรรทุก (ตัวเลขล้วน)
        "truck"       — ป้ายรถบรรทุก (ก.XX-XXXX format)
        "unknown"     — ไม่สามารถจำแนกได้
    """
    if not norm:
        return "unknown"

    clean = norm.replace("-", "").replace(".", "").replace(" ", "")

    # Count Thai characters
    thai_chars = [c for c in clean if "\u0e01" <= c <= "\u0e2e"]

    if len(thai_chars) >= 2:
        return "personal"  # includes taxi plates like 1ฆข1234

    if len(thai_chars) == 1:
        # Single Thai char + long digits: truck format (ท.99-1234 = ท991234)
        if re.match(r"^[ก-ฮ]\d{5,6}$", clean):
            return "truck"
        # Single Thai char + short digits: motorcycle or possibly truncated
        return "motorcycle"

    # Pure numeric → commercial/government
    if clean.isdigit():
        return "commercial"

    return "unknown"


def format_plate_display(text: str) -> str:
    """
    จัดรูปแบบการแสดงผลทะเบียน ใส่ช่องว่าง/ขีดตามรูปแบบมาตรฐาน

    Examples:
        "กก1234"    → "กก 1234"
        "1กก1234"   → "1กก 1234"
        "1ฆข1234"   → "1ฆข 1234"   (taxi)
        "320394"    → "32-0394"
        "ท991234"   → "ท.99-1234"
    """
    if not text:
        return text

    clean = text.replace(" ", "").replace("-", "").replace(".", "")

    # Pattern: 1-2 digit prefix + 2 Thai chars + digits → "1กก 1234" / "1ฆข 1234"
    m = re.match(r"^(\d{1,2})([ก-ฮ]{2})(\d{1,4})$", clean)
    if m:
        return f"{m.group(1)}{m.group(2)} {m.group(3)}"

    # Pattern: 1 digit + 1 Thai char + digits → "1ก 1234" (motorcycle)
    m = re.match(r"^(\d)([ก-ฮ])(\d{1,4})$", clean)
    if m:
        return f"{m.group(1)}{m.group(2)} {m.group(3)}"

    # Pattern: 2 Thai chars + digits → "กก 1234"
    m = re.match(r"^([ก-ฮ]{2})(\d{1,4})$", clean)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    # Pattern: 1 Thai char + short digits → "ก 1234" (motorcycle)
    m = re.match(r"^([ก-ฮ])(\d{1,4})$", clean)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    # Pattern: pure numeric 6 digits → "32-0394" (NN-NNNN)
    m = re.match(r"^(\d{2})(\d{4})$", clean)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    # Pattern: pure numeric 5 digits → "36-177"
    m = re.match(r"^(\d{2})(\d{3})$", clean)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    # Pattern: Thai char + 2 digits + 3-4 digits → "ท.99-1234" (truck)
    m = re.match(r"^([ก-ฮ])(\d{1,2})(\d{3,4})$", clean)
    if m:
        return f"{m.group(1)}.{m.group(2)}-{m.group(3)}"

    # Already has dash — preserve it
    if "-" in text:
        return text

    return text