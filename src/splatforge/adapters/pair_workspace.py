"""Bounded metadata-only PairSet workspace serialization."""

from pathlib import Path

from splatforge.core.pairs import MAX_PAIR_METADATA_BYTES, PairSet
from splatforge.core.views import canonical_json_bytes


class LocalPairWorkspace:
    def write_pair_set(self, workspace: Path, payload: PairSet) -> None:
        data = canonical_json_bytes(payload.model_dump(mode="json")) + b"\n"
        if len(data) > MAX_PAIR_METADATA_BYTES:
            raise ValueError("PairSet metadata exceeds its structural byte bound")
        output = workspace / "output"
        output.mkdir()
        with (output / "pair_set.json").open("xb") as stream:
            stream.write(data)
