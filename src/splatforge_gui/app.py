"""Optional desktop entrypoint; never loaded by base CLI startup."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def main() -> int:
    try:
        from PySide6.QtCore import QStandardPaths
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print('Install the GUI extra: python -m pip install "splatforge[gui]"', file=sys.stderr)
        return 1
    from splatforge_gui.widgets.window import MainWindow

    app = QApplication(sys.argv)
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
    window = MainWindow()
    window.controller.error.connect(lambda error: logger.error(error.traceback[:65536]))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
