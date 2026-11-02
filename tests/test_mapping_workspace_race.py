"""Native SQLite journals may disappear while resource polling walks the workspace."""

from pathlib import Path

import pytest
from mapping_helpers import map_run, mapping_inputs
from test_views_execution import query

from splatforge.core.reconstruction import (
    RECONSTRUCTION_ARTIFACT_TYPE,
    GlobalMapperSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
)


@pytest.mark.parametrize(
    "settings", [GlobalMapperSettings(), IncrementalMapperSettings(), HierarchicalMapperSettings()],
)
def test_disappearing_native_journal_does_not_cancel_valid_mapping(tmp_path, monkeypatch, settings):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    original_run = fixture.run
    original_is_file = Path.is_file
    observed = []

    def run(request, *, cancellation=None, poll=None):
        if request.argv[0] in {"global_mapper", "mapper", "hierarchical_mapper"} and len(
            request.argv
        ) > 2:
            journal = request.working_directory / "mapping.db-journal"
            journal.write_bytes(b"temporary native journal")

            def disappear(path):
                found = original_is_file(path)
                if path == journal and found:
                    path.unlink()
                    observed.append(path)
                return found

            with monkeypatch.context() as patch:
                patch.setattr(Path, "is_file", disappear)
                assert not cancellation.is_cancelled()
            assert not journal.exists()
        return original_run(request, cancellation=cancellation, poll=poll)

    monkeypatch.setattr(fixture, "run", run)
    result = map_run(value, fixture, verified, settings=settings)
    assert observed and result.status == "succeeded" and result.artifact is not None


def test_missing_required_mapping_database_still_fails_without_publication(tmp_path, monkeypatch):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    original_run = fixture.run

    def run(request, *, cancellation=None, poll=None):
        if request.argv[0] == "global_mapper" and len(request.argv) > 2:
            database = Path(request.argv[request.argv.index("--database_path") + 1])
            database.unlink()
            cancellation.is_cancelled()  # Required DB is not a disposable journal.
            pytest.fail("Missing required database must refuse mapping")
        return original_run(request, cancellation=cancellation, poll=poll)

    monkeypatch.setattr(fixture, "run", run)
    with pytest.raises(ValueError, match="mapper_process_failure"):
        map_run(value, fixture, verified)
    assert query(value.root, "SELECT count(*) FROM artifacts WHERE artifact_type=?",
                 (RECONSTRUCTION_ARTIFACT_TYPE,)) == [(0,)]
