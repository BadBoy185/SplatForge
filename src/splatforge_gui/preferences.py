"""Allowlisted machine/UI preferences; no numerical project configuration."""

from pathlib import Path

from PySide6.QtCore import QSettings


class Preferences:
    KEYS = {
        "geometry",
        "theme",
        "recent",
        "page",
        "mode",
        "colmap",
        "trainer_python",
        "lichtfeld",
        "model_directory",
    }

    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings or QSettings("SplatForge", "Desktop")

    def get(self, key: str, default=None):
        if key not in self.KEYS:
            raise KeyError(key)
        return self.settings.value(key, default)

    def set(self, key: str, value) -> None:
        if key not in self.KEYS:
            raise KeyError(key)
        self.settings.setValue(key, value)

    def recent(self) -> list[str]:
        value = self.get("recent", [])
        return ([value] if isinstance(value, str) else list(value or []))[:15]

    def remember(self, root: Path) -> None:
        path = str(root.absolute())
        self.set(
            "recent", [path, *(p for p in self.recent() if p.casefold() != path.casefold())][:15]
        )

    def remove(self, path: str) -> None:
        self.set("recent", [p for p in self.recent() if p != path])
