"""Set output semantics are independent of algorithm recipe, paths and native IDs."""

from uuid import UUID, uuid4

import pytest
from mapping_helpers import mapping_for, write_model

from splatforge.adapters.colmap_reconstruction import ColmapReconstructionReader, read_components
from splatforge.core.reconstruction import (
    ReconstructionCalibration,
    ReconstructionLineage,
    ReconstructionSet,
    reconstruction_semantic_digest,
)


def make_set(mapping, components):
    members = {v for c in components for v in c.registered_view_ids}
    unregistered = tuple(m.view_id for m in mapping.images if m.view_id not in members)
    value = ReconstructionSet.model_construct(
        upstream=(
            ReconstructionLineage(
                input_name="synthetic", artifact_id=uuid4(), semantic_digest="a" * 64
            ),
        ),
        mapping_input_digest="b" * 64,
        input_view_ids=tuple(m.view_id for m in mapping.images),
        method_id="synthetic.direct_geometry",
        resolved_settings=(),
        calibration=ReconstructionCalibration(
            policy="explicit_priors",
            backend_identity="c" * 64,
            cameras_before="d" * 64,
            cameras_after="d" * 64,
            input_after_digest="b" * 64,
            result_digest="e" * 64,
        ),
        backend_numerical_identity="c" * 64,
        recipe_key="f" * 64,
        components=components,
        component_count=len(components),
        registered_view_count=len(members),
        unregistered_view_count=len(unregistered),
        unregistered_view_ids=unregistered,
        native_format="colmap.sparse.binary.v1",
        semantic_digest="0" * 64,
    )
    return ReconstructionSet.model_validate(
        {**value.model_dump(), "semantic_digest": reconstruction_semantic_digest(value)}
    )


def test_set_semantics_native_ids_numbering_paths_uuid_json_and_mapper_independent(tmp_path):
    views = tuple(UUID(int=i) for i in range(1, 8))
    a, b = mapping_for(views), mapping_for(views, offset=900)
    values = []
    for root, mapping, names, offset in (
        (tmp_path / "a", a, ("0", "9"), 10),
        (tmp_path / "b", b, ("400", "2"), 300),
    ):
        for name, selected in zip(names, (mapping.images[:3], mapping.images[3:6]), strict=True):
            write_model(
                root / "sparse" / name, mapping, selected=selected, native_camera_offset=offset
            )
        (root / "backend_mapping.json").write_text(mapping.model_dump_json())
        value = make_set(mapping, read_components(root, mapping))
        values.append(value)
        reader = ColmapReconstructionReader(root, value)
        assert tuple(reader.unregistered_views()) == (UUID(int=7),)
        assert (
            sum(len(tuple(reader.registered_views(c.component_id))) for c in reader.components())
            == 6
        )
    assert values[0].semantic_digest == values[1].semantic_digest
    assert values[0].upstream != values[1].upstream
    altered = values[0].model_copy(update={"method_id": "future.mapper", "recipe_key": "1" * 64})
    assert reconstruction_semantic_digest(altered) == values[0].semantic_digest
    assert ReconstructionSet.model_validate_json(values[0].model_dump_json(indent=4)) == values[0]
    assert ReconstructionSet.model_validate_json(values[0].model_dump_json()) == values[0]
    changed = values[0].model_copy(update={"unregistered_view_ids": (UUID(int=8),)})
    assert reconstruction_semantic_digest(changed) != values[0].semantic_digest


def test_duplicate_membership_refused_and_unknown_points_are_not_zero(tmp_path):
    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 4)))
    write_model(tmp_path / "sparse" / "4", mapping)
    value = make_set(mapping, read_components(tmp_path, mapping))
    component = value.components[0]
    unknown = component.model_copy(
        update={"point_count": None, "points": "unavailable", "tracks": "unavailable"}
    )
    assert unknown.point_count is None and unknown.point_count != 0
    assert component.point_count == 0 and component.points == "not_published"
    with pytest.raises(ValueError, match="membership"):
        ReconstructionSet.model_validate(
            {**value.model_dump(), "components": (component, component)}
        )
