"""GUI-only bounded thumbnail decoding; QPixmap remains on the Qt GUI thread."""

from collections import OrderedDict, deque
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, Qt, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QPixmap

from splatforge_gui.tasks import TaskExecutor


def decode_thumbnail(path: Path, side: int = 192) -> QImage:
    if path.stat().st_size > 256 * 1024**2:
        raise ValueError("preview.encoded_byte_limit")
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 64000000:
        raise ValueError("preview.pixel_limit_or_invalid_image")
    reader.setScaledSize(size.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError(reader.errorString())
    return image.scaled(
        side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


class ThumbnailModel(QAbstractListModel):
    request = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.references = ()
        self.cache: OrderedDict[str, QImage | None] = OrderedDict()
        self.pending: set[str] = set()
        self.executor = TaskExecutor(self)
        self.jobs = {}
        self.queue = deque()
        self.request.connect(self._request, Qt.ConnectionType.QueuedConnection)
        self.executor.result.connect(self._result)
        self.executor.error.connect(self._error)
        self.executor.finished.connect(self._finished)

    def rowCount(self, parent=None) -> int:
        return 0 if parent and parent.isValid() else len(self.references)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.references):
            return None
        reference = self.references[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return reference.caption
        if role == Qt.ItemDataRole.UserRole:
            return reference
        if role == Qt.ItemDataRole.DecorationRole:
            if reference.identity in self.cache:
                image = self.cache[reference.identity]
                self.cache.move_to_end(reference.identity)
                return QPixmap.fromImage(image) if image is not None else None
            if reference.identity not in self.pending:
                self.pending.add(reference.identity)
                self.request.emit(reference.identity, reference.path)
        return None

    def replace(self, references) -> None:
        self.beginResetModel()
        self.references = tuple(references)
        for identity, _ in self.queue:
            self.pending.discard(identity)
        self.queue.clear()
        self.endResetModel()

    @Slot(str, object)
    def _request(self, identity: str, path: Path) -> None:
        if len(self.jobs) >= 8:
            if len(self.queue) < 100:
                self.queue.append((identity, path))
            else:
                self.pending.discard(identity)
            return
        key = self.executor.submit("thumbnail", lambda: decode_thumbnail(path))
        self.jobs[key] = identity

    @Slot(str)
    def _finished(self, key: str) -> None:
        self.jobs.pop(key, None)
        if self.queue:
            identity, path = self.queue.popleft()
            self._request(identity, path)

    @Slot(str, object)
    def _result(self, key: str, image) -> None:
        self._store(self.jobs[key], image)

    @Slot(str, object)
    def _error(self, key: str, error) -> None:
        self._store(self.jobs[key], None)

    def _store(self, identity: str, image) -> None:
        self.pending.discard(identity)
        self.cache[identity] = image
        while len(self.cache) > 128:
            self.cache.popitem(last=False)
        for i, reference in enumerate(self.references):
            if reference.identity == identity:
                self.dataChanged.emit(
                    self.index(i), self.index(i), [Qt.ItemDataRole.DecorationRole]
                )
