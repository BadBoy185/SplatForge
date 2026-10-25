"""Optional desktop entrypoint; never loaded by base CLI startup."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def main() -> int:
    try:
        from PySide6.QtCore import QStandardPaths
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        print('Install the GUI extra: python -m pip install "splatforge[gui]"', file=sys.stderr)
        return 1
    from splatforge_gui.qml_app import create_engine
    from splatforge_gui.qml_bridge import DesktopViewModel

    app = QGuiApplication(sys.argv)
    app.setOrganizationName("SplatForge")
    app.setApplicationName("Desktop")
    directory = Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    )
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "desktop.log", maxBytes=1024**2, backupCount=3, encoding="utf-8"
    )
    logger = logging.getLogger("splatforge_gui")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    view_model = DesktopViewModel()
    view_model.controller.error.connect(lambda error: logger.error(error.traceback[:65536]))
    try:
        engine = create_engine(view_model)
    except RuntimeError:
        logger.exception("Desktop presentation could not load")
        return 1
    engine.warnings.connect(lambda errors: logger.warning("\n".join(map(str, errors))))
    result = app.exec()
    logger.removeHandler(handler)
    handler.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
