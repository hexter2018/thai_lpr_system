#!/usr/bin/env python3
"""
Stream Manager Service
Runs RTSP capture and MJPEG server for all cameras
"""
import asyncio
import logging
import signal
import sys
from typing import Dict

from app.stream.rtsp_manager import RTSPManager
from app.stream.mjpeg_server import MJPEGServer
from app.db.session import AsyncSessionLocal
from app.db.models import Camera
from sqlalchemy import select

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

class StreamManagerService:
    """Manages all camera streams and MJPEG server"""
    
    def __init__(self):
        self.rtsp_managers: Dict[str, RTSPManager] = {}
        self.mjpeg_server: MJPEGServer = None
        self.running = False
    
    async def load_cameras(self):
        """Load active cameras from database"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Camera).where(Camera.status == 'active')
            )
            cameras = result.scalars().all()
        
        return cameras
    
    async def start_camera_stream(self, camera):
        """Start RTSP capture for a camera"""
        try:
            manager = RTSPManager(
                camera_id=camera.camera_id,
                rtsp_url=camera.rtsp_url,
                fps_target=camera.fps_target,
                codec=camera.codec,
                zone_polygon=camera.zone_polygon if camera.zone_enabled else None
            )
            
            # Start capture in background
            asyncio.create_task(manager.start_capture())
            
            self.rtsp_managers[camera.camera_id] = manager
            
            log.info(f"Started stream for camera: {camera.camera_id}")
            
        except Exception as e:
            log.error(f"Failed to start stream for {camera.camera_id}: {e}")
    
    async def start(self):
        """Start stream manager service"""
        log.info("Starting Stream Manager Service...")
        
        self.running = True
        
        # Load cameras
        cameras = await self.load_cameras()
        log.info(f"Loaded {len(cameras)} active cameras")
        
        # Start MJPEG server
        self.mjpeg_server = MJPEGServer(port=8090)
        asyncio.create_task(self.mjpeg_server.start())
        
        # Start camera streams
        for camera in cameras:
            await self.start_camera_stream(camera)
        
        # Monitor and reload cameras periodically
        while self.running:
            await asyncio.sleep(60)  # Check every minute
            
            # Reload cameras (handle added/removed)
            cameras = await self.load_cameras()
            active_ids = {c.camera_id for c in cameras}
            
            # Stop removed cameras
            for camera_id in list(self.rtsp_managers.keys()):
                if camera_id not in active_ids:
                    log.info(f"Stopping removed camera: {camera_id}")
                    await self.rtsp_managers[camera_id].stop()
                    del self.rtsp_managers[camera_id]
            
            # Start new cameras
            for camera in cameras:
                if camera.camera_id not in self.rtsp_managers:
                    log.info(f"Starting new camera: {camera.camera_id}")
                    await self.start_camera_stream(camera)
    
    async def stop(self):
        """Stop stream manager service"""
        log.info("Stopping Stream Manager Service...")
        
        self.running = False
        
        # Stop all camera streams
        for manager in self.rtsp_managers.values():
            await manager.stop()
        
        # Stop MJPEG server
        if self.mjpeg_server:
            await self.mjpeg_server.stop()
        
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
