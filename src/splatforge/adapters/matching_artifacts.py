"""M7b payload and lineage validation shared by publication/cache/recovery."""

from pathlib import Path

from splatforge.adapters.artifact_validation import (
    ValidatedArtifact,
    _payload_digest,
    _plain_file,
    _read_bounded,
)
from splatforge.adapters.feature_database import NativeFeaturePayload
from splatforge.adapters.matching_database import (
    inspect_raw_matches,
    inspect_verified_geometry,
    validate_camera_priors,
)
from splatforge.core.execution import ArtifactManifest, PayloadFile
from splatforge.core.features import (
    FEATURE_ARTIFACT_TYPE,
    MAX_FEATURE_METADATA_BYTES,
    LocalFeatureSet,
)
from splatforge.core.geometry import GEOMETRY_ARTIFACT_TYPE, CameraPriorSet, VerifiedGeometrySet
from splatforge.core.matching import MATCH_ARTIFACT_TYPE, MAX_MATCH_METADATA_BYTES, MatchSet
from splatforge.core.pairs import MAX_PAIR_METADATA_BYTES, PAIR_ARTIFACT_TYPE, PairSet


def read_matching_inputs(output: Path) -> tuple[LocalFeatureSet, PairSet]:
    return (
        LocalFeatureSet.model_validate_json(
            _read_bounded(output / "features.json", MAX_FEATURE_METADATA_BYTES, "Feature snapshot")
        ),
        PairSet.model_validate_json(
            _read_bounded(output / "pair_set.json", MAX_PAIR_METADATA_BYTES, "PairSet snapshot")
        ),
    )


def validate_matching_output(
    output: Path,
    artifact_type: str,
    verified_payloads: dict[str, PayloadFile] | None,
) -> ValidatedArtifact:
    geometry = artifact_type == GEOMETRY_ARTIFACT_TYPE
    required = {
        "features.json",
        "backend_mapping.json",
        "matches.db",
        "pair_set.json",
        "match_set.json",
    }
    if geometry:
        required |= {"verified_geometry.json", "cameras.json"}
    names = {p.name for p in output.iterdir()}
    if names not in (required, required | {"manifest.json"}):
        raise ValueError("M7b output has missing/unexpected payloads")
    if any(not _plain_file(output / name) for name in required):
        raise ValueError("M7b payload requires plain independent files")
    features, pairs = read_matching_inputs(output)
    mapping = NativeFeaturePayload.model_validate_json(
        _read_bounded(output / "backend_mapping.json", 32 * 1024**2, "Native mapping")
    )
    matches = MatchSet.model_validate_json(
        _read_bounded(output / "match_set.json", MAX_MATCH_METADATA_BYTES, "MatchSet")
    )
    if (
        matches.features_semantic_digest != features.semantic_digest
        or matches.pairs_semantic_digest != pairs.semantic_digest
        or matches.descriptor != features.descriptor
    ):
        raise ValueError("MatchSet upstream semantic identities/signature differ from snapshots")
    raw = inspect_raw_matches(
        output / "matches.db",
        features,
        pairs,
        mapping,
        maximum_matches=matches.settings.max_num_matches,
        maximum_bytes=1024**4,
        allow_geometry=geometry,
    )
    if raw != matches.pairs:
        raise ValueError("Raw match numerical summaries differ from database")
    parsed = matches
    if geometry:
        parsed = VerifiedGeometrySet.model_validate_json(
            _read_bounded(
                output / "verified_geometry.json", MAX_MATCH_METADATA_BYTES, "VerifiedGeometrySet"
            )
        )
        cameras = CameraPriorSet.model_validate_json(
            _read_bounded(output / "cameras.json", MAX_FEATURE_METADATA_BYTES, "Camera priors")
        )
        if (
            parsed.matches_semantic_digest != matches.semantic_digest
            or parsed.camera_prior_digest != cameras.semantic_digest
        ):
            raise ValueError("Verified geometry input identities differ from snapshots")
        if {v.view_id: (v.width, v.height) for v in cameras.cameras} != {
            v.view_id: (v.width, v.height) for v in features.views
        }:
            raise ValueError("Verification camera universe differs from features")
        validate_camera_priors(output / "matches.db", cameras, mapping)
        summaries = inspect_verified_geometry(
            output / "matches.db",
            features,
            pairs,
            mapping,
            matches,
            parsed.settings,
            maximum_bytes=1024**4,
        )
        if summaries != parsed.pairs:
            raise ValueError("Verified geometry numerical summaries differ from database")
    payloads = []
    for name in sorted(required):
        size, digest = _payload_digest(output, output / name, verified_payloads)
        payloads.append(PayloadFile(path=name, size=size, sha256=digest))
    return ValidatedArtifact(
        payloads=tuple(payloads), parsed=parsed, semantic_digest=parsed.semantic_digest
    )


def validate_matching_lineage(
    parsed: MatchSet | VerifiedGeometrySet, manifest: ArtifactManifest
) -> None:
    lineage = {i.input_name: i for i in manifest.input_lineage}
    if isinstance(parsed, MatchSet):
        expected = (
            (
                "local_features",
                FEATURE_ARTIFACT_TYPE,
                parsed.features_artifact_id,
                parsed.features_semantic_digest,
            ),
            (
                "pair_set",
                PAIR_ARTIFACT_TYPE,
                parsed.pairs_artifact_id,
                parsed.pairs_semantic_digest,
            ),
        )
    else:
        expected = (
            (
                "match_set",
                MATCH_ARTIFACT_TYPE,
                parsed.matches_artifact_id,
                parsed.matches_semantic_digest,
            ),
        )
    if len(lineage) != len(expected) or len(manifest.input_lineage) != len(expected):
        raise ValueError("M7b lineage count mismatch")
    for name, kind, artifact, digest in expected:
        item = lineage.get(name)
        if (
            item is None
            or item.artifact_id != artifact
            or item.artifact_type != kind
            or item.semantic_digest != digest
            or item.contract_version != 1
        ):
            raise ValueError("M7b lineage differs from exact input artifact")
