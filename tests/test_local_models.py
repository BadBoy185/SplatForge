"""Model inspection never provisions bytes or delegates URI resolution to COLMAP."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from matching_helpers import MatchingFixture
from test_features_adapter import report

from splatforge.adapters.colmap_features import extraction_arguments
from splatforge.adapters.colmap_matching_options import matching_arguments
from splatforge.adapters.local_models import local_model_argument
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.application.model_provisioning import learned_route_provisioning
from splatforge.core.capabilities import FreshnessPolicy
from splatforge.core.features import resolve_extraction_settings
from splatforge.core.matching import resolve_matching_settings
from splatforge.core.sfm_profiles import FeatureMatchingChoice


def inspect(fixture, root, *, pin=None):
    if pin is not None:
        fixture.feature_help = fixture.feature_help.replace(
            "(=loma-b.onnx)", f"(=https://example.invalid/model;loma-b.onnx;{pin})"
        )
    adapter = fixture.adapter()._capabilities
    return adapter.probe(
        explicit_executable=fixture.exe, explicit_model_directory=root,
        bundled_executable=None, bundled_model_directory=None, deep=False,
        observed_at=datetime.now(UTC), freshness=FreshnessPolicy(),
    )


@pytest.mark.parametrize("missing", ["root", "loma-detector.onnx", "loma_matcher_R.onnx"])
def test_all_route_roles_and_exact_manual_rerun_are_reported(tmp_path, missing):
    fixture = MatchingFixture(tmp_path)
    root = fixture.model_root
    if missing == "root":
        root = tmp_path / "not provisioned"
    else:
        # Fixture-owned files only; absence must not cause a download or execution.
        (root / missing).rename(root / (missing + ".unused"))
    evidence = inspect(fixture, root)
    choice = FeatureMatchingChoice(extractor=resolve_extraction_settings("LOMA_B"),
                                   matcher=resolve_matching_settings("LOMA_R"))
    result = learned_route_provisioning(choice, evidence)
    assert not result.ready and len(result.models) == 3
    gaps = [m for m in result.models if m.evidence.status != "available"]
    assert gaps and all(m.expected_root == str(root) and m.checked_path for m in gaps)
    assert all(m.sha256 is None and m.size is None for m in gaps)
    assert "LOMA_B-LOMA_R" in result.rerun_command
    assert "SPLATFORGE_COLMAP_MODEL_DIR" in result.configuration
    assert all("reference digest unavailable" in m.evidence.message for m in gaps)
    assert all(len(r.argv) <= 2 for r in fixture.requests)
    assert not root.exists() if missing == "root" else root.exists()


@pytest.mark.parametrize("valid", [True, False])
def test_reference_digest_preserved_on_absent_or_wrong_bytes(tmp_path, valid):
    fixture = MatchingFixture(tmp_path)
    path = fixture.model_root / "loma-b.onnx"
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    if valid:
        path.rename(path.with_suffix(".absent"))
    else:
        path.write_bytes(b"wrong checkpoint bytes")
    model = next(m for m in inspect(fixture, fixture.model_root, pin=expected).models
                 if m.role == "loma.b")
    assert model.expected_sha256 == expected and model.evidence.status == "unavailable"
    assert model.expected_name == "loma-b.onnx"
    assert model.sha256 == (None if valid else hashlib.sha256(path.read_bytes()).hexdigest())
    assert "no download" in model.evidence.message


def test_existing_sha_prefixed_native_cache_file_is_read_only_and_reference_verified(tmp_path):
    fixture = MatchingFixture(tmp_path)
    path = fixture.model_root / "loma-b.onnx"
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    cached = path.with_name(pin + "-" + path.name)
    path.rename(cached)
    before = (cached.read_bytes(), cached.stat().st_mtime_ns)
    model = next(m for m in inspect(fixture, fixture.model_root, pin=pin).models
                 if m.role == "loma.b")
    assert model.evidence.status == "available" and model.sha256 == model.expected_sha256 == pin
    assert model.resolved_path == str(cached)
    assert before == (cached.read_bytes(), cached.stat().st_mtime_ns) and not path.exists()


def test_wrong_plain_file_cannot_be_hidden_by_valid_cached_alternative(tmp_path):
    fixture = MatchingFixture(tmp_path)
    path = fixture.model_root / "loma-b.onnx"
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(pin + "-" + path.name).write_bytes(path.read_bytes())
    path.write_bytes(b"wrong")
    model = next(m for m in inspect(fixture, fixture.model_root, pin=pin).models
                 if m.role == "loma.b")
    assert model.evidence.status == "unavailable" and model.resolved_path == str(path)


def test_unknown_reference_records_observed_sha_without_claiming_reference_trust(tmp_path):
    directory = tmp_path / "models with spaces ž"
    directory.mkdir()
    fixture = MatchingFixture(directory)
    model = next(m for m in report(fixture).models if m.role == "loma.b")
    assert model.sha256 and model.size and model.expected_sha256 is None
    assert "reference digest unavailable" in model.evidence.message


@pytest.mark.parametrize("value", ["https://example.invalid/model.onnx", "file:///model.onnx",
                                   "relative.onnx", "https://host/m;name;digest"])
def test_url_or_unresolved_model_transport_is_rejected(value):
    with pytest.raises(ValueError, match="absolute local"):
        local_model_argument(Path(value))


def test_exact_model_arguments_are_required_and_never_default_to_remote(tmp_path):
    fixture = MatchingFixture(tmp_path)
    feature, matching = resolve_extraction_settings("LOMA_B"), resolve_matching_settings("LOMA_R")
    backend = fixture.adapter().prepare(feature, colmap=fixture.exe,
                                        model_directory=fixture.model_root)
    for models in ({}, {"loma.detector": Path("https://example.invalid/model"),
                        "loma.b": tmp_path / "local.onnx"}):
        with pytest.raises((KeyError, ValueError)):
            extraction_arguments(feature, backend.option_names, database=tmp_path / "db",
                                 images=tmp_path, models=models)
    native = fixture.matching_adapter().prepare(matching, feature_settings=feature,
                                                colmap=fixture.exe,
                                                model_directory=fixture.model_root)
    with pytest.raises(ValueError, match="absolute local"):
        matching_arguments(matching, native.option_names, database=tmp_path / "db",
                           pairs=tmp_path / "pairs",
                           models={"loma.matcher.r": Path("https://example.invalid/model")})


def test_missing_models_fail_planning_without_numerical_launch(tmp_path):
    fixture = MatchingFixture(tmp_path)
    missing = tmp_path / "absent models"
    with pytest.raises(FeatureCapabilityError, match="loma.detector"):
        fixture.adapter().prepare(resolve_extraction_settings("LOMA_B"),
                                  colmap=fixture.exe, model_directory=missing)
    assert not any(r.argv[0] == "feature_extractor" and len(r.argv) > 2
                   for r in fixture.requests)
    assert not missing.exists()


def test_default_root_is_bounded_read_only_and_does_not_use_native_remote_defaults(tmp_path):
    fixture = MatchingFixture(tmp_path)
    adapter = fixture.adapter()._capabilities
    adapter._environment = {"LOCALAPPDATA": str(tmp_path)}
    root, source = adapter._resolve_model_root(None, None)
    assert root == tmp_path / "SplatForge" / "models" / "colmap" and source == "local_default"
    assert not root.exists()
    before = adapter.configuration_key()
    adapter._environment = {"LOCALAPPDATA": str(tmp_path / "other")}
    assert adapter.configuration_key() != before


def test_learned_gpu_proves_own_inference_without_sift_gpu_dependency(tmp_path, monkeypatch):
    fixture = MatchingFixture(tmp_path)
    adapter = fixture.adapter()

    def unexpected(*args, **kwargs):
        raise AssertionError("Learned GPU must not depend on unrelated SIFT inference")

    monkeypatch.setattr(adapter._capabilities, "_probe_sift", unexpected)
    backend = adapter.prepare(resolve_extraction_settings("ALIKED_N16ROT", use_gpu=True),
                              colmap=fixture.exe, model_directory=fixture.model_root)
    assert backend.capability_evidence[0].status == "available"
    assert backend.capability_evidence[0].capability_id.endswith("aliked_n16rot.gpu")
