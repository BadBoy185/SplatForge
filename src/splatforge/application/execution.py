"""Application orchestration for the single concrete M1b1 route."""

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
    FakeRunResult,
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
    """Execution requires the explicit state v1 to v2 migration."""


class UnresolvedExecutionError(ProjectError):
    """A prior run needs the M1b2 recovery workflow before execution may continue."""


class PublicationUnresolvedError(ProjectError):
    """A filesystem publication exists without an authoritative success commit."""


class ExecutionProject(Protocol):
    document: ProjectDocument
    state_version: int


class FakeStageMethods(Protocol):
    def execute_sequence(
        self, workspace: Path, *, start: int, settings: SequenceSettings
    ) -> None: ...

    def execute_scale(
        self,
        workspace: Path,
        *,
        input_payload: NumbersPayload,
        settings: ScaleSettings,
    ) -> None: ...


class ExecutionRepository(Protocol):
    def writer(
        self, root: Path, *, owner_token: UUID
    ) -> AbstractContextManager[None]: ...

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

    def mark_attempt_failed(
        self, root: Path, *, attempt_id: UUID, message: str
    ) -> None: ...

    def mark_run_failed(self, root: Path, *, run_id: UUID, message: str) -> None: ...

    def mark_run_succeeded(self, root: Path, *, run_id: UUID) -> None: ...

    def load_numbers(self, root: Path, artifact: ArtifactHandle) -> NumbersPayload: ...

    def show_run(self, root: Path, run_id: UUID) -> str: ...


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

        with self._repository.writer(root, owner_token=owner_token):
            project = self._repository.inspect_project(root)
            if project.state_version == 1:
                raise StateUpgradeRequiredError(
                    "State upgrade required: run 'splatforge project upgrade-state <project>'"
                )
            if project.state_version != 2:
                raise ProjectError(f"Unsupported state schema version {project.state_version}")
            self._repository.ensure_no_unfinished_run(root)
            project_copy = ProjectDocument.model_validate(
                project.document.model_dump(mode="json")
            )
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
                first = self._run_sequence(root, snapshot, warnings, cache_hits)
                outputs[route.sequence.node_id] = first
                second = self._run_scale(
                    root, snapshot, first, warnings, cache_hits
                )
                outputs[route.scale.node_id] = second
                self._repository.mark_run_succeeded(root, run_id=run_id)
                self._event(warnings, root, run_id, code="run.succeeded")
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
            status=RunStatus.SUCCEEDED,
            outputs=outputs,
            cache_hits=tuple(cache_hits),
            warnings=tuple(warnings),
        )

    def show(self, root: Path, run_id: UUID) -> str:
        return self._repository.show_run(root, run_id)

    def _run_sequence(
        self,
        root: Path,
        snapshot: RunSnapshot,
        warnings: list[RunWarning],
        cache_hits: list[str],
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
                Path(attempt.workspace), start=node.start, settings=node.settings
            )
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
        except Exception as exc:
            self._repository.mark_attempt_failed(
                root, attempt_id=attempt.attempt_id, message=str(exc)
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
            )
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
        except Exception as exc:
            self._repository.mark_attempt_failed(
                root, attempt_id=attempt.attempt_id, message=str(exc)
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
            details={
                "ineligible": [item.model_dump(mode="json") for item in lookup.ineligible]
            },
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
