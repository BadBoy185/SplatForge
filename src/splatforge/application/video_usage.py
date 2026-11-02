"""Build video usage drafts; persistence uses the ordinary project Save/CAS path."""

from typing import Literal

from splatforge.core.project import ProjectDocument
from splatforge.core.video_usage import (
    VideoInterval,
    VideoSource,
    VideoUsageEntry,
    VideoUsageError,
    VideoUsageIntent,
    edit_intervals,
)


def video_usage_draft(
    document: ProjectDocument,
    source: VideoSource,
    operation: Literal["add", "update", "remove", "exclude", "reset", "empty"],
    value: VideoInterval | None = None,
    index: int = -1,
) -> ProjectDocument:
    if document.video_usage.schema_version != 1:
        raise VideoUsageError("unsupported_video_usage_version", "Unsupported video usage version")
    # Reset is an explicit removal of stale intent, including identity-mismatch intent.
    current = None if operation == "reset" else document.video_usage.resolve(source)
    updated = edit_intervals(current, source, operation, value, index)
    entries = [e for e in document.video_usage.entries if e.source_id != source.source_id]
    if updated is not None:
        entries.append(
            VideoUsageEntry(
                source_id=source.source_id,
                content_sha256=source.content_sha256,
                stream_index=source.stream_index,
                intervals=updated,
            )
        )
    intent = VideoUsageIntent.model_validate(
        {
            **document.video_usage.model_dump(mode="json"),
            "entries": [
                e.model_dump(mode="json") for e in sorted(entries, key=lambda e: str(e.source_id))
            ],
        }
    )
    return ProjectDocument.model_validate(
        {**document.model_dump(mode="json"), "video_usage": intent.model_dump(mode="json")}
    )
