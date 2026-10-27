"""Manual-review regressions: project isolation, inspection and truthful evidence."""

import os
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QObject, QSize, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtQml import QQmlExpression, qmlContext  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_sources import inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.application.desktop import ThumbnailReference  # noqa: E402
from splatforge.application.media_progress import ImportReporter  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402
from splatforge_gui.qml_media import GalleryModel, MediaProvider  # noqa: E402
from splatforge_gui.source_status import SourceSession  # noqa: E402


def idle(desktop):
    until(lambda: not desktop.controller.executor.busy)


def provider_image(provider, url):
    return provider.requestImage(url.removeprefix("image://media/"), QSize(), QSize())


def test_thumbnail_namespace_revokes_cached_queued_and_async_replies(app, tmp_path, monkeypatch):
    from splatforge_gui import thumbnails

    entered, release = Event(), Event()
    image = QImage(16, 12, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)

    def delayed(path, side=192):
        entered.set()
        assert release.wait(10)
        return image

    monkeypatch.setattr(thumbnails, "decode_thumbnail", delayed)
    gallery = GalleryModel()
    provider = MediaProvider(gallery)
    # Deliberately collide identities, as with gallery indices or copied projects.
    ref = ThumbnailReference(identity="same", path=tmp_path / "A.png", caption="A")
    gallery.replace((ref,))
    generation = gallery.generation
    old_url = gallery.image_url("same")
    gallery.data(gallery.index(0), gallery.ImageRole)
    until(entered.is_set)
    gallery.replace((ref.model_copy(update={"path": tmp_path / "B.png"}),))
    assert old_url != gallery.image_url("same")
    assert provider_image(provider, old_url).isNull()
    gallery._request("same", ref.path, generation)
    assert len(gallery.jobs) == 1 and not gallery.queue
    release.set()
    until(lambda: not gallery.executor.busy)
    assert not gallery.cache  # Late A response cannot become B's same-ID thumbnail.
    assert not gallery._store("same", image, generation)
    gallery._store("same", image, gallery.generation)
    assert not provider_image(provider, gallery.image_url("same")).isNull()
    gallery.replace(())
    assert provider_image(provider, old_url).isNull()
    assert not gallery.cache


def test_real_project_photo_video_switch_revokes_images_and_selection(desktop, tmp_path):
    root_a = open_project(desktop, tmp_path)
    inject_media(desktop, root_a)
    desktop.addFiles([str(photo(tmp_path / "A.png"))])
    idle(desktop)
    root_b = tmp_path / "B"
    build_project_service().create(root_b, "B")
    desktop.setSourceView("Grid")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        thumbs = desktop._source.thumbnails
        until(lambda: bool(thumbs.cache) and not thumbs.executor.busy)
        source_a = desktop._source.rows[0]
        url_a = desktop.sources.data(desktop.sources.index(0, 0), desktop.sources.ImageRole)
        assert not provider_image(desktop.media.provider, url_a).isNull()
        desktop.media.previewSource(str(source_a.identity))
        idle(desktop)
        large_a = desktop.media.state["largeImage"]
        preview_token_a = desktop.media._preview_token
        gallery_token_a = desktop.media._token
        assert not provider_image(desktop.media.provider, large_a).isNull()
        desktop.openProject(str(root_b))
        idle(desktop)
        assert desktop.sources.selectedId == "" and desktop.media.state["largeImage"] == ""
        assert provider_image(desktop.media.provider, url_a).isNull()
        assert provider_image(desktop.media.provider, large_a).isNull()
        desktop.media.completed(
            "qml_image", (preview_token_a, QImage(8, 8, QImage.Format_RGB32), "")
        )
        desktop.media.completed("qml_gallery", (gallery_token_a, ()))
        assert desktop.media.state["largeImage"] == "" and desktop.media.gallery.rowCount() == 0
        video = tmp_path / "DJI_0051.MP4"
        video.write_bytes(b"synthetic video")
        desktop.addFiles([str(video)])
        idle(desktop)
        row_b = desktop._source.rows[0]
        assert row_b.values["type"] == "video"
        tile_name = "tile-" + str(row_b.identity)
        until(lambda: visual_item(window.contentItem(), tile_name) is not None)
        tile = visual_item(window.contentItem(), tile_name)
        assert tile.property("imageUrl") == ""
        assert visual_item(tile, "photoThumbnail") is None
        assert "VIDEO" in visual_item(tile, "thumbnailPlaceholder").property("text")
        click(window, tile_name)
        assert desktop.sources.selectedId == str(row_b.identity)
        desktop.setSourceView("List")
        assert desktop.sources.selectedId == str(row_b.identity)
        desktop.setSourceView("Grid")
        assert tile.property("imageUrl") == ""
        # Reverse direction: video project -> photo project has no retained video selection.
        desktop.openProject(str(root_a))
        idle(desktop)
        assert desktop.sources.selectedId == ""
        assert desktop._source.rows[0].identity == source_a.identity
        assert provider_image(desktop.media.provider, url_a).isNull()
        until(lambda: bool(thumbs.cache) and not thumbs.executor.busy)
        fresh = desktop.sources.data(desktop.sources.index(0, 0), desktop.sources.ImageRole)
        assert fresh != url_a and not provider_image(desktop.media.provider, fresh).isNull()
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop._source.thumbnails.executor.busy)
        dispose(engine)


