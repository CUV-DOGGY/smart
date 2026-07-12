import os
from pydantic_setings import  BaseSetting,SettingsConfigDict
class Settings(BaseSetting):
    MODEL_NAME:str
    DEEPSEEK_API_KEY:str
    DEEPSEEK_BASE_URL:str
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
        )
settings = Settings()