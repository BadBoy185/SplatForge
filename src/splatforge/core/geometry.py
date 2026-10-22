"""Independent geometric verification settings, camera inputs and numerical output."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from heapq import nlargest
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.features import Digest, LocalFeatureSet, digest_json
from splatforge.core.matching import (
    MAX_MATCHES_PER_PAIR,
    MatchingResourceEstimate,
    MatchingResourceLimits,
    MatchSet,
)
from splatforge.core.pairs import MAX_PAIRS, PairEndpoints
from splatforge.core.views import MAX_VIEWS, FrozenModel, canonical_json_bytes

GEOMETRY_ARTIFACT_TYPE = "geometry.verified_geometry_set"


class VerificationSettings(FrozenModel):
    method_id: Literal["geometric_verification.colmap"] = "geometric_verification.colmap"
    settings_version: Literal[1] = 1
    min_num_inliers: int = Field(default=15, ge=8, le=MAX_MATCHES_PER_PAIR, strict=True)
    max_error: float = Field(default=4.0, gt=0, le=100)
    confidence: float = Field(default=0.999, gt=0, lt=1)
    max_num_trials: int = Field(default=10000, ge=100, le=1_000_000, strict=True)
    min_inlier_ratio: float = Field(default=0.0, ge=0, le=1)
    multiple_models: bool = Field(default=False, strict=True)
    compute_relative_pose: bool = Field(default=False, strict=True)
    detect_watermark: bool = Field(default=True, strict=True)
    multiple_ignore_watermark: bool = Field(default=True, strict=True)
    watermark_detection_max_error: float = Field(default=4.0, gt=0, le=100)
    filter_stationary_matches: bool = Field(default=False, strict=True)
    stationary_matches_max_error: float = Field(default=4.0, gt=0, le=100)
    use_degensac: bool = Field(default=False, strict=True)
    use_sampson_refinement: bool = Field(default=True, strict=True)
    random_seed: int = Field(default=0, ge=0, le=2**31 - 1, strict=True)
    num_threads: int = Field(default=1, ge=1, le=64, strict=True)
    batch_size: int = Field(default=1000, ge=1, le=1000, strict=True)


class ViewCameraPrior(FrozenModel):
    view_id: UUID
    camera_group_id: UUID | None = None
    model: Literal["SIMPLE_PINHOLE", "PINHOLE", "SIMPLE_RADIAL", "RADIAL", "OPENCV", "FULL_OPENCV"]
    width: int = Field(ge=1, le=32768, strict=True)
    height: int = Field(ge=1, le=32768, strict=True)
    parameters: tuple[float, ...] = Field(min_length=3, max_length=12)
    prior_focal_length: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def perspective_parameters(self) -> ViewCameraPrior:
        count = {
            "SIMPLE_PINHOLE": 3,
            "PINHOLE": 4,
            "SIMPLE_RADIAL": 4,
            "RADIAL": 5,
            "OPENCV": 8,
            "FULL_OPENCV": 12,
        }[self.model]
        if len(self.parameters) != count or self.parameters[0] <= 0:
            raise ValueError("Camera parameter count/focal length differs from perspective model")
        if self.model in {"PINHOLE", "OPENCV", "FULL_OPENCV"} and self.parameters[1] <= 0:
            raise ValueError("Camera fy must be positive")
        return self

    def sharing_key(self) -> tuple[bool, UUID]:
        return self.camera_group_id is not None, self.camera_group_id or self.view_id


class CameraPriorSet(FrozenModel):
    contract_version: Literal[1] = 1
    policy: Literal["explicit_v1", "uncalibrated_focal_1.2_v1"] = "explicit_v1"
    cameras: tuple[ViewCameraPrior, ...] = Field(min_length=1, max_length=MAX_VIEWS)

    @model_validator(mode="after")
    def canonical(self) -> CameraPriorSet:
        ids = [v.view_id.int for v in self.cameras]
        if ids != sorted(set(ids)):
            raise ValueError("Camera priors require unique canonical view order")
        groups = {}
        for camera in self.cameras:
            group = camera.sharing_key()
            numerical = camera.model_dump(exclude={"view_id", "camera_group_id"})
            if group in groups and groups[group] != numerical:
                raise ValueError("Shared camera group requires identical calibration/dimensions")
            groups[group] = numerical
        return self

    @property
    def semantic_digest(self) -> str:
        groups = {}
        for camera in self.cameras:
            groups.setdefault(camera.sharing_key(), []).append(str(camera.view_id))
        sharing = sorted(groups.values(), key=lambda members: UUID(members[0]).int)
        return digest_json(
            {
                "contract_version": 1,
                "sharing": sharing,
                "cameras": [
                    c.model_dump(mode="json", exclude={"camera_group_id"}) for c in self.cameras
                ],
            }
        )


class GeometryPairState(StrEnum):
    NO_RAW_MATCHES = "no_raw_matches"
    INSUFFICIENT_RAW_MATCHES = "insufficient_raw_matches"
    GEOMETRICALLY_REJECTED = "geometrically_rejected"
    VERIFIED = "verified"


def uncalibrated_camera_priors(features: LocalFeatureSet) -> CameraPriorSet:
    return CameraPriorSet(
        policy="uncalibrated_focal_1.2_v1",
        cameras=tuple(
            ViewCameraPrior(
                view_id=v.view_id,
                model="SIMPLE_RADIAL",
                width=v.width,
                height=v.height,
                parameters=(1.2 * max(v.width, v.height), v.width / 2, v.height / 2, 0.0),
                prior_focal_length=False,
            )
            for v in features.views
        ),
    )


class GeometryPairSummary(PairEndpoints):
    state: GeometryPairState
    raw_match_count: int = Field(ge=0, le=MAX_MATCHES_PER_PAIR, strict=True)
    inlier_count: int = Field(ge=0, le=MAX_MATCHES_PER_PAIR, strict=True)
    # Native IDs never cross this boundary; numerical output is streamed into this digest.
    geometry_digest: Digest
    configuration: int = Field(ge=0, le=9, strict=True)
    has_f: bool = False
    has_e: bool = False
    has_h: bool = False
    has_relative_pose: bool = False
    estimated_left_camera: ViewCameraPrior | None = None
    estimated_right_camera: ViewCameraPrior | None = None


class VerifiedGeometrySet(FrozenModel):
    contract_version: Literal[1] = 1
    matches_artifact_id: UUID
    matches_semantic_digest: Digest
    method_id: Literal["geometric_verification.colmap"] = "geometric_verification.colmap"
    method_version: Literal[1] = 1
    settings: VerificationSettings
    camera_prior_digest: Digest
    backend_numerical_identity: Digest
    input_pair_count: int = Field(ge=1, le=MAX_PAIRS, strict=True)
    eligible_pair_count: int = Field(ge=0, le=MAX_PAIRS, strict=True)
    accepted_pair_count: int = Field(ge=0, le=MAX_PAIRS, strict=True)
    rejected_pair_count: int = Field(ge=0, le=MAX_PAIRS, strict=True)
    total_raw_matches: int = Field(ge=0, le=MAX_PAIRS * MAX_MATCHES_PER_PAIR, strict=True)
    total_verified_inliers: int = Field(ge=0, le=MAX_PAIRS * MAX_MATCHES_PER_PAIR, strict=True)
    pairs: tuple[GeometryPairSummary, ...] = Field(min_length=1, max_length=MAX_PAIRS)
    semantic_digest: Digest

    @model_validator(mode="after")
    def consistent(self) -> VerifiedGeometrySet:
        keys = [(p.left_view_id.int, p.right_view_id.int) for p in self.pairs]
        accepted = sum(p.state == GeometryPairState.VERIFIED for p in self.pairs)
        if keys != sorted(set(keys)) or len(keys) != self.input_pair_count:
            raise ValueError("Geometry must explain every canonical input pair exactly once")
        if (
            self.accepted_pair_count != accepted
            or self.rejected_pair_count != len(keys) - accepted
            or self.eligible_pair_count != sum(p.raw_match_count > 0 for p in self.pairs)
            or self.total_raw_matches != sum(p.raw_match_count for p in self.pairs)
            or self.total_verified_inliers != sum(p.inlier_count for p in self.pairs)
        ):
            raise ValueError("Geometry totals differ from pair summaries")
        for pair in self.pairs:
            if (
                pair.estimated_left_camera is not None
                and pair.estimated_left_camera.view_id != pair.left_view_id
            ) or (
                pair.estimated_right_camera is not None
                and pair.estimated_right_camera.view_id != pair.right_view_id
            ):
                raise ValueError("Estimated camera must use its canonical pair endpoint UUID")
            expected = (
                GeometryPairState.NO_RAW_MATCHES
                if pair.raw_match_count == 0
                else GeometryPairState.INSUFFICIENT_RAW_MATCHES
                if pair.raw_match_count < self.settings.min_num_inliers
                else GeometryPairState.VERIFIED
                if pair.inlier_count >= self.settings.min_num_inliers and pair.configuration >= 2
                else GeometryPairState.GEOMETRICALLY_REJECTED
            )
            if pair.state != expected or pair.inlier_count > pair.raw_match_count:
                raise ValueError("Geometry pair state/count is inconsistent")
        if geometry_semantic_digest(self) != self.semantic_digest:
            raise ValueError("VerifiedGeometrySet semantic digest mismatch")
        return self


def geometry_semantic_digest(value: VerifiedGeometrySet) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            value.model_dump(
                mode="json",
                exclude={"matches_artifact_id", "pairs", "semantic_digest"},
            )
        )
    )
    for pair in value.pairs:
        digest.update(canonical_json_bytes(pair.model_dump(mode="json")))
    return digest.hexdigest()


def verification_recipe_key(
    match_digest: str,
    camera_digest: str,
    settings: VerificationSettings,
    backend_identity: str,
) -> str:
    return digest_json(
        {
            "fingerprint_version": 1,
            "contract_version": 1,
            "method_version": 1,
            "matches": match_digest,
            "cameras": camera_digest,
            "settings": settings.model_dump(mode="json"),
            "backend": backend_identity,
        }
    )


def estimate_verification_resources(
    features: LocalFeatureSet,
    matches: MatchSet,
    settings: VerificationSettings,
    limits: MatchingResourceLimits,
    *,
    upstream_bytes: int,
) -> MatchingResourceEstimate:
    workers = min(settings.num_threads, settings.batch_size, matches.matched_pair_count)
    concurrent = nlargest(workers, (p.raw_match_count for p in matches.pairs))
    # Known numerical buffers: uint32 raw index pairs, two float64 2D point
    # arrays per concurrent pair, and float64 image coordinates. Native solver
    # and allocator overhead remain unknown; this does not promise allocation.
    working = matches.total_raw_match_count * 8 + sum(concurrent) * 32
    if workers:
        working += features.total_feature_count * 16
    database = upstream_bytes + matches.total_raw_match_count * 32 + 1024**2
    if (
        len(matches.pairs) > limits.max_pairs
        or matches.total_raw_match_count > limits.max_raw_matches
        or features.total_feature_count > limits.max_total_features
        or database * 3 > limits.max_workspace_bytes
        or working > limits.max_pair_working_bytes
    ):
        raise ValueError(
            "Verification pair/correspondence/workspace/working-memory budget exceeded"
        )
    return MatchingResourceEstimate(
        pair_count=matches.matched_pair_count,
        view_count=len(features.views),
        total_features=features.total_feature_count,
        raw_matches=matches.total_raw_match_count,
        database_bytes=database,
        peak_workspace_bytes=database * 3,
    )