@pytest.mark.parametrize("kind", ["photo", "video"])
@pytest.mark.parametrize("view", ["List", "Grid"])
def test_selected_source_details_human_fields_and_collapsed_provenance(
    desktop,
    tmp_path,
    kind,
    view,
):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    path = tmp_path / ("photo.png" if kind == "photo" else "DJI_0051.MP4")
    photo(path) if kind == "photo" else path.write_bytes(b"synthetic video")
    desktop.addFiles([str(path)])
    idle(desktop)
    desktop.setSourceView(view)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        identity = str(desktop._source.rows[0].identity)
        name = ("source-" if view == "List" else "tile-") + identity
        until(lambda: visual_item(window.contentItem(), name) is not None)
        click(window, name)
        assert desktop.sources.selectedId == identity
        assert visual_item(window.contentItem(), "sourceDetails").isEnabled()
        click(window, "sourceDetails")
        page = visual_item(window.contentItem(), "sourcesPage")
        dialog = page.findChild(QObject, "sourceDetailsDialog")
        assert dialog.property("visible")
        assert dialog.property("title") == path.name
        assert visual_item(window.contentItem(), "sourceHumanType").property("text") == kind.title()
        assert str(path) in visual_item(window.contentItem(), "sourceHumanLocation").property(
            "text"
        )
        assert (
            visual_item(window.contentItem(), "sourceHumanDimensions").property("text") == "16 × 12"
        )
        technical = visual_item(window.contentItem(), "sourceTechnicalDetails")
        assert not technical.property("expanded")
        assert identity in technical.property("text")
        assert desktop.sources.selected["sha256"] in technical.property("text")
        technical.setProperty("expanded", True)
        assert technical.property("expanded")
        click(window, "closeSourceDetails")
        click(window, "sourceGridMode" if view == "List" else "sourceListMode")
        assert desktop.sources.selectedId == identity
        click(window, "sourceDetails")
        assert not technical.property("expanded")
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop._source.thumbnails.executor.busy)
        dispose(engine)


