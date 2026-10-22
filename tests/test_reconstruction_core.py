"""Numerical identities and explicit camera convention, without native execution."""

import math
from uuid import UUID

import pytest

from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    MappingCalibrationPolicy,
    MappingInput,
    MappingResourceLimits,
    ReconstructionCamera,
    ReconstructionPose,
    RegisteredView,
    component_semantic_digest,
    estimate_mapping_resources,
    mapping_recipe_key,
    membership_id,
)

VIEWS = tuple(UUID(int=i) for i in (1, 2, 3))


def test_component_membership_identity_and_geometry_are_separate():
    camera = ReconstructionCamera(
        camera_id=membership_id(VIEWS, "camera"),
        model="PINHOLE",
        width=32,
        height=24,
        parameters=(100, 110, 16, 12),
    )
    views = tuple(
        RegisteredView(
            view_id=v,
            camera_id=camera.camera_id,
            pose=ReconstructionPose(quaternion_wxyz=(1, 0, 0, 0), translation=(0, 0, 0)),
        )
        for v in VIEWS
    )
    changed = (
        views[0].model_copy(
            update={"pose": ReconstructionPose(quaternion_wxyz=(1, 0, 0, 0), translation=(1, 0, 0))}
        ),
        *views[1:],
    )
    assert membership_id(v.view_id for v in changed) == membership_id(VIEWS)
    assert component_semantic_digest((camera,), views) != component_semantic_digest(
        (camera,), changed
    )
    assert membership_id((*VIEWS[:2], UUID(int=4))) != membership_id(VIEWS)
    assert membership_id(reversed(VIEWS)) == membership_id(VIEWS)
    assert component_semantic_digest((camera,), reversed(views)) == component_semantic_digest(
        (camera,), views
    )
    opposite = tuple(
        v.model_copy(update={"pose": v.pose.model_copy(update={"quaternion_wxyz": (-1, 0, 0, 0)})})
        for v in views
    )
    assert component_semantic_digest((camera,), opposite) == component_semantic_digest(
        (camera,), views
    )


def test_exact_world_to_camera_wxyz_and_center_convention():
    pose = ReconstructionPose(
        quaternion_wxyz=(math.sqrt(0.5), 0, 0, math.sqrt(0.5)), translation=(1, 2, 3)
    )
    for row, expected in zip(
        pose.rotation_matrix(), ((0, -1, 0), (1, 0, 0), (0, 0, 1)), strict=True
    ):
        assert row == pytest.approx(expected)
    assert pose.camera_center() == pytest.approx((-2, 1, -3))
    r, center = pose.rotation_matrix(), pose.camera_center()
    assert tuple(
        sum(r[i][j] * center[j] for j in range(3)) + pose.translation[i] for i in range(3)
    ) == pytest.approx((0, 0, 0))
    with pytest.raises(ValueError, match="unit length"):
        ReconstructionPose(quaternion_wxyz=(0, 0, 0, 0), translation=(0, 0, 0))
    with pytest.raises(ValueError):
        ReconstructionPose(quaternion_wxyz=(1, 0, 0, 0), translation=(float("nan"), 0, 0))


def test_recipe_only_numerical_dependencies_and_resource_refusal():
    value = MappingInput(
        view_ids=VIEWS,
        cameras_digest="a" * 64,
        keypoints_digest="b" * 64,
        geometry_digest="c" * 64,
        verified_pair_count=2,
        keypoint_count=30,
        inlier_count=20,
    )
    settings = GlobalMapperSettings()

    def key(v=value, s=settings):
        return mapping_recipe_key(
            v.semantic_digest, s, MappingCalibrationPolicy.PRESERVE_PRIORS, None, "d" * 64
        )

    assert key() != key(s=settings.model_copy(update={"random_seed": 1}))
    assert key() != key(v=value.model_copy(update={"keypoints_digest": "e" * 64}))
    assert key() != key(v=value.model_copy(update={"cameras_digest": "e" * 64}))
    assert key() != key(v=value.model_copy(update={"geometry_digest": "e" * 64}))
    a, b = MappingResourceLimits(), MappingResourceLimits(max_views=10001)
    assert estimate_mapping_resources(value, 100, a) == estimate_mapping_resources(value, 100, b)
    with pytest.raises(ValueError, match="resource_limit"):
        estimate_mapping_resources(value, 100, MappingResourceLimits(max_inliers=10))
    with pytest.raises(ValueError):
        GlobalMapperSettings(multiple_models=False)
