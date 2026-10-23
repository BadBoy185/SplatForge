"""Bounded observed phases, diagnostic leaves and fail-closed native logs."""

import pytest

from splatforge.adapters.mapping_logs import MappingLogReader


def test_observed_hierarchy_phases_and_diagnostic_clusters(tmp_path):
    phases = []
    reader = MappingLogReader(tmp_path, phases.append)
    reader.poll()
    assert not phases
    log = tmp_path / "colmap.log.INFO.fixture"
    for text in (
        "Partitioning scene\n",
        "Cluster 0 with 10 images\nCluster 1 with 10 images\nReconstructing clusters\n",
        "Merging clusters\n",
    ):
        with log.open("a", encoding="utf8") as stream:
            stream.write(text)
        reader.poll()
    assert phases == ["partitioning_scene", "reconstructing_clusters", "merging_clusters"]
    assert reader.diagnostics()["leaf_clusters"] == 2
    assert reader.diagnostics()["leaf_images"] == [10, 10]
    assert "Merging clusters" in reader.complete_text()


@pytest.mark.parametrize("kind", ["empty", "many", "directory", "truncated"])
def test_missing_unsafe_or_truncated_logs_refused(tmp_path, kind):
    reader = MappingLogReader(tmp_path, lambda _: None)
    if kind == "empty":
        with pytest.raises(ValueError, match="evidence_unverified"):
            reader.complete_text()
    elif kind == "many":
        for i in range(9):
            (tmp_path / str(i)).write_bytes(b"a")
        with pytest.raises(ValueError, match="log_resource"):
            reader.poll()
    elif kind == "directory":
        (tmp_path / "nested").mkdir()
        with pytest.raises(ValueError, match="log_resource"):
            reader.poll()
    else:
        path = tmp_path / "colmap.log.INFO.fixture"
        path.write_text("Partitioning scene\n", encoding="utf8")
        reader.poll()
        path.write_bytes(b"x")
        with pytest.raises(ValueError, match="truncated"):
            reader.poll()


def test_ambiguous_or_disappeared_info_cannot_reuse_stale_positive_evidence(tmp_path):
    reader = MappingLogReader(tmp_path, lambda _: None)
    first = tmp_path / "colmap.log.INFO.first"
    first.write_text("Partitioning scene\n", encoding="utf8")
    reader.poll()
    second = tmp_path / "colmap.log.INFO.second"
    second.write_text("Falling back to CPU\n", encoding="utf8")
    with pytest.raises(ValueError, match="ambiguous"):
        reader.complete_text()
    first.unlink()
    second.unlink()
    with pytest.raises(ValueError, match="evidence_unverified"):
        reader.complete_text()
