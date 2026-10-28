"""Real verification work, ETA evidence, cancellation and job isolation."""

from threading import Event

import pytest
from test_media import media_service

from splatforge.application.media import CallbackCancellation, MediaOperationCancelled
from splatforge.application.media_progress import ImportReporter
from splatforge.bootstrap import build_project_service


def registered(tmp_path, count=4):
    root = tmp_path / "Project"
    build_project_service().create(root, "Verification")
    service, files, _ = media_service(root)
    paths = [tmp_path / f"Photo {i}.png" for i in range(count)]
    for p in paths:
        p.write_bytes(b"synthetic source")
    service.add(root, paths)
    return root, service, files, paths


def test_verification_reports_real_known_monotonic_work_and_current_source(tmp_path):
    root, service, _, paths = registered(tmp_path)
    events = []
    results = service.verify(root, progress=events.append)
    assert len(results) == 4
    assert events[0].observation.completed == 0
    assert events[0].eta.likely_seconds is None
    assert all(e.observation.work.total == 4 for e in events)
    assert all(e.observation.work.stage_id == "media.verify" for e in events)
    assert [e.observation.completed for e in events] == sorted(
        e.observation.completed for e in events
    )
    assert [e.observation.elapsed_seconds for e in events] == sorted(
        e.observation.elapsed_seconds for e in events
    )
    assert [e.filename for e in events if e.phase == "checked"] == [p.name for p in paths]
    assert events[-1].phase == "succeeded"
    assert events[-1].observation.completed == 4
    assert events[-1].eta.likely_seconds == 0


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_verification_has_no_fake_success(tmp_path, cancel):
    root, service, _, _ = registered(tmp_path)
    stop, events = Event(), []

    def observe(value):
        events.append(value)
        if value.observation.completed == 1:
            if cancel:
                stop.set()
            else:
                raise OSError("Verification state write unavailable")

    with pytest.raises(MediaOperationCancelled if cancel else OSError):
        service.verify(root, cancellation=CallbackCancellation(stop.is_set), progress=observe)
    assert all(e.phase != "succeeded" for e in events)
    assert events[-1].observation.completed == 1


def test_verification_eta_requires_stable_evidence_and_expires():
    now, events = [0.0], []
    reporter = ImportReporter(30, events.append, clock=lambda: now[0], operation="verify")
    reporter.emit("checking", 0, "A.png")
    assert events[-1].eta.likely_seconds is None
    for completed in range(1, 10):
        now[0] += 2
        reporter.emit("checked", completed, f"{completed}.png")
    assert "stable_live" in events[-1].eta.reasons
    assert events[-1].eta.likely_seconds > 0
    now[0] += 40
    reporter.emit("checking", 9, "slow.png")
    assert events[-1].eta.likely_seconds is None


def test_empty_verification_is_honest(tmp_path):
    root = tmp_path / "empty"
    build_project_service().create(root, "Empty")
    events = []
    assert media_service(root)[0].verify(root, progress=events.append) == ()
    assert events[-1].observation.completed == events[-1].observation.work.total == 0
