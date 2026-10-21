"""Owned M3 workspace file operations behind the application boundary."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

from splatforge.adapters.artifact_validation import stream_sha256
from splatforge.application.views_contracts import MaterializedFile
from splatforge.core.views import CandidateViewSet, SelectedViewSet


class LocalViewWorkspace:
    def __init__(self, *, free_bytes: Callable[[Path], int] | None = None) -> None:
        self._free_bytes = free_bytes or (lambda path: shutil.disk_usage(path).free)

    def free_bytes(self, workspace: Path) -> int:
        return self._free_bytes(workspace)

    def prepare_candidate(self, workspace: Path) -> None:
        owned = workspace.resolve()
        (owned / "output" / "images").mkdir(parents=True)
        (owned / "decoded").mkdir()

    def source_output_directory(self, workspace: Path, source_index: int) -> Path:
        if source_index < 0:
            raise ValueError("source index must be non-negative")
        return workspace.resolve() / "decoded" / f"source-{source_index:06d}"

    def publish_candidate_image(
        self, workspace: Path, temporary_path: Path, relative_path: str
    ) -> MaterializedFile:
        owned = workspace.resolve()
        temporary = temporary_path.resolve()
        if not temporary.is_relative_to(owned):
            raise ValueError("Materialized frame escapes its owned workspace")
        if not temporary.is_file() or temporary.is_symlink() or temporary.is_junction():
            raise ValueError("Materialized frame is not a plain workspace file")
        destination = self._safe_relative(owned / "output", relative_path)
        if destination.exists():
            raise ValueError(f"Duplicate deterministic candidate path: {relative_path}")
        temporary.replace(destination)
        size, digest = stream_sha256(destination)
        return MaterializedFile(size=size, sha256=digest)

    def write_candidate_metadata(
        self, workspace: Path, candidate: CandidateViewSet
    ) -> None:
        self._write_json_new(
            workspace.resolve() / "output" / "candidate_views.json",
            candidate.model_dump_json(indent=2),
        )

    def write_selected_metadata(
        self, workspace: Path, selected: SelectedViewSet
    ) -> None:
        output = workspace.resolve() / "output"
        output.mkdir()
        self._write_json_new(
            output / "selected_views.json", selected.model_dump_json(indent=2)
        )

    @staticmethod
    def _safe_relative(root: Path, relative: str) -> Path:
        windows = PureWindowsPath(relative)
        parts = relative.split("/")
        if (
            not relative
            or windows.drive
            or windows.root
            or PurePosixPath(relative).is_absolute()
            or "\\" in relative
            or ":" in relative
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("Workspace path is not a safe relative path")
        candidate = root
        for part in parts:
            candidate /= part
            if candidate.is_symlink() or candidate.is_junction():
                raise ValueError("Workspace path traverses a filesystem redirection")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise ValueError("Workspace path escapes its output directory")
        return resolved

    @staticmethod
    def _write_json_new(path: Path, text: str) -> None:
        payload = text.encode("utf-8") + b"\n"
        with path.open("xb") as stream:
            if stream.write(payload) != len(payload):
                raise OSError(f"Could not write complete metadata file: {path.name}")
            stream.flush()
            os.fsync(stream.fileno())
