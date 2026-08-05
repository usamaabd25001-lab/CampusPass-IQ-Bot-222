from __future__ import annotations

import os
import time
from dataclasses import dataclass, asdict

import psutil


@dataclass(frozen=True, slots=True)
class RuntimeMetrics:
    process_rss_bytes: int
    process_cpu_percent: float
    system_memory_percent: float
    system_cpu_percent: float
    disk_percent: float
    open_files: int
    threads: int
    uptime_seconds: int

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


class RuntimeMetricsService:
    def __init__(self) -> None:
        self._started = time.monotonic()
        self._process = psutil.Process(os.getpid())
        self._process.cpu_percent(None)

    def snapshot(self) -> RuntimeMetrics:
        try:
            open_files = len(self._process.open_files())
        except (psutil.AccessDenied, OSError):
            open_files = -1
        return RuntimeMetrics(
            process_rss_bytes=int(self._process.memory_info().rss),
            process_cpu_percent=round(float(self._process.cpu_percent(None)), 2),
            system_memory_percent=round(float(psutil.virtual_memory().percent), 2),
            system_cpu_percent=round(float(psutil.cpu_percent(None)), 2),
            disk_percent=round(float(psutil.disk_usage("/").percent), 2),
            open_files=open_files,
            threads=int(self._process.num_threads()),
            uptime_seconds=max(0, int(time.monotonic() - self._started)),
        )
