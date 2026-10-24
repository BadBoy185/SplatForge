"""Bounded typed validation for published artifact families."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path, PurePosixPath, PureWindowsPath

from PIL import Image

from splatforge.core.dataset import (
    COMPONENT_ARTIFACT_TYPE as DATASET_COMPONENT_TYPE,
)
from splatforge.core.dataset import (
    SET_ARTIFACT_TYPE as DATASET_SET_TYPE,
)
from splatforge.core.dataset import (
    PreparedDatasetComponent,
    PreparedDatasetSet,
)
from splatforge.core.execution import ArtifactManifest, PayloadFile
from splatforge.core.fake_pipeline import (
    NUMBERS_ARTIFACT_TYPE,
    SCALED_ARTIFACT_TYPE,
    NumbersPayload,
    ScaledNumbersPayload,
    semantic_digest,
)
from splatforge.core.features import (
    FEATURE_ARTIFACT_TYPE,
    MAX_FEATURE_METADATA_BYTES,
    LocalFeatureSet,
)
from splatforge.core.geometry import GEOMETRY_ARTIFACT_TYPE, VerifiedGeometrySet
from splatforge.core.matching import MATCH_ARTIFACT_TYPE, MatchSet
from splatforge.core.pairs import (
    MAX_PAIR_METADATA_BYTES,
    PAIR_ARTIFACT_TYPE,
    PairSet,
)
from splatforge.core.quality import (
    QUALITY_ARTIFACT_TYPE,
    QualityReport,
    SharpestSelectedViewSet,
    quality_semantic_digest,
    sharpest_selected_semantic_digest,
)
from splatforge.core.reconstruction import RECONSTRUCTION_ARTIFACT_TYPE, ReconstructionSet
from splatforge.core.reconstruction_selection import (
    SELECTION_ARTIFACT_TYPE,
    ReconstructionSelectionArtifact,
)
from splatforge.core.reconstruction_validation import (
    GEOMETRY_ARTIFACT_TYPE as VALIDATION_GEOMETRY_ARTIFACT_TYPE,
)
from splatforge.core.reconstruction_validation import (
    METRICS_ARTIFACT_TYPE,
    REPORT_ARTIFACT_TYPE,
)
from splatforge.core.retrieval import RETRIEVAL_ARTIFACT_TYPE, RetrievalRepresentationSet
from splatforge.core.training import GaussianScene, GaussianSceneSet, TrainingCheckpoint
from splatforge.core.validation_artifacts import (
    ReconstructionMetricsArtifact,
    ReconstructionReportArtifact,
    ValidationGeometryArtifact,
)
from splatforge.core.views import (
    CANDIDATE_ARTIFACT_TYPE,
    MAX_VIEWS,
    SELECTED_ARTIFACT_TYPE,
    CandidateViewSet,
    ImageFormat,
    SelectedViewSet,
    candidate_semantic_digest,
    selected_semantic_digest,
)

MAX_METADATA_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_PAYLOADS = MAX_VIEWS + 1
MAX_DECODE_PIXELS = 64_000_000
MAX_DECODE_BYTES = 256 * 1024 * 1024
MAX_ENCODED_IMAGE_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class ValidatedArtifact:
    payloads: tuple[PayloadFile, ...]
    semantic_digest: str
    parsed: (
        ReconstructionSet
        | PreparedDatasetComponent
        | PreparedDatasetSet
        | GaussianScene
        | GaussianSceneSet
        | TrainingCheckpoint
        | ValidationGeometryArtifact
        | ReconstructionMetricsArtifact
        | ReconstructionReportArtifact
        | ReconstructionSelectionArtifact
        | PairSet
        | RetrievalRepresentationSet
        | LocalFeatureSet
        | MatchSet
        | VerifiedGeometrySet
        | NumbersPayload
        | ScaledNumbersPayload
        | CandidateViewSet
        | QualityReport
        | SelectedViewSet
        | SharpestSelectedViewSet
    )


class ValidationStrength(IntEnum):
    PAYLOAD_INTEGRITY = 1
    FULL_DECODE = 2


class ArtifactValidationContext:
    """One operation's immutable typed results; never retains image bytes."""

    def __init__(self, *, mapping_integrity_only: bool = False) -> None:
        # M9 downstream reads may reuse the indexed M8 structural validation only
        # after fresh manifest + every-payload SHA verification. This context is
        # separate from ordinary M8 cache/recovery and never survives an operation.
        self.mapping_integrity_only = mapping_integrity_only
        self.results: dict[
            tuple[str, ...],
            tuple[ValidationStrength, ArtifactManifest, Path, ValidatedArtifact],
        ] = {}


