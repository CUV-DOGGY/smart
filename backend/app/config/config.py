from pydantic import Field
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

    # JWT 配置
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "smart-customer-service"
    JWT_AUDIENCE: str = "smart-customer-service-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )


settings = Settings()
