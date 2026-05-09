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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
