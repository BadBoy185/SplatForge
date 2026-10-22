"""Doctor matching gates backed by disposable native inference, not help tokens."""

from __future__ import annotations

import shutil
import sqlite3
import struct
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from splatforge.adapters.colmap_help import ParsedOptionHelp
from splatforge.adapters.colmap_matching_options import matching_arguments, verification_arguments
from splatforge.adapters.learned_feature_probe import loma_version_status
from splatforge.adapters.local_models import reports_cpu_fallback
from splatforge.application.doctor_contracts import DoctorTeardownError
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    DatabaseCompatibility,
    FreshnessPolicy,
    ModelEvidence,
    SubcommandDiscovery,
    required_status,
)
from splatforge.core.features import (
    FeatureSettings,
    FeatureViewSummary,
    resolve_extraction_settings,
)
from splatforge.core.geometry import VerificationSettings
from splatforge.core.matching import (
    COMPATIBLE_MATCHERS,
    MatcherSettings,
    matcher_model_role,
    resolve_matching_settings,
)
from splatforge.core.media import ExecutableIdentity

if TYPE_CHECKING:
    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter


def probe_matching_routes(
    adapter: ColmapCapabilityAdapter,
    *,
    capabilities: tuple[CapabilityEvidence, ...],
    models: tuple[ModelEvidence, ...],
    helps: tuple[tuple[str, SubcommandDiscovery, ParsedOptionHelp], ...],
    database: DatabaseCompatibility,
    identity: ExecutableIdentity,
    deep: bool,
    observed_at: datetime,
    freshness: FreshnessPolicy,
    environment: Mapping[str, str],
    requested: MatcherSettings | None = None,
    feature_settings: FeatureSettings | None = None,
    verification_only: bool = False,
    cuda_build: CapabilityStatus = CapabilityStatus.UNKNOWN,
) -> tuple[tuple[CapabilityEvidence, ...], tuple[ModelEvidence, ...]]:
    existing = {c.capability_id: c for c in capabilities}
    by_role = {m.role: m for m in models}
    parsed = {item[1].command: item[2] for item in helps}
    help_status = {item[1].command: item[1].evidence.status for item in helps}
    match_help, verify_help = parsed["matches_importer"], parsed["geometric_verifier"]
    variants = tuple(dict.fromkeys(v for values in COMPATIBLE_MATCHERS.values() for v in values))
    for token in variants:
        for gpu in (False, True):
            settings = resolve_matching_settings(token, use_gpu=gpu)
            if requested is not None and requested.variant == token and requested.use_gpu == gpu:
                settings = requested
            cid = f"colmap.match.{token.lower()}.{'gpu' if gpu else 'cpu'}"
            role = matcher_model_role(settings)
            statuses = [
                adapter._token_status(match_help, token),
                database.evidence.status,
                help_status["matches_importer"],
            ]
            if role:
                statuses.append(by_role[role].evidence.status)
                if existing["colmap.onnx"].status == CapabilityStatus.UNAVAILABLE:
                    statuses.append(CapabilityStatus.UNAVAILABLE)
            if token.startswith("LOMA"):
                statuses.append(loma_version_status(identity.version_line))
            if gpu:
                # This method's own contained GPU inference establishes its health;
                # matching a published input must not require a SIFT extractor probe.
                statuses.append(cuda_build)
            status = required_status(tuple(statuses))
            gaps = "; ".join(
                m.evidence.message
                for m in models
                if m.role == role and m.evidence.status != CapabilityStatus.AVAILABLE
            )
            message = (
                gaps or f"{token} requires explicit PairSet, raw-only options and native inference"
            )
            code = "colmap.match_prerequisite_missing"
            try:
                matching_arguments(
                    settings,
                    match_help.option_names,
                    database=Path("probe.db"),
                    pairs=Path("pairs.txt"),
                    models={role: Path("model.onnx").absolute()},
                )
            except ValueError as exc:
                if status != CapabilityStatus.UNAVAILABLE:
                    status = (
                        CapabilityStatus.UNAVAILABLE
                        if match_help.recognized
                        else CapabilityStatus.UNKNOWN
                    )
                message = str(exc)
            should_probe = (
                deep
                and not verification_only
                and (
                    (not gpu and feature_settings is None)
                    if requested is None
                    else settings == requested
                )
            )
            if status == CapabilityStatus.AVAILABLE:
                status, code = CapabilityStatus.UNKNOWN, "colmap.match_probe_not_run"
                if should_probe:
                    try:
                        _smoke(
                            adapter,
                            settings,
                            feature_settings,
                            parsed,
                            by_role,
                            database,
                            identity,
                            environment,
                        )
                        status, code = CapabilityStatus.AVAILABLE, "colmap.match_probe_succeeded"
                        message = (
                            f"{token} {'GPU' if gpu else 'CPU'} validated raw native inference"
                        )
                        if role:
                            by_role[role] = by_role[role].model_copy(
                                update={"compatibility_verified": True},
                            )
                            if existing["colmap.onnx"].status == CapabilityStatus.UNKNOWN:
                                existing["colmap.onnx"] = adapter._evidence(
                                    "colmap.onnx",
                                    CapabilityStatus.AVAILABLE,
                                    "colmap.matcher_onnx_inference_verified",
                                    "Matching inference verified native ONNX runtime",
                                    observed_at,
                                    freshness.resource_health_seconds,
                                    identity,
                                )
                    except DoctorTeardownError:
                        raise
                    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
                        status, code = CapabilityStatus.UNAVAILABLE, "colmap.match_probe_failed"
                        message = f"{token}: {exc}"
            existing[cid] = adapter._evidence(
                cid,
                status,
                code,
                message[:1024],
                observed_at,
                freshness.resource_health_seconds,
                identity,
            )
    # Preserve old aggregate discovery IDs; M7b per-device IDs require functional
    # explicit-pair evidence and are the only matching gates used by Doctor/plans.
    for token in variants:
        cpu = existing[f"colmap.match.{token.lower()}.cpu"]
        existing.setdefault(
            f"colmap.match.{token.lower()}",
            cpu.model_copy(
                update={"capability_id": f"colmap.match.{token.lower()}"},
            ),
        )
    cid = "colmap.verification.standalone"
    status, code = CapabilityStatus.UNKNOWN, "colmap.verification_probe_not_run"
    message = "Standalone geometric verification needs a disposable raw-match database"
    try:
        verification_arguments(
            VerificationSettings(), verify_help.option_names, database=Path("p.db")
        )
        if (
            deep
            and (verification_only or requested is None and feature_settings is None)
            and database.evidence.status == CapabilityStatus.AVAILABLE
        ):
            _smoke(
                adapter,
                resolve_matching_settings("SIFT_BRUTEFORCE"),
                None,
                parsed,
                by_role,
                database,
                identity,
                environment,
                verify=True,
            )
            status, code = CapabilityStatus.AVAILABLE, "colmap.verification_probe_succeeded"
            message = "Standalone verifier produced validated geometry from raw SIFT matches"
    except DoctorTeardownError:
        raise
    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
        status, code, message = (
            CapabilityStatus.UNAVAILABLE
            if verify_help.recognized
            or help_status["geometric_verifier"] == CapabilityStatus.UNAVAILABLE
            else CapabilityStatus.UNKNOWN,
            "colmap.verification_probe_failed",
            str(exc),
        )
    existing[cid] = adapter._evidence(
        cid,
        status,
        code,
        message[:1024],
        observed_at,
        freshness.resource_health_seconds,
        identity,
    )
    return tuple(existing.values()), tuple(by_role[m.role] for m in models)


