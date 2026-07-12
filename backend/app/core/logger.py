#日志配置
import logging
Handler = logging.StreamHandler()
Handler.setLevel(logging.INFO)
Formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
Handler.setFormatter(Formatter)
Logger = logging.getLogger()
Logger.setLevel(logging.INFO)
Logger.addHandler(Handler)