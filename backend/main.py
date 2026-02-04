from fastapi import FastAPI
from routers import upload, verify, master_data
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()


app.add_middleware(
CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)


app.include_router(upload.router, prefix="/api/upload")
app.include_router(verify.router, prefix="/api/verify")
app.include_router(master_data.router, prefix="/api/master")


@app.get("/")
def read_root():
return {"status": "Thai ALPR API running"}