def test_session_evidence_reopen_check_missing_and_failed_check(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    path = photo(tmp_path / "source.png")
    desktop.addFiles([str(path)])
    idle(desktop)
    assert desktop.sources.rows[0].values["availabilityState"] == "available"
    assert desktop.sources.rows[0].values["checkedLabel"] == "Checked during import"
    desktop.openProject(str(root))
    idle(desktop)
    assert desktop.sources.rows[0].values["availabilityState"] == "neutral"
    desktop.verifySources()
    idle(desktop)
    row = desktop.sources.rows[0]
    assert row.values["availabilityState"] == "available"
    # Even persisted successful verification is historical after an Open/reopen.
    desktop.openProject(str(root))
    idle(desktop)
    assert desktop.sources.rows[0].values["availabilityState"] == "neutral"
    assert desktop.sources.rows[0].values["lastVerifiedLabel"] != "Not recorded"
    desktop.controller.submit(
        "verify",
        lambda f: (_ for _ in ()).throw(OSError("Could not read source")),
        mutation=True,
    )
    idle(desktop)
    assert desktop.sources.rows[0].values["availabilityState"] == "warning"
    assert desktop.sources.rows[0].values["availability"] == "Needs attention"
    path.unlink()
    desktop.verifySources()
    idle(desktop)
    assert desktop.sources.rows[0].values["availabilityState"] == "missing"
    session = SourceSession()
    session.enter(uuid4())
    result = desktop.controller.factory().service("media").verify(root)[0]
    session.verified(
        [result.model_copy(update={"outcome": "unchanged", "assurance": "unavailable"})]
    )
    assert session.project(row)["availabilityState"] == "warning"
    session.enter(uuid4())
    assert session.project(row)["availabilityState"] == "neutral"


def test_ingest_progress_rejects_previous_project_previous_job_and_backwards(desktop, tmp_path):
    open_project(desktop, tmp_path)
    controller = desktop.controller
    events = []
    reporter = ImportReporter(5, events.append)
    reporter.emit("checked", 2, "a.png")
    controller.operation, controller.ingest_status, controller._ingest_token = (
        "ingest",
        "running",
        "new",
    )
    controller._import_observed(controller.generation - 1, "new", events[0])
    controller._import_observed(controller.generation, "old", events[0])
    assert controller.ingest_progress is None
    controller._import_observed(controller.generation, "new", events[0])
    assert desktop.state["progress"]["fraction"] == 0.4
    assert "2 / 5" in desktop.state["progress"]["work"]
    stale = events[0].model_copy(update={
        "observation": events[0].observation.model_copy(update={
            "observed_at": datetime.now(UTC) - timedelta(seconds=10),
        }),
    })
    controller.ingest_progress = stale
    controller.poll()
    assert desktop.state["progress"]["eta"] == "Time remaining unavailable"
    assert desktop.state["progress"]["fraction"] == 0.4
    assert not controller.executor.busy
    controller.ingest_progress = events[0]
    backwards = events[0].model_copy(
        update={
            "observation": events[0].observation.model_copy(update={"completed": 1}),
        }
    )
    controller._import_observed(controller.generation, "new", backwards)
    assert controller.ingest_progress == events[0]
    controller.ingest_status = "cancelled"
    reporter.emit("succeeded", 5)
    controller._import_observed(controller.generation, "new", events[-1])
    assert controller.ingest_progress == events[0]
    controller.operation = None


def test_real_ingest_ui_count_and_cancellation_preserve_committed_sources(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    _, probe = inject_media(desktop, root)
    old = photo(tmp_path / "old.png")
    desktop.addFiles([str(old)])
    idle(desktop)
    identity = desktop.sources.rows[0].identity
    entered, release = Event(), Event()
    original_probe = probe.probe

    def waiting(path, media_type, **kwargs):
        if path.name == "two.png":
            entered.set()
            assert release.wait(10)
        return original_probe(path, media_type, **kwargs)

    probe.probe = waiting
    candidates = [photo(tmp_path / name) for name in ("one.png", "two.png")]
    try:
        desktop.addFiles([str(p) for p in candidates])
        until(entered.is_set)
        until(lambda: desktop.state["progress"]["phase"] == "Reading metadata")
        assert desktop.state["progress"]["fraction"] == 0.5
        assert "1 / 2 files checked" in desktop.state["progress"]["work"]
        assert "two.png" in desktop.state["progress"]["work"]
        assert desktop.state["progress"]["eta"] == "Estimating…"
        desktop.cancel()
        release.set()
        idle(desktop)
        assert desktop.controller.ingest_status == "cancelled"
        assert desktop.controller.ingest_progress.phase != "succeeded"
        assert [r.identity for r in desktop.sources.rows] == [identity]
        assert all(p.exists() for p in candidates)
    finally:
        release.set()
        idle(desktop)


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_source_switch_buttons_apply_current_theme_and_selection_immediately(
    desktop,
    tmp_path,
    theme,
):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    desktop.addFiles([str(photo(tmp_path / "source.png"))])
    idle(desktop)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        desktop.setTheme(theme)
        until(lambda: visual_item(window.contentItem(), "sourceGridMode") is not None)
        click(window, "sourceGridMode")
        for name, token in [("sourceGridMode", "accent"), ("sourceListMode", "raised")]:
            button = visual_item(window.contentItem(), name)
            expression = QQmlExpression(qmlContext(button), button, "Theme." + token)
            expected = expression.evaluate()[0]
            assert not expression.hasError()
            assert button.property("background").property("color") == expected
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop._source.thumbnails.executor.busy)
        dispose(engine)