def stream_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def validate_workspace_output(
    output: Path, artifact_type: str, *, decode_pixels: bool = True,
    verified_payloads: dict[str, PayloadFile] | None = None,
    mapping_integrity_only: bool = False,
    checkpoint: Callable[[], None] | None = None,
) -> ValidatedArtifact:
    if not output.is_dir() or output.is_symlink() or output.is_junction():
        raise ValueError("Stage did not create a safe output directory")
    if artifact_type in {NUMBERS_ARTIFACT_TYPE, SCALED_ARTIFACT_TYPE}:
        return _validate_fake(output, artifact_type, verified_payloads)
    if artifact_type.startswith("training."):
        from splatforge.adapters.training_artifacts import read_training_output

        return read_training_output(output, artifact_type, checkpoint=checkpoint or (lambda: None))
    if artifact_type in {DATASET_COMPONENT_TYPE, DATASET_SET_TYPE}:
        from splatforge.adapters.dataset_artifacts import validate_dataset_output

        return validate_dataset_output(output, artifact_type, verified_payloads,
                                       checkpoint=checkpoint)
    if artifact_type == CANDIDATE_ARTIFACT_TYPE:
        return _validate_candidate(output, decode_pixels=decode_pixels,
                                   verified_payloads=verified_payloads)
    if artifact_type == PAIR_ARTIFACT_TYPE:
        return _validate_pairs(output, verified_payloads)
    if artifact_type == RECONSTRUCTION_ARTIFACT_TYPE:
        from splatforge.adapters.mapping_artifacts import (
            validate_mapping_integrity_receipt,
            validate_mapping_output,
        )

        if mapping_integrity_only and verified_payloads is not None:
            return validate_mapping_integrity_receipt(output, verified_payloads)
        return validate_mapping_output(output, verified_payloads)
    if artifact_type in {VALIDATION_GEOMETRY_ARTIFACT_TYPE, METRICS_ARTIFACT_TYPE,
                         REPORT_ARTIFACT_TYPE, SELECTION_ARTIFACT_TYPE}:
        from splatforge.adapters.validation_artifacts import validate_validation_output

        return validate_validation_output(output, artifact_type, verified_payloads)
    if artifact_type == RETRIEVAL_ARTIFACT_TYPE:
        from splatforge.adapters.retrieval_artifacts import validate_retrieval_output

        return validate_retrieval_output(output, verified_payloads)
    if artifact_type == FEATURE_ARTIFACT_TYPE:
        return _validate_features(output, verified_payloads)
    if artifact_type in {MATCH_ARTIFACT_TYPE, GEOMETRY_ARTIFACT_TYPE}:
        from splatforge.adapters.matching_artifacts import validate_matching_output

        return validate_matching_output(output, artifact_type, verified_payloads)
    if artifact_type == QUALITY_ARTIFACT_TYPE:
        return _validate_quality(output, verified_payloads)
    if artifact_type == SELECTED_ARTIFACT_TYPE:
        return _validate_selected(output, verified_payloads)
    raise ValueError(f"Unsupported artifact type: {artifact_type}")


