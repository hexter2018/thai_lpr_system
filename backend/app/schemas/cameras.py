from pydantic import BaseModel

class CameraBase(BaseModel):
    camera_id: str
    name: str
    rtsp_url: str
    enabled: bool = True

class CameraOut(CameraBase):
    id: int

class CameraUpsertIn(CameraBase):
    pass
