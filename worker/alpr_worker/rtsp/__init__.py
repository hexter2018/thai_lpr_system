# NOTE: RTSPFrameProducer ไม่ import ที่นี่เพื่อหลีกเลี่ยง RuntimeWarning
# เมื่อรัน: python -m alpr_worker.rtsp.frame_producer
# ถ้าต้องการใช้ ให้ import ตรงจาก module:
#   from alpr_worker.rtsp.frame_producer import RTSPFrameProducer

from .quality_filter import MotionDetector, QualityScorer, FrameDeduplicator
from .config import RTSPConfig
from .roi_zone import ROIZone, ROIConfig

__all__ = [
    "MotionDetector",
    "QualityScorer",
    "FrameDeduplicator",
    "RTSPConfig",
    "ROIZone",
    "ROIConfig",
]