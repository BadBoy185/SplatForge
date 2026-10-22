"""Explicit construction of application services."""

from pathlib import Path

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_features import ColmapFeatureAdapter
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.ffmpeg import FFmpegAdapter
from splatforge.adapters.ffprobe import FFprobeAdapter
from splatforge.adapters.gpu_capabilities import NvidiaSmiCapabilityAdapter
from splatforge.adapters.media_storage import LocalMediaRepository
from splatforge.adapters.pair_workspace import LocalPairWorkspace
from splatforge.adapters.performance import (
    LocalHardwareObserver,
    LocalPerformanceHistory,
    default_performance_path,
)
from splatforge.adapters.process_runner import ExecutableResolver, LocalProcessRunner
from splatforge.adapters.project_backup import LocalMigrationBackupPreparer
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.quality import PillowQualityAdapter
from splatforge.adapters.retrieval_artifacts import LocalRetrievalAdapter
from splatforge.adapters.source_files import LocalSourceFiles
from splatforge.adapters.state_schema import LocalStateSchemaUpgrader
from splatforge.adapters.view_workspace import LocalViewWorkspace
from splatforge.application.doctor import DoctorService
from splatforge.application.execution import FakeExecutionService
from splatforge.application.features import FeaturesService
from splatforge.application.matching import MatchingService
from splatforge.application.media import MediaService
from splatforge.application.pairs import PairsService
from splatforge.application.progress import PerformanceService, ProgressSupport
from splatforge.application.progress_reader import RunProgressService
from splatforge.application.projects import ProjectService
from splatforge.application.retrieval import RetrievalService
from splatforge.application.retrieval_benchmark import RetrievalBenchmarkService
from splatforge.application.sfm_profiles import SfmProfileService
from splatforge.application.views import ViewsService
from splatforge.core.builtin_methods import build_builtin_registry
from splatforge.core.progress import ExecutionHardwareProfile


def build_performance_history(path: Path | None = None) -> LocalPerformanceHistory:
    return LocalPerformanceHistory(path if path is not None else default_performance_path())


def build_performance_service(path: Path | None = None) -> PerformanceService:
    return PerformanceService(build_performance_history(path))


def build_progress_support(performance_path: Path | None = None) -> ProgressSupport:
    try:
        hardware = LocalHardwareObserver().observe()
    except Exception:
        hardware = ExecutionHardwareProfile()
    return ProgressSupport(history=build_performance_history(performance_path), hardware=hardware)


def build_run_progress_service() -> RunProgressService:
    return RunProgressService(LocalExecutionRepository(project_store=LocalProjectStore()))


def build_doctor_service(
    *,
    bundled_colmap: Path | None = None,
    bundled_model_directory: Path | None = None,
) -> DoctorService:
    resolver = ExecutableResolver()
    runner = LocalProcessRunner(resolver)
    return DoctorService(
        ColmapCapabilityAdapter(runner=runner, resolver=resolver),
        NvidiaSmiCapabilityAdapter(runner=runner, resolver=resolver),
        build_builtin_registry(),
        bundled_colmap=bundled_colmap,
        bundled_model_directory=bundled_model_directory,
    )


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


def build_views_service(
    *, ffmpeg_path: str | None = None, performance_path: Path | None = None,
) -> ViewsService:
    store = LocalProjectStore()
    execution_repository = LocalExecutionRepository(project_store=store)
    media_repository = LocalMediaRepository(project_store=store)
    return ViewsService(
        execution_repository,
        media_repository,
        LocalSourceFiles(),
        FFmpegAdapter(executable=ffmpeg_path),
        LocalViewWorkspace(),
        PillowQualityAdapter(),
        progress=build_progress_support(performance_path),
    )


def build_pairs_service(*, performance_path: Path | None = None) -> PairsService:
    return PairsService(
        LocalExecutionRepository(project_store=LocalProjectStore()), LocalPairWorkspace(),
        progress=build_progress_support(performance_path),
        retrieval_adapter=LocalRetrievalAdapter(),
    )


def build_retrieval_service(*, performance_path: Path | None = None) -> RetrievalService:
    return RetrievalService(LocalExecutionRepository(project_store=LocalProjectStore()),
                            LocalRetrievalAdapter(),
                            progress=build_progress_support(performance_path))


def build_retrieval_benchmark_service() -> RetrievalBenchmarkService:
    return RetrievalBenchmarkService(
        LocalExecutionRepository(), build_retrieval_service(), build_pairs_service(),
        build_matching_service(),
    )


def build_features_service(*, performance_path: Path | None = None) -> FeaturesService:
    return FeaturesService(
        LocalExecutionRepository(project_store=LocalProjectStore()), ColmapFeatureAdapter(),
        progress=build_progress_support(performance_path),
    )


def build_matching_service(*, performance_path: Path | None = None) -> MatchingService:
    return MatchingService(
        LocalExecutionRepository(project_store=LocalProjectStore()), ColmapMatchingAdapter(),
        progress=build_progress_support(performance_path),
    )


def build_sfm_profile_service() -> SfmProfileService:
    return SfmProfileService(ColmapFeatureAdapter(), ColmapMatchingAdapter())
