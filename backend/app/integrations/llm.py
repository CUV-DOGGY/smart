from langchain_openai import ChatOpenAI

from app.config import settings


def create_llm(*, http_async_client=None) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.MODEL_NAME,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        streaming=True,
        http_async_client=http_async_client,
    )