def validate_published_artifact(
    artifact_directory: Path, manifest: ArtifactManifest, *, decode_pixels: bool = True,
    mapping_integrity_only: bool = False,
) -> ValidatedArtifact:
    if manifest.artifact_type == PAIR_ARTIFACT_TYPE and (
        len(manifest.payloads) != 1 or manifest.payloads[0].path != "pair_set.json"
    ):
        raise ValueError("PairSet manifest requires exactly pair_set.json")
    payload_limit = (MAX_VIEWS + 4
                     if manifest.artifact_type == DATASET_COMPONENT_TYPE else MAX_PAYLOADS)
    if len(manifest.payloads) > payload_limit:
        raise ValueError("Artifact manifest declares too many payload files")
    paths = [payload.path for payload in manifest.payloads]
    if len(paths) != len(set(paths)):
        raise ValueError("Artifact manifest declares a duplicate payload path")
    verified_payloads = {}
    for payload in manifest.payloads:
        path = safe_payload_path(artifact_directory, payload.path)
        if not _plain_file(path):
            raise ValueError("Manifest payload is not a plain file")
        if manifest.artifact_type == PAIR_ARTIFACT_TYPE and (
            payload.size > MAX_PAIR_METADATA_BYTES or path.stat().st_size > MAX_PAIR_METADATA_BYTES
        ):
            raise ValueError("PairSet metadata exceeds its structural byte bound")
        size, digest = stream_sha256(path)
        if size != payload.size or digest != payload.sha256:
            raise ValueError("Published payload size or digest mismatch")
        verified_payloads[payload.path] = payload
    validated = validate_workspace_output(
        artifact_directory, manifest.artifact_type, decode_pixels=decode_pixels,
        verified_payloads=verified_payloads,
        mapping_integrity_only=mapping_integrity_only,
    )
    if validated.payloads != manifest.payloads:
        raise ValueError("Published payload manifest differs from validated files")
    if validated.semantic_digest != manifest.semantic_digest:
        raise ValueError("Published semantic digest differs from validated content")
    if isinstance(validated.parsed, QualityReport):
        if len(manifest.input_lineage) != 1:
            raise ValueError("QualityReport requires exactly one candidate lineage input")
        candidate = manifest.input_lineage[0]
        if (
            candidate.input_name != "candidate_views"
            or candidate.artifact_id != validated.parsed.candidate_artifact_id
            or candidate.semantic_digest != validated.parsed.candidate_semantic_digest
        ):
            raise ValueError("QualityReport candidate provenance differs from lineage")
    if isinstance(validated.parsed, SharpestSelectedViewSet):
        lineage = {item.input_name: item for item in manifest.input_lineage}
        if set(lineage) != {"candidate_views", "quality_report"}:
            raise ValueError("Sharpest selection requires candidate and quality lineage")
        if (
            lineage["candidate_views"].artifact_id != validated.parsed.candidate_artifact_id
            or lineage["candidate_views"].semantic_digest
            != validated.parsed.candidate_semantic_digest
            or lineage["quality_report"].artifact_id != validated.parsed.quality_artifact_id
            or lineage["quality_report"].semantic_digest != validated.parsed.quality_semantic_digest
        ):
            raise ValueError("Sharpest selection provenance differs from lineage")
    if isinstance(validated.parsed, PairSet):
        validate_pair_lineage(validated.parsed, manifest)
    if isinstance(validated.parsed, (GaussianScene, GaussianSceneSet, TrainingCheckpoint)):
        from splatforge.adapters.training_artifacts import validate_training_lineage

        validate_training_lineage(validated.parsed, manifest)
    if isinstance(validated.parsed, (PreparedDatasetComponent, PreparedDatasetSet)):
        from splatforge.adapters.dataset_artifacts import validate_dataset_lineage

        validate_dataset_lineage(validated.parsed, manifest)
    if isinstance(validated.parsed, ReconstructionSet):
        from splatforge.adapters.mapping_artifacts import validate_mapping_lineage

        validate_mapping_lineage(validated.parsed, manifest)
    if isinstance(validated.parsed, (ValidationGeometryArtifact, ReconstructionMetricsArtifact,
                                     ReconstructionReportArtifact,
                                     ReconstructionSelectionArtifact)):
        from splatforge.adapters.validation_artifacts import validate_validation_lineage

        validate_validation_lineage(validated.parsed, manifest)
    if isinstance(validated.parsed, RetrievalRepresentationSet):
        from splatforge.adapters.retrieval_artifacts import validate_retrieval_lineage

        validate_retrieval_lineage(validated.parsed, manifest)
    if isinstance(validated.parsed, LocalFeatureSet):
        validate_feature_lineage(validated.parsed, manifest)
    if isinstance(validated.parsed, (MatchSet, VerifiedGeometrySet)):
        from splatforge.adapters.matching_artifacts import validate_matching_lineage

        validate_matching_lineage(validated.parsed, manifest)
    return validated


