#!/usr/bin/env python3
"""
Stream Manager Service
Runs RTSP capture with line crossing detection for all cameras
"""
import asyncio
import logging
import signal
import sys
from typing import Dict, List, Optional, Tuple

from app.stream.rtsp_manager import RTSPManager
from app.stream.mjpeg_server import MJPEGServer
from app.db.session import AsyncSessionLocal, async_engine
from sqlalchemy import select

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


class StreamManagerService:
    """Manages all camera streams with line crossing detection"""
    
    def __init__(self, count_line: Optional[List[Tuple[int, int]]] = None):
        """
        Initialize Stream Manager
        
        Args:
            count_line: Virtual counting line as [(x1, y1), (x2, y2)]
                       If None, uses default horizontal line
        """
        self.rtsp_manager: RTSPManager | None = None
        self.active_camera_ids: set[str] = set()
        self.running = False
        self.count_line = count_line or [(100, 400), (900, 400)]
        
        log.info("StreamManagerService initialized with count_line: %s", self.count_line)
    
    async def load_cameras(self):
        """Load active cameras from database"""
        try:
            async with AsyncSessionLocal() as session:
                from app.db.models import Camera
                
                result = await session.execute(
                    select(Camera).where(Camera.enabled.is_(True))
                )
                cameras = result.scalars().all()
                
                return cameras
        except Exception as e:
            log.error(f"Error loading cameras: {e}")
            return []
    
    async def start_streams(self, cameras: List):
        """Start all RTSP streams with line crossing tracking"""
        camera_configs: Dict[str, object] = {
            camera.camera_id: camera for camera in cameras if camera.enabled
        }

        self.rtsp_manager = RTSPManager(
            camera_configs=camera_configs,
            redis_client=None,
            db_session_factory=AsyncSessionLocal,
            count_line=self.count_line,  # Pass count line to RTSP manager
        )
        self.rtsp_manager.start()
        self.active_camera_ids = set(camera_configs.keys())
        log.info(
            "Started streams for cameras: %s (count_line=%s)",
            sorted(self.active_camera_ids),
            self.count_line
        )

    async def restart_streams(self, cameras: List):
        """Restart stream manager after camera configuration changes"""
        if self.rtsp_manager:
            self.rtsp_manager.stop()
        await self.start_streams(cameras)
    
    async def start(self):
        """Start stream manager service"""
        log.info("Starting Stream Manager Service...")
        
        self.running = True
        
        # Load cameras
        cameras = await self.load_cameras()
        log.info(f"Loaded {len(cameras)} active cameras")
        
        # Start streams
        await self.start_streams(cameras)
              
        # Monitor and reload cameras periodically
        while self.running:
            await asyncio.sleep(60)  # Check every minute
            
            # Reload cameras (handle added/removed)
            cameras = await self.load_cameras()
            next_ids = {c.camera_id for c in cameras if c.enabled}

            if next_ids != self.active_camera_ids:
                log.info(
                    "Camera set changed from %s to %s, restarting streams",
                    sorted(self.active_camera_ids),
                    sorted(next_ids),
                )
                await self.restart_streams(cameras)
    
    async def stop(self):
        """Stop stream manager service"""
        log.info("Stopping Stream Manager Service...")
        
        self.running = False
        
        if self.rtsp_manager:
            self.rtsp_manager.stop()
            self.rtsp_manager = None
            self.active_camera_ids.clear()
        
        # Close database engine
        await async_engine.dispose()
        
        log.info("Stream Manager Service stopped")
    
    def set_count_line(self, count_line: List[Tuple[int, int]]):
        """Update count line (requires restart)"""
        self.count_line = count_line
        log.info("Count line updated to: %s (restart required)", count_line)


async def main():
    """Main entry point"""
    # Optional: Parse count line from environment variable
    import os
    import json
    count_line_env = os.getenv("COUNT_LINE")
    if count_line_env:
        try:
            count_line = json.loads(count_line_env)
            log.info("Using count line from env: %s", count_line)
        except Exception as e:
            log.warning("Failed to parse COUNT_LINE env: %s, using default", e)
            count_line = None
    else:
        count_line = None
    
    service = StreamManagerService(count_line=count_line)
    
    # Handle signals
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        log.info("Received shutdown signal")
        asyncio.create_task(service.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await service.start()
    except Exception as e:
        log.error(f"Stream manager error: {e}", exc_info=True)
        await service.stop()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())