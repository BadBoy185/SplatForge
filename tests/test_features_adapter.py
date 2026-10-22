"""Verified native command/model gates and database semantics without ML imports."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from feature_helpers import NativeFixture
from test_views_execution import harness, prepare

from splatforge.adapters.colmap_features import extraction_arguments
from splatforge.adapters.feature_database import inspect_feature_database
from splatforge.adapters.learned_feature_probe import loma_version_status
from splatforge.core.capabilities import CapabilityStatus, FreshnessPolicy
from splatforge.core.features import resolve_extraction_settings


def report(fixture, *, deep=False):
    return fixture.adapter()._capabilities.probe(
        explicit_executable=fixture.exe,
        explicit_model_directory=fixture.model_root,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=deep,
        observed_at=datetime.now(UTC),
        freshness=FreshnessPolicy(),
    )


@pytest.mark.parametrize("variant", ["SIFT", "ALIKED_N16ROT", "ALIKED_N32", "LOMA_B", "LOMA_B128"])
def test_verified_command_uses_native_identity_local_models_and_supported_options(
    tmp_path, variant
):
    fixture = NativeFixture(tmp_path)
    settings = resolve_extraction_settings(variant)
    backend = fixture.adapter().prepare(
        settings, colmap=fixture.exe, model_directory=fixture.model_root
    )
    argv = extraction_arguments(
        settings,
        backend.option_names,
        database=tmp_path / "project ž" / "features.db",
        images=tmp_path / "selected images",
        models={m.role: Path(m.resolved_path) for m in backend.models},
    )
    assert argv[0] == "feature_extractor" and "--FeatureExtraction.type" in argv
    assert argv[argv.index("--FeatureExtraction.type") + 1] == variant
    assert argv[argv.index("--FeatureExtraction.use_gpu") + 1] == "0"
    assert str(tmp_path / "project ž" / "features.db") in argv
    assert all(not value.startswith("https://") for value in argv)
    assert all(m.compatibility_verified for m in backend.models)
    for request in fixture.requests:
        assert request.executable == str(fixture.exe.resolve())
        assert request.max_stdout_bytes <= 256 * 1024
        assert request.timeout_seconds <= 45


@pytest.mark.parametrize(
    "version,status",
    [
        ("COLMAP 4.2.0 (Commit x)", "unavailable"),
        ("COLMAP 4.2.1 (Commit x)", "available"),
        ("COLMAP 4.3.0", "available"),
        ("COLMAP 3.13.0", "unavailable"),
        ("COLMAP 4.2", "unknown"),
        ("COLMAP 4.2.1-dev", "unknown"),
        (None, "unknown"),
    ],
)
def test_loma_floor_is_fail_closed(version, status):
    assert loma_version_status(version) == status


@pytest.mark.parametrize("problem", ["version", "onnx", "model", "option", "token", "schema"])
def test_learned_route_requires_all_positive_evidence(tmp_path, problem):
    fixture = NativeFixture(tmp_path)
    if problem == "version":
        fixture.top_help = fixture.top_help.replace("4.2.1", "4.2.0")
    elif problem == "onnx":
        fixture.top_help = fixture.top_help.replace("ONNX_ENABLED=ON", "ONNX_ENABLED=OFF")
    elif problem == "model":
        (fixture.model_root / "loma-b.onnx").unlink()
    elif problem == "option":
        fixture.feature_help = fixture.feature_help.replace("--LomaExtraction.min_score arg\n", "")
    elif problem == "token":
        fixture.feature_help = fixture.feature_help.replace(", LOMA_B, LOMA_B128", "")
    else:
        fixture.feature_help = fixture.feature_help.replace("{SIFT,", "{BROKEN SIFT,")
    with pytest.raises(ValueError):
        fixture.adapter().prepare(
            resolve_extraction_settings("LOMA_B"),
            colmap=fixture.exe,
            model_directory=fixture.model_root,
        )


def test_lightweight_does_not_infer_learned_runtime_from_help(tmp_path):
    observed = report(NativeFixture(tmp_path))
    for variant in ("aliked_n16rot", "aliked_n32", "loma_b", "loma_b128"):
        assert (
            observed.capability(f"colmap.feature.{variant}.cpu").status == CapabilityStatus.UNKNOWN
        )
    assert not any(m.compatibility_verified for m in observed.models)


def test_native_default_only_help_requires_real_functional_probe(tmp_path):
    fixture = NativeFixture(tmp_path)
    fixture.feature_help = fixture.feature_help.replace(
        " {SIFT, ALIKED_N16ROT, ALIKED_N32, LOMA_B, LOMA_B128}", ""
    )
    observed = report(fixture)
    assert observed.command_discovery.subcommands[0].parser_profile == "native_options_v2"
    assert observed.capability("colmap.feature.loma_b.cpu").status == "unknown"
    assert fixture.adapter().prepare(
        resolve_extraction_settings("LOMA_B"),
        colmap=fixture.exe,
        model_directory=fixture.model_root,
    )


def test_unknown_and_unsupported_tokens_remain_distinct(tmp_path):
    fixture = NativeFixture(tmp_path)
    fixture.feature_help = fixture.feature_help.replace(", LOMA_B, LOMA_B128", "")
    assert report(fixture).capability("colmap.feature.loma_b.cpu").status == "unavailable"
    fixture.feature_help = "unrecognized help shape"
    assert report(fixture).capability("colmap.feature.loma_b.cpu").status == "unknown"


def test_sift_does_not_require_loma_version_floor(tmp_path):
    fixture = NativeFixture(tmp_path)
    fixture.top_help = fixture.top_help.replace("4.2.1", "3.13.0")
    assert fixture.adapter().prepare(
        resolve_extraction_settings("SIFT"), colmap=fixture.exe, model_directory=None
    )


def test_doctor_marks_only_verified_extraction_runnable(tmp_path):
    from test_doctor import FakeGpu

    from splatforge.application.doctor import DoctorService
    from splatforge.core.builtin_methods import build_builtin_registry

    fixture = NativeFixture(tmp_path)
    observed = DoctorService(
        fixture.adapter()._capabilities, FakeGpu(), build_builtin_registry()
    ).report(deep=True, colmap=fixture.exe, model_directory=fixture.model_root)
    for method in observed.methods:
        assert method.runnable == method.method_id.startswith("feature_extraction.")


def test_backend_pinned_model_hash_is_checked_before_inference(tmp_path):
    fixture = NativeFixture(tmp_path)
    fixture.feature_help = fixture.feature_help.replace(
        "=loma-b.onnx)", "=https://example.invalid/model;loma-b.onnx;" + "0" * 64 + ")"
    )
    observed = report(fixture)
    model = next(m for m in observed.models if m.role == "loma.b")
    assert model.evidence.status == "unavailable"
    assert "SHA-256" in model.evidence.message


@pytest.mark.parametrize("changed", ["executable", "model", "runtime"])
def test_changed_frozen_identity_refused_before_numerical_process(tmp_path, changed):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    adapter = fixture.adapter()
    settings = resolve_extraction_settings("LOMA_B")
    backend = adapter.prepare(settings, colmap=fixture.exe, model_directory=fixture.model_root)
    if changed == "executable":
        fixture.exe.write_bytes(b"replaced native executable")
    elif changed == "model":
        (fixture.model_root / "loma-b.onnx").write_bytes(b"changed model")
    else:
        (fixture.exe.parent / "onnxruntime.dll").write_bytes(b"changed runtime")
    workspace = tmp_path / "work" / "attempt"
    workspace.mkdir(parents=True)
    candidate = value.execution.load_candidate_views(value.root, views.candidate_artifact)

    class Control:
        def is_cancelled(self):
            return False

    count = len(fixture.requests)
    with pytest.raises(ValueError, match="identity|runtime"):
        adapter.extract(
            workspace,
            backend=backend,
            settings=settings,
            candidate_directory=(value.root / views.candidate_artifact.manifest_path).parent,
            views=candidate.views,
            timeout_seconds=10,
            maximum_database_bytes=10**7,
            minimum_free_bytes=10**6,
            cancellation=Control(),
            evidence_sink=lambda _record: None,
        )
    assert len(fixture.requests) == count


def test_native_ids_and_sqlite_layout_do_not_change_feature_semantics(tmp_path):
    import sqlite3
    from contextlib import closing

    from test_features_execution import build

    from splatforge.adapters.feature_database import NativeFeaturePayload

    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    result = build(value, views, fixture)
    features = value.execution.load_local_features(value.root, result.feature_artifact)
    directory = (value.root / result.feature_artifact.manifest_path).parent
    # Mutate only an independent downstream workspace copy.
    import shutil

    private = tmp_path / "independent.db"
    shutil.copyfile(directory / "features.db", private)
    payload = NativeFeaturePayload.model_validate_json(
        (directory / "backend_mapping.json").read_bytes()
    )
    with closing(sqlite3.connect(private)) as db, db:
        for table in ("images", "keypoints", "descriptors"):
            db.execute(f"UPDATE {table} SET image_id=image_id+1000")
        db.commit()
        db.execute("VACUUM")
    summaries, mapping = inspect_feature_database(
        private,
        features.views,
        features.settings,
        expected_schema=(payload.user_version, payload.application_id, payload.tables),
    )
    assert summaries == features.views
    assert mapping.images != payload.images
