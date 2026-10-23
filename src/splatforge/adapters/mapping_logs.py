"""Bounded attempt-owned native log observation; counts never imply a fraction."""

import re
from collections.abc import Callable
from pathlib import Path

from splatforge.application.features_contracts import FeatureResourceError


class MappingLogReader:
    def __init__(self, directory: Path, phase: Callable[[str], None]) -> None:
        self.directory, self.phase = directory, phase
        self.offset = 0
        self.text = ""
        self.last_phase = None
        self.file_identity = None
        self.info_available = False

    def poll(self) -> None:
        self.info_available = False
        if self.directory.is_symlink() or self.directory.is_junction():
            raise FeatureResourceError("mapping.log_resource: redirected log directory")
        entries = []
        for index, path in enumerate(self.directory.iterdir()):
            if (
                index >= 8
                or path.is_symlink()
                or path.is_junction()
                or not path.is_file()
                or path.stat().st_nlink != 1
            ):
                raise FeatureResourceError("mapping.log_resource: unsafe native logs")
            entries.append(path)
        if sum(p.stat().st_size for p in entries) > 32 * 1024**2:
            raise FeatureResourceError("mapping.log_resource: native logs exceed 32 MiB bound")
        info = [p for p in entries if ".log.INFO." in p.name]
        if len(info) > 1:
            raise FeatureResourceError("mapping.log_resource: ambiguous native INFO logs")
        if not info:
            return
        stat = info[0].stat()
        identity = (stat.st_dev, stat.st_ino)
        if (
            self.file_identity is not None
            and self.file_identity != identity
            or stat.st_size < self.offset
        ):
            raise FeatureResourceError("mapping.log_resource: native log replaced or truncated")
        self.file_identity = identity
        self.info_available = True
        with info[0].open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read(32 * 1024**2 + 1)
        self.offset += len(data)
        self.text += data.decode("utf8", errors="replace")
        observed = None
        for marker, name in (
            ("Partitioning scene", "partitioning_scene"),
            ("Reconstructing clusters", "reconstructing_clusters"),
            ("Merging clusters", "merging_clusters"),
        ):
            if marker in self.text:
                observed = name
        if observed and observed != self.last_phase:
            self.phase(observed)
            self.last_phase = observed

    def complete_text(self) -> str:
        self.poll()
        if not self.info_available or not self.text:
            raise ValueError("mapping.native_evidence_unverified: complete native INFO log missing")
        return self.text

    def diagnostics(self) -> dict[str, object]:
        clusters = re.findall(r"Cluster (\d+) with (\d+) images", self.text)
        return {
            "partition_observed": "Partitioning scene" in self.text,
            "leaf_clusters": len({int(i) for i, _ in clusters}),
            "leaf_images": [int(count) for _, count in clusters],
            "reconstructing_clusters_observed": "Reconstructing clusters" in self.text,
            "merge_observed": "Merging clusters" in self.text,
        }
