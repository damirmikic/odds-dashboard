"""Application log: events of the running server (upstream failures, drop stream, snapshots, bugs), not prices.

Modules log to `xtip.*` loggers. Nothing is written until main() calls setup(), so importing a module (tests) never
touches data/logs. Log state changes (failed, recovered), not every refresh, and never the API key.
"""
from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler

MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 4  # app.log plus four rotated files: 25 MB at most

logger = logging.getLogger("xtip")
logger.addHandler(logging.NullHandler())  # unconfigured (tests): stay silent instead of logging's stderr fallback


def log_thread_crash(args):
    """A background thread that dies stops its work silently (no drops, no closing lines), so record it."""
    name = args.thread.name if args.thread else "?"
    logger.critical("Nit %s je pala", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def setup(directory):
    """Log to the console (journald on the server) and to <directory>/app.log; returns the file's path, None when it
    cannot be opened: a read-only disk must not stop the dashboard."""
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    threading.excepthook = log_thread_crash
    path = os.path.join(directory, "app.log")
    try:
        os.makedirs(directory, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    except OSError as exc:
        logger.warning("Log fajl nije dostupan, logujem samo u konzolu: %s", exc)
        return None
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return path
