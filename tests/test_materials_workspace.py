"""Embedded workspace state, bounded review and preserved processing readiness."""

import os
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import dispose  # noqa: E402
from test_qml_sources import inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge_gui import qml_media  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402
from splatforge_gui.thumbnails import decode_preview  # noqa: E402


def idle(vm):
    until(lambda: not vm.controller.executor.busy and not vm.controller.mutating
          and not vm.media.preview_executor.busy)


def imported(vm, tmp_path):
    root = open_project(vm, tmp_path)
    inject_media(vm, root)
    vm.addFiles([str(photo(tmp_path / f"image {i}.png")) for i in range(3)])
    idle(vm)
    return root, [str(r.identity) for r in vm._source.rows]


def test_review_raster_never_upscales_and_caps_detail(app, tmp_path):
    tiny = photo(tmp_path / "tiny.png")
    assert decode_preview(tiny).size() == QImage(str(tiny)).size()
    large = QImage(8192, 512, QImage.Format.Format_RGB32)
    large.fill(Qt.GlobalColor.green)
    path = tmp_path / "wide.png"
    assert large.save(str(path))
    raster = decode_preview(path)
    assert (raster.width(), raster.height()) == (4096, 256)
    with pytest.raises(ValueError, match="invalid"):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image")
        decode_preview(bad)


def test_sparse_preview_releases_source_already_destroyed_with_workspace(app):
    from PySide6.QtCore import QObject, Signal
    from shiboken6 import delete

    from splatforge_gui.point_preview import PointPreview

    class Source(QObject):
        previewChanged = Signal()
        _preview = None

    source = Source()
    preview = PointPreview()
    preview.source = source
    delete(source)
    preview.source = None
    assert preview.source is None


def test_rapid_review_coalesces_and_rejects_stale_project_delivery(desktop, tmp_path, monkeypatch):
    _, ids = imported(desktop, tmp_path)
    entered, release = Event(), Event()
    calls = []
    decode = qml_media.decode_preview

    def slow(path):
        calls.append(path.name)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return decode(path)

    monkeypatch.setattr(qml_media, "decode_preview", slow)
    try:
        desktop.media.showSource(ids[0])
        until(entered.is_set)
        desktop.media.showSource(ids[1])
        desktop.media.showSource(ids[2])
        assert len(calls) == 1
        assert desktop.media.state["largeImage"] == ""
        release.set()
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        idle(desktop)
        assert calls == ["image 0.png", "image 2.png"]
        assert desktop.media.state["previewTitle"] == "image 2.png"
        desktop.media.closePreview()
        assert desktop.media.state["largeImage"] == ""
        # Explicit reload is a new preview generation; session return is not.
        desktop.media.showSource(ids[0])
        desktop.controller.open(desktop.controller.root)
        idle(desktop)
        assert desktop.media.state["previewIndex"] == 0
        assert desktop.media.state["videoUrl"] == ""
    finally:
        release.set()
        idle(desktop)


def test_reselect_current_photo_retains_loaded_raster(desktop, tmp_path, monkeypatch):
    _, ids = imported(desktop, tmp_path)
    calls = []
    decode = qml_media.decode_preview

    def record(path):
        calls.append(path)
        return decode(path)

    monkeypatch.setattr(qml_media, "decode_preview", record)
    desktop.media.activateSource(ids[0])
    until(lambda: desktop.media.state["previewStatus"] == "Ready")
    idle(desktop)
    url = desktop.media.state["largeImage"]
    desktop.media.activateSource(ids[0])
    idle(desktop)
    assert len(calls) == 1
    assert desktop.media.state["largeImage"] == url


def test_close_revokes_deferred_properties_before_worker_drain(desktop, tmp_path, monkeypatch):
    from splatforge.application.desktop import GuiFacade

    _, ids = imported(desktop, tmp_path)
    calls = []
    original = GuiFacade.source_details

    def record(facade, *args):
        calls.append(args)
        return original(facade, *args)

    monkeypatch.setattr(GuiFacade, "source_details", record)
    desktop.media.showSource(ids[0])
    desktop.requestClose()
    idle(desktop)
    QTest.qWait(150)
    assert not desktop.media.details_timer.isActive()
    assert not calls
    assert desktop.media.state["largeImage"] == ""
    assert desktop.requestClose()


