"""Best-effort, private machine-local performance history, separate schema v1."""

from __future__ import annotations

import ctypes
import hashlib
import math
import os
import platform
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from pydantic import ValidationError

from splatforge.application.eta import quantile
from splatforge.core.progress import (
    ExecutionHardwareProfile,
    HistoryRead,
    PerformanceSample,
    PerformanceSignature,
    PerformanceStatistics,
    SignatureStatistics,
)

PERFORMANCE_SCHEMA_VERSION = 1
SAMPLES_PER_SIGNATURE = 64
MAX_SAMPLES = 4096


def signature_key(signature: PerformanceSignature) -> str:
    return hashlib.sha256(signature.model_dump_json().encode("utf-8")).hexdigest()


def default_performance_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".local" / "share") / (
        "SplatForge/performance.sqlite"
    )


class SystemProgressClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utcnow(self) -> datetime:
        return datetime.now(UTC)


class LocalHardwareObserver:
    """Only CPU classification needed by M3/M4/M6; no GPU/native capability probe."""

    def observe(self) -> ExecutionHardwareProfile:
        family = platform.system().lower()
        architecture = platform.machine().lower()
        architecture = (
            architecture if architecture in {"amd64", "x86_64", "arm64", "aarch64"} else ("unknown")
        )
        ram_bucket = None
        if os.name == "nt":
            import winreg

            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
                ) as key:
                    model, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                architecture = re.sub(r"[^a-zA-Z0-9_.-]+", "_", model.strip())[:128]
            except OSError:
                pass

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong)
                    for name in (
                        "total_physical",
                        "available_physical",
                        "total_page",
                        "available_page",
                        "total_virtual",
                        "available_virtual",
                        "available_extended",
                    )
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                gib = max(1, math.ceil(status.total_physical / 1024**3))
                ram_bucket = 2 ** math.ceil(math.log2(gib))
        return ExecutionHardwareProfile(
            platform_family=family if family in {"windows", "linux", "darwin"} else "unknown",
            cpu_family=architecture,
            logical_cpus=os.cpu_count(),
            ram_gib_bucket=ram_bucket,
            device="cpu",
        )


class _UnsupportedHistory(ValueError):
    pass


class LocalPerformanceHistory:
    def __init__(
        self,
        path: Path,
        *,
        per_signature: int = SAMPLES_PER_SIGNATURE,
        max_samples: int = MAX_SAMPLES,
    ) -> None:
        if not 1 <= per_signature <= SAMPLES_PER_SIGNATURE or not 1 <= max_samples <= MAX_SAMPLES:
            raise ValueError("History retention must fit the v1 bounds")
        self.path = path
        self._per_signature = per_signature
        self._max_samples = max_samples

    @contextmanager
    def _connect(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # Existing/newer databases are never replaced or silently reset.
        connection = sqlite3.connect(
            f"{self.path.absolute().as_uri()}?mode={'rwc' if create else 'ro'}",
            uri=True,
            timeout=0.05,
        )
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and create:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                if tables:
                    raise _UnsupportedHistory()
                with connection:
                    connection.execute(
                        "CREATE TABLE samples (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "signature_key TEXT NOT NULL, recorded_at TEXT NOT NULL, "
                        "sample_json TEXT NOT NULL)"
                    )
                    connection.execute(
                        "CREATE INDEX sample_signature ON samples(signature_key, sequence)"
                    )
                    connection.execute("PRAGMA user_version=1")
                version = 1
            if version != PERFORMANCE_SCHEMA_VERSION:
                raise _UnsupportedHistory()
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _warning(exc: Exception) -> str:
        # Exception strings may contain paths/usernames; never retain them here.
        return (
            "history.unsupported_schema"
            if isinstance(exc, _UnsupportedHistory)
            else ("history.unavailable")
        )

    def read(self, signature: PerformanceSignature) -> HistoryRead:
        if not self.path.exists():
            return HistoryRead()
        samples = []
        warnings = []
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT sample_json FROM samples WHERE signature_key=? "
                    "ORDER BY sequence DESC LIMIT ?",
                    (signature_key(signature), self._per_signature),
                )
                for (payload,) in rows:
                    try:
                        if len(payload) > 16384:
                            raise ValueError("Oversized sample")
                        sample = PerformanceSample.model_validate_json(payload)
                        if sample.signature != signature:
                            raise ValueError("Mismatched indexed signature")
                        samples.append(sample)
                    except (ValidationError, ValueError, TypeError):
                        warnings.append("history.malformed_row")
        except (OSError, sqlite3.Error, ValueError) as exc:
            warnings.append(self._warning(exc))
        return HistoryRead(samples=tuple(samples), warnings=tuple(sorted(set(warnings))))

    def record(self, sample: PerformanceSample) -> tuple[str, ...]:
        try:
            sample = PerformanceSample.model_validate_json(sample.model_dump_json())
            with self._connect(create=True) as connection, connection:
                key = signature_key(sample.signature)
                connection.execute(
                    "INSERT INTO samples(signature_key, recorded_at, sample_json) VALUES (?,?,?)",
                    (key, sample.recorded_at.isoformat(), sample.model_dump_json()),
                )
                connection.execute(
                    "DELETE FROM samples WHERE signature_key=? AND sequence NOT IN "
                    "(SELECT sequence FROM samples WHERE signature_key=? "
                    "ORDER BY recorded_at DESC, sequence DESC LIMIT ?)",
                    (key, key, self._per_signature),
                )
                connection.execute(
                    "DELETE FROM samples WHERE sequence NOT IN (SELECT sequence FROM samples "
                    "ORDER BY recorded_at DESC, sequence DESC LIMIT ?)",
                    (self._max_samples,),
                )
        except (OSError, sqlite3.Error, ValueError) as exc:
            return (self._warning(exc),)
        return ()

    def statistics(self) -> PerformanceStatistics:
        if not self.path.exists():
            return PerformanceStatistics()
        grouped: dict[str, list[float]] = {}
        signatures: dict[str, PerformanceSignature] = {}
        warnings = []
        count = 0
        try:
            with self._connect() as connection:
                for key, payload in connection.execute(
                    "SELECT signature_key, sample_json FROM samples ORDER BY sequence DESC LIMIT ?",
                    (self._max_samples,),
                ):
                    try:
                        if len(payload) > 16384:
                            raise ValueError("Oversized sample")
                        sample = PerformanceSample.model_validate_json(payload)
                        if signature_key(sample.signature) != key:
                            raise ValueError("Mismatched indexed signature")
                        count += 1
                        grouped.setdefault(key, []).append(sample.throughput)
                        signatures[key] = sample.signature
                    except (ValueError, TypeError):
                        warnings.append("history.malformed_row")
        except (OSError, sqlite3.Error, ValueError) as exc:
            warnings.append(self._warning(exc))
        return PerformanceStatistics(
            sample_count=count,
            signatures=tuple(
                SignatureStatistics(
                    signature_key=key,
                    signature=signatures[key],
                    count=len(rates),
                    median_throughput=median(rates),
                    lower_throughput=quantile(rates, 0.1),
                    upper_throughput=quantile(rates, 0.9),
                )
                for key, rates in sorted(grouped.items())[:256]
            ),
            warnings=tuple(sorted(set(warnings))),
        )

    def reset(self) -> tuple[str, ...]:
        if not self.path.exists():
            return ()
        try:
            with self._connect() as connection:
                # Reopen writable only after checking the independent schema.
                pass
            with self._connect(create=True) as connection, connection:
                connection.execute("DELETE FROM samples")
        except (OSError, sqlite3.Error, ValueError) as exc:
            return (self._warning(exc),)
        return ()
