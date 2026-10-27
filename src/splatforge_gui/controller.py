"""Thread-affine UI state; each job builds fresh application services in its worker."""

import json
from collections.abc import Callable
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from splatforge.bootstrap import build_gui_facade
from splatforge.core.project import ProjectDocument
from splatforge_gui.tasks import TaskError, TaskExecutor


class ProjectController(QObject):
    changed = Signal(object)
    progress_changed = Signal(object)
    metrics_changed = Signal(object)
    completed = Signal(str, object)
    error = Signal(object)
    busy_changed = Signal(bool)
    dirty_changed = Signal(bool)

    def __init__(self, parent=None, factory: Callable = build_gui_facade) -> None:
        super().__init__(parent)
        self.factory, self.root, self.overview, self.draft = factory, None, None, None
        self.executor = TaskExecutor(self)
        self.jobs: dict[str, tuple[str, bool, int]] = {}
        self.generation = 0
        self.mutating = False
        self.operation: str | None = None
        self.refreshing = False
        self.polling = False
        self.active = ()
        self.ingest_cancel = Event()
        self.cancelled_runs: set[str] = set()
        self.request = None
        self.reconstruction_plan = None
        self._pending_save = None
        self.executor.result.connect(self._result)
        self.executor.error.connect(self._error)
        self.executor.finished.connect(self._finished)
        self.timer = QTimer(self)
        self.timer.setInterval(750)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    @property
    def dirty(self) -> bool:
        return self.draft is not None

    @property
    def can_cancel(self) -> bool:
        return bool(self.active) or (
            self.mutating
            and self.operation
            in {"ingest", "verify", "reconstruction", "selection", "dataset", "training"}
        )

    @property
    def has_unresolved(self) -> bool:
        return bool(
            self.overview
            and any(
                r.values["status"] == "running" or "unresolved" in (r.values.get("teardown") or "")
                for r in self.overview.index.runs
            )
        )

    def submit(
        self,
        name: str,
        action: Callable,
        *,
        mutation: bool = False,
        allow_unresolved: bool = False,
    ) -> str:
        if self.operation == "save" and name != "save":
            self.error.emit(
                TaskError("Wait for project metadata to finish saving", "ProjectBusy", "", name)
            )
            return ""
        if mutation and (
            self.mutating
            or (
                not allow_unresolved
                and (self.active or (self.has_unresolved and name not in {"create", "open"}))
            )
        ):
            self.error.emit(
                TaskError(
                    "Active/unresolved work blocks project mutations", "ProjectBusy", "", name
                )
            )
            return ""
        if mutation and name not in {"create", "open"} and self.overview is None:
            self.error.emit(
                TaskError("Open a project before starting this operation", "NoProject", "", name)
            )
            return ""
        factory = self.factory
        if mutation:
            self.ingest_cancel.clear()
            self.cancelled_runs.clear()
        identity = self.executor.submit(
            name, lambda: action(factory()), control=name in {"cancel", "progress"}
        )
        self.jobs[identity] = (name, mutation, self.generation)
        if mutation:
            self.mutating = True
            self.operation = name
            self.busy_changed.emit(True)
        return identity

    def create(self, root: Path, label: str) -> None:
        self._load_project(root, label)

    def open(self, root: Path) -> None:
        self._load_project(root)

    def _load_project(self, root: Path, label: str | None = None) -> None:
        name = "create" if label is not None else "open"
        if self.mutating or self.active:
            self.error.emit(
                TaskError("Finish or cancel active work first", "ProjectBusy", "", name)
            )
            return
        self.generation += 1
        self.refreshing = self.polling = False
        target = root.absolute()

        def load(facade):
            if label is not None:
                facade.create(target, label)
            return target, facade.overview(target)

        # Keep the current workspace until the complete persisted overview validates.
        self.submit(name, load, mutation=True)

    def refresh(self) -> None:
        if self.root is None or self.refreshing or self.operation in {"save", "create", "open"}:
            return
        root = self.root
        self.refreshing = True
        self.submit("refresh", lambda f: f.overview(root))

    @Slot()
    def poll(self) -> None:
        if self.root is None or self.polling or self.operation in {"save", "create", "open"}:
            return
        root = self.root
        self.polling = True

        def read(f):
            runs = f.progress(root)
            return runs, f.live_metrics(root, runs)

        self.submit("progress", read)

    def edit(self, document: ProjectDocument) -> None:
        self.draft = ProjectDocument.model_validate(document.model_dump())
        self.dirty_changed.emit(True)

    def save(self) -> None:
        root, draft = self.root, self.draft
        if not root or not draft:
            return
        if self.mutating or self.active or self.has_unresolved:
            self.submit("save", lambda f: f.save(root, draft), mutation=True)
            return
        # Windows readers may hold project.json without delete sharing. Drain owned
        # reads before atomic metadata replacement; long processing still polls normally.
        self._pending_save = (root, draft)
        self.mutating, self.operation = True, "save"
        self.ingest_cancel.clear()
        self.busy_changed.emit(True)
        self._start_pending_save()

    def _start_pending_save(self) -> None:
        if self._pending_save is None or self.jobs:
            return
        root, draft = self._pending_save
        self._pending_save = None
        self.mutating, self.operation = False, None
        self.busy_changed.emit(False)
        self.submit("save", lambda f: f.save(root, draft), mutation=True)

    def discard(self) -> None:
        self.draft = None
        self.dirty_changed.emit(False)

    def cancel(self) -> None:
        self.ingest_cancel.set()
        root = self.root
        for active in self.active:
            identity = str(active.run_id)
            if identity not in self.cancelled_runs:
                self.cancelled_runs.add(identity)
                self.submit("cancel", lambda f, run=active.run_id: f.cancel(root, run))

    def scan_folder(self, directory: Path) -> None:
        from splatforge.application.desktop import enumerate_media

        self.submit("folder", lambda f: enumerate_media(directory))

    def ingest(self, paths: tuple[Path, ...]) -> None:
        from splatforge.application.media import CallbackCancellation

        root = self.root
        if root is None:
            self.error.emit(TaskError("Open a project first", "NoProject", "", "ingest"))
            return
        self.ingest_cancel.clear()
        cancellation = CallbackCancellation(self.ingest_cancel.is_set)
        self.submit(
            "ingest",
            lambda f: f.service("media").add(root, paths, cancellation=cancellation),
            mutation=True,
        )

    def verify_sources(self) -> None:
        from splatforge.application.media import CallbackCancellation

        root = self.root
        if root:
            cancellation = CallbackCancellation(self.ingest_cancel.is_set)
            self.submit(
                "verify",
                lambda f: f.service("media").verify(root, cancellation=cancellation),
                mutation=True,
            )

    def preview_image(self, reference) -> None:
        from splatforge_gui.thumbnails import decode_thumbnail

        self.submit("image", lambda f: decode_thumbnail(reference.path, 1024))

    def configure_reconstruction(self) -> None:
        from splatforge.application.desktop_workflow import reconstruction_request

        if self.overview:
            document = self.draft or self.overview.document
            signature = document.settings.model_dump_json()
            self.submit("request", lambda f: (signature, reconstruction_request(document)))

    def stage_request_as_intent(self) -> None:
        from splatforge.core.project import MethodSettingsEnvelope
        from splatforge.core.sfm_profiles import ResolvedFeatureMatchingRoute

        if self.overview is None or self.request is None:
            return
        document = self.draft or self.overview.document
        features = self.request.features
        if self.request.profile:
            plan = self.reconstruction_plan
            if not plan or plan["request"] != self.request.model_dump(mode="json"):
                self.error.emit(
                    TaskError(
                        "Resolve this profile with Plan before saving intent",
                        "ProfileUnresolved",
                        "",
                        "settings",
                    )
                )
                return
            features = ResolvedFeatureMatchingRoute.model_validate_json(
                json.dumps(plan["resolved_feature_matching"])
            ).choice
        updates = {}
        for slot, value, method in (
            (
                "frame_selection",
                self.request.selection,
                "frame_selection.sharpest_interval"
                if hasattr(self.request.selection, "reject_duplicates")
                else "frame_selection.fixed_fps",
            ),
            (
                "feature_extraction",
                features.extractor,
                features.extractor.method_id,
            ),
            (
                "feature_matching",
                features.matcher,
                features.matcher.method_id,
            ),
            ("pair_selection", self.request.pairing, self.request.pairing.method_id),
            ("mapping", self.request.mapper, self.request.mapper.method_id),
        ):
            old = getattr(document.settings, slot)
            updates[slot] = MethodSettingsEnvelope.model_validate(
                {
                    **old.model_dump(mode="json"),
                    "method_id": method,
                    "settings_schema_version": 1,
                    "settings": value.model_dump(mode="json"),
                }
            )
        self.edit(
            document.model_copy(update={"settings": document.settings.model_copy(update=updates)})
        )

    def reconstruct(self, colmap: Path | None, models: Path | None, planning: bool) -> None:
        from splatforge.application.desktop_workflow import plan_reconstruction, run_reconstruction
        from splatforge.core.sfm_profiles import ResolvedFeatureMatchingRoute

        root, request = self.root, self.request
        if root is None or request is None:
            return
        resolution = None
        if not planning:
            plan = self.reconstruction_plan
            tools = {
                "colmap": str(colmap) if colmap else None,
                "models": str(models) if models else None,
            }
            if (
                not plan
                or plan["request"] != request.model_dump(mode="json")
                or plan["tools"] != tools
            ):
                self.error.emit(
                    TaskError(
                        "Run Plan again for these exact settings/tools",
                        "StalePlan",
                        "",
                        "reconstruction",
                    )
                )
                return
            resolution = ResolvedFeatureMatchingRoute.model_validate_json(
                json.dumps(plan["resolved_feature_matching"])
            )
        self.ingest_cancel.clear()
        cancellation = self.ingest_cancel

        def checkpoint() -> None:
            if cancellation.is_set():
                from splatforge.application.execution import ExecutionCancelledError

                raise ExecutionCancelledError()

        self.submit(
            "reconstruction_plan" if planning else "reconstruction",
            lambda f: (
                plan_reconstruction(f, root, request, colmap, models)
                if planning
                else run_reconstruction(f, root, request, colmap, models, checkpoint, resolution)
            ),
            mutation=not planning,
        )

    def validation_details(self, run) -> None:
        root = self.root
        self.submit(
            "validation_details",
            lambda f: (run, *f.service("validation").inspect_details(root, run)),
        )

    def select_components(self, run, components=(), issues=(), reason=None) -> None:
        root = self.root
        self.submit(
            "selection",
            lambda f: f.service("selection").select(
                root,
                validation_run_id=run,
                component_ids=components,
                override_issue_ids=issues,
                override_reason=reason,
            ),
            mutation=True,
        )

    def dataset(self, run, settings, colmap, planning: bool) -> None:
        root = self.root
        self.submit(
            "dataset_plan" if planning else "dataset",
            lambda f: (f.service("dataset").plan if planning else f.service("dataset").prepare)(
                root, selection_run_id=run, settings=settings, colmap=colmap
            ),
            mutation=not planning,
        )

    def training(self, run, runtime, settings, planning: bool, resume=None) -> None:
        root = self.root
        self.submit(
            "training_plan" if planning else "training",
            lambda f: (
                f.service("training").plan(root, run, runtime, settings)
                if planning
                else f.service("training").run(root, run, runtime, settings, resume_run=resume)
            ),
            mutation=not planning,
        )

    def trainer_capability(self, runtime) -> None:
        self.submit("trainer_capability", lambda f: f.service("training").capability(runtime))

    def resume_check(self, run, checkpoint, runtime, settings, token=None) -> None:
        root = self.root
        self.submit(
            "resume_check",
            lambda f: {
                **f.service("training").check_resume(root, run, checkpoint, runtime, settings),
                "request_token": token,
            },
        )

    def doctor(self, colmap, models, deep=False, lichtfeld=None) -> None:
        self.submit(
            "doctor",
            lambda f: {
                "colmap_learned_gpu": f.service("doctor")
                .report(colmap=colmap, model_directory=models, deep=deep)
                .model_dump(mode="json"),
                "lichtfeld": f.service("training").external_status(lichtfeld),
                "media": {
                    "status": "unknown_unvalidated",
                    "reason": "Actual FFprobe/FFmpeg operations are validated during ingest/views",
                },
            },
        )

    def inspect_artifact(self, artifact) -> None:
        root = self.root
        self.submit("inspect", lambda f: f.inspect(root, artifact))

    def inspect_run(self, run) -> None:
        root = self.root
        self.submit("run_details", lambda f: f.service("execution").show(root, run))

    def recover_run(self, run) -> None:
        root = self.root
        # Recovery, unlike an ordinary mutation, must remain reachable with unresolved work.
        self.submit(
            "recovery", lambda f: f.recover(root, run), mutation=True, allow_unresolved=True
        )

    def cleanup(self, plan=None) -> None:
        root = self.root
        self.submit(
            "cleanup_preview" if plan is None else "cleanup_apply",
            lambda f: (
                f.service("cleanup").preview(root)
                if plan is None
                else f.service("cleanup").apply(root, preview_digest=plan.preview_digest)
            ),
            mutation=plan is not None,
        )

    def pin(self, artifact, pinned: bool) -> None:
        root = self.root
        self.submit(
            "pin", lambda f: f.service("cleanup").pin(root, artifact, pinned), mutation=True
        )

    def gallery(self, run, offset=0) -> None:
        root = self.root
        self.submit("gallery", lambda f: f.gallery(root, run, offset))

    @Slot(str, object)
    def _result(self, identity: str, result) -> None:
        name, _, generation = self.jobs[identity]
        if generation != self.generation:
            return
        if name == "refresh":
            if self.operation == "save":
                return  # A fresh overview follows the reserved metadata write.
            self.overview, self.active = result, result.active
            self.changed.emit(result)
        elif name == "progress":
            previous, self.active = self.active, result[0]
            if self.mutating and self.ingest_cancel.is_set():
                self.cancel()
            self.progress_changed.emit(self.active)
            self.metrics_changed.emit(result[1])
            result = self.active
            if previous and {r.run_id for r in previous} != {r.run_id for r in self.active}:
                self.refresh()
        elif name in {"create", "open"}:
            # Reads can still be requested against the retained workspace while
            # loading. None of their replies belong to the adopted workspace.
            self.generation += 1
            self.root, self.overview = result
            self.active = self.overview.active
            self.request = self.reconstruction_plan = None
            self.draft = None
            self.changed.emit(self.overview)
            self.dirty_changed.emit(False)
        elif name == "save":
            self.discard()
        elif name == "request":
            document = self.draft or self.overview.document
            if result[0] != document.settings.model_dump_json():
                return
            result = result[1]
            self.request = result
        elif name == "reconstruction_plan":
            self.reconstruction_plan = result
        elif name == "recovery":
            self.refresh()
        self.completed.emit(name, result)

    @Slot(str, object)
    def _error(self, identity: str, error) -> None:
        if self.jobs[identity][2] == self.generation:
            if self.jobs[identity][0] == "cancel":
                self.cancelled_runs.clear()
                self.ingest_cancel.clear()
            if self.jobs[identity][0] == "request":
                self.completed.emit("request_unavailable", error.message)
            elif error.category in {
                "ExecutionCancelledError",
                "MediaOperationCancelled",
                "ProbeCancelledError",
            }:
                self.completed.emit("cancelled", error.message)
            else:
                self.error.emit(error)

    @Slot(str)
    def _finished(self, identity: str) -> None:
        name, mutation, generation = self.jobs.pop(identity)
        if name == "refresh" and generation == self.generation:
            self.refreshing = False
        if name == "progress" and generation == self.generation:
            self.polling = False
        if mutation:
            self.mutating = False
            self.operation = None
            self.busy_changed.emit(False)
            self.refresh()
        self._start_pending_save()
