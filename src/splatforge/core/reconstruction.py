"""Portable immutable reconstruction records and numerical identities (M8a v1)."""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Iterable, Iterator
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from splatforge.core.features import Digest, FeatureBackend, digest_json
from splatforge.core.geometry import ViewCameraPrior
from splatforge.core.views import MAX_VIEWS, FrozenModel

RECONSTRUCTION_ARTIFACT_TYPE = "mapping.reconstruction_set"
CONVENTION = "right_handed_camera_from_world_x_right_y_down_z_forward_wxyz_pixels_center_0.5_v1"
IDENTITY_NAMESPACE = UUID("ac772aa6-ef6e-5fc8-a1fe-fd51f2b39bd9")
MAX_RECONSTRUCTION_METADATA_BYTES = 64 * 1024**2


class RecordAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_PUBLISHED = "not_published"


class MappingCalibrationPolicy(StrEnum):
    PRESERVE_PRIORS = "preserve_priors"
    VIEW_GRAPH = "view_graph"


class ViewGraphCalibrationSettings(FrozenModel):
    settings_version: Literal[1] = 1
    cross_validate_prior_focal_lengths: bool = True
    min_calibrated_pair_ratio: float = Field(default=0.5, ge=0, le=1)
    reestimate_relative_pose: bool = True
    min_focal_length_ratio: float = Field(default=0.1, gt=0)
    max_focal_length_ratio: float = Field(default=10.0, gt=0)
    max_calibration_error: float = Field(default=2.0, gt=0)
    relpose_max_error: float = Field(default=1.0, gt=0)
    relpose_min_num_inliers: int = Field(default=30, ge=8, le=100000, strict=True)
    relpose_min_inlier_ratio: float = Field(default=0.25, ge=0, le=1)
    random_seed: int = Field(default=0, ge=0, le=2**31 - 1, strict=True)

    @model_validator(mode="after")
    def ratios(self) -> ViewGraphCalibrationSettings:
        if self.max_focal_length_ratio < self.min_focal_length_ratio:
            raise ValueError("Invalid calibration focal-length ratio range")
        return self


class GlobalMapperSettings(FrozenModel):
    method_id: Literal["mapping.colmap_global"] = "mapping.colmap_global"
    settings_version: Literal[1] = 1
    min_num_matches: int = Field(default=15, ge=8, le=100000, strict=True)
    num_threads: int = Field(default=1, ge=1, le=64, strict=True)
    random_seed: int = Field(default=0, ge=0, le=2**31 - 1, strict=True)
    multiple_models: Literal[True] = True
    min_model_size: int = Field(default=3, ge=3, le=MAX_VIEWS, strict=True)
    ba_num_iterations: int = Field(default=3, ge=1, le=100, strict=True)
    gp_max_num_iterations: int = Field(default=100, ge=1, le=10000, strict=True)
    ba_ceres_max_num_iterations: int = Field(default=200, ge=1, le=10000, strict=True)
    ba_refine_focal_length: bool = True
    ba_refine_principal_point: bool = False
    ba_refine_extra_params: bool = True
    # Deliberately fixed CPU/CERES route. Remaining native defaults are frozen by
    # exact executable + DLL identity, rather than claimed as portable defaults.
    gp_use_gpu: Literal[False] = False
    ba_ceres_use_gpu: Literal[False] = False
    ba_backend: Literal["CERES"] = "CERES"


class MappingBackend(FeatureBackend):
    adapter_id: Literal["splatforge.colmap_global"] = "splatforge.colmap_global"
    operation: Literal["global_mapper"] = "global_mapper"
    calibration_option_names: tuple[str, ...] = ()


