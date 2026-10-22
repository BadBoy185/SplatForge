"""Native COLMAP extraction using the existing contained process boundary."""

from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_runtime import scoped_runtime_environment
from splatforge.adapters.feature_database import inspect_feature_database, seal_feature_database
from splatforge.adapters.feature_progress import FeatureProgressReader
from splatforge.adapters.local_models import local_model_argument, reports_cpu_fallback
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
    FeatureProgress,
    FeatureResourceError,
    FeatureTeardownError,
    FeatureTimeoutError,
)
from splatforge.core.capabilities import CapabilityStatus, ExecutableSelection, FreshnessPolicy
from splatforge.core.features import (
    AlikedExtractionSettings,
    FeatureBackend,
    FeatureRuntimeFile,
    FeatureSettings,
    FeatureViewSummary,
    LomaExtractionSettings,
    SiftExtractionSettings,
    digest_json,
    model_roles,
)
from splatforge.core.process import ProcessInvocationEvidence, ProcessResult
from splatforge.core.views import CandidateView, canonical_json_bytes

MODEL_OPTIONS = {
    "aliked.n16rot": "AlikedExtraction.n16rot_model_path",
    "aliked.n32": "AlikedExtraction.n32_model_path",
    "loma.detector": "LomaExtraction.detector_model_path",
    "loma.b": "LomaExtraction.descriptor_model_path",
    "loma.b128": "LomaExtraction.descriptor_b128_model_path",
}


def extraction_arguments(
    settings: FeatureSettings,
    options: tuple[str, ...],
    *,
    database: Path,
    images: Path,
    models: dict[str, Path],
) -> tuple[str, ...]:
    """Reject unsupported slots individually; never substitute another algorithm."""
    names = set(options)
    values: list[tuple[str, object]] = [("database_path", database), ("image_path", images)]
    if "FeatureExtraction.type" in names:
        values.append(("FeatureExtraction.type", settings.variant))
    elif settings.variant != "SIFT":
        raise FeatureCapabilityError("Backend lacks typed extractor selection")
    common = "FeatureExtraction" if "FeatureExtraction.use_gpu" in names else "SiftExtraction"
    values.extend(
        (
            (f"{common}.use_gpu", int(settings.use_gpu)),
            (f"{common}.max_image_size", settings.max_image_size),
            (f"{common}.num_threads", 1),
        )
    )
    if settings.use_gpu:
        values.append((f"{common}.gpu_index", "0"))
    family = (
        "SiftExtraction"
        if isinstance(settings, SiftExtractionSettings)
        else "AlikedExtraction"
        if isinstance(settings, AlikedExtractionSettings)
        else "LomaExtraction"
    )
    values.append((f"{family}.max_num_features", settings.max_features))
    if isinstance(settings, (AlikedExtractionSettings, LomaExtractionSettings)):
        values.append((f"{family}.min_score", settings.min_score))
    if isinstance(settings, LomaExtractionSettings):
        # Explicit FP32 prevents URL-backed BF16 fallback/downloads.
        values.extend(
            (
                ("LomaExtraction.use_bf16", 0),
                ("LomaExtraction.use_fast_resize", int(settings.use_fast_resize)),
            )
        )
    values.extend((MODEL_OPTIONS[role], local_model_argument(models[role]))
                  for role in model_roles(settings))
    missing = [name for name, _ in values if name not in names]
    if missing:
        raise FeatureCapabilityError(
            "Unsupported backend extraction options: " + ", ".join(missing)
        )
    return (
        "feature_extractor",
        *(arg for name, value in values for arg in (f"--{name}", str(value))),
    )


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def native_transport_path(path: Path) -> Path:
    """Use an existing Windows short alias; create no links and change no identity."""
    absolute = path.absolute()
    if os.name != "nt" or str(absolute).isascii():
        return absolute
    existing = absolute if absolute.exists() else absolute.parent
    buffer = ctypes.create_unicode_buffer(32768)
    get_short = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    get_short.restype = ctypes.c_uint32
    count = get_short(str(existing), buffer, len(buffer))
    if not 0 < count < len(buffer) or not buffer.value.isascii():
        raise FeatureCapabilityError(
            "COLMAP requires an ASCII transport path on this Windows build; "
            "no existing short alias is available. Use an ASCII project location."
        )
    return Path(buffer.value) if absolute.exists() else Path(buffer.value) / absolute.name