def test_current_exclusion_preserves_batch_and_plan_is_revoked(desktop, tmp_path):
    _, ids = imported(desktop, tmp_path)
    desktop.sources.selectAllVisible()
    desktop.media.showSource(ids[0])
    idle(desktop)
    desktop.controller.reconstruction_plan = {"runnable": True}
    desktop.workflow._messages["reconstruction"] = "Plan ready"
    desktop.media.togglePreviewParticipation()
    idle(desktop)
    assert len(desktop.controller.overview.document.source_participation.excluded_source_ids) == 1
    assert desktop.media.state["previewTitle"] == "image 1.png"
    assert desktop.sources.selectedCount == 2
    assert desktop.controller.reconstruction_plan is None
    assert not desktop.workflow.state["canReconstruct"]
    assert "Run Plan again" in desktop.workflow.state["messages"]["reconstruction"]


def test_current_exclusions_do_not_replace_explicit_historical_request(desktop, tmp_path):
    from uuid import uuid4

    _, ids = imported(desktop, tmp_path)
    historical = uuid4()
    desktop.controller.request = desktop.controller.request.model_copy(
        update={"views_run": historical}
    )
    plan = {"runnable": True, "historical": str(historical)}
    desktop.controller.reconstruction_plan = plan
    desktop.setSourceIncluded(ids[0], False)
    idle(desktop)
    assert desktop.controller.request.views_run == historical
    assert desktop.controller.reconstruction_plan is plan


def test_controller_refuses_execution_when_plan_is_not_runnable(desktop, tmp_path):
    imported(desktop, tmp_path)
    desktop.controller.reconstruction_plan = {"runnable": False}
    desktop.controller.reconstruct(None, None, False)
    assert desktop.state["error"]["category"] == "StalePlan"
    assert not desktop.controller.executor.busy


def test_saved_properties_error_stays_local_to_media_review(desktop, tmp_path, monkeypatch):
    from splatforge.application.desktop import GuiFacade

    _, ids = imported(desktop, tmp_path)

    def unavailable(*_):
        raise OSError("Saved inventory is temporarily unavailable")

    monkeypatch.setattr(GuiFacade, "source_details", unavailable)
    desktop.media.showSource(ids[0])
    until(lambda: "error" in desktop.media.state["sourceDetails"])
    idle(desktop)
    assert "temporarily unavailable" in desktop.media.state["sourceDetails"]["error"]
    assert desktop.media.state["previewStatus"] == "Ready"
    assert not desktop.state["error"]


@pytest.mark.parametrize("dialog", ["groups", "settings"])
def test_review_keys_yield_to_modal_dialog(desktop, tmp_path, dialog):
    from test_qml_interaction import click

    _, ids = imported(desktop, tmp_path)
    desktop.media.showSource(ids[0])
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        idle(desktop)
        if dialog == "groups":
            click(window, "sourceGroups")
        else:
            QTest.keyClick(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
            QTest.qWait(30)
        QTest.keyClick(window, Qt.Key.Key_Right)
        assert desktop.media.state["previewIndex"] == 1
        QTest.keyClick(window, Qt.Key.Key_Escape)
        QTest.keyClick(window, Qt.Key.Key_Right)
        assert desktop.media.state["previewIndex"] == 2
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("width,height", [(1024, 640), (1440, 900)])
def test_workspace_fills_window_and_panel_collapse_keeps_viewer(desktop, tmp_path, width, height):
    _, ids = imported(desktop, tmp_path)
    desktop.media.showSource(ids[0])
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        window.resize(width, height)
        idle(desktop)
        QTest.qWait(80)
        page = visual_item(window.contentItem(), "sourcesPage")
        viewer = visual_item(window.contentItem(), "materialViewer")
        host = visual_item(window.contentItem(), "workspaceHost")
        assert page.height() == pytest.approx(host.height())
        assert viewer.height() > height * 0.7
        assert viewer.width() > width * 0.45
        old_width = viewer.width()
        page.setProperty("catalogVisible", False)
        QTest.qWait(50)
        assert viewer.width() > old_width
        page.setProperty("catalogVisible", True)
        desktop.setSourceView("Grid")
        QTest.qWait(80)
        catalog = visual_item(window.contentItem(), "materialsCatalog")
        for name in ("sourceListMode", "sourceGridMode", "filterAll", "sourceSectionPicker"):
            control = visual_item(window.contentItem(), name)
            corner = control.mapToItem(catalog, QPointF(control.width(), 0))
            assert corner.x() <= catalog.width() + 1, name
        all_filter = visual_item(window.contentItem(), "filterAll")
        point = all_filter.mapToScene(QPointF(all_filter.width() / 2,
                                             all_filter.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=point)
        assert desktop.state["sourceFilter"] == "All"
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)
