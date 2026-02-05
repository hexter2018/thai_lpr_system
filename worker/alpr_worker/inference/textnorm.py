import re
THAI_ALNUM = re.compile(r"[^0-9ก-ฮA-Za-z-]")

def normalize_plate_text(text: str) -> str:
    t = (text or "").strip()
    t = THAI_ALNUM.sub("", t)
    t = t.replace(" ", "")
    return t.upper()
