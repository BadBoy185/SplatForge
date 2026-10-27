"""Bounded local discovery; never hash, probe, copy or publish source files."""

import os
import stat
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from splatforge.application.media_contracts import MediaCancellation, classify_media_path
from splatforge.application.media_scan import MediaScanResult, ScanEntry, ScanLimits, ScanProgress


class LocalMediaScanner:
    def scan(
        self,
        paths: tuple[Path, ...],
        *,
        limits: ScanLimits | None = None,
        cancellation: MediaCancellation | None = None,
        progress: Callable[[ScanProgress], None] | None = None,
    ) -> MediaScanResult:
        limits = limits or ScanLimits()
        entries: list[ScanEntry] = []
        seen: set[str] = set()
        visited: set[tuple[int, int]] = set()
        scanned, directories, stopped = len(paths), 0, ""
        deadline = monotonic() + limits.max_seconds

        def checkpoint() -> bool:
            nonlocal stopped
            if cancellation:
                cancellation.checkpoint()
            if monotonic() >= deadline:
                stopped = "time"
            return not stopped

        def report() -> None:
            if progress:
                progress(ScanProgress(entries=scanned, directories=directories))

        def order(path: Path) -> tuple[str, str]:
            return str(path).casefold(), str(path)

        # Root input size is bounded too, including mixed OS drops.
        if len(paths) > limits.max_entries:
            return MediaScanResult(stopped="entries")
        roots = {Path(os.path.abspath(p)) for p in paths}
        pending = [(p, 0) for p in sorted(roots, key=order, reverse=True)]
        while pending and checkpoint():
            path, depth = pending.pop()
            key = os.path.normcase(str(path))
            if key in seen:
                continue
            seen.add(key)
            try:
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or (
                    getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                ):
                    entries.append(ScanEntry(path=path, reason="Link or reparse point skipped"))
                elif stat.S_ISDIR(info.st_mode):
                    identity = info.st_dev, info.st_ino
                    if identity in visited:
                        continue
                    visited.add(identity)
                    if directories >= limits.max_directories:
                        stopped = "directories"
                        break
                    if depth > limits.max_depth:
                        stopped = "depth"
                        break
                    directories += 1
                    report()
                    children = []
                    with os.scandir(path) as iterator:
                        for child in iterator:
                            if not checkpoint():
                                break
                            if scanned >= limits.max_entries:
                                stopped = "entries"
                                break
                            scanned += 1
                            children.append(Path(child.path))
                            if scanned % 64 == 0:
                                report()
                    if stopped:
                        # Never expose an arbitrary filesystem-order prefix of an
                        # oversized directory. Earlier complete directories survive.
                        break
                    pending.extend(
                        (p, depth + 1) for p in sorted(children, key=order, reverse=True)
                    )
                elif stat.S_ISREG(info.st_mode):
                    media_type = classify_media_path(path)
                    entries.append(ScanEntry(
                        path=path, media_type=media_type,
                        reason="" if media_type else "Unsupported file type",
                    ))
                else:
                    entries.append(ScanEntry(path=path, reason="Not a regular media file"))
            except OSError as exc:
                entries.append(ScanEntry(path=path, reason=f"Could not read: {exc}"))
        if cancellation:
            cancellation.checkpoint()
        report()
        return MediaScanResult(
            entries=tuple(sorted(entries, key=lambda e: order(e.path))),
            scanned=scanned, directories=directories, stopped=stopped,
        )
