import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError

from splatforge.application.projects import ProjectError, ProjectService
from splatforge.bootstrap import build_project_service
from splatforge.core import build_builtin_registry, recommended_flat_video_profile
from splatforge.core.project import ProjectDocument


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}


def test_create_save_reopen_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "P\u0159\u00edli\u0161 \u017elu\u0165ou\u010dk\u00fd project"
    service = build_project_service()
    created = service.create(root, "Prvn\u00ed projekt")
    assert {p.name for p in root.iterdir()} == {
        "project.json",
        "project.lock",
        "state.sqlite",
    }
    assert created.revision == 0
    assert created.inventory_reference is None
    assert service.open(root) == created
    with closing(sqlite3.connect(root / "state.sqlite")) as connection:
        assert {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        } == {
            "metadata",
            "runs",
            "attempts",
            "artifacts",
            "run_outputs",
            "source_verifications",
        }
        assert dict(connection.execute("SELECT key, value FROM metadata")) == {
            "state_schema_version": "4",
            "project_id": str(created.project_id),
        }
    state_before = (root / "state.sqlite").read_bytes()
    monkeypatch.chdir(tmp_path.parent)
    created.label = "Updated"
    saved = service.save(root, created)
    assert saved.updated_at >= created.updated_at
    assert saved.created_at == created.created_at
    assert saved.revision == 1
    assert service.open(root) == saved
    assert json.loads(service.show(root)) == saved.model_dump(mode="json")
    assert (root / "state.sqlite").read_bytes() == state_before
    assert {p.name for p in root.iterdir()} == {
        "project.json",
        "project.lock",
        "state.sqlite",
    }


def test_complete_prototype_conversion(tmp_path: Path) -> None:
    config = recommended_flat_video_profile()
    config.frame_selection.method_id = "frame_selection.fixed_fps"
    config.frame_selection.target_fps = 7.5
    config.frame_selection.max_frames = None
    config.frame_selection.reject_blur = False
    config.frame_selection.reject_duplicates = False
    config.sfm.feature_extractor_id = "feature_extraction.sift"
    config.sfm.pair_selector_id = "pair_selection.exhaustive"
    config.sfm.feature_matcher_id = "feature_matching.lightglue_sift"
    config.sfm.mapper_id = "mapping.colmap_incremental"
    config.training.trainer_id = "training.gsplat"
    config.training.preset = "custom-prototype-value"
    before = config.model_dump()
    service = build_project_service()
    project = service.create(tmp_path, "Custom", config)
    settings = service.open(tmp_path).settings
    assert settings.frame_selection.settings == {
        "target_fps": 7.5,
        "max_frames": None,
        "reject_blur": False,
        "reject_duplicates": False,
    }
    assert settings.frame_selection.method_id == config.frame_selection.method_id
    assert settings.feature_extraction.method_id == config.sfm.feature_extractor_id
    assert settings.pair_selection.method_id == config.sfm.pair_selector_id
    assert settings.feature_matching.method_id == config.sfm.feature_matcher_id
    assert settings.mapping.method_id == config.sfm.mapper_id
    assert settings.training.method_id == config.training.trainer_id
    assert settings.training.settings == {"preset": config.training.preset}
    assert project.preset_provenance is None
    assert config.model_dump() == before


