"""Read-only result inspection, explicit diagnostics, recovery and scoped cleanup."""

from uuid import UUID

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from splatforge_gui.presentation import guarded, plain, render, timestamp


class InspectionViewModel(QObject):
    changed = Signal()
    previewChanged = Signal()

    def __init__(self, desktop) -> None:
        super().__init__(desktop)
        self.desktop, self.controller = desktop, desktop.controller
        self._preview, self._cleanup = None, None
        self._doctor, self._details, self._message = {}, "", ""
        self._recovery_runs, self._recovery_run = [], ""
        self._project_id = None
        self._doctor_request = None
        self._state_cache = None
        self.changed.connect(self._invalidate_state)
        self.controller.changed.connect(self.overview)
        self.controller.completed.connect(self.completed)
        self.desktop._artifacts.selectionChanged.connect(self.selection_changed)
        desktop._workflow.changed.connect(self.changed)

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        # QML bindings can read this projection many times in a single frame.
        if self._state_cache is not None:
            return self._state_cache
        preview = self._preview
        report = self._doctor.get("colmap_learned_gpu", {})
        colmap = report.get("colmap", {})
        binary = colmap.get("binary", {})
        gpu = report.get("gpu", {})
        learned = [
            m
            for m in report.get("methods", [])
            if any(k in m["method_id"] for k in ("loma", "aliked", "lightglue"))
        ]
        trainer = self.desktop._workflow._capability
        external = self._doctor.get("lichtfeld", {})
        health = [
            {
                "title": "Media",
                "icon": "sources",
                "status": "Not checked",
                "detail": "Actual FFprobe / FFmpeg operations are validated during "
                "ingest and view preparation.",
                "exact": render(self._doctor.get("media", {})),
            },
            {
                "title": "COLMAP",
                "icon": "reconstruct",
                "status": "Detected"
                if binary.get("status") == "available"
                else binary.get("status", "Not checked"),
                "detail": binary.get(
                    "message",
                    "Run Doctor to inspect the installed backend and individual processing routes.",
                ),
                "exact": render(colmap),
            },
            {
                "title": "Learned models",
                "icon": "cube",
                "status": "Routes verified"
                if any(m["runnable"] for m in learned)
                else "Not ready"
                if learned
                else "Not checked",
                "detail": (
                    f"{sum(m['runnable'] for m in learned)} verified routes. "
                    "Exact method compatibility is listed below."
                )
                if learned
                else "Model files and compatible inference routes require positive evidence.",
                "exact": render(learned),
            },
            {
                "title": "GPU",
                "icon": "diagnostics",
                "status": "Detected" if gpu.get("devices") else "Not checked",
                "detail": " · ".join(d["name"] for d in gpu.get("devices", []))
                or "Device presence does not establish CUDA processing or trainer readiness.",
                "exact": render(gpu),
            },
            {
                "title": "Trainer",
                "icon": "train",
                "status": "Ready" if trainer else "Not checked",
                "detail": f"{trainer.gpu_name} · gsplat {trainer.gsplat_version}"
                if trainer
                else "Explicitly probe the configured Python, Torch, CUDA "
                "and gsplat runtime on Train.",
                "exact": render(trainer) if trainer else "Not checked",
            },
            {
                "title": "LichtFeld",
                "icon": "results",
                "status": external.get("status", "Not checked"),
                "detail": str(
                    external.get("version")
                    or "Optional external viewer. Doctor reads identity without launching its GUI."
                ),
                "exact": render(external),
            },
        ]
        selected = self.desktop._artifacts.selected
        self._state_cache = {
            "hasPreview": preview is not None,
            "outputTitle": selected.get("title", "Select an output"),
            "outputStatus": selected.get("storage_status", "No selection"),
            "publishedAt": timestamp(selected.get("published_at")),
            "previewLabel": preview.label if preview else "Select a published output to inspect",
            "pointCount": len(preview.points) if preview else 0,
            "cameraCount": len(preview.cameras) if preview else 0,
            "path": str(preview.directory) if preview else "",
            "payloadBytes": preview.metadata.get("payload_bytes") if preview else None,
            "metadata": render(preview.metadata) if preview else "",
            "details": self._details,
            "message": self._message,
            "health": health,
            "methods": report.get("methods", []),
            "recoveryRuns": self._recovery_runs,
            "recoveryRun": self._recovery_run,
            "cleanup": {**plain(self._cleanup), "digest": self._cleanup.preview_digest}
            if self._cleanup
            else {},
        }
        return self._state_cache

    def _invalidate_state(self) -> None:
        self._state_cache = None

    def selection_changed(self) -> None:
        if self._preview and str(self._preview.artifact_id) != self.desktop._artifacts.selectedId:
            self._preview = None
            self.previewChanged.emit()
        self.changed.emit()

    @Slot(str)
    @guarded
    def inspectArtifact(self, identity: str) -> None:
        self.desktop._artifacts.select(identity)
        if self.desktop._artifacts.selectedId:
            self.controller.inspect_artifact(UUID(identity))
            self.changed.emit()

    @Slot(str)
    @guarded
    def inspectRun(self, identity: str) -> None:
        self.desktop._runs.select(identity)
        if self.desktop._runs.selectedId:
            self.controller.inspect_run(UUID(identity))

    @Slot(str)
    def chooseRecovery(self, identity: str) -> None:
        if identity in {r["value"] for r in self._recovery_runs}:
            self._recovery_run = identity
            self.changed.emit()

    @Slot(str)
    @guarded
    def action(self, name: str) -> None:
        workflow = self.desktop._workflow
        if name in {"doctor", "deepDoctor"}:
            if any(job[0] == "doctor" for job in self.controller.jobs.values()):
                return
            self._doctor = {}
            self._doctor_request = dict(self.desktop._machine)
            self.controller.doctor(
                workflow.tool("colmap"),
                workflow.tool("model_directory"),
                name == "deepDoctor",
                workflow.tool("lichtfeld"),
            )
            self._message = "Inspecting explicit local capabilities…"
        elif name == "recover" and self._recovery_run:
            self.controller.recover_run(UUID(self._recovery_run))
        elif name == "inspectRecovery" and self._recovery_run:
            self.controller.inspect_run(UUID(self._recovery_run))
        elif name == "previewCleanup":
            self._cleanup = None
            self.controller.cleanup()
        elif name in {"pin", "unpin"} and self.desktop._artifacts.selectedId:
            self.controller.pin(UUID(self.desktop._artifacts.selectedId), name == "pin")
        elif name in {"openFolder", "copyPath"} and self._preview:
            if self._preview.directory.is_relative_to(self.controller.root):
                if name == "openFolder":
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._preview.directory)))
                else:
                    self.desktop.copyText(str(self._preview.directory))
        self.changed.emit()

    @Slot(str, bool)
    def applyCleanup(self, digest: str, confirmed: bool) -> None:
        if confirmed and self._cleanup and digest == self._cleanup.preview_digest:
            self.controller.cleanup(self._cleanup)
            self._cleanup = None
            self.changed.emit()

    def overview(self, value) -> None:
        if self._project_id != value.document.project_id:
            self._project_id = value.document.project_id
            self._cleanup, self._preview = None, None
            self._details, self._message, self._recovery_run = "", "", ""
            self.previewChanged.emit()
        self._recovery_runs = [{"label": "Choose a run to inspect / recover", "value": ""}]
        for row in value.index.runs:
            if row.values["status"] in {"running", "interrupted"} or "unresolved" in (
                row.values.get("teardown") or ""
            ):
                self._recovery_runs.append(
                    {
                        "value": str(row.identity),
                        "label": f"{row.values['status'].title()} · "
                        f"{row.values.get('stage', '')} · {row.identity}",
                    }
                )
        if self._recovery_run not in {r["value"] for r in self._recovery_runs}:
            self._recovery_run = ""
        self.changed.emit()

    def completed(self, name: str, value) -> None:
        if name == "inspect" and str(value.artifact_id) == self.desktop._artifacts.selectedId:
            self._preview = value
            self.previewChanged.emit()
        elif name == "doctor":
            if self._doctor_request is not None and self._doctor_request != self.desktop._machine:
                return
            self._doctor = value
            self._message = (
                "Doctor complete. Review individual method evidence; unknown is not ready."
            )
        elif name == "cleanup_preview":
            self._cleanup = value
            self.desktop.dialogRequested.emit("cleanup")
        elif name in {"cleanup_apply", "recovery"}:
            self._details = render(value)
            self._message = "Application result received. Review exact lifecycle evidence."
        elif name == "run_details":
            self._details = value if isinstance(value, str) else render(value)
        self.changed.emit()
