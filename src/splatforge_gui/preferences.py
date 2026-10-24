"""Allowlisted machine/UI preferences; no numerical project configuration."""

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


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


def apply_theme(app: QApplication, choice: str) -> None:
    if app.property("splatforgeSystemStyle") is None:
        app.setProperty("splatforgeSystemStyle", app.style().objectName())
    scheme = {
        "System": Qt.ColorScheme.Unknown,
        "Light": Qt.ColorScheme.Light,
        "Dark": Qt.ColorScheme.Dark,
    }[choice]
    app.styleHints().setColorScheme(scheme)
    if choice == "System":
        app.setStyle(app.property("splatforgeSystemStyle"))
        app.setPalette(QPalette())
        return
    app.setStyle("Fusion")
    palette = app.style().standardPalette()
    if choice == "Dark":
        for role, color in {
            QPalette.ColorRole.Window: "#292929",
            QPalette.ColorRole.Base: "#202020",
            QPalette.ColorRole.AlternateBase: "#303030",
            QPalette.ColorRole.Button: "#353535",
            QPalette.ColorRole.WindowText: "#eeeeee",
            QPalette.ColorRole.Text: "#eeeeee",
            QPalette.ColorRole.ButtonText: "#eeeeee",
            QPalette.ColorRole.PlaceholderText: "#aaaaaa",
            QPalette.ColorRole.Highlight: "#3d78a8",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.ToolTipBase: "#ffffdc",
            QPalette.ColorRole.ToolTipText: "#111111",
            QPalette.ColorRole.Link: "#61aaf2",
        }.items():
            palette.setColor(role, QColor(color))
        for role in (
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#999999"))
    app.setPalette(palette)
