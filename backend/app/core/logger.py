import logging
import re


class SensitiveQueryParameterFilter(logging.Filter):
    """隐藏日志 URL 中的高德 Key 和数字签名。"""

    _pattern = re.compile(
        r"([?&](?:key|sig)=)[^&\s\"]+",
        flags=re.IGNORECASE,
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = self._pattern.sub(r"\1***", message)
        record.args = ()
        return True


Handler = logging.StreamHandler()
Handler.setLevel(logging.INFO)
Handler.addFilter(SensitiveQueryParameterFilter())
Formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
Handler.setFormatter(Formatter)
Logger = logging.getLogger()
Logger.setLevel(logging.INFO)
Logger.addHandler(Handler)
