"""
Structured logging with emoji prefixes for the snipe bot.
"""
import logging
import sys

_FMT = "%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s"
_DATE = "%H:%M:%S"

_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE))
        logging.root.addHandler(handler)
        logging.root.setLevel(logging.INFO)
        _configured = True

    return logging.getLogger(f"snipe.{name}")
