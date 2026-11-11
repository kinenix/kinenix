"""Log output of the worker's own messages (triggers loaded, started, fired), so journald shows them (#156).

Without a handler, Python prints only warnings and errors of the `kinenix_worker` loggers, so
`journalctl -u kinenix-worker` could not show which triggers started or when each one fired.
"""
import logging
import os

LEVEL_VARIABLE = "KINENIX_WORKER_LOG_LEVEL"
_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"  # the same as kinenix-core's run output


def configure_logging() -> logging.Logger:
    """Send `kinenix_worker` messages to stderr at INFO, or at the level in KINENIX_WORKER_LOG_LEVEL."""
    logger = logging.getLogger("kinenix_worker")
    name = os.environ.get(LEVEL_VARIABLE, "INFO").strip().upper()
    level = logging.getLevelName(name)
    if not isinstance(level, int):
        level = logging.INFO
    logger.setLevel(level)
    if not any(getattr(h, "_kinenix_worker", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._kinenix_worker = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.propagate = False
    if not isinstance(logging.getLevelName(name), int):
        logger.warning(f"{LEVEL_VARIABLE}={name} is not a log level; using INFO.")
    return logger
