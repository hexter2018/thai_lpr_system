"""
Best Shot Buffer — เลือก 1 เฟรมที่ดีที่สุดต่อ 1 "event" (1 คันรถ)

ทำงานโดย:
1. Buffer เฟรมที่ผ่าน filter ทั้งหมด (เก็บแค่ path + score)
2. เมื่อตรวจพบ "gap" (ไม่มีเฟรมใหม่เกิน gap_sec) → flush best
3. หรือเมื่อ buffer เต็ม window → flush best
4. ส่งแค่เฟรมเดียวที่ดีที่สุดไป process

ใช้ quality_score จาก QualityScorer เป็น proxy
(ไม่ต้องรัน YOLO/OCR บน producer container)

ENV vars:
  RTSP_BESTSHOT_WINDOW_SEC   = 3.0   วินาที max ที่จะ buffer
  RTSP_BESTSHOT_GAP_SEC      = 1.5   วินาทีที่ไม่มีเฟรมใหม่ = จบ event
  RTSP_BESTSHOT_MIN_FRAMES   = 2     จำนวนเฟรมขั้นต่ำก่อน flush
  RTSP_BESTSHOT_ENABLED      = true  เปิด/ปิด feature
"""
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

log = logging.getLogger(__name__)


@dataclass
class FrameCandidate:
    """เก็บข้อมูลเฟรมที่ buffer ไว้"""
    image_path: str          # path ที่ save ไว้แล้ว
    quality_score: float     # จาก QualityScorer
    timestamp: float         # time.time()
    metadata: dict = field(default_factory=dict)

    @property
    def score(self) -> float:
        return self.quality_score


class BestShotBuffer:
    """
    Buffer เฟรมแล้วเลือก best shot ต่อ 1 event (1 คันรถ)
    
    Usage:
        buffer = BestShotBuffer()
        
        # ใน loop:
        candidate = FrameCandidate(path, score, time.time())
        result = buffer.add(candidate)
        if result:
            # result = best FrameCandidate → ส่งไป process
            enqueue(result.image_path)
        
        # เช็ค gap timeout:
        flushed = buffer.check_timeout()
        if flushed:
            enqueue(flushed.image_path)
    """
    
    def __init__(self):
        self.window_sec = float(os.getenv("RTSP_BESTSHOT_WINDOW_SEC", "3.0"))
        self.gap_sec = float(os.getenv("RTSP_BESTSHOT_GAP_SEC", "1.5"))
        self.min_frames = int(os.getenv("RTSP_BESTSHOT_MIN_FRAMES", "2"))
        self.enabled = os.getenv("RTSP_BESTSHOT_ENABLED", "true").lower() == "true"
        
        self._buffer: List[FrameCandidate] = []
        self._window_start: float = 0.0
        self._last_add: float = 0.0
        
        log.info(
            "BestShotBuffer: enabled=%s window=%.1fs gap=%.1fs min_frames=%d",
            self.enabled, self.window_sec, self.gap_sec, self.min_frames,
        )
    
    def add(self, candidate: FrameCandidate) -> Optional[FrameCandidate]:
        """
        เพิ่มเฟรมเข้า buffer
        
        Returns:
            FrameCandidate ถ้า window เต็มแล้ว (flush best + เริ่ม window ใหม่)
            None ถ้ายัง buffer อยู่
        """
        if not self.enabled:
            # bypass — ส่งทุกเฟรมเหมือนเดิม
            return candidate
        
        now = candidate.timestamp
        
        # ถ้า buffer ว่าง → เริ่ม window ใหม่
        if not self._buffer:
            self._buffer.append(candidate)
            self._window_start = now
            self._last_add = now
            return None
        
        # ถ้าเกิน window → flush best แล้วเริ่มใหม่ด้วย candidate ปัจจุบัน
        if (now - self._window_start) >= self.window_sec:
            best = self._flush()
            # เริ่ม window ใหม่ด้วย candidate ปัจจุบัน
            self._buffer.append(candidate)
            self._window_start = now
            self._last_add = now
            return best
        
        # ยังอยู่ใน window → buffer ต่อ
        self._buffer.append(candidate)
        self._last_add = now
        return None
    
    def check_timeout(self, now: Optional[float] = None) -> Optional[FrameCandidate]:
        """
        เรียกใน loop เพื่อเช็คว่ามี gap timeout หรือไม่
        (ไม่มีเฟรมใหม่เกิน gap_sec → flush)
        
        Returns:
            FrameCandidate ถ้า timeout แล้ว flush
            None ถ้ายังไม่ timeout
        """
        if not self.enabled or not self._buffer:
            return None
        
        now = now or time.time()
        if (now - self._last_add) >= self.gap_sec:
            return self._flush()
        
        return None
    
    def flush_remaining(self) -> Optional[FrameCandidate]:
        """Flush remaining buffer (เรียกตอน shutdown)"""
        if self._buffer:
            return self._flush()
        return None
    
    def _flush(self) -> Optional[FrameCandidate]:
        """เลือก best จาก buffer แล้ว clear"""
        if not self._buffer:
            return None
        
        best = max(self._buffer, key=lambda c: c.score)
        count = len(self._buffer)
        
        # ลบไฟล์ที่ไม่ได้เลือก
        for c in self._buffer:
            if c.image_path != best.image_path:
                try:
                    Path(c.image_path).unlink(missing_ok=True)
                except Exception as e:
                    log.debug("Failed to delete non-best frame %s: %s", c.image_path, e)
        
        log.info(
            "BestShot: selected 1/%d frames (score=%.1f, window=%.1fs)",
            count, best.score, time.time() - self._window_start,
        )
        
        self._buffer.clear()
        self._window_start = 0.0
        self._last_add = 0.0
        
        return best
    
    @property
    def buffered_count(self) -> int:
        return len(self._buffer)


# === Self-test ===
if __name__ == "__main__":
    import os
    os.environ["RTSP_BESTSHOT_WINDOW_SEC"] = "2.0"
    os.environ["RTSP_BESTSHOT_GAP_SEC"] = "0.8"
    os.environ["RTSP_BESTSHOT_MIN_FRAMES"] = "2"
    
    logging.basicConfig(level=logging.INFO)
    
    print("BestShotBuffer Self-Test")
    print("=" * 40)
    
    buffer = BestShotBuffer()
    
    # Simulate 5 frames in 1 second (same vehicle)
    t0 = time.time()
    results = []
    for i in range(5):
        score = [40, 55, 70, 85, 60][i]  # frame 4 is best
        c = FrameCandidate(
            image_path=f"/tmp/test_{i}.jpg",
            quality_score=score,
            timestamp=t0 + i * 0.2,
        )
        r = buffer.add(c)
        if r:
            results.append(r)
    
    # Simulate gap timeout
    time.sleep(1.0)
    r = buffer.check_timeout()
    if r:
        results.append(r)
    
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    assert results[0].quality_score == 85, f"Expected best score 85, got {results[0].quality_score}"
    print(f"✅ Selected best: score={results[0].quality_score}")
    
    print("\n✅ All tests passed!")
