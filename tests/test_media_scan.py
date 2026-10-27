"""Read-only discovery contracts, using tiny files and no processing backends."""

import os
from pathlib import Path

import pytest

from splatforge.adapters.media_scanner import LocalMediaScanner
from splatforge.application.media import CallbackCancellation, MediaOperationCancelled
from splatforge.application.media_scan import ScanLimits


def populate(root: Path) -> None:
    for name in ("a.JPG", "nested/z.MOV", "nested/deep/b.png", "notes.txt", "cloud.ply"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def test_nested_classification_determinism_and_overlapping_candidates(tmp_path):
    populate(tmp_path)
    scanner = LocalMediaScanner()
    first = scanner.scan((tmp_path, tmp_path / "a.JPG", tmp_path / "nested"))
    second = scanner.scan((tmp_path / "nested", tmp_path / "a.JPG", tmp_path))
    assert first == second
    assert len(first.supported) == 3
    assert first.ignored == 2 and first.directories == 3
    assert [e.media_type for e in first.entries] == ["photo", None, "photo", "video", None]
    assert len(set(first.supported)) == 3
    assert [str(e.path) for e in first.entries] == sorted(
        (str(e.path) for e in first.entries), key=lambda p: (p.casefold(), p)
    )


def test_empty_unsupported_and_missing_directory(tmp_path):
    scanner = LocalMediaScanner()
    assert not scanner.scan((tmp_path,)).entries
    (tmp_path / "cloud.ply").touch()
    result = scanner.scan((tmp_path,))
    assert not result.supported and result.ignored == 1
    result = scanner.scan((tmp_path / "missing",))
    assert not result.supported and "Could not read" in result.entries[0].reason


def test_scan_cancellation_checkpoints(tmp_path):
    populate(tmp_path)
    checks = []

    def cancel():
        checks.append(1)
        return len(checks) >= 5

    with pytest.raises(MediaOperationCancelled):
        LocalMediaScanner().scan((tmp_path,), cancellation=CallbackCancellation(cancel))
    assert len(checks) == 5


@pytest.mark.parametrize("limits,reason", [
    (ScanLimits(max_entries=3), "entries"),
    (ScanLimits(max_directories=1), "directories"),
    (ScanLimits(max_depth=0), "depth"),
])
def test_scan_limits_are_explicit_and_repeatable(tmp_path, limits, reason):
    populate(tmp_path)
    result = LocalMediaScanner().scan((tmp_path,), limits=limits)
    assert result.stopped == reason
    assert result.scanned <= limits.max_entries
    assert result.directories <= limits.max_directories
    assert LocalMediaScanner().scan((tmp_path,), limits=limits) == result


def test_flat_directory_does_not_collect_unbounded_or_arbitrary_prefix(tmp_path, monkeypatch):
    from splatforge.adapters import media_scanner

    for i in range(50):
        (tmp_path / f"{i}.png").touch()
    original, reads = os.scandir, []

    class Iterator:
        def __enter__(self):
            self.it = original(tmp_path)
            return self

        def __exit__(self, *args):
            self.it.close()

        def __iter__(self):
            for entry in self.it:
                reads.append(entry.name)
                yield entry

    monkeypatch.setattr(media_scanner.os, "scandir", lambda _: Iterator())
    result = LocalMediaScanner().scan((tmp_path,), limits=ScanLimits(max_entries=5))
    assert result.stopped == "entries" and result.scanned == 5
    assert len(reads) <= 5 and not result.supported


def test_time_limit(tmp_path, monkeypatch):
    from splatforge.adapters import media_scanner

    times = iter([0, 31])
    monkeypatch.setattr(media_scanner, "monotonic", lambda: next(times))
    assert LocalMediaScanner().scan((tmp_path,)).stopped == "time"


def test_scan_skips_symlink_loop(tmp_path):
    populate(tmp_path)
    link = tmp_path / "nested" / "cycle"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    result = LocalMediaScanner().scan((tmp_path,))
    assert len(result.supported) == 3 and result.directories == 3
    assert next(e for e in result.entries if e.path == link).reason.startswith("Link")


def test_scan_skips_reparse_directory_without_enumerating(tmp_path, monkeypatch):
    original = Path.lstat

    class Reparse:
        st_mode = 0o040755
        st_file_attributes = 0x400

    monkeypatch.setattr(Path, "lstat", lambda p: Reparse() if p == tmp_path else original(p))
    result = LocalMediaScanner().scan((tmp_path,))
    assert result.directories == 0 and result.ignored == 1
    assert "reparse" in result.entries[0].reason


def test_unreadable_directory_is_reported(tmp_path, monkeypatch):
    from splatforge.adapters import media_scanner

    def denied(path):
        raise PermissionError("synthetic access denied")

    monkeypatch.setattr(media_scanner.os, "scandir", denied)
    result = LocalMediaScanner().scan((tmp_path,))
    assert result.ignored == 1 and not result.supported
    assert "access denied" in result.entries[0].reason
