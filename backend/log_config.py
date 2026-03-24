"""Logging configuration for the arbitrage bot.

Sets up a rotating file handler (JSON structured) and a console handler.
"""
import logging
import logging.handlers
import json
import os
import datetime
from config import LOG_DIR, LOG_FILE, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "scan_id"):
            log_entry["scan_id"] = record.scan_id
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging():
    """Configure root logger with file + console handlers.

    Idempotent — skips handler setup if already configured.
    """
    root = logging.getLogger()

    # Guard: don't add duplicate handlers on repeated calls
    if root.handlers:
        return root

    os.makedirs(LOG_DIR, exist_ok=True)
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Rotating file handler (JSON)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, LOG_FILE),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
    )
    file_handler.setFormatter(JSONFormatter())
    root.addHandler(file_handler)

    # Console handler (human-readable)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                          datefmt="%H:%M:%S")
    )
    root.addHandler(console_handler)

    return root