def validate_feature_lineage(parsed: LocalFeatureSet, manifest: ArtifactManifest) -> None:
    lineage = {i.input_name: i for i in manifest.input_lineage}
    if len(manifest.input_lineage) != 2 or set(lineage) != {"candidate_views", "selected_views"}:
        raise ValueError("Features require exact candidate and selected lineage")
    selected = lineage["selected_views"]
    if (selected.artifact_id != parsed.selected_artifact_id
            or selected.semantic_digest != parsed.selected_semantic_digest
            or selected.artifact_type != SELECTED_ARTIFACT_TYPE or selected.contract_version != 1
            or lineage["candidate_views"].artifact_type != CANDIDATE_ARTIFACT_TYPE
            or lineage["candidate_views"].contract_version != 1):
        raise ValueError("Feature provenance differs from manifest lineage")


def _validate_features(
    output: Path, verified_payloads: dict[str, PayloadFile] | None = None,
) -> ValidatedArtifact:
    from splatforge.adapters.feature_database import validate_feature_payload

    names = {p.name for p in output.iterdir()}
    required = {"features.json", "backend_mapping.json", "features.db"}
    if names not in (required, required | {"manifest.json"}):
        raise ValueError("Feature output has missing/unexpected payloads")
    if any(not _plain_file(output / name) for name in required):
        raise ValueError("Feature payload must contain plain files")
    features = LocalFeatureSet.model_validate_json(_read_bounded(
        output / "features.json", MAX_FEATURE_METADATA_BYTES, "LocalFeatureSet metadata",
    ))
    validate_feature_payload(output, features)
    payloads = []
    for name in sorted(required):
        size, digest = _payload_digest(output, output / name, verified_payloads)
        payloads.append(PayloadFile(path=name, size=size, sha256=digest))
    return ValidatedArtifact(payloads=tuple(payloads), semantic_digest=features.semantic_digest,
                             parsed=features)


def validate_pair_lineage(parsed: PairSet, manifest: ArtifactManifest) -> None:
    """Check exact provenance before publication as well as on cache/recovery reads."""
    lineage = {item.input_name: item for item in manifest.input_lineage}
    expected = {
        "candidate_views", "selected_views",
    } | ({"retrieval_representation"} if parsed.retrieval else set())
    if len(manifest.input_lineage) != len(expected) or set(lineage) != expected:
        raise ValueError("PairSet requires exactly candidate and selected lineage")
    if parsed.retrieval:
        item = lineage["retrieval_representation"]
        if (item.artifact_id != parsed.retrieval.artifact_id
                or item.semantic_digest != parsed.retrieval.semantic_digest
                or item.artifact_type != RETRIEVAL_ARTIFACT_TYPE or item.contract_version != 1):
            raise ValueError("PairSet retrieval provenance differs from manifest lineage")
    for name, artifact_id, digest, artifact_type in (
        ("candidate_views", parsed.candidate_artifact_id, parsed.candidate_semantic_digest,
         CANDIDATE_ARTIFACT_TYPE),
        ("selected_views", parsed.selected_artifact_id, parsed.selected_semantic_digest,
         SELECTED_ARTIFACT_TYPE),
    ):
        item = lineage[name]
        if (item.artifact_id != artifact_id or item.semantic_digest != digest
                or item.artifact_type != artifact_type or item.contract_version != 1):
            raise ValueError("PairSet provenance differs from manifest lineage")


