"""Capture real Qt Quick windows for manual review; never starts processing.

Use an existing tiny test project. Images are evidence, not pixel golden tests.
Set QT_SCALE_FACTOR before launching to review a different device pixel ratio.
"""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QSettings, QTimer
from PySide6.QtGui import QGuiApplication

from splatforge.core.progress import (
    PipelineProgressSnapshot,
    ProgressStatus,
    StageProgressSnapshot,
    WorkDescription,
    WorkUnit,
)
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument(
        "--synthetic-progress",
        action="store_true",
        help="Add clearly identified synthetic progress review evidence",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    prefs = Preferences(QSettings(str(args.output / "review.ini"), QSettings.Format.IniFormat))
    prefs.set("recent", [])
    prefs.set("page", 0)
    prefs.set("theme", "Dark")
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.timer.stop()
    engine = create_engine(vm)
    window = engine.rootObjects()[0]
    window.resize(args.width, args.height)
    records = []
    scenarios = [("dark-no-project", "Dark", 0, "Guided")]
    scenarios += [
        ("dark-" + name, "Dark", i, "Guided")
        for i, name in enumerate(
            ("home", "sources", "reconstruct", "dataset", "train", "results", "diagnostics")
        )
    ]
    scenarios += [
        ("dark-reconstruct-advanced", "Dark", 2, "Advanced"),
        ("dark-results-advanced", "Dark", 5, "Advanced"),
    ]
    scenarios += [
        ("light-" + name, "Light", page, "Guided")
        for name, page in (("home", 0), ("reconstruct", 2), ("results", 5))
    ]
    if args.synthetic_progress:
        scenarios += [("dark-active-SYNTHETIC", "Dark", 4, "Guided")]
    index = 0

    def save() -> None:
        nonlocal index
        name = scenarios[index][0]
        if not window.isExposed():
            raise RuntimeError("Review requires an exposed native window")
        path = args.output / (name + ".png")
        if not window.grabWindow().save(str(path)):
            raise RuntimeError("Could not save " + str(path))
        records.append(
            {
                "file": path.name,
                "device_pixel_ratio": window.devicePixelRatio(),
                "width": window.width(),
                "height": window.height(),
                "synthetic_progress": name.endswith("SYNTHETIC"),
            }
        )
        print(path.name, flush=True)
        index += 1
        if index == 1:
            vm.openProject(str(args.project.resolve()))
        QTimer.singleShot(100, advance)

    def advance() -> None:
        if vm.controller.executor.busy or vm._media._gallery.executor.busy:
            QTimer.singleShot(100, advance)
            return
        if index == len(scenarios):
            # The synthetic display has no owned work; release it before window close.
            vm.controller.active = ()
            vm.controller.progress_changed.emit(())
            (args.output / "manifest.json").write_text(
                json.dumps(
                    {
                        "project": str(args.project.resolve()),
                        "captures": records,
                        "qml_warnings": engine.load_errors,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            app.quit()
            return
        name, theme, page, mode = scenarios[index]
        if index and not vm.controller.overview:
            raise RuntimeError("Project did not open: " + str(vm.state["error"]))
        vm.setTheme(theme)
        vm.setMode(mode)
        vm.navigate(page)
        window.findChild(QObject, "pageScroll").property("contentItem").setProperty("contentY", 0)
        if page == 1:
            photo = next((r for r in vm._source.rows if r.values["type"] == "photo"), None)
            if photo:
                vm.media.selectSource(str(photo.identity))
        if page == 4:
            choices = vm.workflow.state["choices"]["dataset"]
            if len(choices) > 1:
                vm.workflow.chooseInput("dataset", choices[1]["value"])
        if page == 5:
            row = next(
                (
                    r
                    for r in vm._outputs.rows
                    if r.values["artifact_type"] == "mapping.reconstruction_set"
                ),
                None,
            )
            if row:
                vm.inspection.inspectArtifact(str(row.identity))
        if name.endswith("SYNTHETIC"):
            work = WorkDescription(
                stage_id="training",
                node_id="training",
                method_id="training.gsplat",
                work_model_id="training.steps_v1",
                unit=WorkUnit.STEPS,
                total=30000,
            )
            stage = StageProgressSnapshot(
                work=work,
                status=ProgressStatus.RUNNING,
                completed=12480,
                fraction=0.416,
                throughput_unit=WorkUnit.STEPS,
            )
            vm.controller.active = (
                PipelineProgressSnapshot(
                    run_id=uuid4(), status="running", elapsed_seconds=258, stages=(stage,)
                ),
            )
            vm.controller.progress_changed.emit(vm.controller.active)
        QTimer.singleShot(600, settle)

    def settle() -> None:
        if vm.controller.executor.busy or vm._media._gallery.executor.busy:
            QTimer.singleShot(100, settle)
        else:
            if scenarios[index][3] == "Advanced":
                flick = window.findChild(QObject, "pageScroll").property("contentItem")
                flick.setProperty(
                    "contentY", min(520, max(0, flick.property("contentHeight") - flick.height()))
                )
            QTimer.singleShot(100, save)

    QTimer.singleShot(600, advance)
    # Bound a failed capture session; no processing is ever owned by this harness.
    QTimer.singleShot(180000, app.quit)
    app.exec()
    vm.controller.active = ()
    return 0 if len(records) == len(scenarios) and not engine.load_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
