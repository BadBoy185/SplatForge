"""M7a functional learned-route gates within Doctor's bounded probe lifecycle."""

from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from splatforge.adapters.colmap_help import ParsedOptionHelp
from splatforge.adapters.local_models import reports_cpu_fallback
from splatforge.adapters.process_runner import ProcessBoundaryError
from splatforge.application.doctor_contracts import DoctorTeardownError
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    DatabaseCompatibility,
    FreshnessPolicy,
    ModelEvidence,
    alternative_status,
    required_status,
)
from splatforge.core.features import (
    AlikedExtractionSettings,
    FeatureSettings,
    FeatureViewSummary,
    LomaExtractionSettings,
    SiftExtractionSettings,
    model_roles,
)
from splatforge.core.media import ExecutableIdentity

if TYPE_CHECKING:
    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter


def loma_version_status(version_line: str | None) -> CapabilityStatus:
    match = re.match(r"^COLMAP (\d+)\.(\d+)\.(\d+)(?:\s|$)", version_line or "")
    if match is None:
        return CapabilityStatus.UNKNOWN
    return (
        CapabilityStatus.AVAILABLE
        if tuple(map(int, match.groups())) >= (4, 2, 1)
        else CapabilityStatus.UNAVAILABLE
    )


def probe_feature_routes(
    adapter: ColmapCapabilityAdapter,
    *,
    capabilities: tuple[CapabilityEvidence, ...],
    models: tuple[ModelEvidence, ...],
    feature: ParsedOptionHelp,
    database: DatabaseCompatibility,
    identity: ExecutableIdentity,
    deep: bool,
    observed_at: datetime,
    freshness: FreshnessPolicy,
    environment: Mapping[str, str],
    requested: FeatureSettings | None = None,
    cuda_build: CapabilityStatus = CapabilityStatus.UNKNOWN,
) -> tuple[tuple[CapabilityEvidence, ...], tuple[ModelEvidence, ...]]:
    # Imports are local to keep M5 and M7a command/validation helpers acyclic.
    from splatforge.adapters.colmap_features import extraction_arguments, hash_file
    from splatforge.adapters.feature_database import inspect_feature_database, seal_feature_database

    existing = {c.capability_id: c for c in capabilities}
    for use_gpu in (False, True):
        cid = f"colmap.feature.sift.{'gpu' if use_gpu else 'cpu'}"
        if feature.recognized and "SIFT" in feature.tokens:
            try:
                extraction_arguments(
                    SiftExtractionSettings(use_gpu=use_gpu),
                    feature.option_names,
                    database=Path("probe.db"),
                    images=Path("images"),
                    models={},
                )
            except ValueError as exc:
                existing[cid] = adapter._evidence(
                    cid,
                    CapabilityStatus.UNAVAILABLE,
                    "colmap.extraction_option_missing",
                    str(exc),
                    observed_at,
                    freshness.static_cli_seconds,
                    identity,
                )
    by_role = {m.role: m for m in models}
    checked_roles = set()
    learned = []
    for variant in ("ALIKED_N16ROT", "ALIKED_N32", "LOMA_B", "LOMA_B128"):
        for gpu in (False, True):
            settings = (
                AlikedExtractionSettings(variant=variant, use_gpu=gpu, max_image_size=192)
                if variant.startswith("ALIKED")
                else LomaExtractionSettings(
                    method_id=f"feature_extraction.{variant.lower()}",
                    variant=variant,
                    use_gpu=gpu,
                    max_image_size=192,
                )
            )
            cid = f"colmap.feature.{variant.lower()}.{'gpu' if gpu else 'cpu'}"
            roles = model_roles(settings)
            statuses = [
                adapter._token_status(feature, variant),
                *(by_role[r].evidence.status for r in roles),
            ]
            if variant.startswith("LOMA"):
                statuses.append(loma_version_status(identity.version_line))
            onnx = existing["colmap.onnx"].status
            if onnx == CapabilityStatus.UNAVAILABLE:
                statuses.append(onnx)
            if gpu:
                # A known CUDA build AND a real learned inference are required. A
                # generic GPU inventory never establishes this runtime combination.
                statuses.append(cuda_build)
            status = required_status(tuple(statuses))
            message = (
                f"{variant} requires its exact token, COLMAP schema, ONNX runtime and pinned "
                "local model files; LoMa additionally requires COLMAP >=4.2.1"
            )
            gaps = "; ".join(by_role[r].evidence.message for r in roles
                             if by_role[r].evidence.status != CapabilityStatus.AVAILABLE)
            if gaps:
                message = gaps
            code = "colmap.learned_prerequisites_incomplete"
            should_probe = deep and (
                not gpu
                if requested is None
                else (requested.variant == variant and requested.use_gpu == gpu)
            )
            if status == CapabilityStatus.AVAILABLE:
                status = CapabilityStatus.UNKNOWN
                code = "colmap.functional_probe_not_run"
                message = f"{variant} {'GPU' if gpu else 'CPU'} needs a disposable inference probe"
                if should_probe and database.evidence.status == CapabilityStatus.AVAILABLE:
                    workspace = Path(tempfile.mkdtemp(prefix="splatforge-colmap-learned-"))
                    ownership = workspace.stat()
                    try:
                        (workspace / "images").mkdir()
                        uid = UUID(int=1)
                        image = workspace / "images" / f"{uid}.png"
                        adapter._write_test_image(image)
                        model_paths = {}
                        for role in roles:
                            record = by_role[role]
                            target = workspace / f"{role}.onnx"
                            shutil.copyfile(record.resolved_path, target)
                            if hash_file(target) != record.sha256:
                                raise ValueError("model identity changed during probe")
                            model_paths[role] = target
                        argv = extraction_arguments(
                            settings,
                            feature.option_names,
                            database=workspace / "probe.db",
                            images=workspace / "images",
                            models=model_paths,
                        )
                        result = adapter._run(
                            identity.resolved_path,
                            argv,
                            adapter._smoke_timeout,
                            working_directory=workspace,
                            environment=environment,
                        )
                        problem = adapter._process_problem(result, operation=variant)
                        if gpu and reports_cpu_fallback(result):
                            raise ValueError("Requested GPU inference reported CPU fallback")
                        if problem:
                            status, code, message = problem
                            diagnostic = result.stderr_text().strip()
                            if len(diagnostic) > 850:
                                # Preserve the native failure after verbose ONNX warnings
                                # within the existing 1024-character evidence bound.
                                tail = adapter._excerpt(diagnostic[-850:])
                                message = message[:120] + "; diagnostic tail: " + tail
                        elif not adapter._same_identity(identity, result.executable):
                            raise ValueError("executable identity changed during inference")
                        else:
                            summary = FeatureViewSummary(
                                view_id=uid,
                                width=192,
                                height=192,
                                image_sha256=hash_file(image),
                                feature_count=0,
                                keypoint_columns=2,
                                content_digest="0" * 64,
                            )
                            seal_feature_database(workspace / "probe.db")
                            checked, _ = inspect_feature_database(
                                workspace / "probe.db",
                                (summary,),
                                settings,
                                expected_schema=(
                                    database.sqlite_user_version,
                                    database.sqlite_application_id,
                                    database.tables,
                                ),
                                maximum_bytes=16 * 1024 * 1024,
                            )
                            if not checked[0].feature_count:
                                raise ValueError("inference produced no validated descriptors")
                            checked_roles.update(roles)
                            status, code = (
                                CapabilityStatus.AVAILABLE,
                                "colmap.learned_probe_succeeded",
                            )
                            message = (
                                f"{variant} validated disposable inference with exact local models"
                            )
                    except DoctorTeardownError:
                        raise
                    except (
                        OSError,
                        ValueError,
                        sqlite3.DatabaseError,
                        ProcessBoundaryError,
                    ) as exc:
                        status, code = CapabilityStatus.UNAVAILABLE, "colmap.learned_probe_failed"
                        message = f"{variant} inference/options/model validation failed: {exc}"
                    finally:
                        if not isinstance(sys.exception(), DoctorTeardownError):
                            adapter._cleanup_workspace(workspace, ownership)
            evidence = adapter._evidence(
                cid,
                status,
                code,
                message,
                observed_at,
                freshness.resource_health_seconds,
                identity,
                prerequisites=(
                    "colmap.database",
                    "colmap.onnx",
                    *(f"colmap.model.{r}" for r in roles),
                ),
            )
            learned.append(evidence)
    if checked_roles and existing["colmap.onnx"].status == CapabilityStatus.UNKNOWN:
        existing["colmap.onnx"] = adapter._evidence(
            "colmap.onnx",
            CapabilityStatus.AVAILABLE,
            "colmap.onnx_inference_verified",
            "Disposable learned inference positively verified the installed ONNX runtime",
            observed_at,
            freshness.resource_health_seconds,
            identity,
        )
    aliked_status = alternative_status(
        tuple(e.status for e in learned if ".aliked_" in e.capability_id)
    )
    if any(t.startswith("ALIKED") for t in feature.tokens) and not {
        "ALIKED_N16ROT",
        "ALIKED_N32",
    }.intersection(feature.tokens):
        aliked_status = CapabilityStatus.UNKNOWN
    existing["colmap.feature.aliked"] = adapter._evidence(
        "colmap.feature.aliked",
        aliked_status,
        "colmap.aliked_functional_gate",
        "ALIKED requires successful variant/device inference",
        observed_at,
        freshness.resource_health_seconds,
        identity,
    )
    return (
        (*existing.values(), *learned),
        tuple(
            m.model_copy(update={"compatibility_verified": m.role in checked_roles}) for m in models
        ),
    )
