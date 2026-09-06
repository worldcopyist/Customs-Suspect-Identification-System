"""Structured, rotating application logs without recording secrets or bodies."""
import logging
from logging.handlers import RotatingFileHandler

from app.core.config import get_settings


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("customs_training")
    if logger.handlers:
        return logger
    settings = get_settings()
    settings.logs_root.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler = RotatingFileHandler(settings.logs_root / "application.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
