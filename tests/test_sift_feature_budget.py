"""Real SIFT soft limits must respect the published hard feature budget."""

import sqlite3
import struct
from contextlib import closing
from pathlib import Path

import pytest
from feature_helpers import NativeFixture
from test_views_execution import harness, prepare, query

from splatforge.application.features import FeaturesService
from splatforge.core.features import resolve_extraction_settings


def oversized_fixture(tmp_path, monkeypatch, *, corrupt_tail=False):
    fixture = NativeFixture(tmp_path)
    original_run = fixture.run

    def run(request, **kwargs):
        result = original_run(request, **kwargs)
        if request.argv[0] == "feature_extractor" and "work" in request.working_directory.parts:
            database = Path(request.argv[request.argv.index("--database_path") + 1])
            with closing(sqlite3.connect(database)) as db, db:
                for (image_id,) in db.execute("SELECT image_id FROM images").fetchall():
                    points = (1.0, 1.0, 2.0, 1.0, float("nan") if corrupt_tail else 3.0, 1.0)
                    db.execute(
                        "UPDATE keypoints SET data=? WHERE image_id=?",
                        (struct.pack("<6f", *points), image_id),
                    )
                    # Distinct rows expose accidental keypoint/descriptor misalignment.
                    db.execute(
                        "UPDATE descriptors SET data=? WHERE image_id=?",
                        (bytes([11]) * 128 + bytes([22]) * 128 + bytes([33]) * 128, image_id),
                    )
        return result

    monkeypatch.setattr(fixture, "run", run)
    return fixture


def test_native_sift_overflow_publishes_paired_prefix_and_reuses_cache(tmp_path, monkeypatch):
    value = harness(tmp_path)
    views = prepare(value)
    fixture = oversized_fixture(tmp_path, monkeypatch)
    service = FeaturesService(value.execution, fixture.adapter())
    settings = resolve_extraction_settings("SIFT", max_features=2)
    first = service.extract(
        value.root, views_run_id=views.run_id, settings=settings, colmap=fixture.exe,
    )
    assert first.status == "succeeded" and not first.cache_hit
    assert first.total_feature_count == 6
    directory = (value.root / first.feature_artifact.manifest_path).parent
    database_uri = (directory / "features.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as db:
        for keypoints, descriptors in db.execute(
            "SELECT k.data,d.data FROM keypoints k JOIN descriptors d USING(image_id)"
        ):
            assert struct.unpack("<4f", keypoints) == (1.0, 1.0, 2.0, 1.0)
            assert descriptors == bytes([11]) * 128 + bytes([22]) * 128
        assert db.execute("SELECT DISTINCT rows FROM keypoints").fetchall() == [(2,)]
        assert db.execute("SELECT DISTINCT rows FROM descriptors").fetchall() == [(2,)]
    value.execution.load_local_features(value.root, first.feature_artifact)
    second = service.extract(
        value.root, views_run_id=views.run_id, settings=settings, colmap=fixture.exe,
    )
    assert second.cache_hit and second.feature_artifact == first.feature_artifact


def test_invalid_sift_tail_is_rejected_before_any_truncation(tmp_path, monkeypatch):
    value = harness(tmp_path)
    views = prepare(value)
    fixture = oversized_fixture(tmp_path, monkeypatch, corrupt_tail=True)
    with pytest.raises(ValueError, match="Non-finite feature"):
        FeaturesService(value.execution, fixture.adapter()).extract(
            value.root, views_run_id=views.run_id,
            settings=resolve_extraction_settings("SIFT", max_features=2), colmap=fixture.exe,
        )
    assert query(value.root, "SELECT count(*) FROM artifacts WHERE artifact_type=?",
                 ("features.local_feature_set",)) == [(0,)]
    databases = list((value.root / "work").rglob("features.db"))
    assert len(databases) == 1
    with closing(sqlite3.connect(databases[0])) as db:
        assert db.execute("SELECT DISTINCT rows FROM keypoints").fetchall() == [(3,)]
        assert db.execute("SELECT DISTINCT rows FROM descriptors").fetchall() == [(3,)]


def test_learned_extractor_overflow_still_fails_without_truncation(tmp_path):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    with pytest.raises(ValueError, match="Invalid feature counts"):
        FeaturesService(value.execution, fixture.adapter()).extract(
            value.root, views_run_id=views.run_id,
            settings=resolve_extraction_settings("ALIKED_N16ROT", max_features=2),
            colmap=fixture.exe, model_directory=fixture.model_root,
        )
    assert query(value.root, "SELECT count(*) FROM artifacts WHERE artifact_type=?",
                 ("features.local_feature_set",)) == [(0,)]
