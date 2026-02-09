from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://alpr:alpr@localhost:5432/alpr"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./storage"
    cors_origins: list[str] = [
            "http://localhost:5173",
            "http://10.32.70.136",
            "http://10.32.70.136:5173"
            ]

    @property
    def cors_origins_list(self):
        if isinstance(self.cors_origins, str):
            return [x.strip() for x in self.cors_origins.split(",") if x.strip()]
        return list(self.cors_origins)

    class Config:
        env_prefix = ""
        case_sensitive = False

settings = Settings()
