"""Durable video usage semantics and exact time, without Qt or external tools."""

from fractions import Fraction
from uuid import uuid4

import pytest
from pydantic import ValidationError

from splatforge.application.video_usage import video_usage_draft
from splatforge.bootstrap import build_project_service
from splatforge.core.project import ProjectDocument
from splatforge.core.video_usage import (
    VideoSource,
    VideoUsageError,
    VideoUsageIntent,
    edit_intervals,
    interval,
    normalize,
)
from splatforge.core.views import RationalValue


def source(start="0", duration="90"):
    return VideoSource(
        source_id=uuid4(),
        content_sha256="a" * 64,
        stream_index=0,
        start=RationalValue.from_fraction(Fraction(start)) if start else None,
        playback_start=RationalValue.from_fraction(Fraction(start)) if start else None,
        duration=RationalValue.from_fraction(Fraction(duration)) if duration else None,
    )


def test_absent_empty_reset_and_atomic_save_readback(tmp_path):
    service = build_project_service()
    root = tmp_path / "interval project"
    document = service.create(root, "Intervals")
    old = document.model_dump(mode="json")
    old.pop("video_usage")
    old = ProjectDocument.model_validate(old)
    path = root / "project.json"
    path.write_text(old.model_dump_json(exclude={"video_usage"}), encoding="utf-8")
    original_bytes = path.read_bytes()
    assert service.open(root).video_usage.entries == ()
    assert path.read_bytes() == original_bytes
    video = source()
    assert old.video_usage.resolve(video) is None
    edited = video_usage_draft(old, video, "add", interval("10", "25"))
    edited = video_usage_draft(edited, video, "add", interval("40", "65"))
    assert service.open(root).video_usage.resolve(video) is None
    saved = service.save(root, edited)
    assert saved.revision == old.revision + 1
    assert service.open(root).video_usage == edited.video_usage
    with pytest.raises(ValueError):
        service.save(root, edited)  # ordinary stale-save protection
    empty = video_usage_draft(saved, video, "empty")
    saved = service.save(root, empty)
    assert service.open(root).video_usage.resolve(video) == ()
    reset = video_usage_draft(saved, video, "reset")
    service.save(root, reset)
    assert service.open(root).video_usage.resolve(video) is None


def test_canonical_union_update_remove_and_half_open_subtraction():
    video = source()
    items = normalize(
        (interval("40", "65"), interval("10", "20"), interval("20", "25"), interval("15", "22"))
    )
    assert items == (interval("10", "25"), interval("40", "65"))
    assert edit_intervals(items, video, "exclude", interval("20", "50")) == (
        interval("10", "20"),
        interval("50", "65"),
    )
    assert edit_intervals(None, video, "exclude", interval("10", "90")) == (interval("0", "10"),)
    assert edit_intervals((), video, "exclude", interval("10", "20")) == ()
    assert edit_intervals(items, video, "update", interval("25", "40"), 0) == (
        interval("25", "65"),
    )
    assert edit_intervals((interval("0", "90"),), video, "remove", index=0) == ()


@pytest.mark.parametrize(
    "start,end", [("1", "1"), ("2", "1"), ("nan", "2"), ("0", "inf"), ("1/0", "5"), ("bad", "2")]
)
def test_invalid_values_do_not_make_intervals(start, end):
    with pytest.raises(VideoUsageError, match="finite") as caught:
        interval(start, end)
    assert caught.value.code == "invalid_interval"


def test_bounds_exact_player_conversion_unknown_metadata_and_identity(tmp_path):
    video = source("7/3", "90")
    assert video.player_time("10001").as_fraction() == Fraction(37003, 3000)
    assert source("-2").player_time("0").as_fraction() == -2
    assert video.player_position("37003/3000") == 10001
    assert source().player_position("1/2000") == 1
    assert source().player_position("1/3000") == 0
    offset = video.model_copy(update={"playback_start": RationalValue(numerator=1, denominator=1)})
    assert offset.player_time("1000").as_fraction() == 2
    for text in ("1.2", "-1", "nan"):
        with pytest.raises(VideoUsageError) as caught:
            video.player_time(text)
        assert caught.value.code == "invalid_position"
    with pytest.raises(VideoUsageError) as caught:
        video.validate_bounds((interval("0", "10"),))
    assert caught.value.code == "out_of_bounds"
    video.validate_bounds((interval("7/3", "277/3"),))
    unknown = source(None, None)
    assert unknown.start is None and unknown.duration is None
    assert edit_intervals(None, unknown, "add", interval("100", "200"))
    with pytest.raises(VideoUsageError) as caught:
        unknown.player_time("0")
    assert caught.value.code == "timeline_origin_unknown"
    with pytest.raises(VideoUsageError) as caught:
        edit_intervals(None, source("0", None), "exclude", interval("1", "2"))
    assert caught.value.code == "duration_unknown"
    service = build_project_service()
    document = service.create(tmp_path / "identity", "Identity")
    draft = video_usage_draft(document, video, "add", interval("10", "25"))
    changed = video.model_copy(update={"content_sha256": "b" * 64})
    with pytest.raises(VideoUsageError) as caught:
        draft.video_usage.resolve(changed)
    assert caught.value.code == "source_identity_changed"
    assert video_usage_draft(draft, changed, "reset").video_usage.resolve(changed) is None
    assert draft.video_usage.resolve(video.model_copy()) == (interval("10", "25"),)


def test_future_envelope_extensions_preserved_but_processing_refused(tmp_path):
    service = build_project_service()
    root = tmp_path / "future"
    document = service.create(root, "Future")
    data = document.model_dump(mode="json")
    data["video_usage"] = {"schema_version": 2, "future": {"value": [1, 2]}}
    saved = service.save(root, ProjectDocument.model_validate(data))
    assert service.open(root).video_usage.model_dump() == saved.video_usage.model_dump()
    with pytest.raises(VideoUsageError) as caught:
        saved.video_usage.resolve(source())
    assert caught.value.code == "unsupported_video_usage_version"
    with pytest.raises(ValidationError):
        VideoUsageIntent.model_validate(
            {
                "entries": [
                    {
                        "source_id": str(uuid4()),
                        "content_sha256": "a" * 64,
                        "stream_index": 0,
                        "intervals": [
                            interval("5", "10").model_dump(),
                            interval("0", "5").model_dump(),
                        ],
                    }
                ]
            }
        )
