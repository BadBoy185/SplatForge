from uuid import uuid4

from splatforge.core.execution import ArtifactHandle, ScaleSettings, SequenceSettings
from splatforge.core.fake_pipeline import scale_recipe_key, sequence_recipe_key


def handle(*, digest: str) -> ArtifactHandle:
    return ArtifactHandle(
        artifact_id=uuid4(),
        artifact_type="fake.numbers",
        contract_version=1,
        recipe_key="a" * 64,
        semantic_digest=digest,
        manifest_path="artifacts/numbers/example/manifest.json",
    )


def test_sequence_key_hashes_only_sequence_dependencies() -> None:
    settings = SequenceSettings(count=3)
    assert sequence_recipe_key(start=2, settings=settings) == sequence_recipe_key(
        start=2, settings=SequenceSettings(count=3)
    )
    assert sequence_recipe_key(start=2, settings=settings) != sequence_recipe_key(
        start=3, settings=settings
    )
    assert sequence_recipe_key(start=2, settings=settings) != sequence_recipe_key(
        start=2, settings=SequenceSettings(count=4)
    )


def test_scale_key_uses_semantic_input_and_ignores_artifact_identity() -> None:
    first = handle(digest="b" * 64)
    second = first.model_copy(
        update={"artifact_id": uuid4(), "recipe_key": "c" * 64}
    )
    assert scale_recipe_key(
        settings=ScaleSettings(factor=2), input_artifact=first
    ) == scale_recipe_key(settings=ScaleSettings(factor=2), input_artifact=second)
    assert scale_recipe_key(
        settings=ScaleSettings(factor=2), input_artifact=first
    ) != scale_recipe_key(settings=ScaleSettings(factor=3), input_artifact=first)
    assert scale_recipe_key(
        settings=ScaleSettings(factor=2), input_artifact=first
    ) != scale_recipe_key(
        settings=ScaleSettings(factor=2),
        input_artifact=handle(digest="d" * 64),
    )
