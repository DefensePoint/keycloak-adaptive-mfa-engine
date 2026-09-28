import logging
import os

from concurrent_log_handler import ConcurrentRotatingFileHandler

from src.core.config.environment import LOG_LEVEL, LOG_DIR


_LOG_FORMAT = "[%(asctime)s][%(levelname)s][PID %(process)d]::%(message)s"
_DATE_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def _resolve_level(value) -> int:
    """Accept a numeric level ("20"/20) or a name ("INFO"); default INFO."""
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return getattr(logging, text.upper(), logging.INFO)


def setup_logging():
    """Configure application logging.

    Logs to stdout/stderr by default (the container captures it via `docker
    logs`). File logging is opt-in: set LOG_DIR to a writable directory to also
    write a rotating log file there. Level is controlled by LOG_LEVEL
    (name or number), defaulting to INFO.
    """
    level = _resolve_level(LOG_LEVEL)

    logger = logging.getLogger()
    logger.setLevel(level)
    logger.handlers = []

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # Optional rotating file handler. Only enabled when LOG_DIR is set, and
    # guarded so a file-logging problem can never crash the app or flood the
    # console with a per-record traceback (the previous behaviour when the log
    # directory did not exist -> FileNotFoundError on every emit()).
    if LOG_DIR:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            file_handler = ConcurrentRotatingFileHandler(
                os.path.join(LOG_DIR, "adaptive-auth.log"),
                mode="a",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning(
                "File logging disabled; could not use LOG_DIR=%s: %s", LOG_DIR, exc
            )

    logging.info(
        "Logging is configured (level=%s, file=%s).",
        logging.getLevelName(level),
        bool(LOG_DIR),
    )
