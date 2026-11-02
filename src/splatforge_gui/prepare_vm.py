"""Prepare presentation delegates saved settings and publication to application services."""

from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from splatforge_gui.frame_review_vm import FrameReviewViewModel
from splatforge_gui.prepare_settings_vm import PrepareSettingsViewModel, request_settings_text


class PrepareViewModel(QObject):
    changed = Signal()

    def __init__(self, desktop) -> None:
        super().__init__(desktop)
        self.desktop, self.controller = desktop, desktop.controller
        self._active = False
        self._context = None
        self._token = uuid4().hex
        self._history_token = ""
        self._status, self._error, self._message = "idle", "", ""
        self._plan = None
        self._history = ()
        self._run, self._resume_id = "", ""
        self._gallery_loading = False
        self._history_loading = False
        self._review = FrameReviewViewModel(self)
        self._review.changed.connect(self.changed)
        self._settings = PrepareSettingsViewModel(self)
        self._settings.changed.connect(self.changed)
        self._settings.editsChanged.connect(self._settings_changed)
        desktop.changed.connect(self._observe)
        self.controller.completed.connect(self._completed)
        self.controller.error.connect(self._failed)
        desktop.media.changed.connect(self.changed)

    @Property(QObject, constant=True)
    def review(self) -> QObject:
        return self._review

    @Property(QObject, constant=True)
    def settings(self) -> QObject:
        return self._settings

    def _settings_changed(self) -> None:
        if self._settings.has_unsaved and self._status != "running":
            self._token, self._plan = uuid4().hex, None
            self._status = "idle"
            self._message = "Settings changed. Save them, then check the plan."
            self.desktop._notice = ""
        self.desktop.changed.emit()
        self.changed.emit()

    def _current_context(self):
        overview = self.controller.overview
        return (self.controller.generation, self.controller.root,
                overview.document.project_id if overview else None)

    @staticmethod
    def _summary(value) -> dict:
        return dict(
            runId=str(value.run_id),
            created=value.created_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            candidateCount=value.candidate_count, selectedCount=value.selected_count,
            rejectedCount=value.rejected_count, measuredCount=value.quality_measured_count,
            autoSelectedCount=value.selected_count,
            autoRejectedCount=value.candidate_count - value.selected_count,
            unavailableCount=value.quality_unavailable_count,
            method=value.method_id, warnings=list(value.warnings), cacheHits=list(value.cache_hits),
            settingsText=request_settings_text(
                value.request, has_video=(value.video_count > 0
                                          if value.video_count is not None else None),
            ),
        )

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        available = self.desktop.state["canMutate"]
        summary = next((self._summary(v) for v in self._history
                        if str(v.run_id) == self._run), {})
        plan = self._plan
        projected = {}
        if plan:
            request = plan.request
            projected = dict(
                photoCount=plan.photo_count, videoCount=plan.video_count,
                usedVideoCount=plan.used_video_count, candidateCount=plan.candidate_count,
                candidateBytes=plan.candidate_bytes, peakWorkspaceBytes=plan.peak_workspace_bytes,
                method=("frame_selection.sharpest_interval" if request.quality else
                        "frame_selection.fixed_fps"),
                targetFps=str(request.selection.target_fps.as_fraction()),
                warnings=[w for w in plan.warnings if w not in plan.blockers],
                blockers=list(plan.blockers or (plan.warnings or (
                    "This saved plan cannot run. Review its settings and sources.",
                ) if not plan.runnable else ())),
                revision=plan.project_revision, runnable=plan.runnable,
            )
        media = self.desktop.media.state
        review = self._review.state
        if summary:
            loaded = bool(self._review._page and self._review._run == self._run)
            summary.update(reviewCountsAvailable=loaded,
                           selectedCount=review["selectedTotal"] if loaded else None,
                           rejectedCount=review["rejectedTotal"] if loaded else None)
        busy = self._status == "running"
        return dict(
            active=self._active, status=self._status, busy=busy,
            canPlan=(available and self._status != "planning" and not review["saving"]
                     and self._settings.state["valid"]),
            canRun=bool(available and plan and plan.runnable and self._status != "planning"
                        and not self.controller.dirty and not self._settings.has_unsaved
                        and not review["saving"]),
            plan=projected, history=[self._summary(v) for v in self._history],
            selectedRun=self._run, selectedSummary=summary, error=self._error,
            message=self._message, galleryLoading=review["loading"],
            historyLoading=self._history_loading,
            galleryOffset=media["offset"], galleryCount=media["count"] if self._run else 0,
            canPrevious=review["canPrevious"], canNext=review["canNext"],
        )

    @Slot()
    def enter(self) -> None:
        try:
            self.desktop._switch(self._enter)
        except ValueError as exc:
            self._error = str(exc)
            self.changed.emit()

    def _enter(self) -> None:
        if self.controller.overview is None:
            return
        self._observe()
        if not self._active:
            self._resume_id = self.desktop.media.state["previewSource"].get("identity", "")
            self._active = True
            self.desktop.media.clearGallery()
            self.desktop.dialogRequested.emit("closeImage")
            self.desktop.videoUsage.filmstrip.stop()
            self.desktop.sources.set_thumbnails_active(False)
            self.desktop.media.gallery.set_active(True)
        self._load_history()
        self.changed.emit()

    @Slot()
    def sources(self) -> None:
        if self._status == "running" or self._review.state["saving"]:
            return
        try:
            self.desktop._switch(self._leave)
        except ValueError as exc:
            self._error = str(exc)
            self.changed.emit()

    def _leave(self) -> None:
        self._active = False
        self._review.deactivate()
        self._gallery_loading = False
        self.desktop.media.clearGallery()
        self.desktop.media.gallery.set_active(True)
        self.desktop.sources.set_thumbnails_active(self.desktop.state["page"] == 1)
        if self._resume_id and self.desktop.state["page"] == 1:
            self.desktop.media.showSource(self._resume_id)
        self.changed.emit()

    @Slot()
    def plan(self) -> None:
        if not self.state["canPlan"]:
            return
        try:
            self.desktop._switch(self._start_plan)
        except ValueError as exc:
            self._error = str(exc)
            self.changed.emit()

    def _start_plan(self) -> None:
        if not self.desktop.state["canMutate"]:
            return
        self._token = token = uuid4().hex
        self._plan, self._error, self._status = None, "", "planning"
        self._message = "Checking saved source participation, video intervals and frame settings…"
        root, document = self.controller.root, self.controller.overview.document
        self.controller.submit("prepare_plan", lambda f: (token, f.service("prepare_data").plan(
            root, expected_project_id=document.project_id, expected_revision=document.revision,
        )), request_token=token)
        self.changed.emit()

    @Slot()
    def run(self) -> None:
        if (self._plan is None or self._status in {"planning", "running"}
                or self._review.state["saving"] or self.controller.mutating
                or self._settings.has_unsaved):
            return
        try:
            self.desktop._switch(self._start_run)
        except ValueError as exc:
            self._error = str(exc)
            self.changed.emit()

    def _start_run(self) -> None:
        if (self._plan is None or self.controller.dirty
                or self._plan.project_revision != self.controller.overview.document.revision):
            self._plan = None
            self._error = "Project changed. Check the saved plan again before preparing data."
            self.changed.emit()
            return
        if not self._plan.runnable:
            return
        self.desktop.media.closePreview()
        self._review.deactivate()
        self.desktop.videoUsage.filmstrip.stop()
        self.desktop.sources.set_thumbnails_active(False)
        self.desktop.media.gallery.set_active(False)
        self._status, self._error = "running", ""
        self._message = "Preparing data from saved sources and settings…"
        self.changed.emit()
        if not self.controller.prepare_data(self._plan, self._token, self._readers_ready):
            self._status = "failed"
            self._restore_gallery()
        self.changed.emit()

    def _readers_ready(self) -> bool:
        return not any(e.busy for e in (
            self.desktop.media.preview_executor, self.desktop.media.gallery.executor,
            self.desktop.videoUsage.filmstrip.executor, self.desktop.sources.thumbnails.executor,
        ))

    def _restore_gallery(self) -> None:
        self.desktop.media.gallery.set_active(True)
        if not self._active:
            self.desktop.sources.set_thumbnails_active(self.desktop.state["page"] == 1)

    @Slot()
    def cancel(self) -> None:
        if self._status == "running" and self.controller.can_cancel:
            self.controller.cancel()
            self._message = "Cancelling — waiting for processing and readers to stop…"
            self.changed.emit()

    @Slot()
    def recover(self) -> None:
        self.desktop.navigate(6)

    def _load_history(self) -> None:
        if self.controller.root is None or self.controller.mutating:
            return
        root, token = self.controller.root, uuid4().hex
        self._history_token = token
        self._history_loading = True
        self.controller.submit("prepare_history", lambda f: (
            token, f.service("prepare_data").results(root),
        ), request_token=token)

    @Slot()
    def refreshHistory(self) -> None:
        if not self._history_loading and not self.controller.mutating:
            self._load_history()
            self.changed.emit()

    @Slot(str)
    def selectRun(self, run: str) -> None:
        if (self._status == "running" or self._review.state["saving"]
                or not any(str(v.run_id) == run for v in self._history)):
            return
        self._run, self._error = run, ""
        self._load_gallery(0)

    def _load_gallery(self, offset: int) -> None:
        if not self._active or not self._run or self.controller.mutating:
            return
        self._review.set_run(self._run)
        self.changed.emit()

    @Slot()
    def previousPage(self) -> None:
        self._review.previousPage()

    @Slot()
    def nextPage(self) -> None:
        self._review.nextPage()

    def _observe(self) -> None:
        self._settings.observe()
        self._settings.changed.emit()
        context = self._current_context()
        if context != self._context:
            self._context = context
            self._active = False
            self._token, self._history_token = uuid4().hex, ""
            self._plan, self._history, self._run, self._resume_id = None, (), "", ""
            self._status, self._error, self._message = "idle", "", ""
            self._gallery_loading = False
            self._history_loading = False
            self._review.reset()
        elif (self._plan and self.controller.overview
              and self._plan.project_revision != self.controller.overview.document.revision):
            self._plan = None
            self._token = uuid4().hex
            if self._status != "running":
                self._status = "idle"
                self._message = "Saved settings changed. Check the plan again."
        if (self._status != "running" and self.controller.draft is not None
                and self.controller.overview is not None
                and self.controller.draft.video_usage
                != self.controller.overview.document.video_usage
                and (self._plan is not None or self._status == "planning")):
            self._token, self._plan = uuid4().hex, None
            self._status = "idle"
            self._message = "Video intervals changed. Save them, then check the plan."
        if (self._active and not self._review._saving
                and (self._review._loading or self._review._page)
                and (self.controller.dirty or (self.controller.mutating
                     and self.controller.operation != "frame_review_apply"))):
            self._review.invalidate()
        self.changed.emit()

    def _completed(self, name, value) -> None:
        if name == "prepare_plan" and value[0] == self._token:
            self._plan = value[1]
            self._status = "ready" if self._plan.runnable else "blocked"
            self._message = ("Saved plan ready." if self._plan.runnable else
                             "Preparation blocked. Review the reason before preparing data.")
        elif name == "prepare_history" and value[0] == self._history_token:
            self._history_loading = False
            self._history = value[1]
            if not any(str(v.run_id) == self._run for v in self._history):
                self._run = str(self._history[0].run_id) if self._history else ""
            if self._active and self._run:
                self._load_gallery(0)
            elif self._active:
                self._gallery_loading = False
                self._review.reset()
                self.desktop.media.clearGallery()
        elif name == "prepare" and value[0] == self._token:
            result = value[1]
            self._status = str(result.status)
            self._restore_gallery()
            if self._status == "succeeded":
                self._run = str(result.run_id)
                self._message = "Preparation complete. Published set saved."
                # Worker-finished precedes the read: the controller refresh will follow.
            else:
                self._message = "Preparation stopped. Published sets remain available."
        elif ((name == "cancelled" and self.controller.operation == "prepare")
              or (name == "prepare_cancelled" and value == self._token)):
            self._status = "cancelled"
            self._message = "Preparation cancelled. Restart with Prepare Data."
            self._restore_gallery()
        elif name == "refresh" and self._active and self._status != "running":
            # Review save already includes confirmed page readback and its anchor.
            page = self._review._page
            revision = self.controller.overview.document.revision
            if (not self._review._error and (not page or page.project_revision != revision
                    or self._review._run != self._run)):
                self._load_history()
        elif name == "qml_gallery" and self._active and value[0] == self.desktop.media._token:
            self._gallery_loading = False
            if len(value) == 3:
                self._error = value[2]
        self.changed.emit()

    def _failed(self, error) -> None:
        if error.stage in {"prepare", "prepare_plan", "prepare_history"}:
            expected = self._history_token if error.stage == "prepare_history" else self._token
            if getattr(error, "request_token", None) != expected:
                return
            self._error = error.message
            if error.stage in {"prepare", "prepare_plan"}:
                self._status = "failed"
                self._message = (
                    "Preparation did not finish. Review the error, then retry."
                    if error.stage == "prepare"
                    else "The saved plan could not be checked. Review the error, then retry."
                )
                self._restore_gallery()
            if error.stage == "prepare_history":
                self._history_loading = False
            self.changed.emit()
