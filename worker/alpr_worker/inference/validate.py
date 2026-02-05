import re

PATTERNS = [
    re.compile(r"^[ก-ฮ]{1,2}\d{1,4}$"),
    re.compile(r"^\d[ก-ฮ]{1,2}\d{1,4}$"),
    re.compile(r"^\d{1,2}-\d{1,4}$"),
]

def is_valid_plate(norm: str) -> bool:
    if not norm:
        return False
    for p in PATTERNS:
        if p.match(norm):
            return True
    return False
