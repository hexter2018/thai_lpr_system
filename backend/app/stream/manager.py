#!/usr/bin/env python3
"""
Stream Manager Service
Runs RTSP capture and MJPEG server for all cameras
"""
import asyncio
import logging
import signal
import sys
from typing import Dict, List

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
    """Manages all camera streams and MJPEG server"""
    
    def __init__(self):
        self.rtsp_manager: RTSPManager | None = None
        self.active_camera_ids: set[str] = set()
        self.running = False
    
    async def load_cameras(self):
        """Load active cameras from database"""
        try:
            async with AsyncSessionLocal() as session:
                # Import here to avoid circular imports
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
        """Start all RTSP streams using the unified stream manager."""
        camera_configs: Dict[str, object] = {
            camera.camera_id: camera for camera in cameras if camera.enabled
        }

        self.rtsp_manager = RTSPManager(
            camera_configs=camera_configs,
            redis_client=None,
            db_session_factory=AsyncSessionLocal,
        )
        self.rtsp_manager.start()
        self.active_camera_ids = set(camera_configs.keys())
        log.info("Started streams for cameras: %s", sorted(self.active_camera_ids))

    async def restart_streams(self, cameras: List):
        """Restart stream manager after camera configuration changes."""
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
        
        # Start MJPEG server
        await self.start_streams(cameras)
        
        # Start camera streams
        for camera in cameras:
            await self.start_camera_stream(camera)
        
        # Monitor and reload cameras periodically
        while self.running:
            await asyncio.sleep(5)  # Check every minute
            
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


async def main():
    """Main entry point"""
    service = StreamManagerService()
    
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
