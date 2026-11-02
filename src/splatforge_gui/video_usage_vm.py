"""Nonvisual Trim boundary. Every edit targets the current preview UUID, never a batch."""

from fractions import Fraction
from math import isfinite

from PySide6.QtCore import Property, QObject, Signal, Slot

from splatforge.application.video_usage import video_usage_draft
from splatforge.core.video_usage import VideoInterval, VideoSource, VideoUsageError, interval
from splatforge.core.views import RationalValue
from splatforge_gui.video_filmstrip import VideoFilmstrip


class VideoUsageViewModel(QObject):
    changed = Signal()

    def __init__(self, desktop) -> None:
        super().__init__(desktop)
        self.desktop, self.controller = desktop, desktop.controller
        self._error = {}
        self._context = None
        self.filmstrip = VideoFilmstrip(desktop)
        desktop.media.changed.connect(self._refresh)
        self.controller.changed.connect(lambda _: self._refresh())
        self.controller.dirty_changed.connect(self._draft_changed)
        self.controller.busy_changed.connect(lambda _: self.changed.emit())

    def _source(self) -> VideoSource:
        row = self.desktop.media.state["previewSource"]
        if row.get("type") != "video":
            raise VideoUsageError("not_video", "Select a registered video")

        def exact(value):
            try:
                return RationalValue.from_fraction(Fraction(value)) if value is not None else None
            except (ValueError, ZeroDivisionError):
                return None

        return VideoSource(
            source_id=row["identity"],
            content_sha256=row["sha256"],
            stream_index=row["streamIndex"],
            start=exact(row.get("timelineStart")),
            playback_start=exact(row.get("playbackStart")),
            duration=exact(row.get("duration")),
        )

    def _refresh(self) -> None:
        context = (
            self.controller.generation,
            self.desktop.media.state["previewSource"].get("identity"),
        )
        if context != self._context:
            self.filmstrip.stop()
            self._context, self._error = context, {}
        self.changed.emit()

    def _draft_changed(self, dirty: bool) -> None:
        if not dirty:
            self._error = {}
        self._refresh()

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        result = {
            "sourceId": "",
            "available": False,
            "canEdit": False,
            "restricted": False,
            "intervals": [],
            "dirty": False,
            "timelineStart": None,
            "playbackStart": None,
            "duration": None,
            "error": self._error,
            "contextKey": str(self.controller.generation),
            "timeline": {},
        }
        if self.controller.overview is None:
            return result
        try:
            source = self._source()
            document = self.controller.draft or self.controller.overview.document
            result.update(
                sourceId=str(source.source_id),
                available=True,
                timelineStart=str(source.start.as_fraction()) if source.start else None,
                playbackStart=(
                    str(source.playback_start.as_fraction()) if source.playback_start else None
                ),
                duration=str(source.duration.as_fraction()) if source.duration else None,
                dirty=document.video_usage != self.controller.overview.document.video_usage,
            )
            items = document.video_usage.resolve(source)
            result.update(
                canEdit=self.desktop.state["canMutate"],
                restricted=items is not None,
                intervals=[
                    {"start": str(i.start.as_fraction()), "end": str(i.end.as_fraction())}
                    for i in (items or ())
                ],
            )
            result["timeline"] = timeline_projection(source, items)
        except VideoUsageError as exc:
            if exc.code != "not_video":
                result["error"] = {"code": exc.code, "message": str(exc)}
                # A mismatched binding can be explicitly reset, never silently reused.
                result["canEdit"] = (
                    exc.code == "source_identity_changed" and self.desktop.state["canMutate"]
                )
        return result

    def _edit(self, operation, start=None, end=None, index=-1) -> bool:
        try:
            if not self.desktop.state["canMutate"]:
                raise VideoUsageError("editing_unavailable", "Project cannot be edited now")
            source = self._source()
            document = self.controller.draft or self.controller.overview.document
            draft = video_usage_draft(
                document,
                source,
                operation,
                interval(start, end) if start is not None else None,
                index,
            )
            if draft != document:
                self.controller.edit(draft)
            self._error = {}
            self.changed.emit()
            return True
        except VideoUsageError as exc:
            self._error = {"code": exc.code, "message": str(exc)}
            self.changed.emit()
            return False

    @Slot(str, str, result=bool)
    def addInterval(self, start: str, end: str) -> bool:
        return self._edit("add", start, end)

    @Slot(int, str, str, result=bool)
    def updateInterval(self, index: int, start: str, end: str) -> bool:
        return self._edit("update", start, end, index)

    @Slot(int, result=bool)
    def removeInterval(self, index: int) -> bool:
        return self._edit("remove", index=index)

    @Slot(str, str, result=bool)
    def excludeInterval(self, start: str, end: str) -> bool:
        return self._edit("exclude", start, end)

    @Slot(result=bool)
    def clearIntervals(self) -> bool:
        return self._edit("empty")

    @Slot(result=bool)
    def resetIntervals(self) -> bool:
        return self._edit("reset")

    @Slot()
    def clearError(self) -> None:
        if self._error:
            self._error = {}
            self.changed.emit()

    @Slot(str, result=int)
    def intervalIndex(self, sourceSeconds: str) -> int:
        """Select the normalized row after an edit, including without a player origin."""
        try:
            source = self._source()
            document = self.controller.draft or self.controller.overview.document
            point = Fraction(sourceSeconds)
            for index, item in enumerate(document.video_usage.resolve(source) or ()):
                if item.start.as_fraction() <= point < item.end.as_fraction():
                    return index
        except (VideoUsageError, ValueError, ZeroDivisionError):
            pass
        return -1

    @Property(QObject, constant=True)
    def thumbnails(self) -> QObject:
        return self.filmstrip

    @Slot(float, float, int)
    def requestThumbnails(self, start: float, end: float, count: int) -> None:
        if not isfinite(start) or not isfinite(end):
            return
        state = self.state
        extent = state["timeline"]
        if not extent.get("available") or self.desktop.state["page"] != 1:
            return
        start = max(extent["startPosition"], start)
        end = min(extent["endPosition"], end)
        if end <= start:
            return
        count = max(1, min(count, 12))
        positions = [round(start + (end - start) * (i + 0.5) / count) for i in range(count)]
        row = self.desktop.media.state["previewSource"]
        self.filmstrip.request(
            state["contextKey"] + ":" + state["sourceId"],
            self.desktop.local_path(row["locator"]), row["streamIndex"], positions,
        )

    @Slot(str, result=str)
    def sourceTime(self, playerMilliseconds: str) -> str:
        try:
            value = self._source().player_time(playerMilliseconds)
            self._error = {}
            self.changed.emit()
            return str(value.as_fraction())
        except VideoUsageError as exc:
            self._error = {"code": exc.code, "message": str(exc)}
            self.changed.emit()
            return ""


    @Slot(str, result=str)
    def playerPosition(self, sourceSeconds: str) -> str:
        try:
            value = self._source().player_position(sourceSeconds)
            self._error = {}
            self.changed.emit()
            return str(value)
        except VideoUsageError as exc:
            self._error = {"code": exc.code, "message": str(exc)}
            self.changed.emit()
            return ""


