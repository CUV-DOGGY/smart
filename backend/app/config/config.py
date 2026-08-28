import ipaddress
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Observability is opt-in until the telemetry pipeline is configured.
    OBSERVABILITY_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = Field(
        default="smartserve-backend",
        min_length=1,
        max_length=255,
    )
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://127.0.0.1:4318"
    OTEL_ENVIRONMENT: str = Field(
        default="development",
        min_length=1,
        max_length=64,
    )
    OTEL_TRACE_SAMPLE_RATIO: float = Field(default=1.0, ge=0.0, le=1.0)
    OTEL_METRIC_EXPORT_INTERVAL: int = Field(
        default=10_000,
        ge=1_000,
        le=300_000,
    )
    BROWSER_TELEMETRY_ENABLED: bool = False
    BROWSER_TELEMETRY_ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    BROWSER_TELEMETRY_RATE_LIMIT_BY_USER: int = Field(
        default=60,
        ge=1,
        le=10_000,
    )
    BROWSER_TELEMETRY_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        ge=1,
        le=3_600,
    )
    BROWSER_TELEMETRY_MAX_REQUEST_BODY_BYTES: int = Field(
        default=1_048_576,
        ge=1_024,
        le=10_485_760,
    )
    BROWSER_TELEMETRY_FORWARD_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        gt=0,
        le=30,
    )

    # LLM 配置
    MODEL_NAME: str
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str

    # MongoDB 配置
    MONGODB_URL: str = "mongodb://localhost:27017/?replicaSet=rs0"
    MONGODB_DB_NAME: str = "smart_customer_service"

    # Redis 配置
    REDIS_URL: str = "redis://127.0.0.1:6380/0"
    REDIS_CONNECT_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0, le=30)
    REDIS_SOCKET_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0, le=30)
    REDIS_HEALTH_CHECK_INTERVAL_SECONDS: int = Field(default=30, ge=0, le=300)

    # Agent execution boundaries
    AGENT_RUN_TIMEOUT_SECONDS: int = Field(default=90, ge=10, le=300)
    AGENT_LOCK_LEASE_SECONDS: int = Field(default=120, ge=30, le=600)
    WRITE_COMMAND_CONFIRMATION_TTL_SECONDS: int = Field(
        default=900,
        ge=60,
        le=86400,
    )
    WRITE_COMMAND_EXECUTION_LEASE_SECONDS: int = Field(
        default=120,
        ge=30,
        le=600,
    )

    # 高德 Web 服务
    AMAP_WEB_SERVICE_KEY: SecretStr
    AMAP_BASE_URL: str = "https://restapi.amap.com"
    AMAP_CONNECT_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0, le=30)
    AMAP_READ_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0, le=30)
    AMAP_MAX_RETRIES: int = Field(default=1, ge=0, le=3)
    AMAP_GEOCODE_CACHE_SECONDS: int = Field(default=86400, ge=60)
    ORDER_GEOCODE_RATE_LIMIT_BY_USER: int = Field(default=30, ge=1)
    ORDER_GEOCODE_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=300,
        ge=1,
    )

    # 认证限流配置
    LOGIN_RATE_LIMIT_GLOBAL: int = Field(default=100, ge=1)
    LOGIN_RATE_LIMIT_BY_IP: int = Field(default=30, ge=1)
    LOGIN_RATE_LIMIT_BY_USERNAME: int = Field(default=10, ge=1)
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=300, ge=1)
    REGISTER_RATE_LIMIT_BY_IP: int = Field(default=10, ge=1)
    REGISTER_RATE_LIMIT_BY_USERNAME: int = Field(default=5, ge=1)
    REGISTER_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=3600, ge=1)
    RATE_LIMIT_KEY_SECRET: str | None = Field(default=None, min_length=32)

    # Argon2 在每个 Python 进程内的资源边界
    PASSWORD_HASH_MAX_CONCURRENCY: int = Field(default=5, ge=1, le=32)
    PASSWORD_HASH_WAIT_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0, le=30)

    # HTTP 与代理配置。只有直连代理在此列表内时才会信任转发头。
    AUTH_MAX_REQUEST_BODY_BYTES: int = Field(default=16 * 1024, ge=1024)
    TRUSTED_PROXY_CIDRS: list[str] = Field(default_factory=list)
    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
    )

    # JWT 配置
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "smart-customer-service"
    JWT_AUDIENCE: str = "smart-customer-service-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)

    @field_validator("TRUSTED_PROXY_CIDRS")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, values: list[str]) -> list[str]:
        for value in values:
            ipaddress.ip_network(value, strict=False)
        return values

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8"
    )


settings = Settings()
