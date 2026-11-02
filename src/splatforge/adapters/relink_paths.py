"""Conservative local path checks for explicit folder relocation (no discovery)."""

from __future__ import annotations

import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

from splatforge.application.media_contracts import SourceUnavailableError
from splatforge.application.projects import ProjectError


class LocalRelinkPathGuard:
    def normalize_folder(self, path: Path, *, must_exist: bool) -> Path:
        # In particular, never touch the old drive: it may be disconnected entirely.
        self._lexical_parts(path)
        absolute = path.absolute()
        if must_exist:
            self._inspect(absolute, directory=True, root=True)
        return absolute

    def relative_path(self, locator: Path, old_folder: Path) -> str | None:
        self._lexical_parts(locator)
        try:
            relative = locator.absolute().relative_to(old_folder)
        except ValueError:
            return None
        value = relative.as_posix()
        self._relative_parts(value)
        return value

    def candidate(self, new_folder: Path, relative_path: str) -> Path:
        parts = self._relative_parts(relative_path)
        return new_folder.joinpath(*parts)

    def validate_candidate(self, new_folder: Path, candidate: Path) -> None:
        self._lexical_parts(candidate)
        try:
            relative = candidate.relative_to(new_folder)
        except ValueError as exc:
            raise ProjectError("Relink candidate escapes the replacement folder") from exc
        self._relative_parts(relative.as_posix())
        self._inspect(new_folder, directory=True, root=True)
        self._inspect(candidate, directory=False, root=False)

    def validate_relative_paths(self, paths: tuple[str, ...]) -> None:
        # Check directory prefixes too: A/one.png and a/two.png are ambiguous on Windows.
        names: dict[str, str] = {}
        for path in paths:
            parts = self._relative_parts(path)
            for length in range(1, len(parts) + 1):
                prefix = "/".join(parts[:length])
                folded = prefix.casefold()
                if folded in names and names[folded] != prefix:
                    raise ProjectError("Registered relative paths have a Windows case collision")
                names[folded] = prefix

    @staticmethod
    def _lexical_parts(path: Path) -> None:
        if ".." in path.parts:
            raise ProjectError("Relink paths must not contain '..' traversal")
        for part in path.parts[1:] if path.anchor else path.parts:
            if ":" in part or PureWindowsPath(part).is_reserved() or part.endswith((".", " ")):
                raise ProjectError("Relink path contains an ambiguous Windows component")

    @staticmethod
    def _relative_parts(relative: str) -> tuple[str, ...]:
        windows = PureWindowsPath(relative)
        parts = relative.split("/")
        if (
            not relative
            or windows.drive
            or windows.root
            or "\\" in relative
            or PurePosixPath(relative).is_absolute()
            or any(part in ("", ".", "..") for part in parts)
            or any(
                ":" in part or PureWindowsPath(part).is_reserved() or part.endswith((".", " "))
                for part in parts
            )
        ):
            raise ProjectError("Relink relative path is unsafe or ambiguous")
        return tuple(parts)

    @staticmethod
    def _inspect(path: Path, *, directory: bool, root: bool) -> None:
        # lstat, rather than resolve, detects links instead of silently following them.
        for component in (*reversed(path.parents), path):
            try:
                info = component.lstat()
            except OSError as exc:
                if root:
                    raise ProjectError(f"Replacement folder is unavailable: {path}: {exc}") from exc
                raise SourceUnavailableError(
                    f"Relink candidate is unavailable: {path}: {exc}",
                    missing=isinstance(exc, FileNotFoundError),
                ) from exc
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ProjectError(
                    f"Relink path traverses a symlink, junction or reparse point: {component}"
                )
            is_leaf = component == path
            if not is_leaf or directory:
                if not stat.S_ISDIR(info.st_mode):
                    raise ProjectError(f"Relink path is not a directory: {component}")
            elif not stat.S_ISREG(info.st_mode):
                raise SourceUnavailableError(f"Relink candidate is not a regular file: {path}")
