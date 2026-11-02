"""Future Trim API uses current video, draft/Save, and revokes current-source plans."""

import os
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until  # noqa: E402
from test_qml_source_participation import idle, populated  # noqa: E402

from splatforge.bootstrap import build_project_service  # noqa: E402


def test_current_video_draft_error_save_discard_and_plan_invalidation(desktop, tmp_path):
    root, _, _, rows = populated(desktop, tmp_path)
    video = next(r for r in rows if r.values["type"] == "video")
    photo = next(r for r in rows if r.values["type"] == "photo")
    desktop.sources.select(str(photo.identity))
    desktop.media.showSource(str(video.identity))
    idle(desktop)
    until(lambda: desktop.controller.request is not None)
    api = desktop.videoUsage
    assert api.state["sourceId"] == str(video.identity)
    assert api.state["available"] and not api.state["restricted"]
    assert api.state["timelineStart"] is None  # old probe: do not invent zero
    assert api.sourceTime("1000") == ""
    assert api.state["error"]["code"] == "timeline_origin_unknown"
    desktop.controller.reconstruction_plan = {"runnable": True}
    assert api.addInterval("10", "25")
    assert desktop.sources.selectedIds == [str(photo.identity)]
    assert desktop.controller.dirty and api.state["dirty"]
    assert desktop.controller.reconstruction_plan is None
    assert not build_project_service().open(root).video_usage.entries
    before = desktop.controller.draft
    assert not api.updateInterval(0, "20", "10")
    assert api.state["error"]["code"] == "invalid_interval"
    assert desktop.controller.draft == before
    errors = []
    desktop.controller.error.connect(errors.append)
    desktop.controller.reconstruct(None, None, True)
    assert errors[-1].category == "UnsavedVideoUsage"
    desktop.controller.discard()
    assert not api.state["restricted"] and not api.state["dirty"]
    assert api.state["error"] == {}
    assert api.addInterval("10", "25")
    desktop.save()
    idle(desktop)
    assert not desktop.controller.dirty and not api.state["dirty"]
    assert api.state["intervals"] == [{"start": "10", "end": "25"}]
    saved = build_project_service().open(root)
    assert str(saved.video_usage.entries[0].source_id) == str(video.identity)
    assert api.excludeInterval("15", "20")
    assert api.state["intervals"] == [{"start": "10", "end": "15"}, {"start": "20", "end": "25"}]
    assert api.updateInterval(1, "15", "30")
    assert api.state["intervals"] == [{"start": "10", "end": "30"}]
    assert api.removeInterval(0) and api.state["restricted"] and not api.state["intervals"]
    assert api.resetIntervals() and not api.state["restricted"]
    desktop.controller.discard()
    assert api.state["restricted"]
    # An exact explicit historical input does not consume present interval intent.
    desktop.controller.request = desktop.controller.request.model_copy(
        update={"views_run": uuid4()}
    )
    desktop.workflow.overview(desktop.controller.overview)
    desktop.controller.reconstruction_plan = {"runnable": True}
    assert api.clearIntervals()
    assert desktop.controller.reconstruction_plan == {"runnable": True}
    desktop.media.closePreview()
    assert not api.state["available"]
