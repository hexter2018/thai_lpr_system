from fastapi import APIRouter
from app.api.routes import upload, dashboard, reads, master, images, cameras, rtsp, reports

api_router = APIRouter()
api_router.include_router(upload.router, tags=["upload"])
api_router.include_router(dashboard.router, tags=["dashboard"])
api_router.include_router(reads.router, tags=["reads"])
api_router.include_router(master.router, tags=["master"])
api_router.include_router(images.router, tags=["images"])
api_router.include_router(cameras.router, tags=["cameras"])
api_router.include_router(rtsp.router, tags=["rtsp"])
api_router.include_router(reports.router, tags=["reports"])
