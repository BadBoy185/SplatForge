"""Isolated native explicit-pair matching and standalone geometric verification."""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_features import (
    FeatureProcessRunner,
    copy_pinned,
    hash_file,
    native_transport_path,
    runtime_files,
)
from splatforge.adapters.colmap_matching_options import matching_arguments, verification_arguments
from splatforge.adapters.colmap_runtime import scoped_runtime_environment
from splatforge.adapters.feature_database import (
    NativeFeaturePayload,
    seal_feature_database,
    validate_feature_payload,
)
from splatforge.adapters.local_models import reports_cpu_fallback
from splatforge.adapters.matching_database import (
    assemble_camera_priors,
    inspect_raw_matches,
    inspect_verified_geometry,
    validate_camera_priors,
)
from splatforge.adapters.process_diagnostics import invocation_evidence
from splatforge.adapters.process_runner import (
    ExecutableResolver,
    LocalProcessRunner,
    ProcessBoundaryError,
    ProcessCleanupError,
    ProcessRequest,
)
from splatforge.application.features_contracts import (
    FeatureCancellation,
    FeatureCancelledError,
    FeatureCapabilityError,
    FeatureProcessError,
    FeatureResourceError,
    FeatureTeardownError,
    FeatureTimeoutError,
)
from splatforge.core.capabilities import CapabilityStatus, FreshnessPolicy
from splatforge.core.features import FeatureSettings, LocalFeatureSet, digest_json
from splatforge.core.geometry import CameraPriorSet, GeometryPairSummary, VerificationSettings
from splatforge.core.matching import (
    MatcherSettings,
    MatchingBackend,
    MatchingResourceEstimate,
    MatchingResourceLimits,
    MatchSet,
    RawPairSummary,
    matcher_model_role,
    validate_matcher_compatibility,
)
from splatforge.core.pairs import PairSet
from splatforge.core.process import ProcessInvocationEvidence


