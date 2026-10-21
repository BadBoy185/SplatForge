"""Explicit construction of application services."""

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.ffprobe import FFprobeAdapter
from splatforge.adapters.media_storage import LocalMediaRepository
from splatforge.adapters.project_backup import LocalMigrationBackupPreparer
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.source_files import LocalSourceFiles
from splatforge.adapters.state_schema import LocalStateSchemaUpgrader
from splatforge.application.execution import FakeExecutionService
from splatforge.application.media import MediaService
from splatforge.application.projects import ProjectService
from splatforge.core.builtin_methods import build_builtin_registry


def build_project_service() -> ProjectService:
    store = LocalProjectStore()
    backup_preparer = LocalMigrationBackupPreparer(store=store)
    upgrader = LocalStateSchemaUpgrader(
        store=store,
        backup_preparer=backup_preparer,
    )
    return ProjectService(store, build_builtin_registry(), upgrader)


def build_execution_service() -> FakeExecutionService:
    store = LocalProjectStore()
    repository = LocalExecutionRepository(project_store=store)
    return FakeExecutionService(repository, LocalFakeStages())


def build_media_service(*, ffprobe_path: str | None = None) -> MediaService:
    store = LocalProjectStore()
    repository = LocalMediaRepository(project_store=store)
    return MediaService(
        repository,
        LocalSourceFiles(),
        FFprobeAdapter(executable=ffprobe_path),
    )
