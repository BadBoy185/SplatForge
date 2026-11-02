"""Close continuations belong to their viewmodel's QObject lifetime."""

import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtTest import QSignalSpy, QTest  # noqa: E402
from shiboken6 import delete, isValid  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import until  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge_gui.preferences import Preferences  # noqa: E402
from splatforge_gui.qml_bridge import DesktopViewModel  # noqa: E402


def make_viewmodel(tmp_path):
    preferences = Preferences(QSettings(str(tmp_path / "lifetime.ini"), QSettings.IniFormat))
    vm = DesktopViewModel(preferences=preferences)
    vm.controller.timer.stop()
    until(lambda: not vm.controller.executor.busy)
    return vm


@pytest.mark.parametrize("continuation", ["worker_retry", "after_save", "completed_close"])
def test_close_continuation_cancels_when_owner_is_destroyed(
    app, tmp_path, monkeypatch, continuation,
):
    vm = make_viewmodel(tmp_path)
    errors = []
    original_hook = sys.excepthook

    def record_error(kind, value, trace):
        errors.append((kind, str(value)))
        original_hook(kind, value, trace)

    try:
        if continuation == "completed_close":
            open_project(vm, tmp_path)
            # This close transition uses the already committed overview; avoid
            # starting an unrelated recent-project refresh while destroying it.
            monkeypatch.setattr(vm, "refresh_recents", lambda: None)
        monkeypatch.setattr(sys, "excepthook", record_error)
        if continuation == "worker_retry":
            with monkeypatch.context() as patch:
                patch.setattr(vm.controller, "executor", SimpleNamespace(busy=True))
                assert vm.requestClose() is False
        elif continuation == "after_save":
            vm._after_save = vm.closeReady.emit
            vm._busy_changed(False)
        else:
            vm._pending_close = True
            vm._overview(vm.controller.overview)
        delete(vm)
        # Pump past both queued zero-delay continuations and the 100 ms retry.
        QTest.qWait(160)
        assert errors == []
    finally:
        if isValid(vm):
            until(lambda: not vm.controller.executor.busy)
            delete(vm)


def test_close_retry_notifies_live_owner_after_readers_drain(app, tmp_path, monkeypatch):
    vm = make_viewmodel(tmp_path)
    try:
        ready = QSignalSpy(vm.closeReady)
        readers = SimpleNamespace(busy=True)
        with monkeypatch.context() as patch:
            patch.setattr(vm.controller, "executor", readers)
            assert vm.requestClose() is False
            assert ready.count() == 0
            readers.busy = False
            until(lambda: ready.count() == 1)
            assert vm.requestClose() is True
    finally:
        delete(vm)
