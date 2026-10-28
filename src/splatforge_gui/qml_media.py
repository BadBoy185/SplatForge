"""Lazy bounded image delivery. QML receives provider keys, never decoding instructions."""

import traceback
from uuid import UUID, uuid4

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from splatforge.application.desktop import ThumbnailReference
from splatforge_gui.presentation import guarded
from splatforge_gui.qml_models import PresentationModel
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
                self.request.emit(reference.identity, reference.path, self.generation)
            if role == self.StatusRole:
                if reference.identity not in self.cache:
                    return "Loading preview…"
                return (
                    "Ready" if self.cache[reference.identity] is not None else "Preview unavailable"
                )
            return (
                self.image_url(reference.identity) if self.cache.get(reference.identity) else ""
            )
        return super().data(index, role)

    def _store(self, identity: str, image, generation: int | None = None) -> bool:
        if not super()._store(identity, image, generation):
            return False
        for i, reference in enumerate(self.references):
            if reference.identity == identity:
                self.dataChanged.emit(
                    self.index(i), self.index(i), [self.ImageRole, self.StatusRole]
                )
        return True


class MediaProvider(QQuickImageProvider):
    def __init__(self, model: GalleryModel) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.model = model
        self.large = QImage()
        self.large_identity = ""
        self.source_model = None

    def requestImage(self, identity, size, requestedSize) -> QImage:
        if identity and identity == self.large_identity:
            value = self.large
        else:
            value = self.source_model.lookup(identity) if self.source_model is not None else None
            if value is None:
                value = self.model.lookup(identity)
        result = QImage(value) if value is not None else QImage()
        size.setWidth(result.width())
        size.setHeight(result.height())
        return result


