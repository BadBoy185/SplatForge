"""M7a immutable metadata, descriptor compatibility and numerical keys."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from splatforge.core.features import (
    AlikedExtractionSettings,
    DescriptorFamily,
    DescriptorSignature,
    FeatureResourceLimits,
    FeatureViewSummary,
    LearnedModelIdentity,
    LocalFeatureSet,
    LomaExtractionSettings,
    SiftExtractionSettings,
    descriptor_signature,
    estimate_feature_resources,
    feature_recipe_key,
    feature_semantic_digest,
    model_roles,
    resolve_extraction_settings,
)

VARIANTS = ("SIFT", "ALIKED_N16ROT", "ALIKED_N32", "LOMA_B", "LOMA_B128")


def features(variant="SIFT"):
    settings = resolve_extraction_settings(variant)
    summaries = tuple(
        FeatureViewSummary(
            view_id=UUID(int=i),
            image_sha256="1" * 64,
            width=64,
            height=64,
            feature_count=3,
            keypoint_columns=2,
            content_digest="2" * 64,
        )
        for i in (1, 2)
    )
    models = tuple(
        LearnedModelIdentity(
            role=r, name=r + ".onnx", source="fixture://test", sha256="3" * 64, size=100
        )
        for r in model_roles(settings)
    )
    provisional = LocalFeatureSet.model_construct(
        selected_artifact_id=uuid4(),
        selected_semantic_digest="4" * 64,
        method_id=settings.method_id,
        settings=settings,
        models=models,
        descriptor=descriptor_signature(settings),
        backend_numerical_identity="5" * 64,
        selected_view_count=2,
        total_feature_count=6,
        views=summaries,
        semantic_digest="0" * 64,
    )
    return LocalFeatureSet.model_validate(
        {**provisional.model_dump(), "semantic_digest": feature_semantic_digest(provisional)}
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_settings_and_metadata_round_trip(variant):
    value = features(variant)
    assert LocalFeatureSet.model_validate_json(value.model_dump_json()) == value
    assert value.settings.settings_version == 1
    with pytest.raises(ValidationError):
        value.settings.max_features = 1
    for invalid in (0, -1, 100001, True, "100", 1.5):
        with pytest.raises((ValueError, ValidationError)):
            resolve_extraction_settings(variant, max_features=invalid)


@pytest.mark.parametrize("family", list(DescriptorFamily))
def test_descriptor_family_cannot_cross_on_equal_dimensions(family):
    signature = DescriptorSignature(
        family=family,
        dimension=256 if family == "loma_b" else 128,
        scalar_type="uint8" if family == "sift" else "float32_le",
    )
    assert all(
        signature != features(v).descriptor
        for v in VARIANTS
        if features(v).descriptor.family != family
    )
    with pytest.raises(ValidationError):
        DescriptorSignature(family=family, dimension=12, scalar_type="uint8")


@pytest.mark.parametrize("variant", VARIANTS)
def test_semantic_digest_excludes_publication_but_includes_numerical_content(variant):
    value = features(variant)
    assert (
        feature_semantic_digest(value.model_copy(update={"selected_artifact_id": uuid4()}))
        == value.semantic_digest
    )
    altered = value.model_copy(
        update={
            "views": (
                value.views[0].model_copy(update={"content_digest": "f" * 64}),
                value.views[1],
            )
        }
    )
    assert feature_semantic_digest(altered) != value.semantic_digest
    key = feature_recipe_key("a" * 64, value.settings, "b" * 64, value.models)
    assert key != feature_recipe_key("c" * 64, value.settings, "b" * 64, value.models)
    assert key != feature_recipe_key("a" * 64, value.settings, "c" * 64, value.models)
    assert key != feature_recipe_key(
        "a" * 64, value.settings.model_copy(update={"max_features": 1}), "b" * 64, value.models
    )
    if value.models:
        models = (value.models[0].model_copy(update={"sha256": "e" * 64}), *value.models[1:])
        assert key != feature_recipe_key("a" * 64, value.settings, "b" * 64, models)


@pytest.mark.parametrize(
    "changes",
    [
        {"selected_view_count": 100001},
        {"total_feature_count": -1},
        {"total_feature_count": 7},
        {"method_id": "feature_extraction.loma_b"},
        {"semantic_digest": "e" * 64},
        {"views": ()},
    ],
)
def test_malformed_feature_metadata_fails(changes):
    with pytest.raises(ValidationError):
        LocalFeatureSet.model_validate({**features().model_dump(), **changes})


def test_variant_and_unsupported_numerical_slots_fail():
    with pytest.raises(ValidationError):
        LomaExtractionSettings(variant="LOMA_B128")
    with pytest.raises(ValidationError):
        LomaExtractionSettings(use_bf16=True)
    with pytest.raises(ValidationError):
        AlikedExtractionSettings(variant="LOMA_R")
    with pytest.raises(ValidationError):
        SiftExtractionSettings(unknown=1)
    with pytest.raises(ValueError):
        resolve_extraction_settings("SIFT", min_score=0.1)


def test_resource_budget_distinguishes_storage_and_rejects_before_allocation():
    estimates = {
        v: estimate_feature_resources(
            views=100,
            pixels=100_000_000,
            encoded_bytes=1000,
            settings=resolve_extraction_settings(v, max_features=2048),
            limits=FeatureResourceLimits(),
        )
        for v in VARIANTS
    }
    assert estimates["LOMA_B"].descriptor_bytes == estimates["SIFT"].descriptor_bytes * 8
    assert estimates["LOMA_B128"].descriptor_bytes == estimates["SIFT"].descriptor_bytes * 4
    with pytest.raises(ValueError, match="workspace budget"):
        estimate_feature_resources(
            views=100,
            pixels=1,
            encoded_bytes=0,
            settings=LomaExtractionSettings(),
            limits=FeatureResourceLimits(max_workspace_bytes=1),
        )
