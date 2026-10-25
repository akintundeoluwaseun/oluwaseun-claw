"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,\"']+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|passwd|secret|cookie)\s*[\"']?\s*[:=]\s*[\"']?)[^\s,\"'}]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
]

_extra_secrets: list[str] = []


def register_secret(value: str) -> None:
    """Add a literal value (e.g. the session token) that must never reach a log."""
    if value and len(value) >= 8 and value not in _extra_secrets:
        _extra_secrets.append(value)


def redact(text: str) -> str:
    for secret in _extra_secrets:
        text = text.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry["fields"] = json.loads(redact(json.dumps(fields, default=str)))
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(log_dir: Path, level: str = "INFO") -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "claw.log"
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = JsonFormatter()
    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    # Uvicorn's access log would print every request URL; keep it quiet.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return log_file


def log_event(logger: logging.Logger, msg: str, **fields: object) -> None:
    logger.info(msg, extra={"fields": fields})
