from urllib.parse import urlencode

def make_image_url(path: str) -> str:
    # frontend calls: /api/images?path=...
    return f"/api/images?{urlencode({'path': path})}"