class MappingInput(FrozenModel):
    contract_version: Literal[1] = 1
    view_ids: tuple[UUID, ...] = Field(min_length=1, max_length=MAX_VIEWS)
    cameras_digest: Digest
    keypoints_digest: Digest
    geometry_digest: Digest
    verified_pair_count: int = Field(ge=0, strict=True)
    keypoint_count: int = Field(ge=0, strict=True)
    inlier_count: int = Field(ge=0, strict=True)
    transport: Literal["independent_camera_frames_v1"] = "independent_camera_frames_v1"

    @model_validator(mode="after")
    def canonical(self) -> MappingInput:
        if list(self.view_ids) != sorted(set(self.view_ids), key=lambda v: v.int):
            raise ValueError("Mapping universe must be unique and canonical")
        return self

    @property
    def semantic_digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class MappingResourceLimits(FrozenModel):
    max_views: int = Field(default=10000, ge=3, le=MAX_VIEWS, strict=True)
    max_pairs: int = Field(default=100000, ge=1, le=1000000, strict=True)
    max_keypoints: int = Field(default=100000000, ge=1, strict=True)
    max_inliers: int = Field(default=100000000, ge=1, strict=True)
    max_database_bytes: int = Field(default=64 * 1024**3, ge=1, le=1024**4, strict=True)
    max_output_bytes: int = Field(default=16 * 1024**3, ge=1, le=1024**4, strict=True)
    max_workspace_bytes: int = Field(default=128 * 1024**3, ge=1, le=1024**4, strict=True)
    timeout_seconds: int = Field(default=7200, ge=1, le=86400, strict=True)


class MappingResourceEstimate(FrozenModel):
    database_bytes: int = Field(ge=1, strict=True)
    peak_workspace_bytes: int = Field(ge=1, strict=True)
    output_bytes: int = Field(ge=1, strict=True)


def estimate_mapping_resources(
    value: MappingInput,
    database_bytes: int,
    limits: MappingResourceLimits,
) -> MappingResourceEstimate:
    # Reservation includes independent copy, SQLite journal growth and sparse output.
    # This is a disk refusal gate, not a prediction of native peak host memory.
    output = (
        value.keypoint_count * 75 + value.inlier_count * 16 + len(value.view_ids) * 2048 + 1024**2
    )
    # Sparse validation uses a bounded disk-backed reciprocal-observation index.
    peak = 3 * database_bytes + 5 * output
    if (
        len(value.view_ids) > limits.max_views
        or value.verified_pair_count > limits.max_pairs
        or value.keypoint_count > limits.max_keypoints
        or value.inlier_count > limits.max_inliers
        or output > limits.max_output_bytes
        or database_bytes > limits.max_database_bytes
        or peak > limits.max_workspace_bytes
    ):
        raise ValueError("mapping.resource_limit: mapping preflight budget exceeded")
    return MappingResourceEstimate(
        database_bytes=database_bytes, peak_workspace_bytes=peak, output_bytes=output
    )


def mapping_recipe_key(
    input_digest: str,
    settings: GlobalMapperSettings,
    policy: MappingCalibrationPolicy,
    calibration: ViewGraphCalibrationSettings | None,
    backend_identity: str,
) -> str:
    return digest_json(
        {
            "fingerprint_version": 1,
            "contract_version": 1,
            "method_version": 1,
            "input": input_digest,
            "settings": settings.model_dump(mode="json"),
            "policy": policy,
            "calibration": calibration.model_dump(mode="json") if calibration else None,
            "backend": backend_identity,
        }
    )


def membership_id(members: Iterable[UUID], kind: str = "component") -> UUID:
    ordered = sorted(set(members), key=lambda v: v.int)
    if not ordered:
        raise ValueError("Identity requires nonempty membership")
    return uuid5(IDENTITY_NAMESPACE, kind + ".membership.v1:" + ",".join(map(str, ordered)))


class ReconstructionPose(FrozenModel):
    """camera_from_world: p_camera = R(wxyz) @ p_world + translation; arbitrary scale."""

    quaternion_wxyz: tuple[float, float, float, float]
    translation: tuple[float, float, float]

    @model_validator(mode="after")
    def rotation_valid(self) -> ReconstructionPose:
        if abs(sum(x * x for x in self.quaternion_wxyz) - 1) > 1e-8:
            raise ValueError("mapping.invalid_pose: quaternion must have unit length")
        return self

    def rotation_matrix(self) -> tuple[tuple[float, float, float], ...]:
        w, x, y, z = self.quaternion_wxyz
        return (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
        )

    def camera_center(self) -> tuple[float, float, float]:
        r, t = self.rotation_matrix(), self.translation
        return tuple(-sum(r[j][i] * t[j] for j in range(3)) for i in range(3))


