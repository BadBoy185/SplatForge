"""Manual cleanup: explicit preview, protected closure, no arbitrary filesystem deletion."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from dataset_helpers import dataset_service, dataset_setup
from test_views_execution import query

from splatforge.application.cleanup import CleanupService
from splatforge.core.dataset import DatasetSettings


def eligible(tmp_path):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)
    service = dataset_service(value, fixture)
    first = service.prepare(value.root, selection_run_id=selection.run.run_id)
    second = service.prepare(
        value.root,
        selection_run_id=selection.run.run_id,
        settings=DatasetSettings(max_image_size=16),
    )
    return value, service, selection, first, second


def test_cleanup_preview_apply_eviction_cache_miss_and_protected_current(tmp_path):
    value, service, selection, first, second = eligible(tmp_path)
    cleanup = CleanupService(value.execution)
    identity = first.dataset.components[0].artifact_id
    original_sources = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in value.source_paths}
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in value.root.rglob("*") if p.is_file()
    }
    preview = cleanup.preview(value.root, (identity,))
    assert len(preview.candidates) == 1 and preview.total_bytes > 0
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in before.items())
    with pytest.raises(ValueError, match="stale_preview"):
        cleanup.apply(value.root, preview_digest="0" * 64, artifact_ids=(identity,))
    applied = cleanup.apply(
        value.root, preview_digest=preview.preview_digest, artifact_ids=(identity,)
    )
    directory = (value.root / first.dataset.components[0].manifest_path).parent
    assert (directory / "manifest.json").exists() and (directory / "dataset.json").exists()
    assert all(not (directory / p.path).exists() for p in applied.candidates[0].payloads)
    assert (
        value.execution.retention_state(value.root)["evictions"][str(identity)]["state"]
        == "evicted"
    )
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in original_sources.items())
    assert service.prepare(
        value.root,
        selection_run_id=selection.run.run_id,
        settings=DatasetSettings(max_image_size=16),
    ).cache_hit
    recomputed = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert not recomputed.component_runs[0].cache_hit
    assert recomputed.dataset.semantic_digest == first.dataset.semantic_digest
    with pytest.raises(ValueError, match="protected_artifact"):
        cleanup.preview(value.root, (recomputed.dataset.components[0].artifact_id,))
    assert service.inspect(value.root, second.run_id)


def test_cleanup_explicit_pin_unknown_source_and_active_refused(tmp_path):
    value, _service, _s, first, second = eligible(tmp_path)
    cleanup = CleanupService(value.execution)
    identity = first.dataset.components[0].artifact_id
    cleanup.pin(value.root, identity)
    with pytest.raises(ValueError, match="protected_artifact"):
        cleanup.preview(value.root, (identity,))
    cleanup.pin(value.root, identity, pinned=False)
    assert cleanup.preview(value.root, (identity,)).candidates
    for identity in (uuid4(), second.dataset.provenance.selected_artifact_id):
        with pytest.raises(ValueError):
            cleanup.preview(value.root, (identity,))
    from splatforge.bootstrap import build_media_service

    source = build_media_service().list(value.root).sources[0]
    with pytest.raises(ValueError, match="unknown_artifact"):
        cleanup.preview(value.root, (source.source_id,))
    run = first.component_runs[0].run_id
    with value.execution._write_connection(value.root) as db, db:
        db.execute("UPDATE attempts SET status='running' WHERE run_id=?", (str(run),))
    with pytest.raises(ValueError, match="protected_artifact"):
        cleanup.preview(value.root, (first.dataset.components[0].artifact_id,))


def test_latest_cached_binding_protects_older_publication(tmp_path):
    value, service, selection, first, _second = eligible(tmp_path)
    current = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert current.cache_hit and current.artifact == first.artifact
    with pytest.raises(ValueError, match="protected_artifact"):
        CleanupService(value.execution).preview(
            value.root, (first.dataset.components[0].artifact_id,)
        )


@pytest.mark.parametrize("redirect", ["symlink", "junction"])
def test_cleanup_refuses_redirected_payload(tmp_path, redirect):
    value, _service, _s, first, _second = eligible(tmp_path)
    directory = (value.root / first.dataset.components[0].manifest_path).parent
    images = directory / "images"
    outside = tmp_path / "protected originals ž"
    images.rename(outside)
    try:
        if redirect == "junction":
            import subprocess

            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(images), str(outside)],
                check=True,
                capture_output=True,
            )
        else:
            images.symlink_to(outside, target_is_directory=True)
    except (OSError, __import__("subprocess").CalledProcessError):
        pytest.skip("Windows fixture requires permission for filesystem redirection")
    with pytest.raises(ValueError):
        CleanupService(value.execution).preview(
            value.root, (first.dataset.components[0].artifact_id,)
        )
    assert len(list(outside.iterdir())) == 3


def test_interrupted_cleanup_keeps_durable_diagnostic_and_can_repreview(tmp_path, monkeypatch):
    value, _service, _s, first, _second = eligible(tmp_path)
    cleanup = CleanupService(value.execution)
    identity = first.dataset.components[0].artifact_id
    preview = cleanup.preview(value.root, (identity,))
    unlink = Path.unlink
    calls = 0

    def fail(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected interrupted cleanup")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail)
        with pytest.raises(OSError, match="interrupted cleanup"):
            cleanup.apply(
                value.root, preview_digest=preview.preview_digest, artifact_ids=(identity,)
            )
    assert (
        value.execution.retention_state(value.root)["evictions"][str(identity)]["state"]
        == "evicting"
    )
    remaining = cleanup.preview(value.root, (identity,))
    assert remaining.candidates[0].state == "evicting"
    cleanup.apply(value.root, preview_digest=remaining.preview_digest, artifact_ids=(identity,))
    assert (
        value.execution.retention_state(value.root)["evictions"][str(identity)]["state"]
        == "evicted"
    )
    assert query(value.root, "SELECT count(*) FROM artifacts")
