import logging
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader

ACTION_LOGGER_NAME = "valutatrade.actions"
PARSER_LOGGER_NAME = "valutatrade.parser"


def _configure_logger(name, path, format_key, settings):
    logger = logging.getLogger(name)
    logger.setLevel(settings.get("log_level"))
    logger.propagate = False

    for handler in logger.handlers[:]:
        if isinstance(handler, RotatingFileHandler):
            if handler.baseFilename == str(path.resolve()):
                return
            logger.removeHandler(handler)
            handler.close()

    handler = RotatingFileHandler(
        path,
        maxBytes=settings.get("log_max_bytes"),
        backupCount=settings.get("log_backup_count"),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(settings.get(format_key)))
    logger.addHandler(handler)


def configure_logging():
    settings = SettingsLoader()
    logs_dir = settings.get("logs_dir")
    logs_dir.mkdir(parents=True, exist_ok=True)
    _configure_logger(
        ACTION_LOGGER_NAME, logs_dir / "actions.log", "action_log_format", settings
    )
    _configure_logger(
        PARSER_LOGGER_NAME, logs_dir / "parser.log", "parser_log_format", settings
    )
