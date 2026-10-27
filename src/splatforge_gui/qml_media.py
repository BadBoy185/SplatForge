"""Lazy bounded image delivery. QML receives provider keys, never decoding instructions."""

import traceback
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
        self.large_identity = ""

    def requestImage(self, identity, size, requestedSize) -> QImage:
        value = (
            self.large if identity == self.large_identity else self.model.cache.get(identity)
        )
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
        self._preview_token = ""
        self._preview_index = -1
        self._preview_title, self._preview_status, self._preview_details = "", "", ""
        self._preview_description = ""
        self._source_gallery = False
        self.controller.completed.connect(self.completed)
        self.controller.changed.connect(self.overview)
        self.desktop._source.modelReset.connect(self.sources_changed)

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
            "galleryRun": self._gallery_run,
            "previewTitle": self._preview_title,
            "previewDescription": self._preview_description,
            "previewStatus": self._preview_status,
            "previewDetails": self._preview_details,
            "previewIndex": self._preview_index + 1,
            "previewCount": len(self._gallery.references),
            "canPrevious": self._preview_index > 0,
            "canNext": 0 <= self._preview_index < len(self._gallery.references) - 1,
        }

    def overview(self, overview) -> None:
        if self._project != overview.document.project_id:
            self._project = overview.document.project_id
            self._token = uuid4().hex
            self._gallery.replace(())
            self._offset, self._large, self._message = 0, "", ""
            self._gallery_run = ""
            self._source_gallery = False
            self.closePreview()
            self.desktop.dialogRequested.emit("closeImage")
            self.changed.emit()

    @Slot(str)
    @guarded
    def selectSource(self, identity: str) -> None:
        self.desktop._source.select(identity)
        row = self.desktop._source.selected
        self._token = uuid4().hex
        self._offset = 0
        self._gallery_run = ""
        self._source_gallery = True
        self.closePreview()
        if row.get("type") == "photo":
            self._gallery.replace(self._photo_references())
            self._message = "Select Preview to view this photo."
        else:
            self._gallery.replace(())
            self._message = (
                "Video added. Frames will be extracted during Prepare Data."
            )
        self.changed.emit()

    def _photo_references(self) -> tuple[ThumbnailReference, ...]:
        return tuple(
            ThumbnailReference(
                identity=str(source.identity),
                path=self.desktop.local_path(source.values["locator"]),
                caption=source.values["filename"],
            )
            for source in self.desktop._source.rows
            if source.values["type"] == "photo"
        )

    def sources_changed(self) -> None:
        if not self._source_gallery:
            return
        current = (
            self._gallery.references[self._preview_index]
            if 0 <= self._preview_index < len(self._gallery.references) else None
        )
        references = self._photo_references()
        if references == self._gallery.references:
            return
        self._gallery.replace(references)
        if current:
            index = next(
                (i for i, r in enumerate(references) if r.identity == current.identity), -1
            )
            if index < 0:
                self.closePreview()
                self.desktop.dialogRequested.emit("closeImage")
            elif references[index] != current:
                self.preview(index)
            else:
                self._preview_index = index
        self.changed.emit()

    @Slot(str)
    def previewSource(self, identity: str) -> None:
        self.selectSource(identity)
        index = next(
            (i for i, r in enumerate(self._gallery.references) if r.identity == identity), -1
        )
        self.preview(index)

    @Slot(str, int)
    @guarded
    def loadGallery(self, run: str, offset: int) -> None:
        if not run:
            return
        self.closePreview()
        self._source_gallery = False
        self._gallery.replace(())
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
        reference = self._gallery.references[index]
        self._preview_token = token = uuid4().hex
        self._preview_index, self._preview_title = index, reference.caption
        self._large, self._preview_details = "", ""
        self.provider.large = QImage()
        self._preview_status = "Loading preview…"
        if self._source_gallery:
            self.desktop._source.select(reference.identity)
        self._preview_description = (
            self.desktop._source.selected.get("description", "Photo preview")
            if self._source_gallery else "Photo preview"
        )

        def decode(_):
            try:
                return token, decode_thumbnail(reference.path, 1024), ""
            except Exception:
                return token, QImage(), traceback.format_exc()

        self.controller.submit("qml_image", decode)
        self.changed.emit()
        self.desktop.dialogRequested.emit("image")

    @Slot(int)
    def stepPreview(self, step: int) -> None:
        if step in {-1, 1} and self._preview_index >= 0:
            self.preview(self._preview_index + step)

    @Slot()
    def closePreview(self) -> None:
        self._preview_token = uuid4().hex
        self._preview_index = -1
        self._large, self._preview_details, self._preview_status = "", "", ""
        self.provider.large = QImage()
        self.provider.large_identity = ""
        self.changed.emit()

    def completed(self, name: str, value) -> None:
        if name == "qml_gallery" and value[0] == self._token:
            self._gallery.replace(value[1])
            self._message = f"{len(value[1])} views · offset {self._offset} · bounded previews"
            self.changed.emit()
        elif name == "qml_image" and value[0] == self._preview_token:
            self.provider.large = value[1]
            self._preview_details = value[2]
            self._preview_status = "Preview unavailable" if value[2] else "Ready"
            self._large = "" if value[2] else "image://media/large/" + uuid4().hex
            self.provider.large_identity = self._large.removeprefix("image://media/")
            self.changed.emit()