class SourceBrowserModel(PresentationModel):
    """Same UUID rows/selection as List; only Grid roles request bounded thumbnails."""

    ImageRole = PresentationModel.CellRole + 1
    StatusRole = ImageRole + 1
    SectionRole = StatusRole + 1
    SelectedRole = SectionRole + 1
    recordsChanged = Signal()
    multiSelectionChanged = Signal()

    def __init__(self, columns=(), parent=None) -> None:
        super().__init__(columns, parent)
        self.thumbnails = GalleryModel(self)
        self._photo_indices = {}
        self._source_indices = {}
        self._signature = ()
        self._context = None
        self.all_rows = ()
        self.participation_filter = "Included"
        self.section_filter = ""
        self.group_labels = {}
        self.sections = []
        self._selected_ids: set[str] = set()
        self._anchor = ""
        self.thumbnails_active = True
        self.thumbnails.dataChanged.connect(self._thumbnail_changed)

    def roleNames(self) -> dict:
        return {
            **super().roleNames(), self.ImageRole: b"imageUrl", self.StatusRole: b"thumbStatus",
            self.SectionRole: b"sectionKey",
            self.SelectedRole: b"sourceSelected",
        }

    def set_context(self, context) -> None:
        if context != self._context:
            self._context = context
            self._signature = ()
            self._photo_indices.clear()
            self.thumbnails.replace(())
            self.clearSelection()
            self.participation_filter = "Included"
            self.section_filter = ""
            self.group_labels = {}

    def replace(self, rows, view=None) -> None:
        from pathlib import Path

        from PySide6.QtCore import QUrl

        rows = tuple(rows)
        signature = tuple(
            (str(r.identity), r.values.get("locator", ""))
            for r in rows if r.values["type"] == "photo"
        )
        if signature != self._signature:
            self._signature = signature
            token = uuid4().hex
            references = []
            self._photo_indices = {}
            for identity, locator in signature:
                url = QUrl(locator)
                path = Path(url.toLocalFile() if url.isLocalFile() else locator)
                self._photo_indices[identity] = len(references)
                references.append(ThumbnailReference(
                    identity=f"source/{token}/{identity}", path=path, caption=identity,
                ))
            self.thumbnails.replace(references)
        self.all_rows = rows
        self._apply_filter()

    def set_filter(self, value: str) -> None:
        if value in {"Included", "Excluded", "All"} and value != self.participation_filter:
            self.clearSelection()
            self.participation_filter = value
            self._apply_filter()

    def set_section(self, value: str) -> None:
        if value != self.section_filter and any(s["value"] == value for s in self.sections):
            self.clearSelection()
            self.section_filter = value
            self._apply_filter()

    def _apply_filter(self) -> None:
        rows = tuple(r for r in self.all_rows if (
            self.participation_filter == "All"
            or r.values.get("isIncluded", True) == (self.participation_filter == "Included")
        ))
        sections = {"group/" + k: {"label": v, "rows": []} for k, v in self.group_labels.items()}
        organized = []
        for row in rows:
            values = row.values
            label = values.get("logicalGroupLabel")
            device = values.get("device", "Unknown device")
            if label:
                key = "group/" + values["logicalGroupId"]
            elif device != "Unknown device":
                label, key = device, "device/" + device.casefold()
            elif values["type"] == "video":
                label, key = "Videos", "videos"
            else:
                label, key = "Unknown device", "unknown"
            sections.setdefault(key, {"label": label, "rows": []})["rows"].append(row)
            organized.append(row.model_copy(update={"values": {
                **values, "sectionKey": key, "sectionLabel": label,
            }}))
        options = [{"value": "", "label": f"All groups · {len(rows)} sources"}]
        ordered = sorted(sections.items(), key=lambda s: (s[1]["label"].casefold(), s[0]))
        for key, section in ordered:
            members = section["rows"]
            photos = sum(r.values["type"] == "photo" for r in members)
            videos = len(members) - photos
            included = sum(r.values.get("isIncluded", True) is True for r in members)
            excluded = sum(r.values.get("isIncluded", True) is False for r in members)
            summary = (
                f"{photos} photos · {videos} videos · {included} included · {excluded} excluded"
            )
            options.append({"value": key, "label": section["label"] + " · " + str(len(members)),
                            "name": section["label"], "summary": summary, "count": len(members)})
        self.sections = options
        if not any(s["value"] == self.section_filter for s in options):
            self.section_filter = ""
        rows = tuple(sorted(
            (r for r in organized if not self.section_filter
             or r.values["sectionKey"] == self.section_filter),
            key=lambda r: (r.values["sectionLabel"].casefold(), r.values["sectionKey"]),
        ))
        old_ids = tuple(str(r.identity) for r in self.rows)
        ids = tuple(str(r.identity) for r in rows)
        self._source_indices = {identity: i for i, identity in enumerate(ids)}
        self._selected_ids.intersection_update(self._source_indices)
        if self._selected not in self._source_indices:
            self._selected = ""
        if self._anchor not in self._source_indices:
            self._anchor = ""
        if old_ids != ids:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()
        elif rows != self.rows:
            # Update the authoritative roles in place. Both retained presentations
            # receive the same notification, including pooled Grid delegates.
            self.rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, 0),
                                      [self.ValuesRole, self.SectionRole])
        self.selectionChanged.emit()
        self.multiSelectionChanged.emit()
        self.countChanged.emit()
        self.recordsChanged.emit()

    @Property("QStringList", notify=multiSelectionChanged)
    def selectedIds(self) -> list[str]:
        return [str(r.identity) for r in self.rows if str(r.identity) in self._selected_ids]

    @Property(int, notify=multiSelectionChanged)
    def selectedCount(self) -> int:
        return len(self._selected_ids)

    @Slot()
    def clearSelection(self) -> None:
        self._selected_ids.clear()
        self._selected = self._anchor = ""
        self._notify_selection()

    @Slot()
    def selectAllVisible(self) -> None:
        self._selected_ids = set(self._source_indices)
        self._notify_selection()

    @Slot(str)
    def select(self, identity: str) -> None:
        self.selectWithModifiers(identity, 0)

    @Slot(str, int)
    def selectWithModifiers(self, identity: str, modifiers: int) -> None:
        if identity not in self._source_indices:
            self.clearSelection()
            return
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier.value)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier.value)
        if shift and self._anchor in self._source_indices:
            start, end = sorted((
                self._source_indices[self._anchor], self._source_indices[identity],
            ))
            interval = {str(r.identity) for r in self.rows[start:end + 1]}
            self._selected_ids = self._selected_ids | interval if control else interval
        elif control:
            self._selected_ids.symmetric_difference_update({identity})
            self._anchor = identity
        else:
            self._selected_ids = {identity}
            self._anchor = identity
        self._selected = identity
        self._notify_selection()

    def focus_source(self, identity: str) -> None:
        """Inspection cursor is independent of the browser's batch selection."""
        self._selected = identity if identity in self._source_indices else ""
        self.selectionChanged.emit()

    def action_ids(self, identity: str) -> frozenset[UUID]:
        ids = self._selected_ids if identity in self._selected_ids else {identity}
        return frozenset(UUID(value) for value in ids if value in self._source_indices)

    def _notify_selection(self) -> None:
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0),
                                  [self.SelectedRole])
        self.selectionChanged.emit()
        self.multiSelectionChanged.emit()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == self.SelectedRole:
            return index.isValid() and str(self.rows[index.row()].identity) in self._selected_ids
        if role == self.SectionRole:
            return self.rows[index.row()].values["sectionKey"] if index.isValid() else ""
        if role in {self.ImageRole, self.StatusRole}:
            if not self.thumbnails_active:
                return ""
            if not index.isValid() or not 0 <= index.row() < len(self.rows):
                return ""
            row = self.rows[index.row()]
            photo_index = self._photo_indices.get(str(row.identity))
            if row.values["type"] != "photo":
                photo_index = None
            if photo_index is None:
                return "" if role == self.ImageRole else "Video"
            return self.thumbnails.data(
                self.thumbnails.index(photo_index),
                GalleryModel.ImageRole if role == self.ImageRole else GalleryModel.StatusRole,
            )
        return super().data(index, role)

    def set_thumbnails_active(self, active: bool) -> None:
        if active == self.thumbnails_active:
            return
        self.thumbnails_active = active
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0),
                                  [self.ImageRole, self.StatusRole])

    def _thumbnail_changed(self, first, last, roles) -> None:
        for i in range(first.row(), last.row() + 1):
            identity = self.thumbnails.references[i].caption
            source_index = self._source_indices.get(identity)
            if source_index is not None:
                index = self.index(source_index, 0)
                self.dataChanged.emit(index, index, [self.ImageRole, self.StatusRole])


