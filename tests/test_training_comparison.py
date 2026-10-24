from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from splatforge.application.training_benchmark import compare_training
from splatforge.core.execution import TrainingRuntime
from splatforge.core.training import TrainingLimits, TrainingMetrics, TrainingSettings
from splatforge.core.training_benchmark import baseline_split, candidate_recipes


def test_comparison_scopes_reads_and_preserves_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    class Repository:
        reading = False

        @contextmanager
        def validation_evidence_operation(self):
            self.reading = True
            try:
                yield
            finally:
                self.reading = False

        def lineage_handle(self, root, artifact, role):
            assert root.is_absolute() and self.reading and role == "checkpoint"
            return artifact

        def load_training(self, root, checkpoint):
            assert self.reading
            return SimpleNamespace(native=SimpleNamespace(size=123))

    class Service:
        repository = Repository()
        calls = []

        def handoff(self, root, run):
            assert root.is_absolute()
            return [{"dataset_digest": "a" * 64}]

        def run(self, root, run, runtime, settings, limits):
            self.calls.append(settings.strategy.strategy)
            if settings.strategy.strategy == "mcmc":
                raise ValueError("controlled MCMC failure")
            return SimpleNamespace(
                status="succeeded",
                scene_set=True,
                jobs=[SimpleNamespace(run_id=UUID(int=len(self.calls)), artifact="checkpoint")],
            )

        def inspect(self, root, run):
            assert self.repository.reading
            return None, SimpleNamespace(
                semantic_digest="b" * 64,
                gaussian_count=12,
                ply_size=2048,
                metrics=TrainingMetrics(),
                recipe_key="c" * 64,
                backend=SimpleNamespace(numerical_identity="d" * 64),
            )

    service = Service()
    base = TrainingSettings(
        max_steps=10,
        split=baseline_split(tuple(UUID(int=i) for i in range(8)), count=1),
    )
    result = compare_training(
        service,
        Path("relative project"),
        UUID(int=42),
        TrainingRuntime(python="python.exe"),
        candidate_recipes(base),
        TrainingLimits(),
    )
    assert service.calls == ["default", "default", "mcmc"]
    assert [row.status for row in result.candidates] == ["succeeded", "succeeded", "failed"]
    assert result.candidates[0].checkpoint_size == 123
    assert result.candidates[2].error == "controlled MCMC failure"
    assert result.recommendation == "none; candidate evidence only"
    assert not service.repository.reading


def test_comparison_preserves_cancelled_receipt_even_with_completed_scenes(tmp_path):
    class Service:
        calls = 0

        def handoff(self, root, run):
            return [{"dataset_digest": "a" * 64}]

        def run(self, *args):
            self.calls += 1
            return SimpleNamespace(status="cancelled", scene_set=True)

        def inspect(self, *args):
            raise AssertionError("Cancelled orchestration cannot become successful evidence")

    service = Service()
    base = TrainingSettings(
        max_steps=10,
        split=baseline_split(tuple(UUID(int=i) for i in range(8)), count=1),
    )
    result = compare_training(
        service, tmp_path, UUID(int=42), TrainingRuntime(python="python.exe"),
        candidate_recipes(base), TrainingLimits(),
    )
    assert service.calls == 1
    assert [row.status for row in result.candidates] == ["cancelled"]
    assert result.candidates[0].scene_digest is None