class ColmapMatchingAdapter:
    def __init__(
        self,
        *,
        runner: FeatureProcessRunner | None = None,
        resolver: ExecutableResolver | None = None,
        capability_adapter: ColmapCapabilityAdapter | None = None,
    ) -> None:
        self._resolver = resolver or ExecutableResolver()
        self._runner = runner or LocalProcessRunner(self._resolver)
        self._capabilities = capability_adapter or ColmapCapabilityAdapter(
            runner=self._runner,
            resolver=self._resolver,
        )
        self._prepared: dict[tuple, tuple[datetime, MatchingBackend]] = {}

    def prepare(
        self,
        settings: MatcherSettings | VerificationSettings,
        *,
        feature_settings: FeatureSettings | None = None,
        colmap: Path | None = None,
        model_directory: Path | None = None,
    ) -> MatchingBackend:
        verification = isinstance(settings, VerificationSettings)
        key = (
            settings.model_dump_json(),
            feature_settings.model_dump_json() if feature_settings else None,
            str(colmap),
            str(model_directory),
            self._capabilities.configuration_key(),
        )
        now = datetime.now(UTC)
        cached = self._prepared.get(key)
        if cached and (now - cached[0]).total_seconds() < 30:
            backend = cached[1]
            if (
                self._resolver.verify_expected_identity(backend.selection.identity)
                and self._capabilities.verify_model_identities(backend.models)
                and runtime_files(backend.selection) == backend.runtime_files
            ):
                return backend
        report = self._capabilities.probe(
            explicit_executable=colmap.absolute() if colmap else None,
            explicit_model_directory=model_directory.absolute() if model_directory else None,
            bundled_executable=None,
            bundled_model_directory=None,
            deep=True,
            observed_at=now,
            freshness=FreshnessPolicy(),
            feature_settings=feature_settings,
            matching_settings=None if verification else settings,
            verification_only=verification,
        )
        cid = (
            "colmap.verification.standalone"
            if verification
            else f"colmap.match.{settings.variant.lower()}.{'gpu' if settings.use_gpu else 'cpu'}"
        )
        capability = report.capability(cid)
        if (
            report.binary.status != CapabilityStatus.AVAILABLE
            or report.database.evidence.status != CapabilityStatus.AVAILABLE
            or capability.status != CapabilityStatus.AVAILABLE
        ):
            raise FeatureCapabilityError(
                f"{settings.method_id}: {capability.status}: {capability.message}; "
                f"database: {report.database.evidence.message}. "
                "Run doctor --deep with local models.",
                evidence=(capability, report.database.evidence),
            )
        selection = report.selected_executable
        assert selection is not None
        operation = "geometric_verifier" if verification else "matches_importer"
        options = next(
            s.option_names for s in report.command_discovery.subcommands if s.command == operation
        )
        role = None if verification else matcher_model_role(settings)
        models = tuple(m for m in report.models if m.role == role)
        runtime = runtime_files(selection)
        numerical = digest_json(
            {
                "adapter_version": 1,
                "executable_sha256": selection.identity.sha256,
                "version": selection.identity.version_line,
                "runtime_profile": selection.runtime_layout.profile
                if selection.runtime_layout
                else None,
                "schema": report.database.model_dump(mode="json", exclude={"evidence"}),
                "runtime_files": [r.model_dump(exclude={"path"}) for r in runtime],
            }
        )
        backend = MatchingBackend(
            operation=operation,
            selection=selection,
            database=report.database,
            option_names=options,
            models=models,
            runtime_files=runtime,
            numerical_identity=numerical,
            actual_precision=(
                "float64"
                if verification
                else "native_sift"
                if settings.variant == "SIFT_BRUTEFORCE"
                else "fp32"
            ),
            capability_evidence=(capability,),
        )
        # Validate exact requested numerical controls before creating an attempt.
        if verification:
            verification_arguments(settings, options, database=Path("p.db"))
        else:
            matching_arguments(
                settings,
                options,
                database=Path("p.db"),
                pairs=Path("pairs.txt"),
                models={m.role: Path(m.resolved_path) for m in models},
            )
        if len(self._prepared) >= 32:
            self._prepared.clear()
        self._prepared[key] = (datetime.now(UTC), backend)
        return backend

    @staticmethod
    def _copy(source: Path, target: Path, cancellation: FeatureCancellation) -> None:
        if source.is_symlink() or source.is_junction():
            raise ValueError("Redirected upstream matching payload")
        copy_pinned(
            source,
            target,
            size=source.stat().st_size,
            digest=hash_file(source),
            cancellation=cancellation,
        )
        if source.samefile(target) or target.stat().st_nlink != 1:
            raise ValueError("Writable upstream link is forbidden")

    def match(
        self,
        workspace: Path,
        *,
        backend: MatchingBackend,
        settings: MatcherSettings,
        feature_directory: Path,
        pair_directory: Path,
        features: LocalFeatureSet,
        pairs: PairSet,
        limits: MatchingResourceLimits,
        estimate: MatchingResourceEstimate,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        phase_sink: Callable[[str], None],
    ) -> tuple[RawPairSummary, ...]:
        validate_matcher_compatibility(features.descriptor, settings)
        mapping = validate_feature_payload(feature_directory, features)
        self._require_schema(mapping, backend)
        output = workspace / "output"
        output.mkdir()
        phase_sink("copying_features")
        self._preflight(workspace, backend, estimate, cancellation)
        for name in ("features.json", "backend_mapping.json"):
            self._copy(feature_directory / name, output / name, cancellation)
        self._copy(pair_directory / "pair_set.json", output / "pair_set.json", cancellation)
        database = output / "matches.db"
        self._copy(feature_directory / "features.db", database, cancellation)
        with closing(sqlite3.connect(database)) as db, db:
            # This is only an owned independent copy. Upstream validation refuses
            # stale publications; clearing additionally protects recipe isolation.
            db.execute("DELETE FROM matches")
            db.execute("DELETE FROM two_view_geometries")
        names = {i.view_id: i.image_name for i in mapping.images}
        pair_list = workspace / "pairs.txt"
        with pair_list.open("x", encoding="utf-8", newline="\n") as stream:
            for p in pairs.pairs:
                stream.write(f"{names[p.left_view_id]} {names[p.right_view_id]}\n")
        models = {}
        for model in backend.models:
            if not model.compatibility_verified:
                raise FeatureCapabilityError("Matcher model lacks functional inference evidence")
            target = workspace / (model.role + ".onnx")
            copy_pinned(
                Path(model.resolved_path),
                target,
                size=model.size,
                digest=model.sha256,
                cancellation=cancellation,
            )
            models[model.role] = native_transport_path(target)
        argv = matching_arguments(
            settings,
            backend.option_names,
            database=native_transport_path(database),
            pairs=native_transport_path(pair_list),
            models=models,
        )
        phase_sink("matching_explicit_pairs")
        self._run(
            workspace,
            backend,
            argv,
            database,
            limits,
            estimate,
            cancellation,
            evidence_sink,
            phase_sink,
        )
        phase_sink("validating_raw_matches")
        seal_feature_database(database)
        summaries = inspect_raw_matches(
            database,
            features,
            pairs,
            mapping,
            maximum_matches=settings.max_num_matches,
            maximum_bytes=estimate.database_bytes,
        )
        if sum(p.raw_match_count for p in summaries) > min(
            limits.max_raw_matches, estimate.raw_matches
        ):
            raise FeatureResourceError(
                "Raw correspondence output exceeds its frozen resource bound"
            )
        return summaries

    def verify(
        self,
        workspace: Path,
        *,
        backend: MatchingBackend,
        settings: VerificationSettings,
        match_directory: Path,
        matches: MatchSet,
        features: LocalFeatureSet,
        pairs: PairSet,
        cameras: CameraPriorSet,
        limits: MatchingResourceLimits,
        estimate: MatchingResourceEstimate,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        phase_sink: Callable[[str], None],
    ) -> tuple[GeometryPairSummary, ...]:
        mapping = NativeFeaturePayload.model_validate_json(
            (match_directory / "backend_mapping.json").read_bytes(),
        )
        self._require_schema(mapping, backend)
        output = workspace / "output"
        output.mkdir()
        phase_sink("copying_raw_matches")
        self._preflight(workspace, backend, estimate, cancellation)
        for name in (
            "features.json",
            "backend_mapping.json",
            "pair_set.json",
            "match_set.json",
            "matches.db",
        ):
            self._copy(match_directory / name, output / name, cancellation)
        database = output / "matches.db"
        observed = inspect_raw_matches(
            database,
            features,
            pairs,
            mapping,
            maximum_matches=matches.settings.max_num_matches,
            maximum_bytes=estimate.database_bytes,
        )
        if observed != matches.pairs:
            raise ValueError("Corrupted upstream MatchSet numerical output")
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("DELETE FROM two_view_geometries")
        assemble_camera_priors(database, cameras, features, mapping)
        phase_sink("verifying_raw_pairs")
        argv = verification_arguments(
            settings, backend.option_names, database=native_transport_path(database)
        )
        self._run(
            workspace,
            backend,
            argv,
            database,
            limits,
            estimate,
            cancellation,
            evidence_sink,
            phase_sink,
        )
        phase_sink("validating_geometry")
        seal_feature_database(database)
        validate_camera_priors(database, cameras, mapping)
        return inspect_verified_geometry(
            database,
            features,
            pairs,
            mapping,
            matches,
            settings,
            maximum_bytes=estimate.database_bytes,
        )

    @staticmethod
    def _require_schema(mapping: NativeFeaturePayload, backend: MatchingBackend) -> None:
        schema = backend.database
        if (mapping.user_version, mapping.application_id, mapping.tables) != (
            schema.sqlite_user_version,
            schema.sqlite_application_id,
            schema.tables,
        ):
            raise FeatureCapabilityError(
                "Upstream native schema differs from the verified matching backend; "
                "use a compatible backend or explicitly rebuild features"
            )

    def _preflight(self, workspace, backend, estimate, cancellation):
        if cancellation.is_cancelled():
            raise FeatureCancelledError("Cancelled before native launch")
        if not self._resolver.verify_expected_identity(backend.selection.identity):
            raise FeatureCapabilityError("COLMAP executable changed; re-plan")
        if runtime_files(backend.selection) != backend.runtime_files:
            raise FeatureCapabilityError("COLMAP runtime changed; re-plan")
        if shutil.disk_usage(workspace).free < estimate.peak_workspace_bytes:
            raise FeatureResourceError("Insufficient free disk for private database copies")

    def _run(
        self,
        workspace,
        backend,
        argv,
        database,
        limits,
        estimate,
        cancellation,
        evidence_sink,
        phase_sink,
    ):
        self._preflight(workspace, backend, estimate, cancellation)
        request = ProcessRequest(
            executable=backend.selection.identity.resolved_path,
            argv=argv,
            working_directory=workspace,
            environment=scoped_runtime_environment(backend.selection.runtime_layout, os.environ),
            timeout_seconds=limits.timeout_seconds,
            max_stdout_bytes=256 * 1024,
            max_stderr_bytes=256 * 1024,
            expected_executable=backend.selection.identity,
        )

        def poll():
            phase_sink(
                "matching_explicit_pairs"
                if backend.operation == "matches_importer"
                else "verifying_raw_pairs"
            )

        class BudgetCancellation:
            owner = cancellation
            failure = None
            next_check = 0.0

            def is_cancelled(self):
                if cancellation.is_cancelled():
                    return True
                if time.monotonic() >= self.next_check:
                    self.next_check = time.monotonic() + 0.25
                    try:
                        size = sum(
                            p.stat().st_size for p in database.parent.iterdir() if p.is_file()
                        )
                        if size > estimate.database_bytes or size > limits.max_workspace_bytes:
                            self.failure = "Native matching database growth budget exceeded"
                    except OSError as exc:
                        self.failure = f"Native workspace resource observation failed: {exc}"
                return self.failure is not None

        budget_control = BudgetCancellation()

        result, error = None, None
        started = time.monotonic()
        try:
            result = self._runner.run(request, cancellation=budget_control, poll=poll)
        except ProcessCleanupError as exc:
            error = exc
            if not exc.teardown_confirmed:
                raise FeatureTeardownError(str(exc)) from exc
            raise FeatureProcessError(str(exc)) from exc
        except (ProcessBoundaryError, OSError) as exc:
            error = exc
            raise FeatureProcessError(str(exc)) from exc
        finally:
            evidence_sink(
                invocation_evidence(
                    request,
                    executable=backend.selection.identity,
                    diagnostic_argv=argv,
                    tool_role="colmap." + backend.operation,
                    source_id=None,
                    elapsed_seconds=time.monotonic() - started,
                    result=result,
                    error=error,
                )
            )
        if not result.teardown_confirmed:
            raise FeatureTeardownError("Native matching process-tree teardown unresolved")
        if budget_control.failure:
            raise FeatureResourceError(budget_control.failure)
        if result.cancelled:
            raise FeatureCancelledError("Native matching cancelled after confirmed teardown")
        if result.timed_out:
            raise FeatureTimeoutError("Native matching timed out after confirmed teardown")
        if result.forced_tree_termination:
            raise FeatureProcessError("Native matching required forced process-tree termination")
        if ("--FeatureMatching.use_gpu" in argv
                and argv[argv.index("--FeatureMatching.use_gpu") + 1] == "1"
                and reports_cpu_fallback(result)):
            raise FeatureProcessError(
                "Frozen GPU matching reported CPU fallback; re-plan explicitly"
            )
        if result.exit_code != 0:
            message = (result.stderr_text() or result.stdout_text())[:2048]
            if any(t in message.lower() for t in ("out of memory", "cuda_error_out_of_memory")):
                raise FeatureResourceError("GPU/host OOM: " + message)
            raise FeatureProcessError(f"Native backend exit {result.exit_code}: {message}")
        if (
            not self._resolver.verify_expected_identity(backend.selection.identity)
            or result.executable.model_copy(update={"version_line": None})
            != backend.selection.identity.model_copy(update={"version_line": None})
            or runtime_files(backend.selection) != backend.runtime_files
        ):
            raise FeatureCapabilityError("Native matching executable/runtime identity changed")
        poll()