def _smoke(
    adapter,
    settings,
    feature_settings,
    parsed,
    models,
    schema,
    identity,
    environment,
    *,
    verify=False,
):
    from contextlib import closing

    from splatforge.adapters.colmap_features import hash_file
    from splatforge.adapters.feature_database import inspect_feature_database, seal_feature_database
    from splatforge.adapters.matching_database import (
        _correspondences,
        _numeric_blob,
        pair_id,
        readonly_database,
    )
    from splatforge.core.features import descriptor_signature

    variant = (
        "SIFT"
        if verify
        else feature_settings.variant
        if feature_settings
        else "LOMA_B128"
        if settings.variant == "LOMA_B128"
        else "LOMA_B"
        if settings.variant.startswith("LOMA")
        else "ALIKED_N16ROT"
        if settings.variant.startswith("ALIKED")
        else "SIFT"
    )
    count = 64 if variant == "SIFT" else 128
    extractor = resolve_extraction_settings(variant, max_features=count, max_image_size=192)
    signature = descriptor_signature(extractor)
    role = None if verify else matcher_model_role(settings)
    roles = (role,) if role else ()
    for role in roles:
        if models[role].evidence.status != CapabilityStatus.AVAILABLE:
            raise ValueError(models[role].evidence.message)
    workspace = Path(tempfile.mkdtemp(prefix="splatforge-colmap-matching-"))
    ownership = workspace.stat()
    try:
        summaries = []
        for i in (1, 2):
            uid = UUID(int=i)
            summaries.append(
                FeatureViewSummary(
                    view_id=uid,
                    width=192,
                    height=192,
                    image_sha256="0" * 64,
                    feature_count=count,
                    keypoint_columns=2,
                    content_digest="0" * 64,
                )
            )
        paths = {}
        for role in roles:
            target = workspace / (role + ".onnx")
            shutil.copyfile(models[role].resolved_path, target)
            if hash_file(target) != models[role].sha256:
                raise ValueError("Model identity changed during matching probe")
            paths[role] = target
        database = workspace / "probe.db"

        def run(argv):
            result = adapter._run(
                identity.resolved_path,
                argv,
                adapter._smoke_timeout,
                working_directory=workspace,
                environment=environment,
            )
            problem = adapter._process_problem(result, operation=argv[0])
            if problem:
                raise ValueError(problem[2])
            if not verify and settings.use_gpu and reports_cpu_fallback(result):
                raise ValueError("Requested GPU inference reported CPU fallback")
            if not adapter._same_identity(identity, result.executable):
                raise ValueError("Executable changed during matching probe")
            text = adapter._combined_text(result).lower()
            if any(
                token in text
                for token in (
                    "failed to create",
                    "failed to run",
                    "onnxruntimeerror",
                    "cuda failure",
                )
            ):
                raise ValueError("Native inference reported initialization/execution failure")

        run(("database_creator", "--database_path", str(database)))
        keypoints = b"".join(
            struct.pack("<ff", 8.5 + (i % 16) * 11, 8.5 + (i // 16) * 22) for i in range(count)
        )
        descriptors = b"".join(
            (
                bytes(255 if j == i else 0 for j in range(signature.dimension))
                if signature.scalar_type == "uint8"
                else struct.pack(
                    f"<{signature.dimension}f",
                    *(1.0 if j == i else 0.0 for j in range(signature.dimension)),
                )
            )
            for i in range(count)
        )
        types = {"SIFT": 0, "ALIKED_N16ROT": 1, "ALIKED_N32": 2, "LOMA_B": 3, "LOMA_B128": 4}
        with closing(sqlite3.connect(database)) as db, db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            typed = "type" in {r[1] for r in db.execute("PRAGMA table_info(descriptors)")}
            if not typed and variant != "SIFT":
                raise ValueError("Learned matching needs typed native descriptors")
            for index, summary in enumerate(summaries, 1):
                db.execute(
                    "INSERT INTO cameras (camera_id,model,width,height,params,prior_focal_length)"
                    " VALUES (?,0,192,192,?,0)",
                    (index, struct.pack("<3d", 230.4, 96.0, 96.0)),
                )
                db.execute(
                    "INSERT INTO images (image_id,name,camera_id) VALUES (?,?,?)",
                    (index, f"{summary.view_id}.png", index),
                )
                db.execute(
                    "INSERT INTO keypoints (image_id,rows,cols,data) VALUES (?,?,2,?)",
                    (index, count, keypoints),
                )
                if typed:
                    db.execute(
                        "INSERT INTO descriptors (image_id,type,rows,cols,data) VALUES (?,?,?,?,?)",
                        (index, types[variant], count, signature.row_bytes, descriptors),
                    )
                else:
                    db.execute(
                        "INSERT INTO descriptors (image_id,rows,cols,data) VALUES (?,?,?,?)",
                        (index, count, signature.row_bytes, descriptors),
                    )
                if {"rigs", "frames", "frame_data"} <= names:
                    db.execute(
                        "INSERT INTO rigs (rig_id,ref_sensor_id,ref_sensor_type) VALUES (?,?,0)",
                        (index, index),
                    )
                    db.execute("INSERT INTO frames (frame_id,rig_id) VALUES (?,?)", (index, index))
                    db.execute(
                        "INSERT INTO frame_data (frame_id,data_id,sensor_id,sensor_type) "
                        "VALUES (?,?,?,0)",
                        (index, index, index),
                    )
            if verify:
                db.execute(
                    "INSERT INTO matches (pair_id,rows,cols,data) VALUES (?,?,2,?)",
                    (
                        pair_id(1, 2),
                        count,
                        b"".join(struct.pack("<II", i, i) for i in range(count)),
                    ),
                )
        seal_feature_database(database)
        if not verify:
            inspect_feature_database(
                database,
                tuple(summaries),
                extractor,
                maximum_bytes=64 * 1024**2,
                expected_schema=(
                    schema.sqlite_user_version,
                    schema.sqlite_application_id,
                    schema.tables,
                ),
            )
        pair_list = workspace / "pairs.txt"
        pair_list.write_text(
            " ".join(f"{s.view_id}.png" for s in summaries) + "\n", encoding="utf-8"
        )
        # Probe only model/device/signature health; numerical filters may legitimately
        # produce zero matches in an attempt. No extraction model is consumed here.
        controls = {"num_threads": 1, "max_num_matches": 128}
        for name, value in (
            ("min_score", 0.0),
            ("min_cossim", -1.0),
            ("max_ratio", 1.0),
            ("max_distance", 2.0),
        ):
            if name in type(settings).model_fields:
                controls[name] = value
        probe_settings = type(settings).model_validate({**settings.model_dump(), **controls})
        if not verify:
            run(
                matching_arguments(
                    probe_settings,
                    parsed["matches_importer"].option_names,
                    database=database,
                    pairs=pair_list,
                    models=paths,
                )
            )
        seal_feature_database(database)
        counts = {1: count, 2: count}
        native = pair_id(1, 2)
        with closing(readonly_database(database)) as db:
            if db.execute("SELECT count(*) FROM matches").fetchone()[0] != 1:
                raise ValueError("Raw smoke did not process the exact requested pair")
            if db.execute("SELECT count(*) FROM two_view_geometries").fetchone()[0]:
                raise ValueError("Raw smoke unexpectedly performed verification")
            values = _correspondences(db, "matches", native, counts, reverse=False, limit=128)
            if settings.variant == "SIFT_BRUTEFORCE" and not values:
                raise ValueError("Matcher initialization produced no validated raw correspondences")
        if verify:
            run(
                verification_arguments(
                    VerificationSettings(),
                    parsed["geometric_verifier"].option_names,
                    database=database,
                )
            )
            seal_feature_database(database)
            with closing(readonly_database(database)) as db:
                row = db.execute(
                    "SELECT config,F,E,H,qvec,tvec FROM two_view_geometries WHERE pair_id=?",
                    (native,),
                ).fetchone()
                if row is None or row[0] not in range(2, 10):
                    raise ValueError("Verifier smoke produced no accepted geometry")
                inliers = _correspondences(
                    db,
                    "two_view_geometries",
                    native,
                    counts,
                    reverse=False,
                    limit=128,
                )
                if len(inliers) < 15 or not set(inliers) <= set(values):
                    raise ValueError("Verifier smoke produced invalid inliers")
                for data, n in zip(row[1:], (9, 9, 9, 4, 3), strict=True):
                    _numeric_blob(data, n)
    finally:
        if not isinstance(sys.exception(), DoctorTeardownError):
            adapter._cleanup_workspace(workspace, ownership)
