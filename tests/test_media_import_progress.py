"""Ingest observations measure completed sources; publication remains atomic."""

from threading import Event

import pytest
from test_media import media_service

from splatforge.application.media import CallbackCancellation, MediaOperationCancelled
from splatforge.application.media_progress import ImportReporter
from splatforge.bootstrap import build_project_service


def test_import_progress_monotonic_real_work_and_terminal_publication(tmp_path):
    root = tmp_path / "project"
    build_project_service().create(root, "Progress")
    service = media_service(root)[0]
    paths = [tmp_path / f"{i}.png" for i in range(3)]
    for path in paths:
        path.write_bytes(b"tiny synthetic probe fixture")
    events = []

    def observe(event):
        events.append(event)
        if event.phase != "succeeded":
            assert service.list(root) is None
        else:
            assert len(service.list(root).sources) == 3

    result = service.add(root, paths, progress=observe)
    assert len(result.added_sources) == 3
    assert [e.observation.completed for e in events] == sorted(
        e.observation.completed for e in events
    )
    assert [e.observation.elapsed_seconds for e in events] == sorted(
        e.observation.elapsed_seconds for e in events
    )
    assert [e.phase for e in events] == ["hashing", "metadata", "checked"] * 3 + [
        "finalizing",
        "succeeded",
    ]
    assert [e.observation.completed for e in events if e.phase == "checked"] == [1, 2, 3]
    assert events[0].eta.likely_seconds is None
    assert events[-1].observation.completed == events[-1].observation.work.total == 3
    assert events[-1].eta.likely_seconds == 0


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_import_never_reports_success_or_replaces_inventory(tmp_path, cancel):
    root = tmp_path / "project"
    build_project_service().create(root, "Atomic")
    service, _, probe = media_service(root)
    original = tmp_path / "old.png"
    original.write_bytes(b"original")
    service.add(root, [original])
    before = service.list(root)
    stop = Event()
    events = []
    paths = [tmp_path / f"{i}.png" for i in range(2)]
    for p in paths:
        p.write_bytes(b"candidate")
    probe_original = probe.probe

    def failing(path, media_type, *, cancellation=None):
        if path == paths[-1]:
            if cancel:
                stop.set()
            else:
                raise ValueError("Unreadable metadata")
        return probe_original(path, media_type, cancellation=cancellation)

    probe.probe = failing
    with pytest.raises(MediaOperationCancelled if cancel else ValueError):
        service.add(
            root, paths, cancellation=CallbackCancellation(stop.is_set), progress=events.append
        )
    assert "succeeded" not in [e.phase for e in events]
    assert service.list(root) == before
    assert all(p.exists() for p in paths)


def test_eta_requires_stable_completed_work_not_a_timer():
    elapsed, events = [0.0], []
    reporter = ImportReporter(20, events.append, clock=lambda: elapsed[0])
    reporter.emit("hashing", 0, "large.mp4")
    elapsed[0] = 100
    reporter.emit("metadata", 0, "large.mp4")
    assert all(e.eta.likely_seconds is None for e in events)
    # A new job with several actual completed files can establish live throughput.
    elapsed[0] = 0
    events.clear()
    reporter = ImportReporter(20, events.append, clock=lambda: elapsed[0])
    reporter.emit("hashing", 0)
    for completed in range(1, 9):
        elapsed[0] = completed * 2
        reporter.emit("checked", completed)
    assert events[1].eta.likely_seconds is None
    assert events[-1].eta.likely_seconds is not None
    assert "stable_live" in events[-1].eta.reasons
    elapsed[0] += 30
    reporter.emit("metadata", 8, "large.mp4")
    assert events[-1].eta.likely_seconds is None
    elapsed[0] += 2
    reporter.emit("finalizing", 20)
    assert events[-1].eta.likely_seconds is None
