"""Pure contracts and recipe keys for the explicit two-node fake route."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from splatforge.core.execution import (
    ArtifactHandle,
    FakeRoute,
    FrozenModel,
    OutputReference,
    ScaleNode,
    ScaleSettings,
    SequenceNode,
    SequenceSettings,
)

FINGERPRINT_SCHEMA_VERSION = 1
ADAPTER_IDENTITY = "splatforge.fake_python"
ADAPTER_VERSION = 1
NUMBERS_ARTIFACT_TYPE = "fake.numbers"
SCALED_ARTIFACT_TYPE = "fake.scaled_numbers"
ARTIFACT_CONTRACT_VERSION = 1


class NumbersPayload(FrozenModel):
    contract_version: Literal[1] = 1
    numbers: tuple[int, ...] = Field(max_length=10_000)


class ScaledNumbersPayload(FrozenModel):
    contract_version: Literal[1] = 1
    numbers: tuple[int, ...] = Field(max_length=10_000)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def semantic_digest(payload: NumbersPayload | ScaledNumbersPayload) -> str:
    return sha256_bytes(canonical_json_bytes(payload.model_dump(mode="json")))


def sequence_recipe_key(*, start: int, settings: SequenceSettings) -> str:
    evidence = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "stage_contract_version": ARTIFACT_CONTRACT_VERSION,
        "method_id": "fake.sequence",
        "method_version": 1,
        "settings_schema_version": 1,
        "resolved_settings": settings.model_dump(mode="json"),
        "adapter_id": ADAPTER_IDENTITY,
        "adapter_version": ADAPTER_VERSION,
        "determinism_policy": "deterministic_integer_json_v1",
        "literal_inputs": {"start": start},
    }
    return sha256_bytes(canonical_json_bytes(evidence))


def scale_recipe_key(*, settings: ScaleSettings, input_artifact: ArtifactHandle) -> str:
    evidence = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "stage_contract_version": ARTIFACT_CONTRACT_VERSION,
        "method_id": "fake.scale",
        "method_version": 1,
        "settings_schema_version": 1,
        "resolved_settings": settings.model_dump(mode="json"),
        "adapter_id": ADAPTER_IDENTITY,
        "adapter_version": ADAPTER_VERSION,
        "determinism_policy": "deterministic_integer_json_v1",
        "consumed_input": {
            "artifact_type": input_artifact.artifact_type,
            "contract_version": input_artifact.contract_version,
            "semantic_digest": input_artifact.semantic_digest,
        },
    }
    return sha256_bytes(canonical_json_bytes(evidence))


def build_fake_route(*, start: int, count: int, factor: int) -> FakeRoute:
    numbers = OutputReference(
        node_id="numbers",
        output_name="numbers",
        artifact_type=NUMBERS_ARTIFACT_TYPE,
        contract_version=ARTIFACT_CONTRACT_VERSION,
    )
    scaled = OutputReference(
        node_id="scaled",
        output_name="scaled_numbers",
        artifact_type=SCALED_ARTIFACT_TYPE,
        contract_version=ARTIFACT_CONTRACT_VERSION,
    )
    return FakeRoute(
        sequence=SequenceNode(
            settings=SequenceSettings(count=count),
            start=start,
            output=numbers,
        ),
        scale=ScaleNode(
            settings=ScaleSettings(factor=factor),
            input=numbers,
            output=scaled,
        ),
        target=scaled,
    )
