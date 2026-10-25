"""Qt Quick composition and resources for the normal desktop entrypoint."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType, qmlTypeId
from PySide6.QtQuickControls2 import QQuickStyle

from splatforge_gui.point_preview import PointPreview
from splatforge_gui.qml_bridge import DesktopViewModel


def create_engine(view_model: DesktopViewModel) -> QQmlApplicationEngine:
    QQuickStyle.setStyle("Basic")
    if qmlTypeId("SplatForge.Preview", 1, 0, "PointPreview") < 0:
        qmlRegisterType(PointPreview, "SplatForge.Preview", 1, 0, "PointPreview")
    engine = QQmlApplicationEngine()
    engine.load_errors = []
    warnings = engine.load_errors
    engine.warnings.connect(lambda errors: warnings.extend(str(e) for e in errors))
    # Deferred deletion runs while the GUI application and Python bridge still exist.
    QGuiApplication.instance().aboutToQuit.connect(engine.deleteLater)
    engine.addImportPath(str(Path(__file__).parent / "qml"))
    engine.addImageProvider("media", view_model._media.provider)
    engine.setInitialProperties({"vm": view_model})
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        raise RuntimeError("QML startup failed: " + "\n".join(engine.load_errors))
    geometry = view_model.preferences.get("geometry")
    if isinstance(geometry, dict):
        window = engine.rootObjects()[0]
        available = window.screen().availableGeometry()
        width = min(available.width(), max(1024, int(geometry.get("width", 1440))))
        height = min(available.height(), max(640, int(geometry.get("height", 900))))
        window.setGeometry(
            max(available.left(), min(int(geometry.get("x", 0)), available.right() - width + 1)),
            max(available.top(), min(int(geometry.get("y", 0)), available.bottom() - height + 1)),
            width,
            height,
        )
    return engine
