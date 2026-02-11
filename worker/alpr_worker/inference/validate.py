import re

PATTERNS = [
    re.compile(r"^[ก-ฮ]{1,2}\d{1,4}$"),        # กก1234, ก1234
    re.compile(r"^\d[ก-ฮ]{1,2}\d{1,4}$"),      # 1กก1234, 9กต8076
    re.compile(r"^\d{2}[ก-ฮ]{1,2}\d{1,4}$"),   # 12กก1234 (rare)
    re.compile(r"^\d{1,2}-\d{1,4}$"),            # 1-1234
    re.compile(r"^[ก-ฮ]{2}\d{3,4}$"),            # กต8076
]

def is_valid_plate(norm: str) -> bool:
    if not norm:
        return False
    for p in PATTERNS:
        if p.match(norm):
            return True
    return False