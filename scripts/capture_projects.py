"""Native Projects/Create review with real, isolated local project fixtures.

No processing, model probes or user preferences. QT_SCALE_FACTOR selects review DPR.
"""
import argparse
import json
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QEventLoop, QMetaObject, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QGuiApplication

from splatforge.bootstrap import build_project_service
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def pause(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def wait(vm: DesktopViewModel) -> None:
    deadline = time.monotonic() + 30
    while vm.controller.executor.busy:
        pause(20)
        if time.monotonic() > deadline:
            raise RuntimeError("Project read did not finish")
    pause(180)


def visual_item(parent, name: str):
    if parent.objectName() == name:
        return parent
    return next((found for child in parent.childItems()
                 if (found := visual_item(child, name)) is not None), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    fixtures = Path(tempfile.mkdtemp(prefix="SplatForge-projects-review-"))
    prefs = Preferences(QSettings(str(fixtures / "review.ini"), QSettings.Format.IniFormat))
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.timer.stop()
    engine = create_engine(vm)
    window = engine.rootObjects()[0]
    window.setPosition(20, 40)
    window.requestActivate()
    wait(vm)
    records = []

    def capture(name: str) -> None:
        wait(vm)
        if not window.isExposed():
            raise RuntimeError("Native window is not exposed")
        path = args.output / (name + ".png")
        picture = window.grabWindow()
        if not picture.save(str(path)):
            raise RuntimeError(str(path))
        records.append(dict(file=path.name, logical=[window.width(), window.height()],
                            pixels=[picture.width(), picture.height()],
                            dpr=window.devicePixelRatio(), exposed=window.isExposed(),
                            native_title_bar=not bool(window.flags() & Qt.FramelessWindowHint)))
        print(path.name, flush=True)

    for width, height in ((1440, 900), (1024, 640)):
        window.resize(width, height)
        for theme in ("Dark", "Light"):
            vm.setTheme(theme)
            capture(f"{theme}-{width}-first-launch")
    roots = []
    for name in ("Courtyard study", "Lom Plešivec — winter survey",
                 "Apartment scan — a long project name for the east wing and upper floors"):
        path = fixtures / name
        document = build_project_service().create(path, name)
        roots.append((path, document))
    missing = fixtures / "Moved project"
    document = build_project_service().create(missing, "Stone quarry")
    moved = fixtures / "Relocated quarry"
    missing.rename(moved)
    for width, height in ((1440, 900), (1024, 640)):
        window.resize(width, height)
        for theme in ("Dark", "Light"):
            vm.setTheme(theme)
            vm.navigate(0)
            prefix = f"{theme}-{width}"
            if not vm.controller.overview:
                capture(prefix + "-empty")
            prefs.set("recent_entries", "")
            prefs.set("recent", [])
            for path, doc in roots:
                prefs.remember(path, project_id=str(doc.project_id), name=doc.label)
            prefs.remember(missing, project_id=str(document.project_id), name=document.label)
            vm.refresh_recents()
            capture(prefix + "-projects")
            menu_button = visual_item(window.contentItem(), "recentProjectMenu")
            QMetaObject.invokeMethod(menu_button, "clicked")
            capture(prefix + "-actions")
            QMetaObject.invokeMethod(
                menu_button.findChild(QObject, "recentProjectActions"), "close"
            )
            dialog = window.findChild(QObject, "createProjectDialog")
            QMetaObject.invokeMethod(dialog, "open")
            window.findChild(QObject, "projectName").setProperty("text", "New courtyard")
            window.findChild(QObject, "projectLocation").setProperty("text", str(fixtures))
            capture(prefix + "-create")
            window.findChild(QObject, "projectName").setProperty("text", "CON")
            capture(prefix + "-validation")
            window.findChild(QObject, "projectName").setProperty("text", roots[0][0].name)
            vm.createProject(str(fixtures), roots[0][0].name)
            capture(prefix + "-nonempty")
            QMetaObject.invokeMethod(dialog, "close")
            vm.openProject(str(roots[0][0]))
            wait(vm)
            vm.navigate(1)
            capture(prefix + "-materials")
            for page in (2, 4, 5):
                vm.navigate(page)
                capture(prefix + f"-section-{page}")
            vm.navigate(0)
            vm.controller.edit(
                vm.controller.overview.document.model_copy(update={"label": "Draft"})
            )
            capture(prefix + "-session")
            vm.controller.discard()
            # Empty list remains truthful even with a retained session.
            prefs.set("recent_entries", "")
            prefs.set("recent", [])
            vm.refresh_recents()
            capture(prefix + "-empty-session")
    vm.openProject(str(roots[2][0]))
    wait(vm)
    window.resize(1024, 640)
    vm.setTheme("Dark")
    capture("Dark-1024-long-project-name")
    wait(vm)
    result = dict(fixtures=str(fixtures), records=records, qml_warnings=engine.load_errors)
    (args.output / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    window.close()
    wait(vm)
    engine.deleteLater()
    QGuiApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    vm.deleteLater()
    app.processEvents()
    return 1 if result["qml_warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
