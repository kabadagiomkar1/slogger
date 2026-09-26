import dataclasses
import datetime
import decimal
import enum
import json
import logging
import pathlib
import uuid

# Name of the LogRecord attribute under which slogger stores user-supplied
# context. Keeping it in a single namespaced attribute means user keys can
# never collide with LogRecord's own attributes (``name``, ``module``, ...).
CONTEXT_ATTR = "slog_context"

# Attributes present on every LogRecord, derived from the running interpreter
# so new attributes (e.g. ``taskName`` in 3.12) are excluded automatically.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


def _json_default(obj):
    """Fallback serializer so a log call never fails because of its payload."""
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (decimal.Decimal, uuid.UUID, pathlib.PurePath)):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, BaseException):
        return repr(obj)
    return repr(obj)


class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[1;36m",  # Bold Cyan
        "INFO": "\033[1;32m",   # Bold Green
        "WARNING": "\033[1;33m",  # Bold Yellow
        "ERROR": "\033[1;31m",  # Bold Red
        "CRITICAL": "\033[1;31m",  # Bold Red
    }
    RESET = "\033[0m"
    WHITE = "\033[1;37m"  # Bold White

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        level_name = f"{color}{record.levelname}{self.RESET}"
        message = f"{self.WHITE}{record.getMessage()}{self.RESET}"
        out = f"[{level_name}]  {message}"

        if record.exc_info:
            out += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            out += "\n" + self.formatStack(record.stack_info)

        return out


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "line": record.lineno,
            "func": record.funcName,
            "file": record.filename,
        }

        if record.exc_info:
            log_object["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_object["stack"] = self.formatStack(record.stack_info)

        # ``extra`` fields set by third-party/stdlib callers.
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and key != CONTEXT_ATTR
        }
        # Context supplied through slogger (span context + call kwargs).
        context = getattr(record, CONTEXT_ATTR, None) or {}

        for key, value in {**extras, **context}.items():
            # Never let user data clobber the fixed schema keys above.
            if key in log_object:
                key = f"ctx_{key}"
            log_object[key] = value

        return json.dumps(log_object, default=_json_default)