class ReconstructionCamera(FrozenModel):
    camera_id: UUID
    model: str
    width: int = Field(ge=1, le=32768, strict=True)
    height: int = Field(ge=1, le=32768, strict=True)
    parameters: tuple[float, ...]

    @model_validator(mode="after")
    def perspective(self) -> ReconstructionCamera:
        ViewCameraPrior(
            view_id=self.camera_id,
            model=self.model,
            width=self.width,
            height=self.height,
            parameters=self.parameters,
        )
        return self


class RegisteredView(FrozenModel):
    view_id: UUID
    camera_id: UUID
    pose: ReconstructionPose


class ReconstructionComponent(FrozenModel):
    component_id: UUID
    semantic_digest: Digest
    registered_view_ids: tuple[UUID, ...] = Field(min_length=1, max_length=MAX_VIEWS)
    registered_view_count: int = Field(ge=1, strict=True)
    camera_count: int = Field(ge=1, strict=True)
    point_count: int | None = Field(default=None, ge=0, strict=True)
    points: RecordAvailability = RecordAvailability.NOT_PUBLISHED
    tracks: RecordAvailability = RecordAvailability.NOT_PUBLISHED
    native_payload: str = Field(min_length=1, max_length=1024)
    native_model_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def membership(self) -> ReconstructionComponent:
        from pathlib import PurePosixPath, PureWindowsPath

        path = self.native_payload
        if (
            "\\" in path
            or PureWindowsPath(path).drive
            or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ValueError("Native component payload requires a contained relative locator")
        ids = self.registered_view_ids
        if (
            list(ids) != sorted(set(ids), key=lambda v: v.int)
            or self.registered_view_count != len(ids)
            or self.component_id != membership_id(ids)
        ):
            raise ValueError("Invalid component identity/membership/count")
        return self


class CalibrationResult(FrozenModel):
    policy: MappingCalibrationPolicy
    settings: ViewGraphCalibrationSettings | None
    method_id: Literal["calibration.colmap_view_graph"] | None = None
    method_version: Literal[1] = 1
    backend_identity: Digest
    cameras_before: Digest
    cameras_after: Digest
    mapping_input_after: MappingInput
    result_digest: Digest

    @model_validator(mode="after")
    def consistent(self) -> CalibrationResult:
        selected = self.policy == MappingCalibrationPolicy.VIEW_GRAPH
        if selected != (self.settings is not None) or selected != (self.method_id is not None):
            raise ValueError("Calibration policy/settings/method mismatch")
        if self.cameras_after != self.mapping_input_after.cameras_digest:
            raise ValueError("Calibration camera state mismatch")
        if self.result_digest != calibration_result_digest(self):
            raise ValueError("Calibration result identity mismatch")
        return self


def calibration_result_digest(value: CalibrationResult) -> str:
    return digest_json(value.model_dump(mode="json", exclude={"result_digest"}))


class ReconstructionSetting(FrozenModel):
    name: str = Field(min_length=1, max_length=128)
    value: bool | int | float | str


class ReconstructionLineage(FrozenModel):
    input_name: str = Field(min_length=1, max_length=128)
    artifact_id: UUID
    semantic_digest: Digest


class ReconstructionCalibration(FrozenModel):
    policy: str = Field(min_length=1, max_length=128)
    method_id: str | None = Field(default=None, max_length=128)
    method_version: int = Field(default=1, ge=1, strict=True)
    settings: tuple[ReconstructionSetting, ...] = Field(default=(), max_length=128)
    backend_identity: Digest
    cameras_before: Digest
    cameras_after: Digest
    input_after_digest: Digest
    result_digest: Digest


class ReconstructionSet(FrozenModel):
    """Backend-neutral output. Producing routes retain their own typed receipts.

    No requirement for features/pairs/verification is imposed on future direct routes.
    Numerical output identity excludes all producing-route and algorithm provenance.
    """

    contract_version: Literal[1] = 1
    upstream: tuple[ReconstructionLineage, ...] = Field(default=(), max_length=8)
    mapping_input_digest: Digest
    input_view_ids: tuple[UUID, ...] = Field(min_length=1, max_length=MAX_VIEWS)
    method_id: str = Field(min_length=1, max_length=128)
    method_version: int = Field(default=1, ge=1, strict=True)
    settings_version: int = Field(default=1, ge=1, strict=True)
    resolved_settings: tuple[ReconstructionSetting, ...] = Field(max_length=128)
    calibration: ReconstructionCalibration
    backend_numerical_identity: Digest
    recipe_key: Digest
    components: tuple[ReconstructionComponent, ...] = Field(min_length=1, max_length=MAX_VIEWS)
    component_count: int = Field(ge=1, strict=True)
    registered_view_count: int = Field(ge=1, strict=True)
    unregistered_view_count: int = Field(ge=0, strict=True)
    unregistered_view_ids: tuple[UUID, ...] = Field(max_length=MAX_VIEWS)
    convention: Literal[CONVENTION] = CONVENTION
    scale: Literal["unknown_arbitrary"] = "unknown_arbitrary"
    native_format: str = Field(min_length=1, max_length=128)
    semantic_digest: Digest

    @model_validator(mode="after")
    def consistent(self) -> ReconstructionSet:
        ids = [c.component_id.int for c in self.components]
        members = [v for c in self.components for v in c.registered_view_ids]
        unregistered = self.unregistered_view_ids
        if (
            ids != sorted(set(ids))
            or len(members) != len(set(members))
            or list(self.input_view_ids) != sorted(set(self.input_view_ids), key=lambda v: v.int)
            or list(unregistered) != sorted(set(unregistered), key=lambda v: v.int)
            or set(members) & set(unregistered)
            or set(members) | set(unregistered) != set(self.input_view_ids)
            or self.component_count != len(ids)
            or self.registered_view_count != len(members)
            or self.unregistered_view_count != len(unregistered)
        ):
            raise ValueError(
                "mapping.universe_violation: component/set membership or totals differ"
            )
        if self.semantic_digest != reconstruction_semantic_digest(self):
            raise ValueError("Reconstruction semantic identity mismatch")
        return self


def resolved_settings(settings: FrozenModel) -> tuple[ReconstructionSetting, ...]:
    return tuple(
        ReconstructionSetting(name=k, value=v)
        for k, v in sorted(settings.model_dump().items())
        if k not in {"method_id", "settings_version"}
    )


def calibration_summary(value: CalibrationResult) -> ReconstructionCalibration:
    return ReconstructionCalibration(
        policy=value.policy,
        method_id=value.method_id,
        method_version=value.method_version,
        settings=resolved_settings(value.settings) if value.settings else (),
        backend_identity=value.backend_identity,
        cameras_before=value.cameras_before,
        cameras_after=value.cameras_after,
        input_after_digest=value.mapping_input_after.semantic_digest,
        result_digest=value.result_digest,
    )


class ClassicalMappingReceipt(FrozenModel):
    """Classical M7 -> Global provenance, separate from the portable output contract."""

    contract_version: Literal[1] = 1
    verification_artifact_id: UUID
    verification_semantic_digest: Digest
    mapping_input: MappingInput
    settings: GlobalMapperSettings
    calibration: CalibrationResult
    backend_numerical_identity: Digest

    @model_validator(mode="after")
    def consistent(self) -> ClassicalMappingReceipt:
        if (
            self.calibration.cameras_before != self.mapping_input.cameras_digest
            or self.calibration.mapping_input_after.view_ids != self.mapping_input.view_ids
            or self.calibration.mapping_input_after.keypoints_digest
            != self.mapping_input.keypoints_digest
            or self.calibration.backend_identity != self.backend_numerical_identity
        ):
            raise ValueError("Calibration lineage differs from mapping input")
        if (
            self.calibration.policy == MappingCalibrationPolicy.PRESERVE_PRIORS
            and self.calibration.mapping_input_after != self.mapping_input
        ):
            raise ValueError("Preserve priors must preserve the complete numerical input")
        return self

    @property
    def recipe_key(self) -> str:
        return mapping_recipe_key(
            self.mapping_input.semantic_digest,
            self.settings,
            self.calibration.policy,
            self.calibration.settings,
            self.backend_numerical_identity,
        )

    def require_output(self, value: ReconstructionSet) -> None:
        if (
            value.mapping_input_digest != self.mapping_input.semantic_digest
            or value.input_view_ids != self.mapping_input.view_ids
            or value.method_id != self.settings.method_id
            or value.method_version != 1
            or value.settings_version != self.settings.settings_version
            or value.resolved_settings != resolved_settings(self.settings)
            or value.calibration != calibration_summary(self.calibration)
            or value.backend_numerical_identity != self.backend_numerical_identity
            or value.native_format != "colmap.sparse.binary.v1"
            or value.recipe_key != self.recipe_key
            or value.upstream
            != (
                ReconstructionLineage(
                    input_name="verified_geometry",
                    artifact_id=self.verification_artifact_id,
                    semantic_digest=self.verification_semantic_digest,
                ),
            )
        ):
            raise ValueError("mapping.input_mismatch: output differs from typed mapping receipt")


def numerical_bytes(values: Iterable[float]) -> bytes:
    result = bytearray()
    for value in values:
        if not math.isfinite(value):
            raise ValueError("Non-finite numerical reconstruction")
        result.extend(struct.pack("<d", 0.0 if value == 0 else value))
    return bytes(result)


def component_semantic_digest(
    cameras: Iterable[ReconstructionCamera],
    views: Iterable[RegisteredView],
    *,
    point_count: int | None = None,
) -> str:
    digest = hashlib.sha256((CONVENTION + ":camera_pose_semantics_v1").encode())
    for camera in sorted(cameras, key=lambda c: c.camera_id.int):
        digest.update(camera.camera_id.bytes)
        digest.update(camera.model.encode("ascii") + b"\0")
        digest.update(struct.pack("<II", camera.width, camera.height))
        digest.update(numerical_bytes(camera.parameters))
    for view in sorted(views, key=lambda v: v.view_id.int):
        digest.update(view.view_id.bytes + view.camera_id.bytes)
        q = view.pose.quaternion_wxyz
        # q and -q encode the same rotation. Normalize the hemisphere only.
        sign = next((1 if x > 0 else -1 for x in q if x != 0), 1)
        digest.update(numerical_bytes(x * sign for x in q))
        digest.update(numerical_bytes(view.pose.translation))
    digest.update(b"native_point_count:")
    digest.update(b"unavailable" if point_count is None else struct.pack("<Q", point_count))
    return digest.hexdigest()


def reconstruction_semantic_digest(value: ReconstructionSet) -> str:
    digest = hashlib.sha256((value.convention + ":" + value.scale).encode())
    for component in value.components:
        digest.update(component.component_id.bytes + bytes.fromhex(component.semantic_digest))
        for view in component.registered_view_ids:
            digest.update(view.bytes)
    digest.update(b"unregistered")
    for view in value.unregistered_view_ids:
        digest.update(view.bytes)
    return digest.hexdigest()


class ReconstructionReader(Protocol):
    """Readers expose UUIDs and typed numerical records; native IDs stay in adapters.

    M8a portable semantics include cameras/poses. Detailed native points/tracks
    remain preserved payloads but are not published through this version's reader.
    Unavailable access raises an explicit error; it is never an empty iterator.
    """

    def components(self) -> Iterator[ReconstructionComponent]: ...
    def cameras(self, component_id: UUID) -> Iterator[ReconstructionCamera]: ...
    def registered_views(self, component_id: UUID) -> Iterator[RegisteredView]: ...
    def unregistered_views(self) -> Iterator[UUID]: ...
    def points(self, component_id: UUID) -> Iterator[object]: ...
    def tracks(self, component_id: UUID) -> Iterator[object]: ...
