"""Bounded tolerant parser for observed COLMAP 4.2.1 per-image extraction logs."""

import re
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from splatforge.application.features_contracts import FeatureProgress, FeatureResourceError


class FeatureProgressReader:
    def __init__(
        self,
        path: Path,
        view_ids: frozenset[UUID],
        variant: str,
        max_features: int,
        sink: Callable[[FeatureProgress], None],
    ) -> None:
        self.path, self.views, self.variant = path, view_ids, variant
        self.limit, self.sink = max_features, sink
        self.offset = 0
        self.pending = b""
        self.current = None
        self.name = None
        self.completed: set[UUID] = set()
        self.features = 0

    def poll(self) -> None:
        if not self.path.exists():
            return
        if self.path.is_symlink() or self.path.is_junction():
            raise FeatureResourceError("Redirected feature progress log")
        path = self.path
        if path.is_dir():
            entries = []
            for index, item in enumerate(path.iterdir()):
                if index >= 8 or item.is_symlink() or item.is_junction() or not item.is_file():
                    raise FeatureResourceError("Unbounded or redirected native log directory")
                entries.append(item)
            if sum(item.stat().st_size for item in entries) > 32 * 1024 * 1024:
                raise FeatureResourceError("Feature progress logs exceeded their byte bound")
            info = [item for item in entries if ".log.INFO." in item.name]
            if len(info) != 1:
                return
            path = info[0]
        size = path.stat().st_size
        if size > 32 * 1024 * 1024 or size < self.offset:
            raise FeatureResourceError("Feature progress log exceeded its bounded capture")
        try:
            with path.open("rb") as stream:
                stream.seek(self.offset)
                data = stream.read(64 * 1024)
        except OSError:
            return  # Optional live evidence cannot determine numerical success.
        self.offset += len(data)
        lines = (self.pending + data).split(b"\n")
        self.pending = lines.pop()[-4096:]
        for raw in lines:
            if len(raw) <= 4096:
                self.line(raw.decode("utf-8", errors="replace"))

    def line(self, line: str) -> None:
        processed = re.search(r"\bProcessed file \[(\d{1,6})/(\d{1,6})\]\s*$", line)
        if processed:
            index, total = map(int, processed.groups())
            self.current = index if 1 <= index <= total == len(self.views) else None
            self.name = None
            return
        name = re.search(r"\bName:\s+([0-9a-f-]{36})\.(?:png|jpg)\s*$", line)
        if name and self.current:
            try:
                uid = UUID(name.group(1))
            except ValueError:
                return
            self.name = uid if uid in self.views else None
            return
        features = re.search(r"\bFeatures:\s+(\d{1,6}) \(([A-Z0-9_]+)\)\s*$", line)
        if features and self.current and self.name and self.name not in self.completed:
            count = int(features.group(1))
            if features.group(2) == self.variant and count <= self.limit:
                self.completed.add(self.name)
                self.features += count
                self.sink(FeatureProgress(len(self.completed), self.features))
            self.current, self.name = None, None
