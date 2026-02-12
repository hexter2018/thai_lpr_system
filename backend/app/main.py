from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from app.core.config import settings
from app.api.router import api_router

app = FastAPI(title="Thai ALPR API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


try:
    from app.api.routers.roi_api import router as roi_router
    app.include_router(roi_router)
    import logging
    logging.getLogger(__name__).info("ROI Agent API loaded: /api/roi-agent/*")
except ImportError:
    import logging
    logging.getLogger(__name__).info("ROI Agent API not available (roi_api.py not found)")
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("ROI Agent API failed to load: %s", e)

@app.get("/healthz")
def healthz():
    return {"ok": True}
