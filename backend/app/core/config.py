from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_REMOTE_URI: str = ""
    MONGODB_DB_NAME: str = "corridas_db"
    MONGODB_REMOTE_DB_NAME: str = ""
    MONGODB_COLLECTION: str = "eventos"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8181
    API_DEBUG: bool = False
    API_KEY: str = ""
    SCRAPERS_API_KEY: str = ""

    AWS_BUCKET_NAME: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    BUCKET_JSON_KEY: str = "eventos_real.json"

    model_config = {
        "env_file": Path(__file__).resolve().parents[2] / ".env",
        "extra": "ignore",
    }

    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


settings = Settings()
