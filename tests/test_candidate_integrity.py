"""Decode integrity must gate workspace, publication, cache reuse and recovery."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from PIL import Image
from test_views_execution import FakeMaterializer, harness, limits, query

from splatforge.adapters.artifact_validation import validate_workspace_output
from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.core.media import VerificationPolicyId
from splatforge.core.views import (
    CANDIDATE_ARTIFACT_TYPE,
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateViewSet,
    FixedFpsSettings,
    ImageFormat,
    candidate_semantic_digest,
    parse_fps,
)


def encoded_image(image_format: str) -> bytes:
    with io.BytesIO() as stream, Image.new("RGB", (16, 12), (30, 80, 160)) as image:
        image.save(stream, format=image_format.upper())
        return stream.getvalue()


def corrupted_image(kind: str) -> bytes:
    if kind == "header_png":
        return encoded_image("png")[:24]
    if kind == "truncated_png":
        return encoded_image("png")[:-16]
    if kind == "malformed_png":
        data = bytearray(encoded_image("png"))
        data[45] ^= 0xFF
        return bytes(data)
    return encoded_image("jpeg")[:-4]


class EncodingMaterializer(FakeMaterializer):
    corrupt: str | None = None

    def materialize(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        frames = super().materialize(*args, **kwargs)
        image_format = args[3].encoding.image_format.value
        for frame in frames:
            frame.temporary_path.write_bytes(
                corrupted_image(self.corrupt) if self.corrupt else encoded_image(image_format)
            )
        return frames


def setup(tmp_path: Path, kind: str):  # type: ignore[no-untyped-def]
    value = harness(tmp_path, mixed=False)
    producer = EncodingMaterializer(value.sources)
    value.service._materializer = producer
    settings = CandidatePoolSettings(
        candidate_fps=parse_fps("2"),
        encoding=CandidateEncodingSettings(
            image_format=ImageFormat.JPEG if "jpeg" in kind else ImageFormat.PNG,
        ),
    )
    return value, producer, settings


def prepare(value, settings):  # type: ignore[no-untyped-def]
    return value.service.prepare(
        value.root, candidate_settings=settings,
        selection_settings=FixedFpsSettings(target_fps=parse_fps("1")), resource_limits=limits(),
        verification_policy=VerificationPolicyId.BALANCED_LOCAL,
    )


def rewrite_historical_corruption(directory: Path, kind: str) -> None:
    """Match all digests so the failure must come from decode integrity."""
    path = directory / "candidate_views.json"
    candidate = CandidateViewSet.model_validate_json(path.read_bytes())
    views = list(candidate.views)
    data = corrupted_image(kind)
    (directory / views[0].image_path).write_bytes(data)
    views[0] = views[0].model_copy(update={"image_sha256": hashlib.sha256(data).hexdigest()})
    candidate = candidate.model_copy(update={"views": tuple(views)})
    path.write_text(candidate.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["semantic_digest"] = candidate_semantic_digest(candidate)
    for payload in manifest["payloads"]:
        content = (directory / payload["path"]).read_bytes()
        payload.update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")


@pytest.mark.parametrize("kind", ["header_png", "truncated_png", "malformed_png", "truncated_jpeg"])
def test_corrupt_image_refuses_workspace_and_publication(tmp_path: Path, kind: str) -> None:
    value, producer, settings = setup(tmp_path, kind)
    producer.corrupt = kind
    with pytest.raises(ValueError):
        prepare(value, settings)
    assert query(value.root, "SELECT status FROM attempts") == [("failed",)]
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]
    outputs = list((value.root / "work").rglob("candidate_views.json"))
    assert len(outputs) == 1
    with pytest.raises(ValueError):
        validate_workspace_output(outputs[0].parent, CANDIDATE_ARTIFACT_TYPE)


@pytest.mark.parametrize("kind", ["truncated_png", "truncated_jpeg"])
def test_historical_corrupt_candidate_is_ineligible_for_cache(tmp_path: Path, kind: str) -> None:
    value, producer, settings = setup(tmp_path, kind)
    first = prepare(value, settings)
    directory = (value.root / first.candidate_artifact.manifest_path).parent
    rewrite_historical_corruption(directory, kind)
    # Repair the DB manifest/semantic evidence as well, reproducing an artifact
    # that the historical header-only validator would have accepted.
    data = (directory / "manifest.json").read_bytes()
    with sqlite3.connect(value.root / "state.sqlite") as connection:
        connection.execute(
            "UPDATE artifacts SET manifest_digest=?, semantic_digest=? WHERE artifact_id=?",
            (hashlib.sha256(data).hexdigest(), json.loads(data)["semantic_digest"],
             str(first.candidate_artifact.artifact_id)),
        )
    lookup = value.execution.find_cache(
        value.root, recipe_key=first.candidate_artifact.recipe_key,
        artifact_type=CANDIDATE_ARTIFACT_TYPE, contract_version=1,
    )
    assert lookup.artifact is None
    assert "not fully decodable" in lookup.ineligible[0].reason
    second = prepare(value, settings)
    assert second.status == "succeeded"
    assert "candidate_views" not in second.cache_hits
    assert len(producer.calls) == 2


@pytest.mark.parametrize("kind", ["truncated_png", "truncated_jpeg"])
def test_corrupt_orphan_with_matching_digests_cannot_be_adopted(tmp_path: Path, kind: str) -> None:
    value, _producer, settings = setup(tmp_path, kind)

    def crash(path: Path) -> None:
        if path.parent.name == "candidate_views":
            rewrite_historical_corruption(path, kind)
            digest = hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()
            with sqlite3.connect(value.root / "state.sqlite") as connection:
                connection.execute(
                    "UPDATE attempts SET expected_manifest_digest=? WHERE expected_artifact_id=?",
                    (digest, path.name),
                )
            raise OSError("crash after historical corrupt publication")

    execution = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=crash),
    )
    value.service._execution = execution
    with pytest.raises(PublicationUnresolvedError):
        prepare(value, settings)
    run_id = UUID(query(value.root, "SELECT run_id FROM runs")[0][0])
    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(value.root, run_id)
    assert recovered.adopted_attempts == ()
    assert recovered.warnings[0].code == "orphan.publication_refused"
    assert "not fully decodable" in recovered.warnings[0].message
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]


def test_decode_pixel_bound_is_checked_before_pillow_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from splatforge.adapters.artifact_validation import validate_decodable_image

    monkeypatch.setattr(Image, "open", lambda *a: pytest.fail("resource bomb reached decoder"))
    with pytest.raises(ValueError, match="resource bound"):
        validate_decodable_image(tmp_path / "bomb.png", 100_000, 100_000, ImageFormat.PNG)


def test_encoded_byte_bound_prevents_oversized_container_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from splatforge.adapters.artifact_validation import (
        MAX_ENCODED_IMAGE_BYTES,
        validate_decodable_image,
    )

    monkeypatch.setattr(Path, "stat", lambda *a, **kw: SimpleNamespace(
        st_size=MAX_ENCODED_IMAGE_BYTES + 1,
    ))
    monkeypatch.setattr(Image, "open", lambda *a: pytest.fail("container bomb reached decoder"))
    with pytest.raises(ValueError, match="encoded byte resource bound"):
        validate_decodable_image(tmp_path / "bomb.png", 16, 12, ImageFormat.PNG)


@pytest.mark.parametrize("kind", ["png", "jpeg"])
def test_valid_historical_candidate_keeps_contract_and_semantic_digest(
    tmp_path: Path, kind: str,
) -> None:
    value, _producer, settings = setup(tmp_path, kind)
    first = prepare(value, settings)
    directory = (value.root / first.candidate_artifact.manifest_path).parent
    metadata = directory / "candidate_views.json"
    candidate = CandidateViewSet.model_validate_json(metadata.read_bytes())
    historical = candidate.model_copy(update={"adapter_version": 1})
    metadata.write_text(historical.model_dump_json() + "\n", encoding="utf-8")
    validated = validate_workspace_output(directory, CANDIDATE_ARTIFACT_TYPE)
    assert validated.parsed.adapter_version == 1
    assert validated.parsed.contract_version == 1
    assert validated.semantic_digest == candidate_semantic_digest(candidate)


@pytest.mark.parametrize("field,value", [("dimensions", (15, 12)), ("format", "JPEG")])
def test_decoded_format_and_dimensions_must_match_declared_metadata(
    tmp_path: Path, field: str, value: object,
) -> None:
    from splatforge.adapters.artifact_validation import validate_decodable_image

    path = tmp_path / "image.png"
    path.write_bytes(encoded_image("png"))
    width, height = value if field == "dimensions" else (16, 12)
    image_format = ImageFormat.JPEG if field == "format" else ImageFormat.PNG
    with pytest.raises(ValueError, match="dimensions or format disagree"):
        validate_decodable_image(path, width, height, image_format)
