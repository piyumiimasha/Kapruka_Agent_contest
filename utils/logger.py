import logging
import sys
from config.settings import settings


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = "[%(levelname)s] [%(name)s] %(asctime)s — %(message)s"
        handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S"))
        logger.addHandler(handler)

    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.DEBUG))
    logger.propagate = False
    return logger