def _payload_digest(
    output: Path, path: Path, verified: dict[str, PayloadFile] | None,
) -> tuple[int, str]:
    payload = (
        verified.get(path.resolve().relative_to(output.resolve()).as_posix())
        if verified is not None else None
    )
    return (payload.size, payload.sha256) if payload is not None else stream_sha256(path)


def _validate_pairs(
    output: Path, verified_payloads: dict[str, PayloadFile] | None = None,
) -> ValidatedArtifact:
    entries = set()
    for index, path in enumerate(output.iterdir()):
        if index >= 2:
            raise ValueError("PairSet output must contain exactly pair_set.json")
        entries.add(path.name)
    if entries not in ({"pair_set.json"}, {"pair_set.json", "manifest.json"}):
        raise ValueError("PairSet output must contain exactly pair_set.json")
    metadata = output / "pair_set.json"
    if not _plain_file(metadata):
        raise ValueError("PairSet metadata must be a plain file")
    parsed = PairSet.model_validate_json(
        _read_bounded(metadata, MAX_PAIR_METADATA_BYTES, "PairSet metadata")
    )
    size, digest = _payload_digest(output, metadata, verified_payloads)
    return ValidatedArtifact(
        payloads=(PayloadFile(path="pair_set.json", size=size, sha256=digest),),
        semantic_digest=parsed.semantic_digest,
        parsed=parsed,
    )


def _validate_fake(
    output: Path, artifact_type: str, verified_payloads: dict[str, PayloadFile] | None = None,
) -> ValidatedArtifact:
    if artifact_type == NUMBERS_ARTIFACT_TYPE:
        name = "numbers.json"
        model = NumbersPayload
    else:
        name = "scaled.json"
        model = ScaledNumbersPayload
    entries = list(output.iterdir())
    if len(entries) == 2 and {path.name for path in entries} == {name, "manifest.json"}:
        entries = [path for path in entries if path.name != "manifest.json"]
    if len(entries) != 1 or entries[0].name != name or not _plain_file(entries[0]):
        raise ValueError(f"Fake stage output must contain exactly {name}")
    data = _read_bounded(entries[0], MAX_METADATA_BYTES, "fake payload")
    parsed = model.model_validate_json(data)
    size, digest = _payload_digest(output, entries[0], verified_payloads)
    return ValidatedArtifact(
        payloads=(PayloadFile(path=name, size=size, sha256=digest),),
        semantic_digest=semantic_digest(parsed),
        parsed=parsed,
    )


def _validate_candidate(
    output: Path, *, decode_pixels: bool = True,
    verified_payloads: dict[str, PayloadFile] | None = None,
) -> ValidatedArtifact:
    entries = {path.name: path for path in output.iterdir()}
    allowed = {"candidate_views.json", "images", "manifest.json"}
    if not set(entries).issubset(allowed) or not {"candidate_views.json", "images"}.issubset(
        entries
    ):
        raise ValueError("Candidate output contains unexpected or missing top-level entries")
    metadata = entries["candidate_views.json"]
    images = entries["images"]
    if not _plain_file(metadata):
        raise ValueError("Candidate metadata is not a plain file")
    if not images.is_dir() or images.is_symlink() or images.is_junction():
        raise ValueError("Candidate images path is not a plain directory")
    parsed = CandidateViewSet.model_validate_json(
        _read_bounded(metadata, MAX_METADATA_BYTES, "candidate metadata")
    )
    if len(parsed.views) > MAX_VIEWS:
        raise ValueError("Candidate payload count exceeds its contract bound")
    actual_entries: list[Path] = []
    for index, path in enumerate(images.iterdir()):
        if index >= MAX_VIEWS:
            raise ValueError("Candidate images directory exceeds its file-count bound")
        actual_entries.append(path)
    if any(not _plain_file(path) for path in actual_entries):
        raise ValueError("Candidate images directory contains a non-file entry")
    actual_paths = {f"images/{path.name}" for path in actual_entries}
    declared_paths = {view.image_path for view in parsed.views}
    if actual_paths != declared_paths:
        missing = sorted(declared_paths - actual_paths)
        unexpected = sorted(actual_paths - declared_paths)
        raise ValueError(
            f"Candidate image listing mismatch; missing={missing[:3]}, unexpected={unexpected[:3]}"
        )
    payloads: list[PayloadFile] = []
    metadata_size, metadata_digest = _payload_digest(output, metadata, verified_payloads)
    payloads.append(
        PayloadFile(path="candidate_views.json", size=metadata_size, sha256=metadata_digest)
    )
    for view in sorted(parsed.views, key=lambda item: item.image_path):
        image_path = safe_payload_path(output, view.image_path)
        width, height, image_format = image_dimensions(image_path)
        if (width, height) != (view.width, view.height):
            raise ValueError(f"Candidate image dimensions disagree for {view.view_id}")
        if image_format != parsed.settings.encoding.image_format:
            raise ValueError(f"Candidate image encoding disagrees for {view.view_id}")
        if decode_pixels:
            validate_decodable_image(image_path, width, height, image_format)
        size, digest = _payload_digest(output, image_path, verified_payloads)
        if digest != view.image_sha256:
            raise ValueError(f"Candidate image digest disagrees for {view.view_id}")
        payloads.append(PayloadFile(path=view.image_path, size=size, sha256=digest))
    if len(payloads) > MAX_PAYLOADS:
        raise ValueError("Candidate artifact has too many payload files")
    return ValidatedArtifact(
        payloads=tuple(payloads),
        semantic_digest=candidate_semantic_digest(parsed),
        parsed=parsed,
    )


