"""Cancellation during the final probe must be observed before inventory commit."""

from threading import Event

import pytest
from test_media import FakeProbe, media_service

from splatforge.application.media import CallbackCancellation, MediaOperationCancelled
from splatforge.bootstrap import build_project_service


def test_cancel_after_final_probe_never_commits(tmp_path):
    cancelled = Event()

    class Probe(FakeProbe):
        def probe(self, path, media_type, *, cancellation=None):
            value = super().probe(path, media_type, cancellation=cancellation)
            cancelled.set()
            return value

    root = tmp_path / "project"
    build_project_service().create(root, "Cancellation")
    service = media_service(root, probe=Probe())[0]
    source = tmp_path / "source.png"
    source.write_bytes(b"tiny probe fixture")
    with pytest.raises(MediaOperationCancelled):
        service.add(root, (source,), cancellation=CallbackCancellation(cancelled.is_set))
    assert service.list(root) is None
