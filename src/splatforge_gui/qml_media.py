"""Lazy bounded image delivery. QML receives provider keys, never decoding instructions."""

from uuid import UUID, uuid4

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from splatforge.application.desktop import ThumbnailReference
from splatforge_gui.presentation import guarded
from splatforge_gui.thumbnails import ThumbnailModel, decode_thumbnail


class GalleryModel(ThumbnailModel):
    CaptionRole = int(Qt.ItemDataRole.UserRole) + 1
    ImageRole = CaptionRole + 1
    StatusRole = ImageRole + 1

    def roleNames(self) -> dict:
        return {
            self.CaptionRole: b"caption",
            self.ImageRole: b"imageUrl",
            self.StatusRole: b"previewStatus",
        }

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.references):
            return None
        reference = self.references[index.row()]
        if role == self.CaptionRole:
            return reference.caption
        if role in (self.ImageRole, self.StatusRole):
            if reference.identity in self.cache:
                self.cache.move_to_end(reference.identity)
            elif reference.identity not in self.pending:
                self.pending.add(reference.identity)
                self.request.emit(reference.identity, reference.path)
            if role == self.StatusRole:
                if reference.identity not in self.cache:
                    return "Loading preview…"
                return (
                    "Ready" if self.cache[reference.identity] is not None else "Preview unavailable"
                )
            return (
                "image://media/" + reference.identity if self.cache.get(reference.identity) else ""
            )
        return super().data(index, role)

    def _store(self, identity: str, image) -> None:
        super()._store(identity, image)
        for i, reference in enumerate(self.references):
            if reference.identity == identity:
                self.dataChanged.emit(
                    self.index(i), self.index(i), [self.ImageRole, self.StatusRole]
                )


class MediaProvider(QQuickImageProvider):
    def __init__(self, model: GalleryModel) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.model = model
        self.large = QImage()

    def requestImage(self, identity, size, requestedSize) -> QImage:
        value = self.large if identity.startswith("large/") else self.model.cache.get(identity)
        result = QImage(value) if value is not None else QImage()
        size.setWidth(result.width())
        size.setHeight(result.height())
        return result


class MediaViewModel(QObject):
    changed = Signal()

    def __init__(self, desktop) -> None:
        super().__init__(desktop)
        self.desktop, self.controller = desktop, desktop.controller
        self._gallery = GalleryModel(self)
        self.provider = MediaProvider(self._gallery)
        self._token, self._offset, self._large, self._message = "", 0, "", ""
        self._gallery_run = ""
        self._project = None
        self.controller.completed.connect(self.completed)
        self.controller.changed.connect(self.overview)

    @Property(QObject, constant=True)
    def gallery(self) -> QObject:
        return self._gallery

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        return {
            "offset": self._offset,
            "count": len(self._gallery.references),
            "largeImage": self._large,
            "message": self._message,
        }

    def overview(self, overview) -> None:
        if self._project != overview.document.project_id:
            self._project = overview.document.project_id
            self._token = uuid4().hex
            self._gallery.replace(())
            self._offset, self._large, self._message = 0, "", ""
            self.changed.emit()

    @Slot(str)
    @guarded
    def selectSource(self, identity: str) -> None:
        self.desktop._source.select(identity)
        row = self.desktop._source.selected
        self._token = uuid4().hex
        self._offset = 0
        if row.get("type") == "photo":
            self._gallery.replace(
                (
                    ThumbnailReference(
                        identity=identity,
                        path=self.desktop.local_path(row["locator"]),
                        caption=row["filename"],
                    ),
                )
            )
            self._message = "Read-only bounded image preview"
        else:
            self._gallery.replace(())
            self._message = (
                "Video previews use materialized views. Prepare views, then choose a published set."
            )
        self.changed.emit()

    @Slot(str, int)
    @guarded
    def loadGallery(self, run: str, offset: int) -> None:
        if not run:
            return
        self._token, self._offset, self._gallery_run = uuid4().hex, max(0, offset), run
        token, root, start = self._token, self.controller.root, self._offset
        self.controller.submit("qml_gallery", lambda f: (token, f.gallery(root, UUID(run), start)))
        self._message = "Loading materialized views…"
        self.changed.emit()

    @Slot(int)
    @guarded
    def preview(self, index: int) -> None:
        if not 0 <= index < len(self._gallery.references):
            return
        reference, token = self._gallery.references[index], self._token
        self.controller.submit(
            "qml_image", lambda _: (token, decode_thumbnail(reference.path, 1024))
        )

    def completed(self, name: str, value) -> None:
        if name == "qml_gallery" and value[0] == self._token:
            self._gallery.replace(value[1])
            self._message = f"{len(value[1])} views · offset {self._offset} · bounded previews"
            self.changed.emit()
        elif name == "qml_image" and value[0] == self._token:
            self.provider.large = value[1]
            self._large = "image://media/large/" + uuid4().hex
            self.changed.emit()
            self.desktop.dialogRequested.emit("image")