def runtime_files(selection: ExecutableSelection) -> tuple[FeatureRuntimeFile, ...]:
    roots = (
        [Path(p) for p in selection.runtime_layout.path_entries]
        if selection.runtime_layout
        else [Path(selection.identity.resolved_path).parent]
    )
    records = []
    for index, root in enumerate(roots):
        for path in sorted(root.glob("*.dll"), key=lambda p: p.name.casefold()):
            if len(records) >= 1024 or path.is_symlink() or path.is_junction():
                raise FeatureCapabilityError("Unbounded or redirected COLMAP runtime layout")
            size = path.stat().st_size
            if not 0 < size <= 2 * 1024**3:
                raise FeatureCapabilityError("Unsupported COLMAP runtime file size")
            records.append(
                FeatureRuntimeFile(
                    name=f"{index}/{path.name.casefold()}",
                    path=str(path),
                    size=size,
                    sha256=hash_file(path),
                )
            )
    return tuple(records)


def copy_pinned(
    source: Path, target: Path, *, size: int, digest: str, cancellation: FeatureCancellation
) -> None:
    observed = hashlib.sha256()
    remaining = size
    with source.open("rb") as src, target.open("xb") as dst:
        while remaining:
            if cancellation.is_cancelled():
                raise FeatureCancelledError("Cancelled during pinned workspace copy")
            chunk = src.read(min(1024 * 1024, remaining))
            if not chunk:
                raise FeatureCapabilityError("Input identity/size changed during workspace copy")
            remaining -= len(chunk)
            dst.write(chunk)
            observed.update(chunk)
        if src.read(1) or observed.hexdigest() != digest:
            raise FeatureCapabilityError("Input identity changed during pinned workspace copy")


class FeatureProcessRunner(Protocol):
    def run(
        self,
        request: ProcessRequest,
        *,
        cancellation: FeatureCancellation | None = None,
        poll: Callable[[], None] | None = None,
    ) -> ProcessResult: ...