def _validate_selected(
    output: Path, verified_payloads: dict[str, PayloadFile] | None = None,
) -> ValidatedArtifact:
    entries = list(output.iterdir())
    allowed = {"selected_views.json", "manifest.json"}
    if {path.name for path in entries} - allowed:
        raise ValueError("Selected output contains unexpected files")
    metadata = output / "selected_views.json"
    if not _plain_file(metadata):
        raise ValueError("Selected output must contain selected_views.json")
    data = _read_bounded(metadata, MAX_METADATA_BYTES, "selected metadata")
    decoded = json.loads(data)
    method_id = decoded.get("selection_method_id") if isinstance(decoded, dict) else None
    parsed: SelectedViewSet | SharpestSelectedViewSet
    if method_id == "frame_selection.sharpest_interval":
        parsed = SharpestSelectedViewSet.model_validate_json(data)
        semantic_digest = sharpest_selected_semantic_digest(parsed)
    elif method_id == "frame_selection.fixed_fps":
        parsed = SelectedViewSet.model_validate_json(data)
        semantic_digest = selected_semantic_digest(parsed)
    else:
        raise ValueError(f"Unsupported selected-view method: {method_id!r}")
    size, digest = _payload_digest(output, metadata, verified_payloads)
    return ValidatedArtifact(
        payloads=(PayloadFile(path="selected_views.json", size=size, sha256=digest),),
        semantic_digest=semantic_digest,
        parsed=parsed,
    )


def _validate_quality(
    output: Path, verified_payloads: dict[str, PayloadFile] | None = None,
) -> ValidatedArtifact:
    entries = list(output.iterdir())
    allowed = {"quality_report.json", "manifest.json"}
    if {path.name for path in entries} - allowed:
        raise ValueError("Quality output contains unexpected files")
    metadata = output / "quality_report.json"
    if not _plain_file(metadata):
        raise ValueError("Quality output must contain quality_report.json")
    parsed = QualityReport.model_validate_json(
        _read_bounded(metadata, MAX_METADATA_BYTES, "quality metadata")
    )
    size, digest = _payload_digest(output, metadata, verified_payloads)
    return ValidatedArtifact(
        payloads=(PayloadFile(path="quality_report.json", size=size, sha256=digest),),
        semantic_digest=quality_semantic_digest(parsed),
        parsed=parsed,
    )