class MediaViewModel(QObject):
    changed = Signal()

    def __init__(self, desktop) -> None:
        super().__init__(desktop)
        self.desktop, self.controller = desktop, desktop.controller
        self._gallery = GalleryModel(self)
        self.provider = MediaProvider(self._gallery)
        self.provider.source_model = desktop._source.thumbnails
        self._token, self._offset, self._large, self._message = "", 0, "", ""
        self._gallery_run = ""
        self._project = None
        self._preview_token = ""
        self._preview_index = -1
        self._preview_title, self._preview_status, self._preview_details = "", "", ""
        self._preview_description = ""
        self._source_gallery = False
        self._review_mutation = None
        self._details_token = ""
        self._source_details = {"fields": [], "technical": ""}
        self.controller.completed.connect(self.completed)
        self.controller.changed.connect(self.overview)
        self.controller.busy_changed.connect(lambda _: self.changed.emit())
        self.desktop._source.recordsChanged.connect(self.sources_changed)
        self.controller.error.connect(lambda _: self._clear_review_mutation())

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
            "sourceDetails": self._source_details,
            "galleryRun": self._gallery_run,
            "previewTitle": self._preview_title,
            "previewDescription": self._preview_description,
            "previewStatus": self._preview_status,
            "previewDetails": self._preview_details,
            "previewIndex": self._preview_index + 1,
            "previewCount": len(self._gallery.references),
            "canPrevious": self._preview_index > 0,
            "canNext": 0 <= self._preview_index < len(self._gallery.references) - 1,
            "previewSource": self._preview_source(),
            "canChangeParticipation": self._source_gallery and self._preview_index >= 0
            and self._review_mutation is None
            and self.desktop.state["canMutate"] and self.desktop.state["participationSupported"],
        }

    def overview(self, overview) -> None:
        context = (overview.document.project_id, self.controller.generation, self.controller.root)
        if self._project != context:
            self._details_token = ""
            self._source_details = {"fields": [], "technical": ""}
            self._project = context
            self._token = uuid4().hex
            self._gallery.replace(())
            self._offset, self._large, self._message = 0, "", ""
            self._gallery_run = ""
            self._source_gallery = False
            self._review_mutation = None
            self.closePreview()
            self.desktop.dialogRequested.emit("closeImage")
            self.changed.emit()

    @Slot(str)
    @Slot(str, int)
    @guarded
    def selectSource(self, identity: str, modifiers: int = 0) -> None:
        self._details_token = ""
        self._source_details = {"fields": [], "technical": ""}
        self.desktop._source.selectWithModifiers(identity, modifiers)
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
                "Frames from included videos will be extracted during Prepare Data."
            )
        self.changed.emit()

    @Slot(str)
    def activateSource(self, identity: str) -> None:
        from PySide6.QtGui import QGuiApplication

        # Qt Controls owns pointer/keyboard delivery. Read the modifiers of that
        # event instead of placing an input surface over nested action buttons.
        self.selectSource(identity, QGuiApplication.keyboardModifiers().value)

    @Slot(str)
    def focusSource(self, identity: str) -> None:
        self.desktop._source.focus_source(identity)
        self.changed.emit()

    def _preview_source(self) -> dict:
        if not self._source_gallery or self._preview_index < 0:
            return {}
        if self._preview_index >= len(self._gallery.references):
            return {}
        identity = self._gallery.references[self._preview_index].identity
        i = self.desktop._source._source_indices.get(identity)
        return dict(self.desktop._source.rows[i].values) if i is not None else {}

    def _clear_review_mutation(self) -> None:
        self._review_mutation = None

    @Slot()
    def togglePreviewParticipation(self) -> None:
        if not self.state["canChangeParticipation"]:
            return
        references = self._gallery.references
        current = references[self._preview_index].identity
        included = self._preview_source().get("isIncluded", True) is False
        # Capture UUID neighbors before the filter changes. Never increment a
        # post-mutation index (B's old index now denotes C).
        candidates = ([r.identity for r in references[self._preview_index + 1:]]
                      + [r.identity for r in reversed(references[:self._preview_index])])
        self._review_mutation = current, included, candidates
        self.desktop._set_participation(frozenset({UUID(current)}), included)

    @Slot()
    @guarded
    def inspectSource(self) -> None:
        source = self.desktop._source.selectedId
        if not source or self.controller.mutating:
            return
        self._details_token = token = uuid4().hex
        self._source_details = {"fields": [], "technical": "Loading saved evidence…"}
        root = self.controller.root
        self.controller.submit(
            "qml_source_details", lambda f: (token, source, f.source_details(root, UUID(source))),
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
        mutation = self._review_mutation
        if mutation:
            identity, included, candidates = mutation
            row = next((r for r in self.desktop._source.all_rows
                        if str(r.identity) == identity), None)
            if row and row.values.get("isIncluded", True) == included:
                self._review_mutation = None
                self._gallery.replace(references)
                indices = {r.identity: i for i, r in enumerate(references)}
                target = next((indices[c] for c in candidates if c in indices), None)
                if target is None:
                    self.closePreview()
                    self.desktop.dialogRequested.emit("closeImage")
                else:
                    self.preview(target)
                return
        if references == self._gallery.references:
            self.changed.emit()
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
        self._source_gallery = True
        self._gallery_run = ""
        self._gallery.replace(self._photo_references())
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
            self.desktop._source.focus_source(reference.identity)
            self._details_token = ""
            self._source_details = {"fields": [], "technical": ""}
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
        self._review_mutation = None
        self._preview_token = uuid4().hex
        self._preview_index = -1
        self._preview_title = self._preview_description = ""
        self._large, self._preview_details, self._preview_status = "", "", ""
        self.provider.large = QImage()
        self.provider.large_identity = ""
        self.changed.emit()

    def completed(self, name: str, value) -> None:
        if (name == "qml_source_details" and value[0] == self._details_token
                and value[1] == self.desktop._source.selectedId):
            from splatforge_gui.presentation import capture_details

            self._source_details = capture_details(value[2])
            self.changed.emit()
        elif name == "qml_gallery" and value[0] == self._token:
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