class ColmapFeatureAdapter:
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
        self._prepared: dict[tuple, tuple[datetime, FeatureBackend]] = {}

    def prepare(
        self,
        settings: FeatureSettings,
        *,
        colmap: Path | None = None,
        model_directory: Path | None = None,
    ) -> FeatureBackend:
        key = (settings.model_dump_json(), str(colmap), str(model_directory),
               self._capabilities.configuration_key())
        now = datetime.now(UTC)
        cached = self._prepared.get(key)
        if cached and (now - cached[0]).total_seconds() < 30:
            backend = cached[1]
            if (self._resolver.verify_expected_identity(backend.selection.identity)
                    and self._capabilities.verify_model_identities(backend.models)
                    and runtime_files(backend.selection) == backend.runtime_files):
                return backend
        report = self._capabilities.probe(
            explicit_executable=colmap.absolute() if colmap else None,
            explicit_model_directory=model_directory.absolute() if model_directory else None,
            bundled_executable=None,
            bundled_model_directory=None,
            deep=True,
            observed_at=now,
            freshness=FreshnessPolicy(),
            feature_settings=settings,
        )
        device = "gpu" if settings.use_gpu else "cpu"
        capability = report.capability(f"colmap.feature.{settings.variant.lower()}.{device}")
        if (
            report.binary.status != CapabilityStatus.AVAILABLE
            or report.database.evidence.status != CapabilityStatus.AVAILABLE
            or capability.status != CapabilityStatus.AVAILABLE
        ):
            model_gaps = " ".join(
                m.evidence.message
                for m in report.models
                if m.role in model_roles(settings)
                and m.evidence.status != CapabilityStatus.AVAILABLE
            )
            raise FeatureCapabilityError(
                f"{settings.variant}: {capability.status.value}: {capability.message}; "
                f"database: {report.database.evidence.message}. "
                f"{model_gaps} Run doctor --deep with local models.",
                evidence=(capability, report.database.evidence),
            )
        selection = report.selected_executable
        assert selection is not None
        models = tuple(
            next(m for m in report.models if m.role == role) for role in model_roles(settings)
        )
        options = next(
            s.option_names
            for s in report.command_discovery.subcommands
            if s.command == "feature_extractor"
        )
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
        backend = FeatureBackend(
            selection=selection,
            database=report.database,
            models=models,
            option_names=options,
            numerical_identity=numerical,
            capability_evidence=(capability,),
            runtime_files=runtime,
            live_progress_profile=(
                "colmap_4.2.1_v1"
                if (selection.identity.version_line or "").startswith("COLMAP 4.2.1 ")
                and {"log_target", "log_path"} <= set(options)
                else None
            ),
        )
        extraction_arguments(
            settings,
            options,
            database=Path("features.db"),
            images=Path("images"),
            models={m.role: Path(m.resolved_path) for m in models},
        )
        if len(self._prepared) >= 32:
            self._prepared.clear()
        self._prepared[key] = (now, backend)
        return backend

    def extract(
        self,
        workspace: Path,
        *,
        backend: FeatureBackend,
        settings: FeatureSettings,
        candidate_directory: Path,
        views: tuple[CandidateView, ...],
        timeout_seconds: int,
        maximum_database_bytes: int,
        minimum_free_bytes: int,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        progress_sink: Callable[[FeatureProgress], None] | None = None,
    ) -> tuple[FeatureViewSummary, ...]:
        if not self._resolver.verify_expected_identity(backend.selection.identity):
            raise FeatureCapabilityError("COLMAP executable identity changed; re-plan extraction")
        if runtime_files(backend.selection) != backend.runtime_files:
            raise FeatureCapabilityError("COLMAP runtime identity changed; re-plan extraction")
        images, output = workspace / "images", workspace / "output"
        images.mkdir()
        output.mkdir()
        if shutil.disk_usage(workspace).free < minimum_free_bytes:
            raise FeatureResourceError("Insufficient space for the estimated feature workspace")
        summaries = []
        for view in sorted(views, key=lambda v: v.view_id.int):
            if cancellation.is_cancelled():
                raise FeatureCancelledError("Cancelled before backend launch")
            source = candidate_directory / view.image_path
            target = images / f"{view.view_id}{source.suffix}"
            # An independent copy; no writable link to an immutable upstream payload.
            copy_pinned(
                source,
                target,
                size=source.stat().st_size,
                digest=view.image_sha256,
                cancellation=cancellation,
            )
            summaries.append(
                FeatureViewSummary(
                    view_id=view.view_id,
                    image_sha256=view.image_sha256,
                    width=view.width,
                    height=view.height,
                    feature_count=0,
                    keypoint_columns=2,
                    content_digest="0" * 64,
                )
            )
        models = {}
        if backend.models:
            (workspace / "models").mkdir()
        for model in backend.models:
            if not model.compatibility_verified or not model.resolved_path or not model.sha256:
                raise FeatureCapabilityError(
                    "Learned model lacks functional compatibility evidence"
                )
            source = Path(model.resolved_path)
            if source.is_symlink() or source.is_junction():
                raise FeatureCapabilityError("Redirected learned model")
            target = workspace / "models" / (model.role + ".onnx")
            copy_pinned(
                source, target, size=model.size, digest=model.sha256, cancellation=cancellation
            )
            models[model.role] = target
        database = output / "features.db"
        # Official Windows builds use narrow APIs while making paths absolute;
        # existing short aliases preserve owned Unicode workspaces without links.
        argv = extraction_arguments(
            settings,
            backend.option_names,
            database=native_transport_path(database),
            images=native_transport_path(images),
            models={role: native_transport_path(path) for role, path in models.items()},
        )
        reader = None
        if backend.live_progress_profile is not None and progress_sink is not None:
            log_path = workspace / "feature-progress"
            log_path.mkdir()
            argv += (
                "--log_target",
                "stderr_and_file",
                "--log_path",
                str(native_transport_path(log_path)),
            )
            reader = FeatureProgressReader(
                log_path,
                frozenset(v.view_id for v in views),
                settings.variant,
                settings.max_features,
                progress_sink,
            )
        request = ProcessRequest(
            executable=backend.selection.identity.resolved_path,
            argv=argv,
            working_directory=workspace,
            environment=scoped_runtime_environment(backend.selection.runtime_layout, os.environ),
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=256 * 1024,
            max_stderr_bytes=256 * 1024,
            expected_executable=backend.selection.identity,
        )
        started = time.monotonic()
        result = None
        error = None
        try:
            result = self._runner.run(
                request, cancellation=cancellation, poll=reader.poll if reader else None
            )
        except ProcessCleanupError as exc:
            error = exc
            if not exc.teardown_confirmed:
                raise FeatureTeardownError(str(exc)) from exc
            raise FeatureProcessError(str(exc)) from exc
        except (ProcessBoundaryError, OSError) as exc:
            error = exc
            raise FeatureProcessError(str(exc)) from exc
        finally:
            evidence = invocation_evidence(
                request,
                executable=backend.selection.identity,
                diagnostic_argv=argv,
                tool_role="colmap.feature_extraction",
                source_id=None,
                elapsed_seconds=time.monotonic() - started,
                result=result,
                error=error,
            )
            evidence_sink(evidence)
        if not result.teardown_confirmed:
            raise FeatureTeardownError("COLMAP process-tree teardown is unresolved")
        if result.cancelled:
            raise FeatureCancelledError("COLMAP extraction cancelled after confirmed teardown")
        if result.timed_out:
            raise FeatureTimeoutError("COLMAP extraction timed out after confirmed teardown")
        if result.forced_tree_termination:
            raise FeatureProcessError("COLMAP required forced tree termination")
        if settings.use_gpu and reports_cpu_fallback(result):
            raise FeatureProcessError(
                "Frozen GPU extraction reported CPU fallback; re-plan explicitly"
            )
        if result.exit_code != 0:
            message = (result.stderr_text() or result.stdout_text())[:1024]
            if any(t in message.lower() for t in ("out of memory", "cuda_error_out_of_memory")):
                raise FeatureResourceError("COLMAP GPU/host OOM: " + message)
            raise FeatureProcessError(f"COLMAP exit {result.exit_code}: {message}")
        if not self._resolver.verify_expected_identity(
            backend.selection.identity
        ) or result.executable.model_copy(
            update={"version_line": None}
        ) != backend.selection.identity.model_copy(update={"version_line": None}):
            raise FeatureCapabilityError("COLMAP executable identity changed during extraction")
        if runtime_files(backend.selection) != backend.runtime_files:
            raise FeatureCapabilityError("COLMAP runtime changed during extraction")
        if reader:
            reader.poll()
        schema = backend.database
        seal_feature_database(database)
        checked, mapping = inspect_feature_database(
            database,
            tuple(summaries),
            settings,
            maximum_bytes=maximum_database_bytes,
            expected_schema=(
                schema.sqlite_user_version,
                schema.sqlite_application_id,
                schema.tables,
            ),
        )
        with (output / "backend_mapping.json").open("xb") as stream:
            stream.write(canonical_json_bytes(mapping.model_dump(mode="json")) + b"\n")
        return checked
