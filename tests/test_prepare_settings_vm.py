"""Save failure, frozen work and stale plan guards for the raw Prepare form."""

from threading import Event

import pytest

pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until  # noqa: E402
from test_qml_prepare import configured, idle  # noqa: E402

from splatforge.bootstrap import build_project_service  # noqa: E402


def setup(desktop, tmp_path):
    root, _, service = configured(desktop, tmp_path)
    video = tmp_path / "Source video.mp4"
    video.write_bytes(b"Owned metadata fixture, no decoder")
    desktop.addFiles([str(video)])
    idle(desktop)
    desktop.prepare.enter()
    idle(desktop)
    return root, service, desktop.prepare.settings


@pytest.mark.parametrize("retry_value", ["512", "1024"])
def test_settings_save_failure_keeps_raw_form_and_previous_document(
    desktop, tmp_path, retry_value,
):
    root, _, form = setup(desktop, tmp_path)
    before = (root / "project.json").read_bytes()
    form.setField("quality_max_side", "512")
    factory = desktop.controller.factory

    def failure():
        facade = factory()

        def fail_save(*_args):
            raise OSError("Owned test: publication refused")

        facade.save = fail_save
        return facade

    desktop.controller.factory = failure
    try:
        form.save()
        idle(desktop)
        assert (root / "project.json").read_bytes() == before
        assert form.has_unsaved and desktop.state["dirty"]
        assert "Save was not confirmed" in form.state["error"]
        assert "publication refused" in form.state["error"]
        assert form.state["fields"]["quality_max_side"] == "512"
        assert not desktop.prepare.state["canRun"]
    finally:
        desktop.controller.factory = factory
    # Returning to persisted values must not readopt the failed staged draft.
    form.setField("quality_max_side", retry_value)
    assert form.has_unsaved and form.state["fields"]["quality_max_side"] == retry_value
    form.save()
    idle(desktop)
    assert not form.has_unsaved and not desktop.state["dirty"]
    assert not form.state["error"]
    assert (build_project_service().open(root).settings.frame_selection
            .model_extra["prepare_data"]["quality"]["quality_max_side"]) == int(retry_value)


def test_invalid_raw_form_blocks_global_save_and_close_until_discard(desktop, tmp_path):
    root, _, form = setup(desktop, tmp_path)
    before = (root / "project.json").read_bytes()
    form.setField("interval_seconds", "0")
    assert not form.state["valid"] and desktop.state["dirty"]
    assert not desktop.save()
    idle(desktop)
    assert (root / "project.json").read_bytes() == before
    assert form.has_unsaved and not desktop.controller.dirty
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    assert not desktop.requestClose() and dialogs[-1] == "unsaved"
    desktop.resolveUnsaved("cancel")
    desktop.prepare.sources()
    desktop.resolveUnsaved("discard")
    assert not form.has_unsaved and not desktop.prepare.state["active"]


def test_running_request_is_frozen_and_form_controls_refuse_changes(desktop, tmp_path):
    _, service, form = setup(desktop, tmp_path)
    entered, release = Event(), Event()
    original = service.run
    requests = []

    def delayed(root, request, **kwargs):
        requests.append(request)
        entered.set()
        assert release.wait(5)
        return original(root, request, **kwargs)

    service.run = delayed
    desktop.prepare.plan()
    idle(desktop)
    expected = desktop.prepare._plan.request
    desktop.prepare.run()
    until(entered.is_set)
    try:
        assert not form.state["canEdit"]
        assert not form.setField("image_format", "png")
        assert requests == [expected] and not form.has_unsaved
    finally:
        release.set()
        idle(desktop)
    assert service.runs[-1][2] == expected


def test_old_plan_factory_error_cannot_replace_edited_form(desktop, tmp_path):
    _, _, form = setup(desktop, tmp_path)
    factory = desktop.controller.factory
    entered, release = Event(), Event()
    hold = True

    def delayed_factory():
        nonlocal hold
        if hold:
            hold = False
            entered.set()
            assert release.wait(5)
            raise ValueError("Obsolete plan factory failed")
        return factory()

    desktop.controller.factory = delayed_factory
    desktop.prepare.plan()
    until(entered.is_set)
    try:
        form.setField("quality_max_side", "512")
        assert desktop.prepare.state["status"] == "idle"
    finally:
        release.set()
        idle(desktop)
        desktop.controller.factory = factory
    assert not desktop.prepare.state["error"]
    assert form.has_unsaved and form.state["fields"]["quality_max_side"] == "512"
    assert not desktop.prepare.state["canRun"]


def test_return_to_sources_during_settings_save_stays_in_prepare(desktop, tmp_path):
    _, _, form = setup(desktop, tmp_path)
    entered, release = Event(), Event()
    factory = desktop.controller.factory

    def slow_factory():
        facade = factory()
        save = facade.save

        def delayed_save(*args):
            entered.set()
            assert release.wait(5)
            return save(*args)

        facade.save = delayed_save
        return facade

    desktop.controller.factory = slow_factory
    form.setField("quality_max_side", "512")
    form.save()
    until(entered.is_set)
    try:
        desktop.prepare.sources()
        assert desktop.prepare.state["active"]
        assert "Finish or cancel" in desktop.prepare.state["error"]
    finally:
        release.set()
        idle(desktop)
        desktop.controller.factory = factory
    assert not form.has_unsaved and not form.state["error"]
