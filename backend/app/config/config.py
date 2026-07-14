import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM 配置
    MODEL_NAME: str
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str

    # MongoDB 配置
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "smart_customer_service"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )


settings = Settings()