"""Narrow desktop presentation boundary; all service work uses ProjectController."""

from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

from splatforge_gui.controller import ProjectController
from splatforge_gui.inspection_vm import InspectionViewModel
from splatforge_gui.models import ARTIFACT_COLUMNS, RUN_COLUMNS, SOURCE_COLUMNS
from splatforge_gui.preferences import Preferences
from splatforge_gui.presentation import (
    artifact_name,
    guarded,
    progress_state,
    timestamp,
    verification_label,
)
from splatforge_gui.qml_dialogs import ComponentSelectionModel, ExactSettingsModel
from splatforge_gui.qml_media import MediaViewModel
from splatforge_gui.qml_models import PresentationModel
from splatforge_gui.workflow_vm import WorkflowViewModel


class DesktopViewModel(QObject):
    changed = Signal()
    dialogRequested = Signal(str)
    closeReady = Signal()

    def __init__(self, controller=None, preferences=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller or ProjectController(self)
        self.preferences = preferences or Preferences()
        self._source = PresentationModel(SOURCE_COLUMNS, self)
        self._artifacts = PresentationModel(ARTIFACT_COLUMNS, self)
        self._outputs = PresentationModel(ARTIFACT_COLUMNS, self)
        self._runs = PresentationModel(RUN_COLUMNS, self)
        self._exact = ExactSettingsModel(self)
        self._components = ComponentSelectionModel(self)
        self._page = 0
        self._metrics, self._project, self._error = {}, {}, {}
        self._recents = []
        self._pending, self._after_save = None, None
        self._pending_close = False
        self._folder = None
        self._notice = ""
        self._mode = self.preferences.get("mode", "Guided")
        self._theme = self.preferences.get("theme", "System")
        self._machine = {
            k: str(self.preferences.get(k, ""))
            for k in ("colmap", "model_directory", "trainer_python", "lichtfeld")
        }
        self._workflow = WorkflowViewModel(self)
        self._media = MediaViewModel(self)
        self._inspection = InspectionViewModel(self)
        self.controller.changed.connect(self._overview)
        self.controller.progress_changed.connect(lambda _: self.changed.emit())
        self.controller.metrics_changed.connect(self._live_metrics)
        self.controller.busy_changed.connect(lambda _: self.changed.emit())
        self.controller.dirty_changed.connect(lambda _: self.changed.emit())
        self.controller.error.connect(self._failed)
        self.controller.completed.connect(self._completed)
        self.refresh_recents()

    @Property(QObject, constant=True)
    def inspection(self) -> QObject:
        return self._inspection

    @Property(QObject, constant=True)
    def media(self) -> QObject:
        return self._media

    @Property(QObject, constant=True)
    def workflow(self) -> QObject:
        return self._workflow

    @Property(QObject, constant=True)
    def sources(self) -> QObject:
        return self._source

    @Property(QObject, constant=True)
    def artifacts(self) -> QObject:
        return self._artifacts

    @Property(QObject, constant=True)
    def outputs(self) -> QObject:
        return self._outputs

    @Property(QObject, constant=True)
    def runs(self) -> QObject:
        return self._runs

    @Property(QObject, constant=True)
    def exact(self) -> QObject:
        return self._exact

    @Property(QObject, constant=True)
    def components(self) -> QObject:
        return self._components

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        return {
            "page": self._page,
            "mode": self._mode,
            "theme": self._theme,
            "hasProject": self.controller.overview is not None,
            "project": self._project,
            "dirty": self.controller.dirty,
            "busy": self.controller.mutating or bool(self.controller.active),
            "exclusive": self.controller.mutating,
            "unresolved": self.controller.has_unresolved,
            "canMutate": self.controller.overview is not None
            and not (
                self.controller.mutating or self.controller.active or self.controller.has_unresolved
            ),
            "progress": progress_state(self.controller, self._metrics),
            "recents": self._recents,
            "machine": self._machine,
            "error": self._error,
            "notice": self._notice,
            "folderCount": len(self._folder.supported) if self._folder else 0,
            "folderIgnored": self._folder.ignored if self._folder else 0,
        }

    @Slot(int)
    def navigate(self, page: int) -> None:
        if 0 <= page <= 6:
            self._page = page
            if self.controller.overview:
                self.preferences.set("page", page)
            self.changed.emit()

    @Slot(str)
    def setMode(self, mode: str) -> None:
        if mode in {"Guided", "Advanced"}:
            self._mode = mode
            self.preferences.set("mode", mode)
            self.changed.emit()

    @Slot(str)
    def setTheme(self, theme: str) -> None:
        if theme in {"System", "Dark", "Light"}:
            self._theme = theme
            self.preferences.set("theme", theme)
            self.changed.emit()

    @Slot(str, str)
    def setMachine(self, key: str, value: str) -> None:
        if key in self._machine:
            self._machine[key] = value
            self.preferences.set(key, value)
            self._workflow.invalidate_runtime()
            self._inspection._doctor = {}
            self._inspection.changed.emit()
            self.changed.emit()

    @staticmethod
    def local_path(value: str) -> Path:
        url = QUrl(value)
        if url.isLocalFile():
            return Path(url.toLocalFile())
        if "://" in value:
            raise ValueError("Choose a local filesystem path")
        return Path(value)

    @Slot(str, result=str)
    def localPath(self, value: str) -> str:
        return str(self.local_path(value))

    def _switch(self, callback) -> None:
        if self.controller.mutating or self.controller.active:
            raise ValueError("Finish or cancel active work before switching projects")
        if self.controller.dirty:
            self._pending = callback
            self.dialogRequested.emit("unsaved")
        else:
            callback()

    @Slot(str)
    @guarded
    def openProject(self, path: str) -> None:
        root = self.local_path(path)
        self._switch(lambda: self.controller.open(root))

    @Slot(str, str)
    @guarded
    def createProject(self, path: str, label: str) -> None:
        if not path or not label.strip():
            raise ValueError("Choose an empty directory and a project name")
        root = self.local_path(path)
        self._switch(lambda: self.controller.create(root, label.strip()))

    @Slot(str)
    def resolveUnsaved(self, choice: str) -> None:
        callback, self._pending = self._pending, None
        if choice == "save":
            self._after_save = callback
            self.controller.save()
        elif choice == "discard":
            self.controller.discard()
            if callback:
                callback()

    @Slot()
    def save(self) -> None:
        self.controller.save()

    @Slot()
    def refresh(self) -> None:
        self.controller.refresh()

    @Slot()
    def cancel(self) -> None:
        if self.controller.can_cancel:
            self.controller.cancel()
            self.changed.emit()

    @Slot(str)
    def removeRecent(self, path: str) -> None:
        self.preferences.remove(path)
        self.refresh_recents()

    def refresh_recents(self) -> None:
        if self.controller.operation == "save":
            return
        paths = self.preferences.recent()

        def read(facade):
            result = []
            for path in paths:
                item = {
                    "path": path,
                    "name": Path(path).name,
                    "available": False,
                    "summary": "Unavailable",
                }
                try:
                    document = facade.service("project").open(Path(path))
                    index = facade.reader.index(Path(path))
                    latest = next(
                        (r for r in index.artifacts if r.values["storage_status"] != "evicted"),
                        None,
                    )
                    item.update(
                        name=document.label,
                        available=True,
                        summary=(
                            artifact_name(latest.values["artifact_type"]) + " published"
                            if latest
                            else "Ready to add sources"
                        ),
                    )
                except (OSError, ValueError):
                    pass
                result.append(item)
            return paths, result

        self.controller.submit("recent_projects", read)

    @Slot("QVariantList")
    @guarded
    def addFiles(self, paths: list) -> None:
        self.controller.ingest(tuple(self.local_path(str(p)) for p in paths))

    @Slot(str)
    @guarded
    def addFolder(self, path: str) -> None:
        self.controller.scan_folder(self.local_path(path))

    @Slot()
    def confirmFolder(self) -> None:
        if self._folder:
            self.controller.ingest(self._folder.supported)
            self._folder = None

    @Slot()
    def verifySources(self) -> None:
        self.controller.verify_sources()

    @Slot("QVariantList")
    @guarded
    def dropUrls(self, urls: list) -> None:
        paths = tuple(self.local_path(str(u)) for u in urls)
        if len(paths) == 1 and paths[0].is_dir():
            self.openProject(str(paths[0]))
        elif paths and self.controller.overview:
            supported = tuple(
                p for p in paths if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".mp4", ".mov"}
            )
            self._notice = f"Ignored {len(paths) - len(supported)} unsupported entries"
            if supported:
                self.controller.ingest(supported)
            self.changed.emit()

    @Slot(str)
    def copyText(self, value: str) -> None:
        QGuiApplication.clipboard().setText(value)

    @Slot("QVariantMap")
    def rememberGeometry(self, value: dict) -> None:
        # QML persists only UI geometry inside the existing QSettings allowlist.
        self.preferences.set("geometry", {k: int(value[k]) for k in ("x", "y", "width", "height")})

    @Slot(result=bool)
    def requestClose(self) -> bool:
        if self.controller.mutating or self.controller.active:
            self.dialogRequested.emit("activeClose")
            return False
        if self.controller.dirty:
            self._pending = self.closeReady.emit
            self.dialogRequested.emit("unsaved")
            return False
        self.controller.timer.stop()
        if self.controller.executor.busy or self._media._gallery.executor.busy:
            QTimer.singleShot(100, self.closeReady.emit)
            return False
        return True

    @Slot()
    def cancelAndClose(self) -> None:
        if self.controller.can_cancel:
            self._pending_close = True
            self.cancel()

    def _overview(self, value) -> None:
        first = not self._project
        self._project = {
            "name": value.document.label,
            "path": str(self.controller.root),
            "sourceCount": len(value.sources),
            "artifactCount": len(value.index.artifacts),
            "runCount": len(value.index.runs),
            "validation": value.index.validation_status,
            "stateVersion": value.index.state_version,
            "truncated": value.index.truncated,
            "workflow": [
                {"name": w.name, "status": w.status, "detail": w.detail} for w in value.workflow
            ],
        }
        self._source.replace(
            tuple(
                r.model_copy(
                    update={
                        "values": {
                            **r.values,
                            "verificationLabel": verification_label(r.values["verification"]),
                        }
                    }
                )
                for r in value.sources
            )
        )
        self._runs.replace(value.index.runs)
        self._artifacts.replace(
            tuple(
                r.model_copy(
                    update={
                        "values": {
                            **r.values,
                            "title": artifact_name(r.values["artifact_type"]),
                            "publishedLabel": timestamp(r.values.get("published_at")),
                        }
                    }
                )
                for r in value.index.artifacts
            )
        )
        important = {
            "mapping.reconstruction_set",
            "dataset.prepared_set",
            "dataset.prepared_component",
            "training.checkpoint",
            "training.gaussian_scene",
            "training.gaussian_scene_set",
        }
        self._outputs.replace(
            tuple(r for r in self._artifacts.rows if r.values["artifact_type"] in important)
        )
        targets = {
            "sources": (1, "Start with your captures", "Add sources"),
            "views": (2, "Prepare your views", "Review reconstruction"),
            "geometry": (2, "Connect your captures", "Review reconstruction"),
            "reconstruction": (2, "Shape your reconstruction", "Review reconstruction"),
            "validation": (2, "Inspect reconstruction quality", "Review validation"),
            "selection": (2, "Choose your components", "Review selection"),
            "dataset": (3, "Prepare a training dataset", "Open dataset"),
            "training": (4, "Train your Gaussian scene", "Open training"),
            "scene": (4, "Continue to a finished scene", "Open training"),
        }
        next_stage = next((w.name for w in value.workflow if w.status != "completed"), None)
        page, title, action = targets.get(
            next_stage, (5, "Your published work is ready", "View results")
        )
        if self.controller.has_unresolved:
            page, title, action = 6, "Review interrupted work", "Open recovery"
        latest = next(
            (r for r in self._outputs.rows if r.values["storage_status"] != "evicted"), None
        )
        self._project.update(
            nextPage=page,
            nextTitle=title,
            nextAction=action,
            latestTitle=latest.values["title"] if latest else "No published result yet",
            latestId=str(latest.identity) if latest else "",
        )
        self.preferences.remember(self.controller.root)
        self.refresh_recents()
        if first:
            self._page = max(0, min(6, int(self.preferences.get("page", 0))))
        self.changed.emit()
        if self._pending_close and not self.controller.mutating and not value.active:
            self._pending_close = False
            if self.controller.has_unresolved:
                self.navigate(6)
            else:
                QTimer.singleShot(0, self.closeReady.emit)

    def _live_metrics(self, metrics: dict) -> None:
        self._metrics = metrics
        self.changed.emit()

    def _failed(self, error) -> None:
        self._pending_close, self._after_save = False, None
        self._error = {
            "message": error.message,
            "category": error.category,
            "details": error.traceback,
            "stage": error.stage,
        }
        self.changed.emit()
        self.dialogRequested.emit("error")

    def _completed(self, name: str, value) -> None:
        if name == "recent_projects":
            if value[0] == self.preferences.recent():
                self._recents = value[1]
        elif name == "folder":
            self._folder = value
            self.dialogRequested.emit("folder")
        elif name == "save" and self._after_save:
            callback, self._after_save = self._after_save, None
            # Run after the executor clears exclusive mutation ownership.
            QTimer.singleShot(0, callback)
        elif name == "progress" and not value and self._pending_close:
            self.controller.refresh()
        elif name == "cancelled":
            self._notice = "Cancelled — application teardown confirmed"
        self.changed.emit()
