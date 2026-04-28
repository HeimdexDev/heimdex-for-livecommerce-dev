"""Lightweight structured-log formatter for the transcode worker.

Problem: stdlib ``logging.basicConfig(format="%(asctime)s %(levelname)s
%(name)s %(message)s")`` drops ``extra={}`` fields entirely. Every
``logger.info("event", extra={"video_id": ..., "elapsed_s": ...})`` in
this worker therefore looks like ``"... event"`` in CloudWatch — no
way to parse per-field values for baselines or dashboards.

Solution: a minimal ``Formatter`` subclass that appends the extras as
space-delimited ``key=<repr-value>`` pairs AFTER the normal message.
CloudWatch Logs Insights and the baseline harvester
(``scripts/capture_scene_detect_baseline.py``) already regex-match on
this shape.

**Scoped to this worker.** If other workers want the same pattern,
lift to ``heimdex-worker-sdk`` — don't copy-paste. For now keep the
blast radius small.
"""

from __future__ import annotations

import logging
from typing import Any


# Attributes the stdlib Formatter machinery sets on every record.
# Anything NOT in this set came from ``extra={}`` and is candidate
# for KV appending. Keeping this as a constant (rather than computing
# per-record) avoids a hot-path dict allocation.
_STANDARD_LOGRECORD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "asctime", "message", "taskName",
    # Library-injected attributes we don't want leaking into the KV tail.
    # `color_message` is set by uvicorn's DefaultFormatter on some access
    # log records; harmless in this worker but defensive for future reuse.
    "color_message",
})


class StructuredExtraFormatter(logging.Formatter):
    """Appends ``logger.info("...", extra={})`` fields as ``k=v`` pairs.

    Output shape:

        2026-04-22 14:22:10 INFO src.tasks.transcode scene_detection_complete
            video_id='abc-123' elapsed_s=4.312 scene_count=17

    Values are ``repr()``-ed so strings are quoted (making the output
    regex-friendly for the harvester's ``video_id['\":=\\s]+['\"]?...``
    patterns) and floats stay as numeric literals.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        # Compose extras view without mutating the record (defensive
        # against handlers later in the chain).
        extras: dict[str, Any] = {
            k: v for k, v in record.__dict__.items()
            if k not in _STANDARD_LOGRECORD_ATTRS and not k.startswith("_")
        }
        if not extras:
            return base
        kv = " ".join(f"{k}={v!r}" for k, v in extras.items())
        return f"{base} {kv}"
