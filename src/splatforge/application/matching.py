"""Two explicit cache boundaries sharing existing attempts/publication/progress."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from splatforge.application.execution import (
    ExecutionCancelledError,
    ExecutionRepository,
    PublicationUnresolvedError,
    StateUpgradeRequiredError,
)
from splatforge.application.features import _Cancellation
from splatforge.application.features_contracts import FeatureCancelledError, FeatureTeardownError
from splatforge.application.matching_contracts import MatchingAdapter
from splatforge.application.progress import ProgressSupport
from splatforge.application.work_models import matching_progress_plan
from splatforge.core.execution import (
    ArtifactHandle,
    FailureCategory,
    FeatureMatchingRoute,
    GeometricVerificationRoute,
    RunSnapshot,
    RunStatus,
)
from splatforge.core.features import LearnedModelIdentity, LocalFeatureSet
from splatforge.core.geometry import (
    CameraPriorSet,
    VerificationSettings,
    VerifiedGeometrySet,
    estimate_verification_resources,
    geometry_semantic_digest,
    uncalibrated_camera_priors,
)
from splatforge.core.matching import (
    MatcherSettings,
    MatchingResourceLimits,
    MatchSet,
    estimate_matching_resources,
    match_semantic_digest,
    numerical_models,
    validate_matcher_compatibility,
)
from splatforge.core.pairs import PairSet
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.sfm_profiles import ResolvedFeatureMatchingRoute
from splatforge.core.views import FrozenModel


class MatchingRepository(ExecutionRepository, Protocol):
    def resolve_run_output(
        self,
        root: Path,
        run_id: UUID,
        node_id: str,
        output_name: str,
    ) -> ArtifactHandle: ...

    def load_local_features(self, root: Path, handle: ArtifactHandle) -> LocalFeatureSet: ...

    def load_pair_set(self, root: Path, handle: ArtifactHandle) -> PairSet: ...

    def load_match_set(self, root: Path, handle: ArtifactHandle) -> MatchSet: ...

    def load_verified_geometry(self, root: Path, handle: ArtifactHandle) -> VerifiedGeometrySet: ...

    def load_match_inputs(
        self,
        root: Path,
        handle: ArtifactHandle,
    ) -> tuple[LocalFeatureSet, PairSet]: ...

    def write_matching_metadata(
        self,
        workspace: Path,
        payload: MatchSet | VerifiedGeometrySet,
        cameras: CameraPriorSet | None = None,
    ) -> None: ...


class MatchingRunResult(FrozenModel):
    result_version: int = 1
    run_id: UUID
    status: RunStatus
    method_id: str
    artifact: ArtifactHandle | None
    pair_count: int
    raw_matches: int
    accepted_pairs: int | None = None
    verified_inliers: int | None = None
    cache_hit: bool
    warnings: tuple[str, ...] = ()


class MatchingService:
    def __init__(
        self,
        repository: MatchingRepository,
        adapter: MatchingAdapter,
        *,
        progress: ProgressSupport | None = None,
    ) -> None:
        self._repository, self._adapter = repository, adapter
        self._progress = progress or ProgressSupport()

    def match(
        self,
        root: Path,
        *,
        features_run_id: UUID,
        pairs_run_id: UUID,
        settings: MatcherSettings,
        resource_limits: MatchingResourceLimits | None = None,
        colmap: Path | None = None,
        model_directory: Path | None = None,
        resolution: ResolvedFeatureMatchingRoute | None = None,
    ) -> MatchingRunResult:
        root, owner = root.resolve(), uuid4()
        repo, limits = self._repository, resource_limits or MatchingResourceLimits()
        with repo.writer(root, owner_token=owner, operation="matches-run"):
            repo.ensure_no_unfinished_run(root)
            features_handle = repo.resolve_run_output(
                root, features_run_id, "local_features", "features"
            )
            pairs_handle = repo.resolve_run_output(root, pairs_run_id, "pair_set", "pairs")
            features = repo.load_local_features(root, features_handle)
            pairs = repo.load_pair_set(root, pairs_handle)
            validate_matcher_compatibility(features.descriptor, settings)
            if resolution and (
                resolution.choice.extractor != features.settings
                or resolution.choice.matcher != settings
            ):
                raise ValueError(
                    "Profile needs its exact extractor artifact; run features extract "
                    "with the resolved settings first. Matching never re-extracts."
                )
            feature_directory = repo.artifact_directory(root, features_handle)
            pair_directory = repo.artifact_directory(root, pairs_handle)
            size = sum(p.stat().st_size for p in feature_directory.iterdir() if p.is_file())
            size += (pair_directory / "pair_set.json").stat().st_size
            estimate_matching_resources(features, pairs, settings, limits, upstream_bytes=size)
            backend = self._adapter.prepare(
                settings,
                feature_settings=features.settings,
                colmap=colmap,
                model_directory=model_directory,
            )
            if resolution:
                require_resolution_inputs(
                    resolution, features, backend.numerical_identity, backend.model_identities()
                )
            estimate = estimate_matching_resources(
                features,
                pairs,
                settings,
                limits,
                upstream_bytes=size,
                model_bytes=sum(m.size for m in backend.model_identities()),
            )
            route = FeatureMatchingRoute(
                features_run_id=features_run_id,
                pairs_run_id=pairs_run_id,
                features=features_handle,
                pairs=pairs_handle,
                settings=settings,
                descriptor=features.descriptor,
                backend=backend,
                resource_limits=limits,
                estimate=estimate,
                resolution=resolution,
            )

            def produce(workspace, control, evidence, phase):
                summaries = self._adapter.match(
                    workspace,
                    backend=backend,
                    settings=settings,
                    feature_directory=feature_directory,
                    pair_directory=pair_directory,
                    features=features,
                    pairs=pairs,
                    limits=limits,
                    estimate=estimate,
                    cancellation=control,
                    evidence_sink=evidence,
                    phase_sink=phase,
                )
                value = MatchSet.model_construct(
                    features_artifact_id=features_handle.artifact_id,
                    features_semantic_digest=features_handle.semantic_digest,
                    pairs_artifact_id=pairs_handle.artifact_id,
                    pairs_semantic_digest=pairs_handle.semantic_digest,
                    method_id=settings.method_id,
                    settings=settings,
                    descriptor=features.descriptor,
                    backend_numerical_identity=backend.numerical_identity,
                    models=backend.model_identities(),
                    requested_pair_count=len(pairs.pairs),
                    processed_pair_count=len(summaries),
                    matched_pair_count=sum(p.raw_match_count > 0 for p in summaries),
                    zero_match_pair_count=sum(p.raw_match_count == 0 for p in summaries),
                    total_raw_match_count=sum(p.raw_match_count for p in summaries),
                    pairs=summaries,
                    semantic_digest="0" * 64,
                )
                value = MatchSet.model_validate(
                    {**value.model_dump(), "semantic_digest": match_semantic_digest(value)}
                )
                repo.write_matching_metadata(workspace, value)
                return value

            return self._execute(root, owner, route, produce)

    def verify(
        self,
        root: Path,
        *,
        matches_run_id: UUID,
        settings: VerificationSettings | None = None,
        cameras: CameraPriorSet | None = None,
        resource_limits: MatchingResourceLimits | None = None,
        colmap: Path | None = None,
        resolution: ResolvedFeatureMatchingRoute | None = None,
    ) -> MatchingRunResult:
        root, owner = root.resolve(), uuid4()
        repo, limits = self._repository, resource_limits or MatchingResourceLimits()
        settings = settings or (
            resolution.choice.verification if resolution else VerificationSettings()
        )
        with repo.writer(root, owner_token=owner, operation="verification-run"):
            repo.ensure_no_unfinished_run(root)
            handle = repo.resolve_run_output(root, matches_run_id, "raw_matches", "matches")
            matches = repo.load_match_set(root, handle)
            features, pairs = repo.load_match_inputs(root, handle)
            if resolution and (
                resolution.choice.extractor != features.settings
                or resolution.choice.matcher != matches.settings
                or resolution.choice.verification != settings
            ):
                raise ValueError(
                    "Resolved profile differs from exact upstream feature/matcher settings"
                )
            cameras = cameras or uncalibrated_camera_priors(features)
            cameras = CameraPriorSet.model_validate(cameras.model_dump())
            if {v.view_id: (v.width, v.height) for v in cameras.cameras} != {
                v.view_id: (v.width, v.height) for v in features.views
            }:
                raise ValueError("Camera prior universe/dimensions differ from feature artifact")
            directory = repo.artifact_directory(root, handle)
            size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
            estimate = estimate_verification_resources(
                features, matches, settings, limits, upstream_bytes=size
            )
            backend = self._adapter.prepare(settings, colmap=colmap)
            if resolution:
                require_resolution_inputs(
                    resolution, features, matches.backend_numerical_identity, matches.models
                )
                if (
                    resolution.decisions[-1].verification_backend_identity
                    != backend.numerical_identity
                ):
                    raise ValueError(
                        "Resolved verification backend changed; resolve the route again"
                    )
            route = GeometricVerificationRoute(
                matches_run_id=matches_run_id,
                matches=handle,
                settings=settings,
                cameras=cameras,
                backend=backend,
                resource_limits=limits,
                estimate=estimate,
                resolution=resolution,
            )

            def produce(workspace, control, evidence, phase):
                summaries = self._adapter.verify(
                    workspace,
                    backend=backend,
                    settings=settings,
                    match_directory=directory,
                    matches=matches,
                    features=features,
                    pairs=pairs,
                    cameras=cameras,
                    limits=limits,
                    estimate=estimate,
                    cancellation=control,
                    evidence_sink=evidence,
                    phase_sink=phase,
                )
                accepted = sum(p.state == "verified" for p in summaries)
                value = VerifiedGeometrySet.model_construct(
                    matches_artifact_id=handle.artifact_id,
                    matches_semantic_digest=handle.semantic_digest,
                    settings=settings,
                    camera_prior_digest=cameras.semantic_digest,
                    backend_numerical_identity=backend.numerical_identity,
                    input_pair_count=len(summaries),
                    eligible_pair_count=matches.matched_pair_count,
                    accepted_pair_count=accepted,
                    rejected_pair_count=len(summaries) - accepted,
                    total_raw_matches=matches.total_raw_match_count,
                    total_verified_inliers=sum(p.inlier_count for p in summaries),
                    pairs=summaries,
                    semantic_digest="0" * 64,
                )
                value = VerifiedGeometrySet.model_validate(
                    {**value.model_dump(), "semantic_digest": geometry_semantic_digest(value)}
                )
                repo.write_matching_metadata(workspace, value, cameras)
                return value

            return self._execute(root, owner, route, produce)

    def _execute(
        self,
        root: Path,
        owner: UUID,
        route: FeatureMatchingRoute | GeometricVerificationRoute,
        produce: Callable,
    ) -> MatchingRunResult:
        repo = self._repository
        project = repo.inspect_project(root)
        if project.state_version != 4:
            raise StateUpgradeRequiredError("Run 'splatforge project upgrade-state <project>'")
        repo.ensure_no_unfinished_run(root)
        run_id = uuid4()
        repo.create_run(
            root,
            RunSnapshot(
                run_id=run_id,
                project_id=project.document.project_id,
                project_revision=project.document.revision,
                owner_token=owner,
                created_at=datetime.now(UTC),
                project_intent=project.document,
                route=route,
            ),
        )
        progress = self._progress.session(
            run_id,
            (matching_progress_plan(route, self._progress.hardware),),
            emit=lambda node, attempt, details: repo.append_event(
                root,
                run_id,
                code="progress.snapshot",
                node_id=node,
                attempt_id=attempt,
                details=details,
            ),
        )
        control = _Cancellation(repo, root, run_id)
        attempt, payload, artifact, cache_hit = None, None, None, False
        warnings = []

        def event(code: str, **details: object) -> None:
            try:
                warning = repo.append_event(
                    root,
                    run_id,
                    code=code,
                    node_id=route.node_id,
                    attempt_id=control.attempt,
                    details=details,
                )
                if warning:
                    warnings.append(warning.message)
            except Exception:
                warnings.append("events.append_failed")

        def evidence(record: ProcessInvocationEvidence) -> None:
            try:
                warning = repo.append_process_evidence(root, run_id, control.attempt, record)
                if warning:
                    warnings.append(warning.message)
            except Exception:
                warnings.append("process_diagnostics.append_failed")

        def phase(name: str) -> None:
            progress.report(route.node_id, 0, phase=name)

        try:
            event("matching.run.started", method=route.settings.method_id)
            control.checkpoint()
            cached = repo.find_cache(
                root,
                recipe_key=route.recipe_key(),
                artifact_type=route.target.artifact_type,
                contract_version=1,
            )
            if cached.artifact:
                payload = (
                    repo.load_match_set(root, cached.artifact)
                    if isinstance(route, FeatureMatchingRoute)
                    else repo.load_verified_geometry(root, cached.artifact)
                )
                require_route_payload(route, payload)
                control.checkpoint()
                repo.bind_cached_output(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    artifact_id=cached.artifact.artifact_id,
                )
                artifact, cache_hit = cached.artifact, True
                progress.cached(route.node_id)
                event("matching.stage.cache_hit", artifact_id=str(artifact.artifact_id))
            else:
                event("matching.stage.cache_miss", reasons=[v.reason for v in cached.ineligible])
                attempt = repo.begin_attempt(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    recipe_key=route.recipe_key(),
                    input_artifact_ids=tuple(i.artifact_id for i in route.input_lineage()),
                    literal_inputs=route.literal_inputs(),
                    environment=route.backend.model_dump(mode="json"),
                    source_verification={"policy": "artifact_integrity", "evidence": []},
                )
                control.attempt = attempt.attempt_id
                progress.start(route.node_id, attempt.attempt_id)
                payload = produce(Path(attempt.workspace), control, evidence, phase)
                require_route_payload(route, payload)
                control.checkpoint()
                artifact = repo.publish_attempt(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    artifact_type=route.target.artifact_type,
                    contract_version=1,
                    recipe_key=route.recipe_key(),
                    attempt=attempt,
                    input_lineage=route.input_lineage(),
                )
                event("matching.stage.published", artifact_id=str(artifact.artifact_id))
            control.checkpoint()
            repo.mark_run_succeeded(root, run_id=run_id)
            status = RunStatus.SUCCEEDED
            if not cache_hit:
                progress.complete(route.node_id)
            event("matching.run.completed")
        except FeatureTeardownError as exc:
            repo.mark_external_interrupted(
                root, run_id=run_id, attempt_id=control.attempt, message=str(exc)
            )
            raise
        except (ExecutionCancelledError, FeatureCancelledError) as exc:
            if not control.accepted and not control.is_cancelled():
                if attempt:
                    repo.mark_attempt_failed(
                        root,
                        attempt_id=attempt.attempt_id,
                        message=str(exc),
                        category=FailureCategory.NON_RETRYABLE,
                    )
                repo.mark_run_failed(root, run_id=run_id, message=str(exc))
                raise ValueError("Backend cancelled without durable owner acceptance") from exc
            status = repo.finish_cancellation(
                root, run_id=run_id, attempt_id=control.attempt, teardown_confirmed=True
            )
            payload, artifact = None, None
            event("matching.run.cancelled")
        except PublicationUnresolvedError:
            raise
        except Exception as exc:
            if attempt:
                repo.mark_attempt_failed(
                    root,
                    attempt_id=attempt.attempt_id,
                    message=str(exc),
                    category=FailureCategory.NON_RETRYABLE,
                )
            repo.mark_run_failed(root, run_id=run_id, message=str(exc))
            event("matching.run.failed", error=str(exc))
            raise
        raw = (
            payload.total_raw_match_count
            if isinstance(payload, MatchSet)
            else payload.total_raw_matches
            if payload
            else 0
        )
        return MatchingRunResult(
            run_id=run_id,
            status=status,
            method_id=route.settings.method_id,
            artifact=artifact,
            pair_count=(len(payload.pairs) if payload else route.estimate.pair_count),
            raw_matches=raw,
            accepted_pairs=payload.accepted_pair_count
            if isinstance(payload, VerifiedGeometrySet)
            else None,
            verified_inliers=payload.total_verified_inliers
            if isinstance(payload, VerifiedGeometrySet)
            else None,
            cache_hit=cache_hit,
            warnings=tuple(warnings) + progress.snapshot().warnings,
        )


def require_resolution_inputs(
    resolution: ResolvedFeatureMatchingRoute,
    features: LocalFeatureSet,
    matcher_backend_identity: str,
    matcher_models: tuple[LearnedModelIdentity, ...],
) -> None:
    decision = resolution.decisions[-1]
    if (
        decision.extractor_backend_identity != features.backend_numerical_identity
        or decision.matcher_backend_identity != matcher_backend_identity
        or numerical_models(decision.extractor_models) != numerical_models(features.models)
        or numerical_models(decision.matcher_models) != numerical_models(matcher_models)
    ):
        raise ValueError(
            "Resolved feature/matcher backend or model identity changed; "
            "resolve the route again using current capabilities"
        )


def require_route_payload(
    route: FeatureMatchingRoute | GeometricVerificationRoute,
    payload: MatchSet | VerifiedGeometrySet,
) -> None:
    if (
        payload.settings != route.settings
        or payload.backend_numerical_identity != route.backend.numerical_identity
    ):
        raise ValueError("M7b output differs from frozen numerical recipe")
    if isinstance(route, FeatureMatchingRoute):
        if (
            not isinstance(payload, MatchSet)
            or payload.features_semantic_digest != route.features.semantic_digest
            or payload.pairs_semantic_digest != route.pairs.semantic_digest
            or payload.descriptor != route.descriptor
            or [m.sha256 for m in payload.models]
            != [m.sha256 for m in route.backend.model_identities()]
        ):
            raise ValueError("MatchSet differs from frozen upstream/model identity")
    elif (
        not isinstance(payload, VerifiedGeometrySet)
        or payload.matches_semantic_digest != route.matches.semantic_digest
        or payload.camera_prior_digest != route.cameras.semantic_digest
    ):
        raise ValueError("Verified geometry differs from frozen matches/cameras")
