"""Narrow desktop presentation boundary; all service work uses ProjectController."""

import os
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import Property, QObject, QStringListModel, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

from splatforge_gui.controller import ProjectController
from splatforge_gui.inspection_vm import InspectionViewModel
from splatforge_gui.models import ARTIFACT_COLUMNS, RUN_COLUMNS, SOURCE_COLUMNS
from splatforge_gui.preferences import Preferences
from splatforge_gui.presentation import (
    artifact_name,
    guarded,
    progress_state,
    project_name_error,
    recent_opened_label,
    source_description,
    source_duration,
    source_summary,
    timestamp,
    verification_label,
)
from splatforge_gui.qml_dialogs import ComponentSelectionModel, ExactSettingsModel
from splatforge_gui.qml_media import MediaViewModel, SourceBrowserModel
from splatforge_gui.qml_models import PresentationModel
from splatforge_gui.source_status import SourceSession
from splatforge_gui.workflow_vm import WorkflowViewModel


class DesktopViewModel(QObject):
    changed = Signal()
    dialogRequested = Signal(str)
    closeReady = Signal()

    def __init__(self, controller=None, preferences=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller or ProjectController(self)
        self.preferences = preferences or Preferences()
        self._source_session = SourceSession()
        self._source = SourceBrowserModel(SOURCE_COLUMNS, self)
        self._artifacts = PresentationModel(ARTIFACT_COLUMNS, self)
        self._outputs = PresentationModel(ARTIFACT_COLUMNS, self)
        self._runs = PresentationModel(RUN_COLUMNS, self)
        self._exact = ExactSettingsModel(self)
        self._components = ComponentSelectionModel(self)
        self._page = 0
        self._metrics, self._project, self._error = {}, {}, {}
        self._recents = []
        self._locate_path, self._locate_token = "", ""
        self._recent_candidate = None
        self._pending, self._after_save = None, None
        self._pending_close = False
        self._folder = None
        self._folder_root = None
        self._scan_files = QStringListModel(self)
        self._scan_progress = {"entries": 0, "directories": 0}
        self._scan_summary = self._empty_scan_summary()
        self._source_view = self.preferences.get("source_view_mode", "List")
        if self._source_view not in {"List", "Grid"}:
            self._source_view = "List"
        self._source.set_thumbnails_active(self._source_view == "Grid" and self._page == 1)
        self._notice = ""
        self._participation_pending = None
        self._groups_pending = None
        self._source_summary = source_summary(())
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
        self.controller.busy_changed.connect(self._busy_changed)
        self.controller.dirty_changed.connect(lambda _: self.changed.emit())
        self.controller.error.connect(self._failed)
        self.controller.completed.connect(self._completed)
        self.controller.scan_progress.connect(self._scanning)
        self._source.countChanged.connect(self._source_count_changed)
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
    def scanFiles(self) -> QObject:
        return self._scan_files

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
            "locateRecentPath": self._locate_path,
            "recentCandidate": {
                "name": self._recent_candidate[2].label,
                "path": str(self._recent_candidate[1]),
            } if self._recent_candidate else {},
            "machine": self._machine,
            "error": self._error,
            "notice": self._notice,
            "sourcesSummary": self._source_summary,
            "sourceCheckResult": (
                f"{int(self.controller.verify_progress.observation.completed)} / "
                f"{int(self.controller.verify_progress.observation.work.total)} checked · "
                if self.controller.verify_status == "succeeded" and self.controller.verify_progress
                else ""
            ),
            "folderCount": self._scan_summary["photos"] + self._scan_summary["videos"],
            "folderIgnored": self._scan_summary["ignored"],
            "scan": {
                **self._scan_summary,
                "scanning": self.controller.operation == "folder",
                "progress": self._scan_progress,
            },
            "sourceView": self._source_view,
            "sourceFilter": self._source.participation_filter,
            "sourceSection": self._source.section_filter,
            "sourceSections": self._source.sections,
            "sourceSectionSummary": next((s.get("summary", "") for s in self._source.sections
                                          if s["value"] == self._source.section_filter), ""),
            "logicalGroups": [{"value": "", "label": "Ungrouped"}] + [
                {"value": str(g.group_id), "label": g.label}
                for g in self.controller.overview.document.logical_source_groups.groups
            ] if self.controller.overview else [],
            "groupsSupported": not self.controller.overview
            or self.controller.overview.document.logical_source_groups.schema_version == 1,
            "participationSupported": not self.controller.overview
            or not self.controller.overview.participation
            or self.controller.overview.participation.supported,
            "participationWarnings": [
                diagnostic.message
                for diagnostic in self.controller.overview.participation.diagnostics
            ] if self.controller.overview and self.controller.overview.participation else [],
        }

    @Slot(str)
    def setSourceFilter(self, value: str) -> None:
        if value != self._source.participation_filter:
            self._media.closePreview()
            self.dialogRequested.emit("closeImage")
        self._source.set_filter(value)
        self._media.sources_changed()
        self.changed.emit()

    @Slot(str)
    def setSourceSection(self, value: str) -> None:
        if value != self._source.section_filter:
            self._media.closePreview()
            self.dialogRequested.emit("closeImage")
        self._source.set_section(value)
        self.changed.emit()

    @Slot(str)
    def createSourceGroup(self, label: str) -> None:
        sources = frozenset(UUID(s) for s in self._source.selectedIds)
        self._switch(lambda: self._save_group("create", label=label, sources=sources))

    @Slot(str, str)
    def renameSourceGroup(self, identity: str, label: str) -> None:
        self._switch(lambda: self._save_group("rename", identity=identity, label=label))

    @Slot(str)
    def deleteSourceGroup(self, identity: str) -> None:
        self._switch(lambda: self._save_group("delete", identity=identity))

    @Slot(str, str)
    def assignSourceGroup(self, source: str, identity: str) -> None:
        sources = self._source.action_ids(source)
        self._switch(lambda: self._save_group("assign", identity=identity, sources=sources))

    @Slot(str)
    def assignSelectedGroup(self, identity: str) -> None:
        sources = frozenset(UUID(s) for s in self._source.selectedIds)
        self._switch(lambda: self._save_group("assign", identity=identity, sources=sources))

    @guarded
    def _save_group(self, action: str, *, identity: str = "", label: str = "",
                    sources: frozenset[UUID] = frozenset()) -> None:
        from splatforge.application.logical_source_groups import logical_groups_draft

        overview = self.controller.overview
        if overview is None:
            raise ValueError("Open a project first")
        draft = logical_groups_draft(
            overview.document, (r.identity for r in overview.sources), action=action,
            group_id=UUID(identity) if identity else None, label=label,
            source_ids=sources,
        )
        self._groups_pending = draft.logical_source_groups
        self.controller.edit(draft)
        self.controller.save()

    def _source_count_changed(self) -> None:
        self._source_summary = source_summary(self._source.all_rows)
        self.changed.emit()

    @Slot(str, bool)
    @guarded
    def setSourceIncluded(self, identity: str, included: bool) -> None:
        self._set_participation(self._source.action_ids(identity), included)

    @Slot(bool)
    def setSelectedIncluded(self, included: bool) -> None:
        self._set_participation(frozenset(UUID(s) for s in self._source.selectedIds), included)

    @guarded
    def _set_participation(self, sources: frozenset[UUID], included: bool) -> None:
        self._switch(lambda: self._save_source_participation(sources, included))

    @guarded
    def _save_source_participation(self, source_ids: frozenset[UUID], included: bool) -> None:
        from splatforge.application.source_participation import participation_draft

        overview = self.controller.overview
        if overview is None:
            raise ValueError("Open a project first")
        document = participation_draft(
            overview.document, (r.identity for r in overview.sources),
            source_ids, included=included,
        )
        self._participation_pending = document.source_participation
        self._participation_notice = (
            "Source restored to processing." if included else
            "Source excluded from processing. Original file was not deleted."
        )
        self._notice = ""
        self.controller.edit(document)
        self.controller.save()

    @Slot(str)
    def setSourceView(self, value: str) -> None:
        if value in {"List", "Grid"}:
            self._source_view = value
            self._source.set_thumbnails_active(value == "Grid" and self._page == 1)
            self.preferences.set("source_view_mode", value)
            self.changed.emit()

    @Slot(result=str)
    def lastProjectParent(self) -> str:
        value = str(self.preferences.get("last_project_parent", ""))
        return value if value and Path(value).is_dir() else ""

    @Slot(int, object)
    def _scanning(self, generation: int, value) -> None:
        if generation == self.controller.generation and self.controller.operation == "folder":
            self._scan_progress = value.model_dump()
            self.changed.emit()

    @Slot(int)
    def navigate(self, page: int) -> None:
        if 0 <= page <= 6:
            self._page = page
            self._source.set_thumbnails_active(self._source_view == "Grid" and page == 1)
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

    @Slot(str, str, result="QVariantMap")
    def projectDestination(self, location: str, name: str) -> dict:
        error = project_name_error(name)
        if error:
            return {"path": "", "error": error, "valid": False}
        try:
            if not location.strip():
                raise ValueError("Choose a parent location for your project.")
            parent = self.local_path(location)
            if not parent.is_absolute():
                raise ValueError("Choose an absolute parent location for your project.")
            return {"path": str(parent / name), "error": "", "valid": True}
        except ValueError as exc:
            return {"path": "", "error": str(exc), "valid": False}

    @Slot(str, str)
    @guarded
    def createProject(self, location: str, name: str) -> None:
        destination = self.projectDestination(location, name)
        if not destination["valid"]:
            raise ValueError(destination["error"])
        root = Path(destination["path"])
        self._switch(lambda: self.controller.create(root, name))

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
        else:
            self._media._clear_review_mutation()

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

    @Slot(str)
    def beginLocateRecent(self, path: str) -> None:
        self._locate_path = path
        self.changed.emit()
        self.dialogRequested.emit("locateRecent")

    @Slot(str, str)
    @guarded
    def locateRecent(self, old_path: str, new_path: str) -> None:
        entry = next((e for e in self.preferences.entries() if e["path"] == old_path), None)
        if entry is None:
            return
        token = self._locate_token = uuid4().hex
        target = self.local_path(new_path).absolute()

        def inspect(facade):
            document = facade.service("project").open(target)
            if entry["projectId"] and entry["projectId"] != str(document.project_id):
                raise ValueError(
                    "This is a different SplatForge project. Choose the relocated project."
                )
            return token, entry, target, document

        self.controller.submit("locate_recent", inspect)

    @Slot()
    def confirmRecentLocation(self) -> None:
        if self._recent_candidate:
            entry, target, document = self._recent_candidate
            if entry in self.preferences.entries():
                self.preferences.relocate(
                    entry["path"], str(target), str(document.project_id), document.label,
                )
            self._recent_candidate = None
            self.refresh_recents()

    def refresh_recents(self) -> None:
        if self.controller.operation in {"save", "ingest"}:
            return
        entries = self.preferences.entries()

        def read(facade):
            result = []
            for entry in entries:
                path = entry["path"]
                item = {
                    **entry,
                    "available": False,
                    "summary": "Project not found",
                    "lastOpenedLabel": recent_opened_label(entry["lastOpened"]),
                }
                try:
                    document = facade.service("project").open(Path(path))
                    if entry["projectId"] and entry["projectId"] != str(document.project_id):
                        raise ValueError("A different project is at this location")
                    item.update(
                        name=document.label,
                        projectId=str(document.project_id),
                        available=True,
                        summary="Available",
                    )
                except (OSError, ValueError) as exc:
                    if Path(path).is_dir():
                        item["summary"] = "Project could not be opened"
                    item["details"] = str(exc)
                result.append(item)
            return entries, result

        self.controller.submit("recent_projects", read)

    @Slot("QVariantList")
    @guarded
    def addFiles(self, paths: list) -> None:
        self.controller.ingest(tuple(self.local_path(str(p)) for p in paths))

    @Slot(str)
    @guarded
    def addFolder(self, path: str) -> None:
        self.cancelFolder()
        self._folder_root = self.local_path(path)
        self._scan_progress = {"entries": 0, "directories": 0}
        self.controller.scan_folder(self.local_path(path))

    @Slot()
    def confirmFolder(self) -> None:
        if self._folder and self._folder.supported and self.state["canMutate"]:
            self.controller.ingest(self._folder.supported, folder_root=self._folder_root)
            self.cancelFolder()

    @Slot()
    def cancelFolder(self) -> None:
        self._folder = None
        self._folder_root = None
        self._scan_summary = self._empty_scan_summary()
        self._scan_files.setStringList([])
        self.changed.emit()

    @staticmethod
    def _empty_scan_summary() -> dict:
        return dict(
            photos=0, videos=0, ignored=0, directories=0,
            limited=False, unreadable=False, existing=0,
            groups=[],
        )

    @Slot()
    def verifySources(self) -> None:
        self.controller.verify_sources()

    @Slot("QVariantList")
    @guarded
    def dropUrls(self, urls: list) -> None:
        paths = tuple(self.local_path(str(u)) for u in urls)
        if self.controller.overview and self._page == 1 and paths:
            self.cancelFolder()
            self._scan_progress = {"entries": 0, "directories": 0}
            self.controller.scan_media(paths)
        elif len(paths) == 1 and paths[0].is_dir():
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
        if (self.controller.executor.busy or self._media._gallery.executor.busy
                or self._source.thumbnails.executor.busy):
            QTimer.singleShot(100, self.closeReady.emit)
            return False
        return True

    @Slot()
    def cancelAndClose(self) -> None:
        if self.controller.can_cancel:
            self._pending_close = True
            self.cancel()

    def _overview(self, value) -> None:
        context = (value.document.project_id, self.controller.generation, self.controller.root)
        if self._source_session.enter(context):
            self._source.set_context(context)
            self.dialogRequested.emit("closeSourceDetails")
            self._participation_pending = None
            self._groups_pending = None
        first = not self._project
        self._project = {
            "id": str(value.document.project_id),
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
        self._project_sources(value)
        self._runs.replace(value.index.runs)
        self._artifacts.replace(
            tuple(
                r.model_copy(update={"values": {
                    **r.values, "title": artifact_name(r.values["artifact_type"]),
                    "publishedLabel": timestamp(r.values.get("published_at")),
                }}) for r in value.index.artifacts
            )
        )
        self._finish_overview(value, first)

    def _project_sources(self, value) -> None:
        self._source.group_labels = {
            str(g.group_id): g.label for g in value.document.logical_source_groups.groups
        } if value.document.logical_source_groups.schema_version == 1 else {}
        self._source.replace(
            tuple(
                r.model_copy(
                    update={
                        "values": {
                            **r.values,
                            "verificationLabel": verification_label(r.values["verification"]),
                            **self._source_session.project(r),
                            "description": source_description(r.values),
                            "durationLabel": source_duration(r.values),
                            "lastVerifiedLabel": timestamp(
                                r.values["verification"].split(" · ")[-1]
                            )
                            if len(r.values["verification"].split(" · ")) == 3 else "Not recorded",
                        }
                    }
                )
                for r in value.sources
            )
        )
        if value.participation and not value.participation.supported:
            self._source.set_filter("All")
        if self._participation_pending == value.document.source_participation:
            self._participation_pending = None
            self._notice = self._participation_notice
        if self._groups_pending == value.document.logical_source_groups:
            self._groups_pending = None
            self._notice = "Source groups saved."

    def _finish_overview(self, value, first: bool) -> None:
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

    def _busy_changed(self, busy: bool) -> None:
        if not busy and self._after_save and not self.controller.dirty:
            callback, self._after_save = self._after_save, None
            # Result delivery and worker-finished delivery are distinct queued
            # events. A zero timer from completed alone can run before teardown.
            QTimer.singleShot(0, callback)
        self.changed.emit()

    def _failed(self, error) -> None:
        self._pending_close, self._after_save = False, None
        if error.stage == "save" and self._participation_pending is not None:
            self._participation_pending = None
            self.controller.discard()
        if error.stage == "save" and self._groups_pending is not None:
            self._groups_pending = None
            self.controller.discard()
        if error.stage == "verify" and self.controller.overview:
            self._source_session.uncertain(self._source.all_rows, "Source check could not finish.")
            self._project_sources(self.controller.overview)
        message = error.message
        if error.stage == "create" and message == "Project destination must be missing or empty":
            message = "This destination already contains files. Choose another name or location."
        self._error = {
            "message": message,
            "category": error.category,
            "details": error.traceback,
            "stage": error.stage,
        }
        self.changed.emit()
        self.dialogRequested.emit("error")

    def _completed(self, name: str, value) -> None:
        if name in {"create", "open"}:
            self._error, self._metrics, self._folder = {}, {}, None
            self.cancelFolder()
            self.dialogRequested.emit("closeFolder")
            document = self.controller.overview.document
            self.preferences.remember(
                self.controller.root, project_id=str(document.project_id), name=document.label,
            )
            self.refresh_recents()
            if name == "create":
                self.preferences.set("last_project_parent", str(self.controller.root.parent))
                self.navigate(1)
        elif name == "recent_projects":
            if value[0] == self.preferences.entries():
                self._recents = value[1]
                for entry in value[1]:
                    if entry["available"]:
                        self.preferences.describe(entry["path"], entry["projectId"], entry["name"])
        elif name == "locate_recent":
            token, entry, target, document = value
            if token == self._locate_token and entry in self.preferences.entries():
                self._recent_candidate = entry, target, document
                if entry["projectId"]:
                    self.confirmRecentLocation()
                else:
                    self.dialogRequested.emit("confirmRecentLocation")
        elif name == "ingest":
            self._source_session.imported(value)
        elif name == "verify":
            self._source_session.verified(value)
            self._project_sources(self.controller.overview)
        elif name == "folder":
            self._folder = value
            existing = {
                os.path.normcase(os.path.abspath(self.local_path(r.values["locator"])))
                for r in self._source.all_rows
            }
            self._scan_summary = {
                "photos": sum(e.media_type == "photo" for e in value.entries),
                "videos": sum(e.media_type == "video" for e in value.entries),
                "ignored": value.ignored,
                "directories": value.directories,
                "limited": bool(value.stopped),
                "unreadable": any(e.reason.startswith("Could not read") for e in value.entries),
                "existing": sum(os.path.normcase(str(p)) in existing for p in value.supported),
                "groups": self._folder_group_preview(value.supported),
            }
            self._scan_files.setStringList([
                f"{e.media_type.value.capitalize() if e.media_type else 'Ignored'} · {e.path}"
                + (f"\n{e.reason}" if e.reason else "") for e in value.entries
            ])
            self.dialogRequested.emit("folder")
        elif name == "progress" and not value and self._pending_close:
            self.controller.refresh()
        elif name == "cancelled":
            if self.controller.operation == "verify" and self.controller.overview:
                self._source_session.uncertain(self._source.all_rows, "Source check was cancelled.")
                self._project_sources(self.controller.overview)
            self.cancelFolder()
            self._notice = "Cancelled — application teardown confirmed"
        self.changed.emit()

    def _folder_group_preview(self, paths) -> list[dict]:
        from collections import Counter

        from splatforge.application.logical_source_groups import folder_group_label

        if self._folder_root is None:
            return []
        counts = Counter(folder_group_label(path, self._folder_root) for path in paths)
        return [{"label": label, "count": counts[label]}
                for label in sorted(counts, key=lambda s: (s.casefold(), s)) if label]