def timeline_projection(source: VideoSource, items: tuple[VideoInterval, ...] | None) -> dict:
    """Read-only display/seek projection; canonical endpoints never round-trip via ms."""
    result = {"available": False, "reason": "", "ranges": []}
    if source.playback_start is None:
        result["reason"] = "Player time mapping is unavailable: the playback origin is unknown."
        return result
    if source.start is None:
        result["reason"] = "The selected video stream's start time is unknown."
        return result
    if source.duration is None:
        result["reason"] = (
            "The original clip duration is unknown. Exact interval fields remain available."
        )
        return result
    start = source.start.as_fraction()
    end = start + source.duration.as_fraction()
    try:
        result.update(
            start=str(start), end=str(end),
            startPosition=source.player_position(str(start)),
            endPosition=source.player_position(str(end)),
            ranges=[
                {"start": source.player_position(str(i.start.as_fraction())),
                 "end": source.player_position(str(i.end.as_fraction()))}
                for i in (items if items is not None else (interval(str(start), str(end)),))
            ],
        )
        # Qt/JS seeks use integer milliseconds. Never spin on collapsed sub-ms spans.
        positions = (result["startPosition"], result["endPosition"])
        if any(abs(p) > 2**53 - 1 for p in positions) or positions[1] <= positions[0]:
            raise VideoUsageError("invalid_position", "Clip extent exceeds player precision")
        result["available"] = True
        cursor = result["startPosition"]
        gaps = []
        for row in result["ranges"]:
            if row["start"] > cursor:
                gaps.append({"start": cursor, "end": row["start"]})
            cursor = row["end"]
        if cursor < result["endPosition"]:
            gaps.append({"start": cursor, "end": result["endPosition"]})
        result["gaps"] = gaps
    except VideoUsageError as exc:
        result["reason"] = str(exc)
    return result

