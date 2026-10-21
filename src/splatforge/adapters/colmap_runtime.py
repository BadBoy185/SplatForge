"""Bounded Windows COLMAP layout discovery; never read or execute wrappers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from splatforge.adapters.process_runner import ExecutableNotFoundError
from splatforge.core.capabilities import ColmapRuntimeLayout

_PLUGIN_ROOTS = (
    "plugins",
    "bin/plugins",
    "lib/plugins",
    "lib",
    "bin",
    ".",
    "Qt6/plugins",
    "Qt5/plugins",
    "lib/qt6/plugins",
    "lib/qt5/plugins",
)


def _contained(path: Path, root: Path, *, directory: bool = False) -> bool:
    """Reject redirected candidates, including intermediate junctions/symlinks."""
    try:
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or current.is_junction():
                return False
        return path.is_dir() if directory else path.is_file()
    except (OSError, ValueError):
        return False


def native_from_locator(wrapper: Path) -> Path:
    """The caller has checked the exact Windows COLMAP.bat name."""
    root = wrapper.parent.resolve(strict=True)
    if _contained(root / wrapper.name, root):
        for candidate in (root / "bin" / "colmap.exe", root / "colmap.exe"):
            if _contained(candidate, root):
                return candidate
    raise ExecutableNotFoundError(
        "COLMAP.bat is an installation locator only; expected native "
        "bin/colmap.exe or colmap.exe beside it. Select a complete COLMAP installation."
    )


def discover_runtime_layout(executable: Path) -> ColmapRuntimeLayout | None:
    if os.name != "nt" or executable.name.lower() != "colmap.exe":
        return None
    # A bin directory alone is not portable-installation evidence. The inert official
    # locator must exist at the matching bounded root; its contents are never opened.
    roots = (executable.parent,)
    if executable.parent.name.lower() == "bin":
        roots += (executable.parent.parent,)
    for root in roots:
        if not _contained(root / "COLMAP.bat", root):
            continue
        if executable not in (root / "colmap.exe", root / "bin" / "colmap.exe"):
            continue
        if not _contained(executable, root):
            continue
        entries = tuple(
            str(path)
            for path in (root, root / "bin", root / "lib")
            if _contained(path, root, directory=True)
        )
        platform = next(
            (
                root / candidate / "platforms"
                for candidate in _PLUGIN_ROOTS
                if _contained(root / candidate / "platforms" / "qwindows.dll", root)
            ),
            None,
        )
        return ColmapRuntimeLayout(
            installation_root=str(root),
            native_executable=str(executable),
            path_entries=entries,
            qt_platform_plugin_directory=str(platform) if platform is not None else None,
        )
    return None


def scoped_runtime_environment(
    layout: ColmapRuntimeLayout | None,
    inherited: Mapping[str, str],
) -> dict[str, str]:
    """Create child overrides only, without exposing inherited values as evidence."""
    environment = dict(inherited)
    if layout is None:
        return environment
    # Windows variable names are case-insensitive even for an injected plain mapping.
    path_key = next((key for key in environment if key.upper() == "PATH"), "PATH")
    original = environment.pop(path_key, "")
    environment["PATH"] = os.pathsep.join(layout.path_entries) + (
        os.pathsep + original if original else ""
    )
    if layout.qt_platform_plugin_directory is not None:
        for key in tuple(environment):
            if key.upper() in {"QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"}:
                del environment[key]
        platform = Path(layout.qt_platform_plugin_directory)
        environment["QT_PLUGIN_PATH"] = str(platform.parent)
        environment["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platform)
    return environment
