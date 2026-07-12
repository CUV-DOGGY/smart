from app.core import Logger
import logging
from app.models import llm
logger = logging.getLogger(__name__)

logger.info("运行成功")
logger.info(llm.invoke("你好"))