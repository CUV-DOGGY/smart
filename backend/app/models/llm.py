from app.config import settings
from langchain_openai import ChatOpenAI
#创建模型
llm = ChatOpenAI(
    model=settings.MODEL_NAME,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL
)