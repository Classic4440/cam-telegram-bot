"""Logging configuration with secret redaction.

python-telegram-bot talks to Telegram through httpx, and httpx logs every request URL at INFO level.
Telegram bot URLs embed the bot token (``/bot<id>:<secret>/getUpdates``), so naive INFO logging leaks
the token into hosted log streams.  We both demote those loggers and redact token-shaped strings.
"""
from __future__ import annotations

import logging
import re

_TOKEN_RE = re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}")
_KEY_RE = re.compile(r"(?i)\b(gsk_|sk-|sb_secret_|eyJ)[A-Za-z0-9._\-]{16,}")


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging crash the app
            return True
        redacted = _TOKEN_RE.sub("bot<redacted>", message)
        redacted = _BEARER_RE.sub(r"\1<redacted>", redacted)
        redacted = _KEY_RE.sub(r"\1<redacted>", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
        force=True,
    )
    redactor = RedactingFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(redactor)
    # httpx/httpcore are chatty and include request URLs (which contain the bot token).
    for noisy in ("httpx", "httpcore", "hpack", "apscheduler.scheduler", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("waitress").setLevel(logging.WARNING)