def safe_payload_path(root: Path, relative: str) -> Path:
    windows = PureWindowsPath(relative)
    parts = relative.split("/")
    if (
        not relative
        or windows.drive
        or windows.root
        or PurePosixPath(relative).is_absolute()
        or "\\" in relative
        or ":" in relative
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("Manifest payload path is not a safe relative path")
    candidate = root
    for part in parts:
        candidate /= part
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("Manifest payload traverses a filesystem redirection")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Manifest payload escapes its artifact directory")
    return resolved


def image_dimensions(path: Path) -> tuple[int, int, ImageFormat]:
    with path.open("rb") as stream:
        prefix = stream.read(24)
        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            if len(prefix) < 24 or prefix[12:16] != b"IHDR":
                raise ValueError(f"Invalid PNG header: {path.name}")
            width = int.from_bytes(prefix[16:20], "big")
            height = int.from_bytes(prefix[20:24], "big")
            if width <= 0 or height <= 0:
                raise ValueError(f"Invalid PNG dimensions: {path.name}")
            return width, height, ImageFormat.PNG
        if not prefix.startswith(b"\xff\xd8"):
            raise ValueError(f"Unsupported candidate image header: {path.name}")
        stream.seek(2)
        consumed = 2
        sof_markers = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while consumed < 1024 * 1024:
            marker_prefix = stream.read(1)
            consumed += 1
            if marker_prefix != b"\xff":
                raise ValueError(f"Invalid JPEG marker: {path.name}")
            marker_bytes = stream.read(1)
            consumed += 1
            while marker_bytes == b"\xff":
                marker_bytes = stream.read(1)
                consumed += 1
            if not marker_bytes:
                break
            marker = marker_bytes[0]
            if marker in {0xD8, 0xD9}:
                continue
            if marker == 0xDA:
                break
            length_bytes = stream.read(2)
            consumed += 2
            if len(length_bytes) != 2:
                break
            length = int.from_bytes(length_bytes, "big")
            if length < 2:
                break
            if marker in sof_markers:
                body = stream.read(min(length - 2, 5))
                if len(body) < 5:
                    break
                height = int.from_bytes(body[1:3], "big")
                width = int.from_bytes(body[3:5], "big")
                if width <= 0 or height <= 0:
                    break
                return width, height, ImageFormat.JPEG
            stream.seek(length - 2, 1)
            consumed += length - 2
    raise ValueError(f"JPEG dimensions are unavailable within the header bound: {path.name}")


def validate_decodable_image(
    path: Path, width: int, height: int, image_format: ImageFormat,
) -> None:
    """Verify and decode one bounded image; no decoded pixels escape this call."""
    if width * height > MAX_DECODE_PIXELS or width * height * 4 > MAX_DECODE_BYTES:
        raise ValueError(f"Candidate image exceeds supported decode resource bound: {path.name}")
    if path.stat().st_size > MAX_ENCODED_IMAGE_BYTES:
        raise ValueError(f"Candidate image exceeds encoded byte resource bound: {path.name}")
    expected_format = "JPEG" if image_format == ImageFormat.JPEG else "PNG"
    try:
        with Image.open(path) as image:
            if image.size != (width, height) or image.format != expected_format:
                raise ValueError("Decoded image dimensions or format disagree")
            if image.width * image.height * max(4, len(image.getbands())) > MAX_DECODE_BYTES:
                raise ValueError("Candidate image exceeds decoded byte bound")
            image.verify()
        # verify() checks container integrity; load() also validates compressed pixels.
        with Image.open(path) as image:
            if image.size != (width, height) or image.format != expected_format:
                raise ValueError("Decoded image dimensions or format changed")
            image.load()
    except (OSError, SyntaxError, EOFError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Candidate image is not fully decodable: {path.name}: {exc}") from exc


def _read_bounded(path: Path, limit: int, label: str) -> bytes:
    size = path.stat().st_size
    if size > limit:
        raise ValueError(f"{label} exceeds its {limit}-byte limit")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) != size or len(data) > limit:
        raise ValueError(f"{label} changed while being read or exceeded its limit")
    return data


def _plain_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and not path.is_junction()


__all__ = [
    "MAX_MANIFEST_BYTES",
    "ValidatedArtifact",
    "image_dimensions",
    "safe_payload_path",
    "stream_sha256",
    "validate_published_artifact",
    "validate_workspace_output",
]