@pytest.mark.parametrize(
    "method_id,version",
    [
        ("future.mapper", 1),
        ("mapping.colmap_global", 99),
        ("future.mapper", 99),
        ("mapping.colmap_global", 1),
    ],
)
def test_opaque_envelope_round_trip(
    tmp_path: Path, method_id: str, version: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = build_project_service()
    service.create(tmp_path, "Opaque")
    path = tmp_path / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    envelope = {
        "method_id": method_id,
        "settings_schema_version": version,
        "settings": {"unknown": [None, True, 3, 1.25, "\u017d", {"nested": False}]},
        "future_extension": {"method_version": "vNext", "data": [1, None]},
        "another_extension": "preserve me",
    }
    raw["settings"]["mapping"] = envelope
    raw["settings"]["frame_selection"]["settings"]["target_fps"] = 19.25
    raw["preset_provenance"]["name"] = "unavailable-old-preset"
    path.write_text(json.dumps(raw), encoding="utf-8")

    def forbidden_defaults() -> None:
        raise AssertionError("Opening/saving must not resolve presets")

    monkeypatch.setattr(
        "splatforge.application.projects.recommended_flat_video_profile", forbidden_defaults
    )
    opened = service.open(tmp_path)
    service.save(tmp_path, opened)
    reopened = service.open(tmp_path)
    assert reopened.settings.mapping.model_dump(mode="json") == envelope
    assert reopened.settings.frame_selection.settings["target_fps"] == 19.25
    assert reopened.preset_provenance.name == "unavailable-old-preset"
    assert reopened.settings.model_dump(mode="json") == raw["settings"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("location", ["settings", "extra"])
def test_non_finite_opaque_value_is_refused_without_rewrite(
    tmp_path: Path, location: str, value: float
) -> None:
    service = build_project_service()
    service.create(tmp_path, "Non-finite")
    path = tmp_path / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    envelope = raw["settings"]["mapping"]
    if location == "settings":
        envelope["settings"]["nested"] = [value]
    else:
        envelope["future_extension"] = {"nested": value}
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = snapshot(tmp_path)

    with pytest.raises(ProjectError, match="finite number"):
        service.open(tmp_path)

    assert snapshot(tmp_path) == before


def test_existing_empty_destination_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "empty destination"
    root.mkdir()

    created = build_project_service().create(root, "Existing empty directory")

    assert created.label == "Existing empty directory"
    assert {path.name for path in root.iterdir()} == {
        "project.json",
        "project.lock",
        "state.sqlite",
    }


@pytest.mark.parametrize("existing", ["file", "directory", "hidden"])
def test_nonempty_destination_refused_without_changes(tmp_path: Path, existing: str) -> None:
    root = tmp_path / "destination"
    root.mkdir()
    if existing == "directory":
        (root / "empty-child").mkdir()
    else:
        (root / (".hidden" if existing == "hidden" else "original.jpg")).write_bytes(b"original")
    before = snapshot(root)
    with pytest.raises(ProjectError, match="missing or empty"):
        build_project_service().create(root, "Refused")
    assert snapshot(root) == before
    assert len(list(root.iterdir())) == 1


def test_file_destination_refused(tmp_path: Path) -> None:
    path = tmp_path / "original.jpg"
    path.write_bytes(b"original")
    with pytest.raises(ProjectError, match="missing or empty"):
        build_project_service().create(path, "Refused")
    assert path.read_bytes() == b"original"


@pytest.mark.parametrize(
    ("version_field", "version"),
    [
        ("project_format_version", 0),
        ("project_format_version", 2),
        ("config_schema_version", 0),
        ("config_schema_version", 2),
        ("state_schema_version", 0),
        ("state_schema_version", 5),
    ],
)
def test_unsupported_versions_do_not_rewrite(
    tmp_path: Path, version_field: str, version: int
) -> None:
    service = build_project_service()
    original = service.create(tmp_path, "Version")
    if version_field == "state_schema_version":
        with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection, connection:
            connection.execute(
                "UPDATE metadata SET value=? WHERE key=?", (str(version), version_field)
            )
    else:
        path = tmp_path / "project.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        target = raw["settings"] if version_field == "config_schema_version" else raw
        target[version_field] = version
        path.write_text(json.dumps(raw), encoding="utf-8")
    before = snapshot(tmp_path)
    for operation in (
        lambda: service.open(tmp_path),
        lambda: service.save(tmp_path, original),
        lambda: service.show(tmp_path),
    ):
        with pytest.raises(ProjectError, match="Unsupported"):
            operation()
        assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "reference",
    [
        "/sources/a.jsonl",
        "C:/sources/a.jsonl",
        "C:sources/a.jsonl",
        "../a.jsonl",
        "sources/../a.jsonl",
        "//server/share/a.jsonl",
        "sources\\a.jsonl",
        "sources//a.jsonl",
        "sources/./a.jsonl",
    ],
)
def test_rejects_invalid_owned_reference(tmp_path: Path, reference: str) -> None:
    service = build_project_service()
    project = service.create(tmp_path, "Paths")
    before = snapshot(tmp_path)
    project.inventory_reference = reference
    with pytest.raises(ValidationError):
        service.save(tmp_path, project)
    assert snapshot(tmp_path) == before


def test_owned_reference_and_project_are_relocatable(tmp_path: Path) -> None:
    service = build_project_service()
    root = tmp_path / "original root"
    project = service.create(root, "Move")
    project.inventory_reference = "sources/inventory.jsonl"
    service.save(root, project)
    moved = tmp_path / "moved \u017d root"
    shutil.copytree(root, moved)
    reopened = service.open(moved)
    assert reopened.project_id == project.project_id
    assert reopened.inventory_reference == "sources/inventory.jsonl"
    assert not (moved / "sources").exists()
    service.save(moved, reopened)


def test_state_identity_and_missing_state_are_not_repaired(tmp_path: Path) -> None:
    service = build_project_service()
    service.create(tmp_path, "Identity")
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection, connection:
        connection.execute("UPDATE metadata SET value='other' WHERE key='project_id'")
    before = snapshot(tmp_path)
    with pytest.raises(ProjectError, match="identities differ"):
        service.open(tmp_path)
    assert snapshot(tmp_path) == before
    (tmp_path / "state.sqlite").unlink()
    with pytest.raises(ProjectError):
        service.open(tmp_path)
    assert not (tmp_path / "state.sqlite").exists()


def test_cannot_save_another_project(tmp_path: Path) -> None:
    service = build_project_service()
    first = tmp_path / "first"
    second = tmp_path / "second"
    service.create(first, "First")
    other = service.create(second, "Second")
    before = snapshot(first)
    with pytest.raises(ProjectError, match="different project"):
        service.save(first, other)
    assert snapshot(first) == before


def test_invalid_role_rejected_before_creation(tmp_path: Path) -> None:
    config = recommended_flat_video_profile()
    config.sfm.mapper_id = "training.none"
    root = tmp_path / "not-created"
    with pytest.raises(ValueError, match="expected mapping"):
        build_project_service().create(root, "Invalid", config)
    assert not root.exists()


def test_application_works_with_injected_store() -> None:
    class MemoryStore:
        document: ProjectDocument | None = None

        def create(self, root: Path, document: ProjectDocument) -> None:
            self.document = document.model_copy(deep=True)

        def load(self, root: Path) -> ProjectDocument:
            assert self.document is not None
            return self.document.model_copy(deep=True)

        def save(
            self, root: Path, document: ProjectDocument, *, expected_revision: int
        ) -> None:
            assert self.document is not None
            assert self.document.revision == expected_revision
            assert document.revision == expected_revision + 1
            self.document = document.model_copy(deep=True)

    service = ProjectService(MemoryStore(), build_builtin_registry())
    root = Path("no-filesystem-required")
    project = service.create(root, "Memory")
    project.label = "Edited"
    saved = service.save(root, project)
    assert service.open(root) == saved
    assert json.loads(service.show(root))["label"] == "Edited"


@pytest.mark.parametrize("invalid", ["outer_field", "owned_path", "malformed_json", "invalid_utf8"])
def test_invalid_document_is_refused_without_rewrite(tmp_path: Path, invalid: str) -> None:
    service = build_project_service()
    service.create(tmp_path, "Invalid")
    path = tmp_path / "project.json"
    if invalid == "invalid_utf8":
        path.write_bytes(b"\xff")
    elif invalid == "malformed_json":
        path.write_text("{", encoding="utf-8")
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if invalid == "outer_field":
            raw["unrecognized_outer_field"] = "must not silently disappear"
        else:
            raw["inventory_reference"] = "../outside.jsonl"
        path.write_text(json.dumps(raw), encoding="utf-8")
    before = snapshot(tmp_path)
    with pytest.raises(ProjectError):
        service.open(tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("timestamp_field", ["created_at", "updated_at"])
def test_non_utc_timestamp_is_refused_without_rewrite(
    tmp_path: Path, timestamp_field: str
) -> None:
    service = build_project_service()
    service.create(tmp_path, "Non-UTC timestamp")
    path = tmp_path / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[timestamp_field] = "2026-10-20T12:00:00+02:00"
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = snapshot(tmp_path)

    with pytest.raises(ProjectError, match="must use UTC"):
        service.open(tmp_path)

    assert snapshot(tmp_path) == before


def test_original_outside_project_is_untouched(tmp_path: Path) -> None:
    source = tmp_path / "original.jpg"
    source.write_bytes(b"tiny synthetic source")
    before = source.read_bytes()
    root = tmp_path / "project"
    service = build_project_service()
    project = service.create(root, "Originals")
    service.save(root, project)
    service.open(root)
    assert source.read_bytes() == before
    assert {p.name for p in root.iterdir()} == {
        "project.json",
        "project.lock",
        "state.sqlite",
    }


@pytest.mark.parametrize(
    "section,field,value",
    [
        (None, "schema_version", 99),
        ("frame_selection", "target_fps", -1),
    ],
)
def test_mutated_invalid_prototype_is_not_persisted(
    tmp_path: Path, section: str | None, field: str, value: int
) -> None:
    config = recommended_flat_video_profile()
    target = config if section is None else getattr(config, section)
    setattr(target, field, value)
    root = tmp_path / "not-created"
    with pytest.raises(ValidationError):
        build_project_service().create(root, "Invalid prototype", config)
    assert not root.exists()
