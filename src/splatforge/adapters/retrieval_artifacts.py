"""Offline, bounded float32 representation transport; no ML runtime or downloader."""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from splatforge.core.pairs import (
    HybridPairSettings,
    PairEndpoints,
    PairRecord,
    PairResourceLimits,
    RetrievalPairSettings,
)
from splatforge.core.retrieval import (
    MAX_RETRIEVAL_METADATA_BYTES,
    RetrievalExport,
    RetrievalRepresentationSet,
    RetrievalResourceLimits,
)
from splatforge.core.retrieval_pairs import search_pairs
from splatforge.core.views import canonical_json_bytes

if TYPE_CHECKING:
    from splatforge.adapters.artifact_validation import ValidatedArtifact
    from splatforge.core.execution import ArtifactManifest, PayloadFile


def plain_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink() or path.is_junction():
        raise ValueError("Retrieval payload must be a plain file")
    if any(p.is_symlink() or p.is_junction() for p in path.parents):
        raise ValueError("Retrieval payload path traverses a redirected directory")


def read_metadata(
    path: Path,
    *,
    published: bool = False,
) -> RetrievalExport | RetrievalRepresentationSet:
    plain_file(path)
    with path.open("rb") as stream:
        data = stream.read(MAX_RETRIEVAL_METADATA_BYTES + 1)
    if len(data) > MAX_RETRIEVAL_METADATA_BYTES:
        raise ValueError("Retrieval metadata exceeds its byte limit")
    model = RetrievalRepresentationSet if published else RetrievalExport
    return model.model_validate_json(data)


def descriptor_rows(
    path: Path,
    export: RetrievalExport,
    *,
    checkpoint: Callable[[], None] = lambda: None,
) -> Iterator[tuple[bytes, tuple[float, ...]]]:
    plain_file(path)
    if path.stat().st_size != export.descriptor_bytes:
        raise ValueError("Retrieval descriptor storage mismatch")
    digest = hashlib.sha256()
    row_bytes = export.settings.descriptor_dimension * 4
    unpack = struct.Struct(f"<{export.settings.descriptor_dimension}f")
    with path.open("rb") as stream:
        for _ in export.views:
            checkpoint()
            raw = stream.read(row_bytes)
            if len(raw) != row_bytes:
                raise ValueError("Incomplete retrieval descriptor row")
            digest.update(raw)
            row = unpack.unpack(raw)
            if (
                any(not math.isfinite(x) for x in row)
                or abs(math.fsum(x * x for x in row) - 1) > 1e-4
            ):
                raise ValueError("Retrieval descriptors must be finite L2 unit vectors")
            yield raw, row
        if stream.read(1) or digest.hexdigest() != export.descriptor_sha256:
            raise ValueError("Retrieval descriptor digest mismatch")


class LocalRetrievalAdapter:
    def inspect_export(self, path: Path) -> RetrievalExport:
        return read_metadata(path)

    def import_export(
        self,
        workspace: Path,
        path: Path,
        payload: RetrievalRepresentationSet,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[int], None],
    ) -> None:
        if read_metadata(path) != payload.export():
            raise ValueError("Retrieval export changed after planning")
        output = workspace / "output"
        output.mkdir()
        with (output / "descriptors.f32").open("xb") as stream:
            for n, (raw, _) in enumerate(
                descriptor_rows(
                    path.parent / "descriptors.f32",
                    payload.export(),
                    checkpoint=checkpoint,
                ),
                1,
            ):
                stream.write(raw)
                progress(n)
        (output / "retrieval.json").write_bytes(
            canonical_json_bytes(payload.model_dump(mode="json")) + b"\n",
        )

    def query(
        self,
        directory: Path,
        representation: RetrievalRepresentationSet,
        settings: RetrievalPairSettings | HybridPairSettings,
        limits: PairResourceLimits,
        resources: RetrievalResourceLimits,
        explicit: tuple[PairEndpoints, ...],
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[int], None],
    ) -> tuple[PairRecord, ...]:
        # Packed float buffers avoid Python float-object expansion for large dimensions.
        import sys
        from array import array

        rows = []
        for raw, _ in descriptor_rows(
            directory / "descriptors.f32", representation.export(), checkpoint=checkpoint
        ):
            row = array("f")
            row.frombytes(raw)
            if sys.byteorder != "little":
                row.byteswap()
            rows.append(row)
        return search_pairs(
            representation.export(),
            rows,
            settings,
            limits,
            resources,
            explicit,
            checkpoint=checkpoint,
            progress=progress,
        )


def validate_retrieval_output(
    output: Path,
    verified_payloads: dict[str, PayloadFile] | None = None,
) -> ValidatedArtifact:
    from splatforge.adapters.artifact_validation import ValidatedArtifact, _payload_digest
    from splatforge.core.execution import PayloadFile

    required = {"retrieval.json", "descriptors.f32"}
    names = {p.name for p in output.iterdir()}
    if names not in (required, required | {"manifest.json"}):
        raise ValueError("Retrieval output contains missing/unexpected payloads")
    parsed = read_metadata(output / "retrieval.json", published=True)
    for _ in descriptor_rows(output / "descriptors.f32", parsed.export()):
        pass
    payloads = []
    for name in sorted(required):
        size, digest = _payload_digest(output, output / name, verified_payloads)
        payloads.append(PayloadFile(path=name, size=size, sha256=digest))
    return ValidatedArtifact(
        payloads=tuple(payloads), semantic_digest=parsed.semantic_digest, parsed=parsed
    )


def validate_retrieval_lineage(
    parsed: RetrievalRepresentationSet,
    manifest: ArtifactManifest,
) -> None:
    from splatforge.core.views import CANDIDATE_ARTIFACT_TYPE, SELECTED_ARTIFACT_TYPE

    expected = (
        (
            "candidate_views",
            parsed.candidate_artifact_id,
            parsed.candidate_semantic_digest,
            CANDIDATE_ARTIFACT_TYPE,
        ),
        (
            "selected_views",
            parsed.selected_artifact_id,
            parsed.selected_semantic_digest,
            SELECTED_ARTIFACT_TYPE,
        ),
    )
    if len(manifest.input_lineage) != 2 or {
        (x.input_name, x.artifact_id, x.semantic_digest, x.artifact_type)
        for x in manifest.input_lineage
        if x.contract_version == 1
    } != set(expected):
        raise ValueError("Retrieval provenance differs from exact candidate/selected lineage")
