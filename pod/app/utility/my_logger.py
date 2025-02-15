from logging import INFO, getLogger
from logging.handlers import RotatingFileHandler

from pythonjsonlogger import json as pjl

from app.settings.my_config import get_settings

my_logger = getLogger(name=__name__)

jsonFileHandler = RotatingFileHandler(filename=f"{get_settings().BASE_DIR}/logs.json", backupCount=5, maxBytes=10 * 1024 * 1024)
fmt = pjl.JsonFormatter("%(name)s %(asctime)s %(levelname)s %(filename)s %(lineno)s %(process)d %(message)s", datefmt="%Y-%m-%d %H:%M:%S", rename_fields={"levelname": "severity", "asctime": "timestamp"})
jsonFileHandler.setFormatter(fmt)

my_logger.addHandler(hdlr=jsonFileHandler)
my_logger.setLevel(level=INFO)
