"""Raw Prepare form; application functions own validation and saved intent."""

from pydantic import ValidationError
from PySide6.QtCore import Property, QObject, Signal, Slot

from splatforge.application.prepare_settings import (
    PrepareRequest,
    preparation_media_context,
    preparation_request_fields,
    prepare_settings_draft,
    prepare_settings_fields,
    prepare_target_fps,
)


def request_settings_text(request: PrepareRequest, *, has_video: bool | None = None) -> str:
    """Present the frozen request without substituting current form values."""
    fields = preparation_request_fields(request)
    sharpest = fields["method"] == "sharpest_interval"
    lines = ["Sharpest per interval" if sharpest else "Uniform · Fixed FPS"]
    if has_video is False:
        lines.append("Photos only · video sampling and dHash suppression not applicable")
    else:
        lines.extend((
            f"Video: one frame every {fields['interval_seconds']} s "
            f"({request.selection.target_fps.as_fraction()} frames/s)",
            f"Candidates: {fields['candidate_fps']} frames/s",
        ))
    if fields["image_format"] == "jpeg":
        lines.append(f"JPEG · qscale {fields['jpeg_qscale']} · yuvj444p")
    else:
        lines.append(f"PNG · compression {fields['png_compression_level']}")
    if sharpest:
        lines.append(f"Analysis proxy max side: {fields['quality_max_side']} px")
        lines.append("Minimum sharpness: " + (
            str(fields["min_sharpness"]) if fields["min_sharpness_enabled"] else "Off"
        ))
        if has_video is not False:
            lines.append("Similar video frames: " + (
                f"dHash distance {fields['duplicate_hamming_threshold']}, "
                f"lookback {fields['duplicate_lookback']}"
                if fields["reject_duplicates"] else "Off"
            ))
    else:
        lines.append("Quality assessment: not run")
    return "\n".join(lines)


class PrepareSettingsViewModel(QObject):
    changed = Signal()
    editsChanged = Signal()

    def __init__(self, preparation) -> None:
        super().__init__(preparation)
        self.preparation = preparation
        self.desktop, self.controller = preparation.desktop, preparation.controller
        self._context = None
        self._fields, self._baseline = {}, {}
        self._frame_signature = self._staged_signature = ""
        self._load_error = self._save_error = ""
        self._conflict = False
        self.controller.completed.connect(self._completed)
        self.controller.error.connect(self._failed)

    @property
    def has_unsaved(self) -> bool:
        return self._fields != self._baseline or bool(self._staged_signature)

    def _document(self):
        return self.controller.draft or (
            self.controller.overview.document if self.controller.overview else None
        )

    def observe(self, *, force: bool = False) -> None:
        """Synchronize read context; never replace a dirty form on background refresh."""
        document = self._document()
        context = (self.controller.generation, self.controller.root,
                   document.project_id if document else None)
        signature = document.settings.frame_selection.model_dump_json() if document else ""
        if (force or context != self._context
                or (not self.has_unsaved and signature != self._frame_signature)):
            self._context, self._frame_signature = context, signature
            self._staged_signature = ""
            self._load_error = self._save_error = ""
            self._conflict = False
            try:
                self._fields = prepare_settings_fields(document) if document else {}
            except (ValueError, KeyError, TypeError) as exc:
                self._fields, self._load_error = {}, str(exc)
            self._baseline = dict(self._fields)
        elif self.has_unsaved and signature not in {
            self._frame_signature, self._staged_signature,
        }:
            self._conflict = True

    def _validated(self):
        document = self._document()
        context = dict(photo_count=0, video_count=0, used_video_count=0, has_video=False)
        if document is None:
            return None, context, ""
        if self._load_error:
            return None, context, self._load_error
        if self._conflict:
            return None, context, "Saved preparation settings changed. Discard and reload the form."
        try:
            context = preparation_media_context(document, self.controller.overview.sources)
            draft = prepare_settings_draft(document, self._fields, has_video=context["has_video"])
            return draft, context, ""
        except ValidationError as exc:
            labels = {
                "jpeg_qscale": "JPEG qscale", "png_compression_level": "PNG compression",
                "quality_max_side": "Analysis proxy maximum side",
                "duplicate_hamming_threshold": "dHash distance",
                "duplicate_lookback": "Recent frames",
            }
            errors = []
            for error in exc.errors(include_url=False, include_input=False):
                field = str(error["loc"][-1]) if error["loc"] else "Settings"
                errors.append(f"{labels.get(field, field)}: {error['msg']}")
            return None, context, "\n".join(errors)
        except (ValueError, KeyError, TypeError) as exc:
            return None, context, str(exc)

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        draft, context, validation_error = self._validated()
        editable = bool(self._fields and self.desktop.state["canMutate"]
                        and self.preparation._status != "running"
                        and not self.preparation._review.state["saving"])
        target = ""
        if context["has_video"]:
            try:
                target = str(prepare_target_fps(self._fields["interval_seconds"]).as_fraction())
            except (ValueError, KeyError, TypeError):
                target = ""
        return dict(
            fields=dict(self._fields), dirty=self.has_unsaved, supported=bool(self._fields),
            valid=draft is not None, error=self._save_error or validation_error,
            canEdit=editable, canSave=bool(editable and draft and self.has_unsaved),
            hasVideo=context["has_video"], photoCount=context["photo_count"],
            videoCount=context["video_count"], usedVideoCount=context["used_video_count"],
            targetFps=target,
        )

    @Slot(str, "QVariant", result=bool)
    def setField(self, key: str, value) -> bool:
        if not self.state["canEdit"] or key not in self._fields:
            return False
        if self._fields[key] != value:
            self._fields[key] = value
            self._save_error = ""
            self.editsChanged.emit()
            self.changed.emit()
        return True

    def stage_for_save(self) -> bool:
        """Only a validated whole form may replace saved preparation intent."""
        if not self.has_unsaved:
            return True
        draft, _, error = self._validated()
        if draft is None or not self.state["canEdit"]:
            self._save_error = error or "Preparation settings cannot be saved during active work."
            self.changed.emit()
            return False
        self._staged_signature = draft.settings.frame_selection.model_dump_json()
        self.controller.edit(draft)
        self._save_error = ""
        return True

    @Slot()
    def save(self) -> None:
        self.desktop.save()

    def discard(self) -> None:
        """Called after the existing project discard, retaining its normal scope."""
        self.observe(force=True)
        self.editsChanged.emit()
        self.changed.emit()

    def _completed(self, name, _value) -> None:
        if name == "save":
            self.observe(force=True)
            self.editsChanged.emit()
            self.changed.emit()

    def _failed(self, error) -> None:
        if error.stage == "save" and self.has_unsaved:
            self._save_error = "Save was not confirmed. " + error.message
            self.changed.emit()
