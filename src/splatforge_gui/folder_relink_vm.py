"""Folder relink presentation; identity, path checks and publication live in the application."""

from uuid import uuid4

from PySide6.QtCore import Property, QObject, QStringListModel, QTimer, Signal, Slot


class FolderRelinkViewModel(QObject):
    changed = Signal()

    def __init__(self, desktop) -> None:
        super().__init__(desktop)
        self.desktop, self.controller = desktop, desktop.controller
        self._rows = QStringListModel(self)
        self._old = self._new = self._message = self._token = ""
        self._status, self._preview = "idle", None
        self._matched = self._total = 0
        self._progress = {}
        self._context = None
        self._resume_id = ""
        self._suspended = False
        self._committed_revision = None
        desktop.changed.connect(self._observe)
        self.controller.completed.connect(self._completed)
        self.controller.error.connect(self._failed)
        self.controller.relink_observed.connect(self._progressed)

    def _current_context(self):
        overview = self.controller.overview
        return (self.controller.generation, self.controller.root,
                overview.document.project_id if overview else None)

    @Property(QObject, constant=True)
    def rows(self) -> QObject:
        return self._rows

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        available = self.desktop.state["canMutate"]
        busy = self._status in {"checking", "applying"}
        return dict(
            oldFolder=self._old, newFolder=self._new, status=self._status, busy=busy,
            canPreview=bool(self._old.strip() and self._new.strip() and available and not busy),
            canApply=bool(self._preview and self._preview.can_apply and available
                          and self._status == "ready"),
            matched=self._matched, total=self._total,
            message=self._message, progress=self._progress,
        )

    @Slot()
    def begin(self) -> None:
        try:
            self.desktop._switch(self._begin)
        except ValueError as exc:
            self._message = str(exc)
            self.changed.emit()

    def _begin(self) -> None:
        if not self.desktop.state["canMutate"]:
            return
        self._context = self._current_context()
        row = self.desktop.sources.selected
        if not row and self.desktop.sources.all_rows:
            row = self.desktop.sources.all_rows[0].values
        self._old = str(self.desktop.local_path(row["locator"]).parent) if row else ""
        self._new = ""
        self._invalidate()
        self.desktop.dialogRequested.emit("folderRelink")

    def _invalidate(self) -> None:
        self._token = uuid4().hex
        self._preview = None
        self._matched = self._total = 0
        self._status, self._message, self._progress = "idle", "", {}
        self._rows.setStringList([])
        self.changed.emit()

    def _set_path(self, value: str, old: bool) -> None:
        if self.state["busy"]:
            return
        try:
            path = str(self.desktop.local_path(value)) if value.strip() else ""
        except ValueError as exc:
            self._invalidate()
            self._message = str(exc)
            self.changed.emit()
            return
        if path != (self._old if old else self._new):
            if old:
                self._old = path
            else:
                self._new = path
            self._invalidate()

    @Slot(str)
    def setOldFolder(self, value: str) -> None:
        self._set_path(value, True)

    @Slot(str)
    def setNewFolder(self, value: str) -> None:
        self._set_path(value, False)

    @Slot()
    def preview(self) -> None:
        if not self.state["canPreview"]:
            return
        try:
            self.desktop._switch(self._start_preview)
        except ValueError as exc:
            self._message = str(exc)
            self.changed.emit()

    def _start_preview(self) -> None:
        self._invalidate()
        self._context = self._current_context()
        self._status, self._message = "checking", "Checking full content identity…"
        self.changed.emit()
        self.controller.preview_folder_relink(
            self.desktop.local_path(self._old), self.desktop.local_path(self._new), self._token,
        )

    @Slot()
    def apply(self) -> None:
        if not self.state["canApply"]:
            return
        try:
            self.desktop._switch(self._start_apply)
        except ValueError as exc:
            self._message = str(exc)
            self.changed.emit()

    def _start_apply(self) -> None:
        if self._preview is None or not self.desktop.state["canMutate"]:
            return
        if self._preview.project_revision != self.controller.overview.document.revision:
            self._invalidate()
            self._message = "Project changed. Check the folders again before relinking."
            self.changed.emit()
            return
        self._resume_id = self.desktop.media.state["previewSource"].get("identity", "")
        self.desktop.media.closePreview()
        self.desktop.dialogRequested.emit("closeImage")
        self.desktop.dialogRequested.emit("closeSourceDetails")
        self.desktop.videoUsage.filmstrip.stop()
        self.desktop.sources.set_thumbnails_active(False)
        self._suspended = True
        self._status, self._message = "applying", "Rechecking content before relinking…"
        self._progress = {}
        self.changed.emit()
        if not self.controller.apply_folder_relink(self._preview, self._token, self._readers_ready):
            self._status = "failed"
            self._restore_readers()
            self.changed.emit()

    def _readers_ready(self) -> bool:
        return not any(executor.busy for executor in (
            self.desktop.media.preview_executor, self.desktop.media.gallery.executor,
            self.desktop.videoUsage.filmstrip.executor, self.desktop.sources.thumbnails.executor,
        ))

    def _restore_readers(self) -> None:
        if self._suspended:
            self._suspended = False
            self.desktop.sources.set_thumbnails_active(self.desktop.state["page"] == 1)
            identity, self._resume_id = self._resume_id, ""
            if identity and self.desktop.state["page"] == 1:
                QTimer.singleShot(0, self, lambda: self.desktop.media.showSource(identity))

    @Slot()
    def cancel(self) -> None:
        if self.state["busy"]:
            self.controller.cancel()
            self._message = "Cancelling — waiting for the current check to stop…"
            self.changed.emit()

    @Slot()
    def dismiss(self) -> None:
        if self.state["busy"]:
            self.cancel()
            return
        self._invalidate()
        self.desktop.dialogRequested.emit("closeFolderRelink")

    def _observe(self) -> None:
        if self._context is not None and self._context != self._current_context():
            self._context = self._current_context()
            self._committed_revision = None
            self._resume_id = ""
            self._restore_readers()
            self._invalidate()
            self.desktop.dialogRequested.emit("closeFolderRelink")
        elif (self._preview is not None and self._status == "ready"
              and self._preview.project_revision != self.controller.overview.document.revision):
            self._invalidate()
            self._message = "Project changed. Check the folders again before relinking."
        if (self._suspended and not self.controller.mutating and
                (self._committed_revision is None or
                 self.controller.overview.document.revision >= self._committed_revision)):
            self._committed_revision = None
            self._restore_readers()
        self.changed.emit()

    def _progressed(self, generation, token, value) -> None:
        if (generation == self.controller.generation and token == self._token
                and self.state["busy"]):
            self._progress = dict(completed=value.completed, total=value.total,
                                  filename=value.filename or "", phase=value.phase)
            self.changed.emit()

    def _completed(self, name, value) -> None:
        if name in {"relink_preview", "relink_apply"}:
            token, result = value
            if token != self._token or self._context != self._current_context():
                return
            if name == "relink_preview":
                if self.controller.ingest_cancel.is_set():
                    self._status, self._message = "cancelled", "Folder check cancelled."
                else:
                    self._preview, self._status = result, "ready"
                    self._matched, self._total = result.matched, result.total
                    self._rows.setStringList([
                        f"{entry.relative_path} · {entry.status.replace('_', ' ')}"
                        + (f"\n{entry.diagnostic}" if entry.diagnostic else "")
                        for entry in result.entries
                    ])
                    self._message = ("All scoped files match. Relink updates their saved locations."
                                     if result.can_apply else
                                     "No registered files in this folder." if not result.total else
                                     "Resolve every problem and check again. No locations changed.")
            else:
                self._committed_revision = result.project_revision
                self.desktop._source_session.relinked(result.sources)
                self._status, self._message = "succeeded", "Source folder relinked successfully."
                self._matched = self._total = len(result.sources)
                self._preview = None
        elif ((name == "cancelled" and self.controller.operation in
               {"relink_preview", "relink_apply"}) or
              (name == "relink_cancelled" and value == self._token)):
            self._status, self._message = "cancelled", "Relink cancelled. No locations changed."
            self._preview = None
            self._matched = self._total = 0
            self._rows.setStringList([])
        self.changed.emit()

    def _failed(self, error) -> None:
        if error.stage in {"relink_preview", "relink_apply"}:
            self._status, self._message = "failed", error.message
            self._preview = None
            self._matched = self._total = 0
            self._rows.setStringList([])
            self.changed.emit()
