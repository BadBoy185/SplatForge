"""Single-process project use cases. Concurrency guarantees arrive in M1a2."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from splatforge.core.models import PipelineConfig
from splatforge.core.presets import recommended_flat_video_profile
from splatforge.core.project import PresetProvenance, ProjectDocument, settings_from_pipeline
from splatforge.core.registry import MethodRegistry


class ProjectError(ValueError):
    """A project cannot be created, read or saved as requested."""


class ProjectStore(Protocol):
    def create(self, root: Path, document: ProjectDocument) -> None: ...

    def load(self, root: Path) -> ProjectDocument: ...

    def save(self, root: Path, document: ProjectDocument) -> None: ...


class ProjectService:
    def __init__(self, store: ProjectStore, registry: MethodRegistry) -> None:
        self._store = store
        self._registry = registry

    def create(
        self, root: Path, label: str, config: PipelineConfig | None = None
    ) -> ProjectDocument:
        provenance = None
        if config is None:
            config = recommended_flat_video_profile()
            provenance = PresetProvenance(name="recommended_flat_video_profile", version=1)
        # Prototype models are mutable; validate their current values before conversion.
        config = PipelineConfig.model_validate(config.model_dump())
        self._registry.validate_pipeline(config)
        now = datetime.now(UTC)
        document = ProjectDocument(
            project_format_version=1,
            project_id=uuid4(),
            revision=0,
            label=label,
            created_at=now,
            updated_at=now,
            inventory_reference=None,
            preset_provenance=provenance,
            settings=settings_from_pipeline(config),
        )
        self._store.create(root, document)
        return document

    def open(self, root: Path) -> ProjectDocument:
        return self._store.load(root)

    def save(self, root: Path, document: ProjectDocument) -> ProjectDocument:
        # M1a1 preserves revision without incrementing or comparing it.
        saved = ProjectDocument.model_validate(
            {**document.model_dump(mode="json"), "updated_at": datetime.now(UTC)}
        )
        self._store.save(root, saved)
        return saved

    def show(self, root: Path) -> str:
        return self.open(root).model_dump_json(indent=2)
