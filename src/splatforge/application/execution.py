"""Application orchestration for the concrete fake execution route."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from splatforge.application.projects import ProjectError
from splatforge.core.execution import (
    ArtifactHandle,
    ArtifactInputLineage,
    AttemptExecution,
    CacheLookup,
    CancellationRequestResult,
    FailureCategory,
    FakeRunResult,
    RecoveryResult,
    RunSnapshot,
    RunStatus,
    RunWarning,
    ScaleSettings,
    SequenceSettings,
)
from splatforge.core.fake_pipeline import (
    NUMBERS_ARTIFACT_TYPE,
    SCALED_ARTIFACT_TYPE,
    NumbersPayload,
    build_fake_route,
    scale_recipe_key,
    sequence_recipe_key,
)
from splatforge.core.project import ProjectDocument


class StateUpgradeRequiredError(ProjectError):
    """Execution requires the explicit state v1/v2 to v3 migration."""


class UnresolvedExecutionError(ProjectError):
    """A prior run needs the M1b2 recovery workflow before execution may continue."""


class PublicationUnresolvedError(ProjectError):
    """A filesystem publication exists without an authoritative success commit."""


class ExecutionCancelledError(ProjectError):
    """Durable cancellation acceptance forbids further execution/publication."""

    def __init__(self, attempt_id: UUID | None = None) -> None:
        super().__init__("Cancellation was durably accepted")
        self.attempt_id = attempt_id


class TeardownUnconfirmedError(ProjectError):
    """Injected fake teardown could not be confirmed."""


class RetryNotAllowedError(ProjectError):
    """The existing run is not eligible for an explicit retry."""


class ExecutionProject(Protocol):
    document: ProjectDocument
    state_version: int


class ExecutionControl(Protocol):
    def checkpoint(self) -> None: ...


class FakeStageMethods(Protocol):
    def execute_sequence(
        self,
        workspace: Path,
        *,
        start: int,
        settings: SequenceSettings,
        control: ExecutionControl,
    ) -> None: ...

    def execute_scale(
        self,
        workspace: Path,
        *,
        input_payload: NumbersPayload,
        settings: ScaleSettings,
        control: ExecutionControl,
    ) -> None: ...


class ExecutionRepository(Protocol):
    def writer(self, root: Path, *, owner_token: UUID) -> AbstractContextManager[None]: ...

    def inspect_project(self, root: Path) -> ExecutionProject: ...

    def ensure_no_unfinished_run(self, root: Path) -> None: ...

    def create_run(self, root: Path, snapshot: RunSnapshot) -> None: ...

    def append_event(
        self,
        root: Path,
        run_id: UUID,
        *,
        code: str,
        node_id: str | None = None,
        attempt_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> RunWarning | None: ...

    def find_cache(
        self,
        root: Path,
        *,
        recipe_key: str,
        artifact_type: str,
        contract_version: int,
    ) -> CacheLookup: ...

    def bind_cached_output(
        self,
        root: Path,
        *,
        run_id: UUID,
        node_id: str,
        output_name: str,
        artifact_id: UUID,
    ) -> None: ...

    def begin_attempt(
        self,
        root: Path,
        *,
        run_id: UUID,
        node_id: str,
        output_name: str,
        recipe_key: str,
        input_artifact_ids: tuple[UUID, ...],
        literal_inputs: dict[str, object],
        retry: bool = False,
    ) -> AttemptExecution: ...

    def publish_attempt(
        self,
        root: Path,
        *,
        run_id: UUID,
        node_id: str,
        output_name: str,
        artifact_type: str,
        contract_version: int,
        recipe_key: str,
        attempt: AttemptExecution,
        input_lineage: tuple[ArtifactInputLineage, ...],
    ) -> ArtifactHandle: ...

    def request_cancellation(self, root: Path, *, run_id: UUID) -> CancellationRequestResult: ...

    def accept_cancellation(self, root: Path, *, run_id: UUID, attempt_id: UUID | None) -> bool: ...

    def finish_cancellation(
        self,
        root: Path,
        *,
        run_id: UUID,
        attempt_id: UUID | None,
        teardown_confirmed: bool,
    ) -> RunStatus: ...

    def recover_run(self, root: Path, *, run_id: UUID) -> RecoveryResult: ...

    def prepare_retry(
        self, root: Path, *, run_id: UUID
    ) -> tuple[RunSnapshot, dict[str, ArtifactHandle]]: ...

    def mark_attempt_failed(
        self,
        root: Path,
        *,
        attempt_id: UUID,
        message: str,
        category: FailureCategory,
    ) -> None: ...

    def mark_run_failed(self, root: Path, *, run_id: UUID, message: str) -> None: ...

    def mark_run_succeeded(self, root: Path, *, run_id: UUID) -> None: ...

    def load_numbers(self, root: Path, artifact: ArtifactHandle) -> NumbersPayload: ...

    def show_run(self, root: Path, run_id: UUID) -> str: ...


class _OwnerExecutionControl:
    def __init__(
        self,
        service: FakeExecutionService,
        root: Path,
        snapshot: RunSnapshot,
        attempt_id: UUID,
    ) -> None:
        self._service = service
        self._root = root
        self._snapshot = snapshot
        self._attempt_id = attempt_id

    def checkpoint(self) -> None:
        self._service._checkpoint(self._root, self._snapshot, self._attempt_id)


class FakeExecutionService:
    def __init__(self, repository: ExecutionRepository, stages: FakeStageMethods) -> None:
        self._repository = repository
        self._stages = stages

    def run(
        self,
        root: Path,
        *,
        start: int = 0,
        count: int = 3,
        factor: int = 2,
    ) -> FakeRunResult:
        route = build_fake_route(start=start, count=count, factor=factor)
        run_id = uuid4()
        owner_token = uuid4()
        warnings: list[RunWarning] = []
        cache_hits: list[str] = []
        outputs: dict[str, ArtifactHandle] = {}
        run_created = False
        status = RunStatus.RUNNING

        with self._repository.writer(root, owner_token=owner_token):
            project = self._repository.inspect_project(root)
            if project.state_version in {1, 2}:
                raise StateUpgradeRequiredError(
                    "State upgrade required: run 'splatforge project upgrade-state <project>'"
                )
            if project.state_version != 3:
                raise ProjectError(f"Unsupported state schema version {project.state_version}")
            self._repository.ensure_no_unfinished_run(root)
            project_copy = ProjectDocument.model_validate(project.document.model_dump(mode="json"))
            snapshot = RunSnapshot(
                run_id=run_id,
                project_id=project_copy.project_id,
                project_revision=project_copy.revision,
                owner_token=owner_token,
                created_at=datetime.now(UTC),
                project_intent=project_copy,
                route=route,
            )
            self._repository.create_run(root, snapshot)
            run_created = True
            self._event(warnings, root, run_id, code="run.started")

            try:
                self._checkpoint(root, snapshot, None)
                first = self._run_sequence(root, snapshot, warnings, cache_hits)
                outputs[route.sequence.node_id] = first
                self._checkpoint(root, snapshot, None)
                second = self._run_scale(root, snapshot, first, warnings, cache_hits)
                outputs[route.scale.node_id] = second
                self._checkpoint(root, snapshot, None)
                self._repository.mark_run_succeeded(root, run_id=run_id)
                status = RunStatus.SUCCEEDED
                self._event(warnings, root, run_id, code="run.succeeded")
            except ExecutionCancelledError as exc:
                status = self._repository.finish_cancellation(
                    root,
                    run_id=run_id,
                    attempt_id=exc.attempt_id,
                    teardown_confirmed=True,
                )
                self._event(
                    warnings,
                    root,
                    run_id,
                    code="run.cancelled",
                    attempt_id=exc.attempt_id,
                )
            except TeardownUnconfirmedError as exc:
                status = self._repository.finish_cancellation(
                    root,
                    run_id=run_id,
                    attempt_id=getattr(exc, "attempt_id", None),
                    teardown_confirmed=False,
                )
            except PublicationUnresolvedError:
                raise
            except Exception as exc:
                if run_created:
                    self._repository.mark_run_failed(root, run_id=run_id, message=str(exc))
                    self._event(
                        warnings,
                        root,
                        run_id,
                        code="run.failed",
                        details={"error": str(exc)},
                    )
                raise

        return FakeRunResult(
            run_id=run_id,
            status=status,
            outputs=outputs,
            cache_hits=tuple(cache_hits),
            warnings=tuple(warnings),
        )

    def show(self, root: Path, run_id: UUID) -> str:
        return self._repository.show_run(root, run_id)

    def cancel(self, root: Path, run_id: UUID) -> CancellationRequestResult:
        self._require_v3(root)
        return self._repository.request_cancellation(root, run_id=run_id)

    def recover(self, root: Path, run_id: UUID) -> RecoveryResult:
        owner_token = uuid4()
        with self._repository.writer(root, owner_token=owner_token):
            self._require_v3(root)
            result = self._repository.recover_run(root, run_id=run_id)
            warnings = list(result.warnings)
            self._event(warnings, root, run_id, code="recovery.completed")
            return result.model_copy(update={"warnings": tuple(warnings)})

    def retry(self, root: Path, run_id: UUID) -> FakeRunResult:
        owner_token = uuid4()
        warnings: list[RunWarning] = []
        cache_hits: list[str] = []
        status = RunStatus.RUNNING
        with self._repository.writer(root, owner_token=owner_token):
            self._require_v3(root)
            snapshot, outputs = self._repository.prepare_retry(root, run_id=run_id)
            self._event(warnings, root, run_id, code="retry.started")
            try:
                self._checkpoint(root, snapshot, None)
                first = outputs.get(snapshot.route.sequence.node_id)
                if first is None:
                    first = self._run_sequence(root, snapshot, warnings, cache_hits, retry=True)
                    outputs[snapshot.route.sequence.node_id] = first
                self._checkpoint(root, snapshot, None)
                second = outputs.get(snapshot.route.scale.node_id)
                if second is None:
                    second = self._run_scale(
                        root, snapshot, first, warnings, cache_hits, retry=True
                    )
                    outputs[snapshot.route.scale.node_id] = second
                self._checkpoint(root, snapshot, None)
                self._repository.mark_run_succeeded(root, run_id=run_id)
                status = RunStatus.SUCCEEDED
                self._event(warnings, root, run_id, code="retry.succeeded")
            except ExecutionCancelledError as exc:
                status = self._repository.finish_cancellation(
                    root,
                    run_id=run_id,
                    attempt_id=exc.attempt_id,
                    teardown_confirmed=True,
                )
                self._event(warnings, root, run_id, code="run.cancelled")
            except TeardownUnconfirmedError as exc:
                status = self._repository.finish_cancellation(
                    root,
                    run_id=run_id,
                    attempt_id=getattr(exc, "attempt_id", None),
                    teardown_confirmed=False,
                )
            except PublicationUnresolvedError:
                raise
            except Exception as exc:
                self._repository.mark_run_failed(root, run_id=run_id, message=str(exc))
                self._event(
                    warnings,
                    root,
                    run_id,
                    code="retry.failed",
                    details={"error": str(exc)},
                )
                raise
        return FakeRunResult(
            run_id=run_id,
            status=status,
            outputs=outputs,
            cache_hits=tuple(cache_hits),
            warnings=tuple(warnings),
        )

    def _require_v3(self, root: Path) -> None:
        version = self._repository.inspect_project(root).state_version
        if version in {1, 2}:
            raise StateUpgradeRequiredError(
                "State upgrade required: run 'splatforge project upgrade-state <project>'"
            )
        if version != 3:
            raise ProjectError(f"Unsupported state schema version {version}")

    def _run_sequence(
        self,
        root: Path,
        snapshot: RunSnapshot,
        warnings: list[RunWarning],
        cache_hits: list[str],
        retry: bool = False,
    ) -> ArtifactHandle:
        node = snapshot.route.sequence
        key = sequence_recipe_key(start=node.start, settings=node.settings)
        cached = self._repository.find_cache(
            root,
            recipe_key=key,
            artifact_type=NUMBERS_ARTIFACT_TYPE,
            contract_version=node.output.contract_version,
        )
        if cached.artifact is not None:
            self._repository.bind_cached_output(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_id=cached.artifact.artifact_id,
            )
            cache_hits.append(node.node_id)
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="cache.hit",
                node_id=node.node_id,
                details={
                    "artifact_id": str(cached.artifact.artifact_id),
                    "ineligible": [item.model_dump(mode="json") for item in cached.ineligible],
                },
            )
            return cached.artifact

        self._cache_miss_event(warnings, root, snapshot.run_id, node.node_id, cached)
        attempt = self._repository.begin_attempt(
            root,
            run_id=snapshot.run_id,
            node_id=node.node_id,
            output_name=node.output.output_name,
            recipe_key=key,
            input_artifact_ids=(),
            literal_inputs={"start": node.start},
            retry=retry,
        )
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="attempt.started",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
        )
        try:
            self._stages.execute_sequence(
                Path(attempt.workspace),
                start=node.start,
                settings=node.settings,
                control=_OwnerExecutionControl(self, root, snapshot, attempt.attempt_id),
            )
            self._checkpoint(root, snapshot, attempt.attempt_id)
            artifact = self._repository.publish_attempt(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_type=node.output.artifact_type,
                contract_version=node.output.contract_version,
                recipe_key=key,
                attempt=attempt,
                input_lineage=(),
            )
        except PublicationUnresolvedError:
            raise
        except (ExecutionCancelledError, TeardownUnconfirmedError):
            raise
        except Exception as exc:
            self._repository.mark_attempt_failed(
                root,
                attempt_id=attempt.attempt_id,
                message=str(exc),
                category=self._failure_category(exc),
            )
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="attempt.failed",
                node_id=node.node_id,
                attempt_id=attempt.attempt_id,
                details={"error": str(exc)},
            )
            raise
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="attempt.succeeded",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
        )
        return artifact

    def _run_scale(
        self,
        root: Path,
        snapshot: RunSnapshot,
        input_artifact: ArtifactHandle,
        warnings: list[RunWarning],
        cache_hits: list[str],
        retry: bool = False,
    ) -> ArtifactHandle:
        node = snapshot.route.scale
        key = scale_recipe_key(settings=node.settings, input_artifact=input_artifact)
        cached = self._repository.find_cache(
            root,
            recipe_key=key,
            artifact_type=SCALED_ARTIFACT_TYPE,
            contract_version=node.output.contract_version,
        )
        if cached.artifact is not None:
            self._repository.bind_cached_output(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_id=cached.artifact.artifact_id,
            )
            cache_hits.append(node.node_id)
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="cache.hit",
                node_id=node.node_id,
                details={
                    "artifact_id": str(cached.artifact.artifact_id),
                    "ineligible": [item.model_dump(mode="json") for item in cached.ineligible],
                },
            )
            return cached.artifact

        self._cache_miss_event(warnings, root, snapshot.run_id, node.node_id, cached)
        attempt = self._repository.begin_attempt(
            root,
            run_id=snapshot.run_id,
            node_id=node.node_id,
            output_name=node.output.output_name,
            recipe_key=key,
            input_artifact_ids=(input_artifact.artifact_id,),
            literal_inputs={},
            retry=retry,
        )
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="attempt.started",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
        )
        lineage = (
            ArtifactInputLineage(
                input_name="numbers",
                artifact_id=input_artifact.artifact_id,
                artifact_type=input_artifact.artifact_type,
                contract_version=input_artifact.contract_version,
                semantic_digest=input_artifact.semantic_digest,
                recipe_key=input_artifact.recipe_key,
            ),
        )
        try:
            input_payload = self._repository.load_numbers(root, input_artifact)
            self._stages.execute_scale(
                Path(attempt.workspace),
                input_payload=input_payload,
                settings=node.settings,
                control=_OwnerExecutionControl(self, root, snapshot, attempt.attempt_id),
            )
            self._checkpoint(root, snapshot, attempt.attempt_id)
            artifact = self._repository.publish_attempt(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_type=node.output.artifact_type,
                contract_version=node.output.contract_version,
                recipe_key=key,
                attempt=attempt,
                input_lineage=lineage,
            )
        except PublicationUnresolvedError:
            raise
        except (ExecutionCancelledError, TeardownUnconfirmedError):
            raise
        except Exception as exc:
            self._repository.mark_attempt_failed(
                root,
                attempt_id=attempt.attempt_id,
                message=str(exc),
                category=self._failure_category(exc),
            )
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="attempt.failed",
                node_id=node.node_id,
                attempt_id=attempt.attempt_id,
                details={"error": str(exc)},
            )
            raise
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="attempt.succeeded",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
        )
        return artifact

    def _checkpoint(
        self,
        root: Path,
        snapshot: RunSnapshot,
        attempt_id: UUID | None,
    ) -> None:
        if self._repository.accept_cancellation(
            root, run_id=snapshot.run_id, attempt_id=attempt_id
        ):
            self._repository.append_event(
                root,
                snapshot.run_id,
                code="cancellation.accepted",
                attempt_id=attempt_id,
            )
            raise ExecutionCancelledError(attempt_id)

    @staticmethod
    def _failure_category(exc: Exception) -> FailureCategory:
        if isinstance(exc, OSError):
            return FailureCategory.TRANSIENT
        return FailureCategory.NON_RETRYABLE

    def _cache_miss_event(
        self,
        warnings: list[RunWarning],
        root: Path,
        run_id: UUID,
        node_id: str,
        lookup: CacheLookup,
    ) -> None:
        self._event(
            warnings,
            root,
            run_id,
            code="cache.miss",
            node_id=node_id,
            details={"ineligible": [item.model_dump(mode="json") for item in lookup.ineligible]},
        )

    def _event(
        self,
        warnings: list[RunWarning],
        root: Path,
        run_id: UUID,
        *,
        code: str,
        node_id: str | None = None,
        attempt_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        warning = self._repository.append_event(
            root,
            run_id,
            code=code,
            node_id=node_id,
            attempt_id=attempt_id,
            details=details,
        )
        if warning is not None:
            warnings.append(warning)
