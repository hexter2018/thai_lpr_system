# Minimal province normalization map (extend as needed)
ALIASES = {
  "กรุงเทพฯ": "กรุงเทพมหานคร",
  "กทม.": "กรุงเทพมหานคร",
  "กทม": "กรุงเทพมหานคร",
  "กรุงเทพมหาคร": "กรุงเทพมหานคร",
}

def normalize_province(p: str) -> str:
    t = (p or "").strip()
    return ALIASES.get(t, t)
