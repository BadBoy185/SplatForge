"""Suspending hidden thumbnails revokes waiting work without abandoning workers."""

import os
from threading import Event
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtGui import QImage  # noqa: E402
from test_gui import app as app  # noqa: E402
from test_gui import until  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402

from splatforge.application.desktop import IndexRow  # noqa: E402
from splatforge_gui import thumbnails  # noqa: E402
from splatforge_gui.qml_media import SourceBrowserModel  # noqa: E402


def source_model(tmp_path, count):
    model = SourceBrowserModel()
    model.thumbnails.executor.pool.setMaxThreadCount(1)
    model.replace(tuple(
        IndexRow(identity=uuid4(), values={
            "type": "photo", "locator": str(tmp_path / f"{i}.png"),
        }) for i in range(count)
    ))
    return model


@pytest.mark.parametrize("decode_fails", [False, True])
def test_suspend_revokes_waiting_decodes_and_reactivation_requests_again(
    app, tmp_path, monkeypatch, decode_fails,
):
    entered, release = Event(), Event()
    decoded = []
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0)
    model = source_model(tmp_path, 4)
    gallery = model.thumbnails
    first, second, _, cached = gallery.references
    cached_url = gallery.image_url(cached.identity)
    gallery._store(cached.identity, image)

    def decode(path, side=192):
        decoded.append(path)
        if path == first.path:
            entered.set()
            assert release.wait(10)
            if decode_fails:
                raise ValueError("held decode failed")
        return image

    monkeypatch.setattr(thumbnails, "decode_thumbnail", decode)
    try:
        for i in range(3):
            model.data(model.index(i, 0), model.ImageRole)
        until(app, lambda: entered.is_set() and len(gallery.jobs) + len(gallery.queue) == 3)
        assert len(gallery.jobs) == 1 and len(gallery.queue) == 2

        model.set_thumbnails_active(False)
        assert not gallery.queue and not gallery.pending
        assert gallery.executor.busy and len(gallery.jobs) == 1
        assert model.data(model.index(1, 0), model.ImageRole) == ""
        release.set()
        until(app, lambda: not gallery.executor.busy)

        assert decoded == [first.path]
        assert not gallery.jobs and not gallery.pending
        assert first.identity not in gallery.cache
        assert gallery.image_url(cached.identity) == cached_url
        assert gallery.lookup(cached_url.removeprefix("image://media/")) == image

        model.set_thumbnails_active(True)
        model.data(model.index(1, 0), model.ImageRole)
        until(app, lambda: second.identity in gallery.cache and not gallery.executor.busy)
        assert decoded == [first.path, second.path]
        assert not gallery.pending
    finally:
        model.set_thumbnails_active(False)
        release.set()
        until(app, lambda: not gallery.executor.busy)
        model.deleteLater()
        app.processEvents()


def test_suspend_revokes_posted_requests_even_after_immediate_reactivation(
    app, tmp_path, monkeypatch,
):
    decoded = []
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0)
    monkeypatch.setattr(
        thumbnails, "decode_thumbnail", lambda path, side=192: (decoded.append(path), image)[1],
    )
    model = source_model(tmp_path, 1)
    gallery = model.thumbnails
    try:
        model.data(model.index(0, 0), model.ImageRole)
        assert gallery.pending and not gallery.jobs
        model.set_thumbnails_active(False)
        model.set_thumbnails_active(True)
        app.processEvents()
        assert not decoded and not gallery.pending and not gallery.jobs

        model.data(model.index(0, 0), model.ImageRole)
        until(app, lambda: bool(gallery.cache) and not gallery.executor.busy)
        assert decoded == [gallery.references[0].path]
    finally:
        model.set_thumbnails_active(False)
        until(app, lambda: not gallery.executor.busy)
        model.deleteLater()
        app.processEvents()


def test_close_waits_for_active_decode_without_draining_hidden_queue(
    desktop, app, tmp_path, monkeypatch,
):
    until(app, lambda: not desktop.controller.executor.busy
          and not desktop.media.gallery.executor.busy
          and not desktop.media.preview_executor.busy
          and not desktop.videoUsage.filmstrip.executor.busy)
    entered, release = Event(), Event()
    decoded = []
    model = desktop.sources
    gallery = model.thumbnails
    gallery.executor.pool.setMaxThreadCount(1)
    model.replace(tuple(
        IndexRow(identity=uuid4(), values={
            "type": "photo", "locator": str(tmp_path / f"{i}.png"),
        }) for i in range(3)
    ))
    model.set_thumbnails_active(True)

    def decode(path, side=192):
        decoded.append(path)
        entered.set()
        assert release.wait(10)
        return QImage(8, 8, QImage.Format.Format_RGB32)

    monkeypatch.setattr(thumbnails, "decode_thumbnail", decode)
    try:
        for i in range(3):
            model.data(model.index(i, 0), model.ImageRole)
        until(app, lambda: entered.is_set() and len(gallery.jobs) + len(gallery.queue) == 3)
        assert not desktop.requestClose()
        assert gallery.executor.busy and not gallery.queue and not gallery.pending
        release.set()
        until(app, lambda: not gallery.executor.busy)
        assert decoded == [gallery.references[0].path]
        assert desktop.requestClose()
    finally:
        model.set_thumbnails_active(False)
        release.set()
        until(app, lambda: not gallery.executor.busy)
