import os
from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

def _redis() -> Redis:
    return Redis.from_url(REDIS_URL)

def stop_key(camera_id: str) -> str:
    return f"rtsp:stop:{camera_id}"

def should_stop(camera_id: str) -> bool:
    r = _redis()
    return r.get(stop_key(camera_id)) == b"1"
