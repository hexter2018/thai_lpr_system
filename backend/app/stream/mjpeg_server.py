"""
MJPEG Server
Serves MJPEG streams over HTTP for web viewing
"""
import asyncio
import logging
from typing import Dict
from aiohttp import web
import cv2
import numpy as np

log = logging.getLogger(__name__)

class MJPEGServer:
    """HTTP server for MJPEG streams"""
    
    def __init__(self, port: int = 8090):
        self.port = port
        self.app = web.Application()
        self.runner = None
        self.site = None
        
        # Frame buffers for each camera
        self.frames: Dict[str, bytes] = {}
        
        # Setup routes
        self.app.router.add_get('/stream/{camera_id}', self.stream_handler)
        self.app.router.add_get('/health', self.health_handler)
    
    async def stream_handler(self, request: web.Request) -> web.StreamResponse:
        """Stream MJPEG for a camera"""
        camera_id = request.match_info['camera_id']
        
        response = web.StreamResponse(
            status=200,
            headers={
                'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Connection': 'keep-alive',
            },
        )
       
        try:
            await response.prepare(request)
            log.info(f"Client connected to stream: {camera_id}")

            while True:
                if camera_id in self.frames:
                    frame_bytes = self.frames[camera_id]
                    
                    await response.write(
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n'
                        + frame_bytes
                        + b'\r\n'
                    )
                
                await asyncio.sleep(0.033)  # ~30 FPS max
        
        except asyncio.CancelledError:
            log.info(f"Client disconnected from stream: {camera_id}")
        except ConnectionResetError:
            log.info(f"Stream connection reset by client: {camera_id}")
        except Exception as e:
            log.error(f"Stream error for {camera_id}: {e}")
        finally:
            return response
    
    async def health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        return web.json_response({
            'status': 'healthy',
            'active_streams': list(self.frames.keys())
        })
    
    def update_frame(self, camera_id: str, frame: np.ndarray, quality: int = 85):
        """Update frame for a camera"""
        try:
            # Encode as JPEG
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            _, buffer = cv2.imencode('.jpg', frame, encode_param)
            
            self.frames[camera_id] = buffer.tobytes()
        
        except Exception as e:
            log.error(f"Failed to encode frame for {camera_id}: {e}")
    
    async def start(self):
        """Start MJPEG server"""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await self.site.start()
        
        log.info(f"MJPEG server started on port {self.port}")
    
    async def stop(self):
        """Stop MJPEG server"""
        if self.site:
            await self.site.stop()
        
        if self.runner:
            await self.runner.cleanup()
        
        log.info("MJPEG server stopped")
