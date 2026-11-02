"""Optional filmstrip: one owned worker, latest visible queue, 32 small rasters."""

from collections import OrderedDict, deque
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from splatforge_gui.tasks import TaskExecutor


class _Cancellation:
    def __init__(self) -> None:
        self.event = Event()

    def is_cancelled(self) -> bool:
        return self.event.is_set()


class FilmstripProvider(QQuickImageProvider):
    def __init__(self, owner) -> None:
        super().__init__(QQuickImageProvider.Image)
        self.owner = owner

    def requestImage(self, identity, size, requested_size):
        image = self.owner.cache.get(identity)
        return image if image is not None else QImage()


class VideoFilmstrip(QObject):
    changed = Signal()

    def __init__(self, desktop) -> None:
        super().__init__(desktop)
        self.desktop = desktop
        self.executor = TaskExecutor(self)
        self.executor.result.connect(self._result)
        self.executor.error.connect(self._error)
        self.executor.finished.connect(self._finished)
        self.provider = FilmstripProvider(self)
        self.context = ""
        self.namespace = uuid4().hex
        self.cache = OrderedDict()
        self.queue = deque()
        self.jobs = {}
        self.positions = []
        self.failed = set()
        self.message = ""

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        return {"frames": [
            {"position": p, "url": f"image://filmstrip/{self.namespace}/{p}"
             if f"{self.namespace}/{p}" in self.cache else ""} for p in self.positions
        ], "message": self.message}

    @Slot()
    def stop(self) -> None:
        self.context = ""
        self.namespace = uuid4().hex
        self.queue.clear()
        self.positions = []
        self.cache.clear()
        self.failed.clear()
        self.message = ""
        for job in self.jobs.values():
            job[2].event.set()
        self.changed.emit()

    def request(self, context: str, path: Path, stream: int, positions: list[int]) -> None:
        if context != self.context:
            self.stop()
            self.context = context
        self.positions = positions[:12]
        self.queue.clear()  # superseded zoom/scroll requests do not build an unbounded queue
        if self.message:
            self.changed.emit()
            return
        pending = {j[1] for j in self.jobs.values() if j[0] == context}
        for p in self.positions:
            key = f"{self.namespace}/{p}"
            if key not in self.cache and p not in self.failed and p not in pending:
                self.queue.append((context, p, path, stream, self.namespace))
        self._next()
        self.changed.emit()

    def _next(self) -> None:
        if self.jobs or not self.queue:
            return
        context, position, path, stream, namespace = self.queue.popleft()
        cancel = _Cancellation()
        factory = self.desktop.controller.factory

        def decode():
            raw = factory().service("video_preview").frame(path, stream, position, cancel)
            image = QImage.fromData(raw)
            if image.isNull() or image.width() > 160 or image.height() > 90:
                raise ValueError("Invalid timeline raster")
            return image

        key = self.executor.submit("timeline_frame", decode)
        self.jobs[key] = (context, position, cancel, namespace)

    @Slot(str, object)
    def _result(self, key: str, image) -> None:
        context, position, _, namespace = self.jobs[key]
        if context != self.context or namespace != self.namespace:
            return
        self.cache[f"{namespace}/{position}"] = image
        while len(self.cache) > 32:
            self.cache.popitem(last=False)
        self.changed.emit()

    @Slot(str, object)
    def _error(self, key: str, error) -> None:
        context, position, _, namespace = self.jobs[key]
        if context == self.context and namespace == self.namespace:
            self.failed.add(position)
            self.message = "Timeline thumbnails unavailable. Editing and playback remain available."
            # A missing tool/codec must not launch the other eleven failing probes.
            self.queue.clear()
            self.changed.emit()

    @Slot(str)
    def _finished(self, key: str) -> None:
        self.jobs.pop(key, None)
        self._next()
