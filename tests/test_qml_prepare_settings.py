"""Direct Prepare controls over real persistence and a deterministic run boundary."""

import json
import os
from fractions import Fraction

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtQml import QQmlExpression, qmlContext  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_prepare import configured, idle  # noqa: E402

from splatforge.application.prepare_settings import (  # noqa: E402
    prepare_settings_fields,
    resolve_preparation_request,
)
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


class SettingsControls:
    """Use actual QML edit/activation handlers, scrolling their inspector into view."""

    def __init__(self, window):
        self.window = window

    def item(self, name):
        result = visual_item(self.window.contentItem(), name)
        assert result is not None, name
        return result

    def reveal(self, name):
        item = self.item(name)
        scroll = self.item("prepareInspectorScroll").property("contentItem")
        scroll.setProperty("contentY", 0)
        QTest.qWait(10)
        y = item.mapToItem(scroll, QPointF(0, item.height() / 2)).y()
        maximum = max(0, scroll.property("contentHeight") - scroll.height())
        scroll.setProperty("contentY", max(0, min(maximum, y - scroll.height() / 2)))
        QTest.qWait(10)
        return item

    def press(self, name):
        self.reveal(name)
        click(self.window, name)

    def type(self, key, value):
        name = "prepareSetting_" + key
        self.press(name)
        QTest.keyClick(self.window, Qt.Key_A, Qt.ControlModifier)
        for character in value:
            QTest.keyClick(self.window, Qt.Key(ord(character)))
        assert self.item(name).property("text") == value

    def choose(self, key, value):
        item = self.reveal("prepareSetting_" + key)
        assert item.isEnabled()
        expression = QQmlExpression(qmlContext(item), item,
            "currentIndex = indexOfValue(" + json.dumps(value) + "); activated(currentIndex)")
        expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        assert item.property("currentValue") == value

    def checked(self, key, value):
        name = "prepareSetting_" + key
        if self.item(name).property("checked") != value:
            self.press(name)
        assert self.item(name).property("checked") is value


def setup(desktop, tmp_path, *, video=True):
    root, image, service = configured(desktop, tmp_path)
    if video:
        source = tmp_path / "Video ž.MP4"
        source.write_bytes(b"Synthetic inventory fixture; no native decoder")
        desktop.addFiles([str(source)])
        idle(desktop)
    desktop.prepare.enter()
    idle(desktop)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1280, 900)
    QTest.qWait(20)
    return root, image, service, engine, SettingsControls(window)


