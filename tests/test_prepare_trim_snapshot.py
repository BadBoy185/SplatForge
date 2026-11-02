"""Trim edits revoke ready and in-flight Prepare plans, including after Discard."""

from uuid import uuid4

import pytest
from test_qml_prepare import app as app
from test_qml_prepare import configured, idle
from test_qml_prepare import desktop as desktop

from splatforge.core.video_usage import VideoUsageEntry, interval


@pytest.mark.parametrize("pending", [False, True])
def test_trim_draft_revokes_prepare_snapshot(desktop, tmp_path, pending):
    _, _, service = configured(desktop, tmp_path)
    desktop.prepare.plan()
    idle(desktop)
    vm = desktop.prepare
    old_plan, old_token = vm._plan, vm._token
    assert vm.state["canRun"]
    if pending:
        vm._plan, vm._status = None, "planning"
    document = desktop.controller.overview.document
    usage = document.video_usage.model_copy(update={"entries": (VideoUsageEntry(
        source_id=uuid4(), content_sha256="a" * 64, stream_index=0,
        intervals=(interval("0", "1"),),
    ),)})
    desktop.controller.edit(document.model_copy(update={"video_usage": usage}))
    assert vm._token != old_token
    assert vm._plan is None and vm.state["status"] == "idle"
    assert not vm.state["canRun"]
    vm._completed("prepare_plan", (old_token, old_plan))
    assert vm._plan is None
    desktop.controller.discard()
    assert not vm.state["canRun"]
    assert not service.runs
