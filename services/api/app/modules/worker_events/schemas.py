from __future__ import annotations

from typing import Literal

WorkerEventLevel = Literal[
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
]

WorkerEventCategory = Literal[
    "worker_lifecycle",
    "job_success",
    "job_failure",
    "system_error",
    "healthcheck",
]
