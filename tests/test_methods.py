from splatforge.core import StageKind, build_builtin_registry


def test_registry_has_replaceable_sfm_methods() -> None:
    registry = build_builtin_registry()

    assert len(registry.list(StageKind.FEATURE_EXTRACTION)) >= 2
    assert len(registry.list(StageKind.PAIR_SELECTION)) >= 4
    assert len(registry.list(StageKind.FEATURE_MATCHING)) >= 2
    assert len(registry.list(StageKind.MAPPING)) >= 3
