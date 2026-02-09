"""
Configuration for RTSP Frame Producer

Loads settings from environment variables
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class RTSPConfig:
    """Configuration for RTSP frame producer"""
    
    # Database
    database_url: str = "postgresql+psycopg2://alpr:alpr@postgres:5432/alpr"
    
    # Redis
    redis_url: str = "redis://redis:6379/0"
    
    # Storage
    storage_dir: str = "/storage"
    
    # Frame capture
    target_fps: float = 2.0
    reconnect_sec: float = 2.0
    
    # Motion detection
    enable_motion_filter: bool = True
    motion_threshold: float = 5.0  # % of pixels changed
    
    # Quality filtering
    enable_quality_filter: bool = True
    min_quality_score: float = 40.0  # 0-100
    
    # Deduplication
    enable_dedup: bool = True
    dedup_cache_size: int = 50
    dedup_threshold: int = 5  # Hamming distance
    
    @classmethod
    def from_env(cls) -> "RTSPConfig":
        """Create config from environment variables"""
        return cls(
            # Database
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql+psycopg2://alpr:alpr@postgres:5432/alpr"
            ),
            
            # Redis
            redis_url=os.getenv(
                "REDIS_URL",
                "redis://redis:6379/0"
            ),
            
            # Storage
            storage_dir=os.getenv("STORAGE_DIR", "/storage"),
            
            # Frame capture
            target_fps=float(os.getenv("RTSP_TARGET_FPS", "2.0")),
            reconnect_sec=float(os.getenv("RTSP_RECONNECT_SEC", "2.0")),
            
            # Motion detection
            enable_motion_filter=os.getenv("RTSP_ENABLE_MOTION_FILTER", "true").lower() == "true",
            motion_threshold=float(os.getenv("RTSP_MOTION_THRESHOLD", "5.0")),
            
            # Quality filtering
            enable_quality_filter=os.getenv("RTSP_ENABLE_QUALITY_FILTER", "true").lower() == "true",
            min_quality_score=float(os.getenv("RTSP_MIN_QUALITY_SCORE", "40.0")),
            
            # Deduplication
            enable_dedup=os.getenv("RTSP_ENABLE_DEDUP", "true").lower() == "true",
            dedup_cache_size=int(os.getenv("RTSP_DEDUP_CACHE_SIZE", "50")),
            dedup_threshold=int(os.getenv("RTSP_DEDUP_THRESHOLD", "5")),
        )
    
    def __str__(self) -> str:
        """Human-readable config"""
        return f"""RTSPConfig:
  Database: {self.database_url}
  Redis: {self.redis_url}
  Storage: {self.storage_dir}
  Target FPS: {self.target_fps}
  Motion Filter: {self.enable_motion_filter} (threshold={self.motion_threshold}%)
  Quality Filter: {self.enable_quality_filter} (min_score={self.min_quality_score})
  Deduplication: {self.enable_dedup} (cache={self.dedup_cache_size}, threshold={self.dedup_threshold})
"""


# Default config instance
default_config = RTSPConfig.from_env()


if __name__ == "__main__":
    """Print current configuration"""
    config = RTSPConfig.from_env()
    print(config)