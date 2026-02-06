from pydantic import BaseModel, Field, AliasChoices

class RtspStartIn(BaseModel):
    camera_id: str = Field(validation_alias=AliasChoices("camera_id", "cameraId"))
    rtsp_url: str = Field(validation_alias=AliasChoices("rtsp_url", "rtspUrl"))
    fps: float = 2.0
    reconnect_sec: float = 2.0

class RtspStopIn(BaseModel):
    camera_id: str = Field(validation_alias=AliasChoices("camera_id", "cameraId"))
