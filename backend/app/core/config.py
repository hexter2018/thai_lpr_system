import json
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://alpr:alpr@localhost:5432/alpr"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./storage"
    cors_origins: str  = (
            "http://localhost:5173",
            "http://10.32.70.136",
            "http://10.32.70.136:5173"
    )

    @property
    def cors_origins_list(self):
        if not self.cors_origins:
            return []
        origins = self.cors_origins.strip()
        if origins.startswith("["):
            try:
                parsed = json.loads(origins)
            except json.JSONDecodeError:
                parsed = origins
        else:
            if isinstance(origins, list):
                return [str(item).strip() for item in origins if str(item).strip()]
        return [x.strip() for x in origins.split(",") if x.strip()]

    class Config:
        env_prefix = ""
        case_sensitive = False

settings = Settings()
