"""Qt-free desktop read/facade contracts over tiny ordinary application publications."""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from training_helpers import FakeTrainer, prepared_training_project, write_ply

from splatforge.adapters.desktop_preview import gaussian_centers, sample_indices
from splatforge.adapters.desktop_reader import LocalDesktopReader
from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.application.training import TrainingService
from splatforge.bootstrap import build_gui_facade
from splatforge.core.execution import TrainingRuntime
from splatforge.core.training import TrainingSettings


@pytest.fixture(scope="module")
def publications(tmp_path_factory):
    root, dataset_run = prepared_training_project(tmp_path_factory.mktemp("desktop-publications"))
    service = TrainingService(LocalExecutionRepository(), FakeTrainer())
    settings = TrainingSettings(max_steps=10, checkpoint_every=5)
    runtime = TrainingRuntime(python=sys.executable)
    first = service.run(root, dataset_run, runtime, settings, stop_after_step=5)
    final = service.run(root, dataset_run, runtime, settings, resume_run=first.jobs[0].run_id)
    return root, dataset_run, service, settings, runtime, first, final


def test_index_and_authoritative_workflow_cli_parity(publications):
    root, _, _, _, _, _, _ = publications
    overview = build_gui_facade().overview(root)
    assert overview.sources
    assert {r.values["status"] for r in overview.index.runs} == {"succeeded"}
    workflow = {item.name: item.status for item in overview.workflow}
    for name in (
        "sources",
        "views",
        "geometry",
        "reconstruction",
        "validation",
        "selection",
        "dataset",
        "training",
        "scene",
    ):
        assert workflow[name] == "completed", (name, overview.workflow)


def test_advanced_mapper_v2_preserves_current_contract(tmp_path):
    from splatforge.application.desktop_workflow import (
        ReconstructionRequest,
        reconstruction_request,
    )
    from splatforge.bootstrap import build_project_service
    from splatforge.core.reconstruction import GlobalAcceleratedSettings

    document = build_project_service().create(tmp_path / "Advanced", "Global v2")
    advanced = GlobalAcceleratedSettings()
    document.settings.mapping.settings = advanced.model_dump(mode="json")
    request = reconstruction_request(document)
    assert request.mapper == advanced
    assert ReconstructionRequest.model_validate_json(request.model_dump_json()).mapper == advanced


@pytest.mark.parametrize("version", [1, 2, 3])
def test_legacy_project_read_model_does_not_upgrade_or_rewrite(tmp_path, version):
    from splatforge.bootstrap import build_project_service

    root = tmp_path / "Legacy"
    build_project_service().create(root, "Legacy intent")
    with closing(sqlite3.connect(root / "state.sqlite")) as db, db:
        db.execute("UPDATE metadata SET value=? WHERE key='state_schema_version'", (str(version),))
        db.execute("DROP TABLE source_verifications")
        if version == 2:
            db.execute("ALTER TABLE attempts DROP COLUMN failure_category")
            db.execute("ALTER TABLE attempts DROP COLUMN teardown_state")
        if version == 1:
            for table in ("run_outputs", "artifacts", "attempts", "runs"):
                db.execute(f"DROP TABLE {table}")
    original = (root / "project.json").read_bytes(), (root / "state.sqlite").read_bytes()
    facade = build_gui_facade()
    overview = facade.overview(root)
    assert overview.document.label == "Legacy intent"
    assert overview.index.state_version == version
    assert not facade.progress(root)
    assert original == ((root / "project.json").read_bytes(), (root / "state.sqlite").read_bytes())


def test_reconstruction_dataset_gaussian_inspection_is_bounded_and_owned(publications):
    root = publications[0]
    reader = LocalDesktopReader()
    index = reader.index(root)
    for kind in (
        "mapping.reconstruction_set",
        "dataset.prepared_component",
        "training.gaussian_scene",
    ):
        row = next(a for a in index.artifacts if a.values["artifact_type"] == kind)
        preview = reader.inspect(root, row.identity)
        assert preview.directory.is_relative_to(root)
        assert preview.semantic_digest == row.values["semantic_digest"]
        assert 0 < len(preview.points) <= 20000
        assert len(preview.cameras) <= 2000
        assert preview.metadata["payload_bytes"] > 0
        if kind == "dataset.prepared_component":
            document = preview.metadata["documents"]["dataset.json"]
            assert len(preview.cameras) == len(document["views"])
        if kind.endswith("gaussian_scene"):
            assert "not final Gaussian rasterization" in preview.label


def test_training_resume_preflight_reuses_exact_m11_compatibility(publications):
    root, dataset, service, settings, runtime, first, _ = publications
    checkpoint = first.jobs[0].run_id
    result = service.check_resume(root, dataset, checkpoint, runtime, settings)
    assert result["compatible"] and result["step"] == 5
    changed = TrainingSettings(max_steps=11, checkpoint_every=5)
    result = service.check_resume(root, dataset, checkpoint, runtime, changed)
    assert not result["compatible"] and "incompatible_checkpoint" in result["reason"]


def test_point_sampling_reads_only_bounded_ply_centers(tmp_path, monkeypatch):
    from splatforge.adapters.gaussian_ply import properties

    path = tmp_path / "tiny.ply"
    rows = []
    for i in range(1000):
        row = [0.0] * len(properties(3))
        row[0], row[-4] = float(i), 1.0
        rows.append(row)
    write_ply(path, rows=rows)
    original = Path.open
    reads = []

    class Reader:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def read(self, count=-1):
            reads.append(count)
            return self.wrapped.read(count)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    monkeypatch.setattr(
        Path, "open", lambda self, *args, **kwargs: Reader(original(self, *args, **kwargs))
    )
    points = gaussian_centers(path, limit=7)
    assert len(points) == 7
    assert [p[0] for p in points] == [float(i) for i in sorted(sample_indices(1000, 7))]
    assert reads == [12] * 7
    assert len(sample_indices(10000000, 20000)) == 20000


def test_reconstruct_composes_existing_services_and_never_selects_largest(tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4

    from splatforge.application.desktop_workflow import reconstruction_request, run_reconstruction
    from splatforge.bootstrap import build_project_service

    request = reconstruction_request(
        build_project_service().create(tmp_path / "project", "Compose")
    )
    calls = []

    def result(name):
        calls.append(name)
        return SimpleNamespace(
            status="succeeded",
            run_id=uuid4(),
            report=SimpleNamespace(model_dump=lambda **kwargs: {"status": "warn"}),
        )

    class Service:
        def prepare(self, *args, **kwargs):
            return result("views")

        def build(self, *args, **kwargs):
            return result("pairs")

        def extract(self, *args, **kwargs):
            return result("features")

        def match(self, *args, **kwargs):
            return result("matches")

        def verify(self, *args, **kwargs):
            return result("verification")

        def run(self, *args, **kwargs):
            return result("mapping")

        def validate(self, *args, **kwargs):
            return result("validation")

    class Facade:
        def service(self, name):
            assert name not in {"profiles", "selection"}
            return Service()

    run_reconstruction(
        Facade(),
        tmp_path,
        request,
        None,
        None,
        lambda: None,
        resolution=SimpleNamespace(choice=request.features),
    )
    assert calls == [
        "views",
        "pairs",
        "features",
        "matches",
        "verification",
        "mapping",
        "validation",
    ]