def test_direct_controls_save_plan_run_and_reopen_exact_request(desktop, tmp_path):
    root, image, service, engine, ui = setup(desktop, tmp_path)
    original = image.read_bytes()
    try:
        assert desktop.prepare.settings.state["hasVideo"]
        ui.choose("method", "sharpest_interval")
        ui.type("interval_seconds", "3/2")
        ui.type("candidate_fps", "3")
        assert "2/3 fps" in ui.item("prepareSetting_targetFps").property("text")
        ui.choose("image_format", "png")
        assert not ui.item("prepareSetting_jpeg_qscale").isVisible()
        ui.type("png_compression_level", "3")
        ui.press("togglePrepareOptions")
        ui.checked("min_sharpness_enabled", True)
        ui.type("min_sharpness", "5/2")
        ui.checked("reject_duplicates", True)
        ui.type("duplicate_hamming_threshold", "7")
        ui.type("duplicate_lookback", "3")
        ui.type("quality_max_side", "512")
        assert desktop.prepare.settings.state["dirty"]
        assert not service.runs
        ui.press("savePrepareSettings")
        idle(desktop)
        assert not desktop.prepare.settings.state["dirty"]
        document = build_project_service().open(root)
        saved = prepare_settings_fields(document)
        request = resolve_preparation_request(document, has_video=True)
        assert saved["interval_seconds"] == "3/2"
        assert request.selection.target_fps.as_fraction() == Fraction(2, 3)
        assert request.candidate.candidate_fps.as_fraction() == 3
        assert request.candidate.encoding.image_format.value == "png"
        assert request.candidate.encoding.png_compression_level == 3
        assert request.selection.min_sharpness.as_fraction() == Fraction(5, 2)
        assert request.selection.reject_duplicates
        assert request.selection.duplicate_hamming_threshold == 7
        assert request.selection.duplicate_lookback == 3
        assert request.quality.quality_max_side == 512
        ui.press("planPrepare")
        idle(desktop)
        ui.press("runPrepare")
        idle(desktop)
        assert service.runs[-1][2] == request
        assert service.runs[-1][:2] == (document.project_id, document.revision)
        # Frozen history is separate from the current editable form.
        frozen = desktop.prepare.state["selectedSummary"]["settingsText"]
        ui.press("togglePreparedRunSettings")
        assert ui.item("preparedRunSettings").property("text") == frozen
        ui.type("candidate_fps", "4")
        assert desktop.prepare.state["selectedSummary"]["settingsText"] == frozen
        assert service.runs[-1][2] == request and not desktop.prepare.state["canRun"]
        # Saving a different form revokes the old plan, never rewrites its run.
        ui.press("savePrepareSettings")
        idle(desktop)
        assert not desktop.prepare.state["canRun"]
        assert desktop.prepare.state["selectedSummary"]["settingsText"] == frozen
        other = tmp_path / "Other project"
        build_project_service().create(other, "Other")
        desktop.openProject(str(other))
        idle(desktop)
        desktop.openProject(str(root))
        idle(desktop)
        assert desktop.prepare.settings.state["fields"]["candidate_fps"] == "4"
        assert desktop.prepare.settings.state["fields"]["min_sharpness"] == "5/2"
        assert image.read_bytes() == original
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_validation_and_independent_filters_never_invent_a_threshold(desktop, tmp_path):
    root, _, service, engine, ui = setup(desktop, tmp_path)
    before = (root / "project.json").read_bytes()
    try:
        ui.choose("method", "sharpest_interval")
        ui.type("interval_seconds", "1")
        ui.type("candidate_fps", "1")
        state = desktop.prepare.settings.state
        assert not state["valid"] and state["error"] and not state["canSave"]
        assert ui.item("prepareSettingsError").isVisible()
        assert not ui.item("savePrepareSettings").isEnabled()
        assert not desktop.prepare.state["canPlan"] and not desktop.prepare.state["canRun"]
        ui.type("candidate_fps", "2")
        ui.press("togglePrepareOptions")
        ui.checked("min_sharpness_enabled", True)
        assert desktop.prepare.settings.state["fields"]["min_sharpness"] == ""
        assert not desktop.prepare.settings.state["valid"]
        ui.type("min_sharpness", "0")
        assert desktop.prepare.settings.state["valid"]
        ui.checked("reject_duplicates", False)
        assert not ui.item("prepareSetting_duplicate_lookback").isEnabled()
        assert ui.item("prepareSetting_min_sharpness").isEnabled()
        ui.press("savePrepareSettings")
        idle(desktop)
        request = resolve_preparation_request(build_project_service().open(root), has_video=True)
        assert request.selection.min_sharpness.as_fraction() == 0
        assert not request.selection.reject_duplicates
        ui.checked("min_sharpness_enabled", False)
        ui.press("savePrepareSettings")
        idle(desktop)
        request = resolve_preparation_request(build_project_service().open(root), has_video=True)
        assert request.selection.min_sharpness is None
        ui.choose("method", "fixed_fps")
        assert not ui.item("prepareSetting_min_sharpness_enabled").isEnabled()
        assert not ui.item("prepareSetting_reject_duplicates").isEnabled()
        assert not ui.item("prepareSetting_quality_max_side").isEnabled()
        assert not service.runs and (root / "project.json").read_bytes() != before
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_photo_context_disables_time_and_video_similarity_only(desktop, tmp_path):
    root, _, _, engine, ui = setup(desktop, tmp_path, video=False)
    try:
        state = desktop.prepare.settings.state
        assert not state["hasVideo"] and state["photoCount"] == 1
        assert "Photos use no time sampling" in ui.item("prepareSettingsContext").property("text")
        assert not ui.item("prepareSetting_interval_seconds").isEnabled()
        assert not ui.item("prepareSetting_candidate_fps").isEnabled()
        ui.choose("method", "sharpest_interval")
        ui.press("togglePrepareOptions")
        assert ui.item("prepareSetting_min_sharpness_enabled").isEnabled()
        assert ui.item("prepareSetting_quality_max_side").isEnabled()
        assert not ui.item("prepareSetting_reject_duplicates").isEnabled()
        assert not ui.item("prepareSetting_duplicate_hamming_threshold").isEnabled()
        ui.type("quality_max_side", "256")
        ui.choose("image_format", "jpeg")
        ui.type("jpeg_qscale", "9")
        ui.press("savePrepareSettings")
        idle(desktop)
        request = resolve_preparation_request(build_project_service().open(root), has_video=False)
        assert request.selection.target_fps.as_fraction() == 1
        assert request.candidate.candidate_fps.as_fraction() == 1
        assert not request.selection.reject_duplicates
        assert request.candidate.encoding.jpeg_qscale == 9
        assert request.quality.quality_max_side == 256
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_invalid_raw_form_is_discarded_by_existing_navigation_choice(desktop, tmp_path):
    _, _, _, engine, ui = setup(desktop, tmp_path)
    try:
        ui.type("interval_seconds", "0")
        assert desktop.prepare.settings.state["dirty"]
        assert not desktop.prepare.settings.state["valid"]
        dialogs = []
        desktop.dialogRequested.connect(dialogs.append)
        ui.press("returnToSources")
        until(lambda: dialogs and dialogs[-1] == "unsaved")
        click(ui.window, "cancelUnsaved")
        assert desktop.prepare.state["active"]
        assert desktop.prepare.settings.state["fields"]["interval_seconds"] == "0"
        ui.press("returnToSources")
        click(ui.window, "discardUnsaved")
        idle(desktop)
        assert not desktop.prepare.state["active"]
        assert not desktop.prepare.settings.state["dirty"]
        assert not desktop.prepare.settings.state["error"]
        assert desktop.prepare.settings.state["fields"]["interval_seconds"] != "0"
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)
