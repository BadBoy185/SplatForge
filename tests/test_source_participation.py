"""Persisted participation, CAS and actual Prepare/cache/history consumption."""

import json
import shutil
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from test_media import media_service
from test_views_execution import (
    candidate_settings,
    harness,
    limits,
    prepare,
)

from splatforge.application.projects import ProjectError, StaleProjectRevisionError
from splatforge.application.source_participation import participation_draft
from splatforge.bootstrap import build_gui_facade, build_project_service
from splatforge.core.media import VerificationPolicyId
from splatforge.core.source_participation import (
    SourceParticipationIntent,
    resolve_effective_sources,
)
from splatforge.core.views import FixedFpsSettings, parse_fps


def change(root, ids, *, included=False, document=None):
    projects = build_project_service()
    document = document or projects.open(root)
    inventory = media_service(root)[0].list(root, document=document)
    draft = participation_draft(
        document, (s.source_id for s in inventory.sources), set(ids), included=included,
    )
    return projects.save(root, draft)


def registered(tmp_path, count=4):
    root = tmp_path / "Projekt ž participation"
    build_project_service().create(root, "Portable")
    service = media_service(root)[0]
    paths = [tmp_path / f"source {i}.png" for i in range(count)]
    for path in paths:
        path.write_bytes(b"tiny synthetic source")
    added = service.add(root, paths)
    return root, service, paths, tuple(s.source_id for s in added.added_sources)


def test_old_document_default_no_eager_rewrite_and_new_source_defaults(tmp_path):
    root, service, paths, ids = registered(tmp_path)
    path = root / "project.json"
    raw = json.loads(path.read_text())
    raw.pop("source_participation")
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    overview = build_gui_facade().overview(root)
    assert overview.participation.included_source_ids == tuple(sorted(ids, key=str))
    assert path.read_bytes() == before
    change(root, {ids[1], ids[3]})
    added = service.add(root, [paths[0]])
    new_id = added.added_sources[0].source_id
    assert new_id not in ids
    overview = build_gui_facade().overview(root)
    assert set(overview.participation.included_source_ids) == {ids[0], ids[2], new_id}
    assert set(overview.participation.excluded_source_ids) == {ids[1], ids[3]}


def test_batch_exclude_restore_reopen_portable_and_no_inventory_or_original_writes(tmp_path):
    root, service, paths, ids = registered(tmp_path)
    document = build_project_service().open(root)
    inventory = (root / document.inventory_reference).read_bytes()
    state = (root / "state.sqlite").read_bytes()
    originals = [p.read_bytes() for p in paths]
    saved = change(root, {ids[3], ids[1]})
    assert saved.revision == document.revision + 1  # One atomic batch save.
    reopened = build_project_service().open(root)
    assert reopened.source_participation.excluded_source_ids == tuple(
        sorted((ids[1], ids[3]), key=str),
    )
    assert reopened.inventory_reference == document.inventory_reference
    assert (root / document.inventory_reference).read_bytes() == inventory
    assert (root / "state.sqlite").read_bytes() == state
    assert [p.read_bytes() for p in paths] == originals
    copied = tmp_path / "Moved project space ž"
    shutil.copytree(root, copied)
    assert (
        build_project_service().open(copied).source_participation == reopened.source_participation
    )
    change(root, {ids[1], ids[3]}, included=True)
    assert not build_project_service().open(root).source_participation.excluded_source_ids
    assert len(service.list(root).sources) == 4


def test_relink_preserves_exclusion_and_duplicate_occurrence_is_included(tmp_path):
    root, service, paths, ids = registered(tmp_path, 1)
    change(root, ids)
    original = service.list(root).sources[0]
    moved = tmp_path / "Relink ž space.png"
    paths[0].rename(moved)
    service.relink(root, ids[0], moved)
    relinked = service.list(root).sources[0]
    assert (relinked.source_id, relinked.source_revision) == (ids[0], original.source_revision)
    assert build_gui_facade().overview(root).participation.excluded_source_ids == ids
    new = service.add(root, [moved]).added_sources[0].source_id
    resolved = build_gui_facade().overview(root).participation
    assert resolved.included_source_ids == (new,)
    assert resolved.excluded_source_ids == ids


def test_cas_prevents_participation_and_unrelated_stale_overwrites(tmp_path):
    root, _, _, ids = registered(tmp_path)
    stale = build_project_service().open(root)
    saved = change(root, {ids[0]})
    with pytest.raises(StaleProjectRevisionError):
        change(root, {ids[1]}, document=stale)
    stale.label = "Stale label"
    with pytest.raises(StaleProjectRevisionError):
        build_project_service().save(root, stale)
    assert build_project_service().open(root) == saved


def test_unknown_extensions_stale_ids_and_future_versions_survive_unrelated_save(tmp_path):
    root, _, _, ids = registered(tmp_path)
    projects = build_project_service()
    document = projects.open(root)
    stale_id = uuid4()
    intent = SourceParticipationIntent(
        excluded_source_ids=(stale_id, ids[0]), future_extension={"nested": [None, "ž", 2]},
    )
    document.source_participation = intent
    document.settings.mapping.__pydantic_extra__["opaque"] = {"next": [1, None]}
    projects.save(root, document)
    overview = build_gui_facade().overview(root)
    assert overview.participation.unknown_excluded_source_ids == (stale_id,)
    assert overview.participation.diagnostics[0].code == "unknown_excluded_sources"
    change(root, {ids[1]})
    document = projects.open(root)
    assert stale_id in document.source_participation.excluded_source_ids
    assert document.source_participation.future_extension == {"nested": [None, "ž", 2]}
    assert document.settings.mapping.opaque == {"next": [1, None]}
    document.source_participation = intent.model_copy(update={"schema_version": 99})
    projects.save(root, document)
    overview = build_gui_facade().overview(root)
    assert not overview.participation.supported
    assert len(overview.sources) == 4
    with pytest.raises(ValueError, match="Unsupported"):
        overview.participation.processing_source_ids()
    with pytest.raises(ProjectError, match="Unsupported"):
        change(root, {ids[1]})
    document = projects.open(root)
    document.label = "Unrelated edit"
    projects.save(root, document)
    assert projects.open(root).source_participation == document.source_participation


def test_canonical_uuid_validation_and_unknown_mutation_is_atomic(tmp_path):
    a, b = UUID(int=1), UUID(int=2)
    first = SourceParticipationIntent(excluded_source_ids=(b, a, b))
    second = SourceParticipationIntent(excluded_source_ids=(a, b))
    assert first.model_dump_json() == second.model_dump_json()
    with pytest.raises(ValidationError):
        SourceParticipationIntent(excluded_source_ids=("bad-id",))
    root, _, _, ids = registered(tmp_path)
    before = (root / "project.json").read_bytes()
    with pytest.raises(ProjectError, match="Unknown source"):
        change(root, {ids[0], uuid4()})
    assert (root / "project.json").read_bytes() == before


def test_actual_atomic_save_failure_preserves_last_committed_intent(tmp_path):
    from splatforge.adapters.project_storage import LocalProjectStore, PersistenceFaultHooks
    from splatforge.application.projects import ProjectService
    from splatforge.core import build_builtin_registry

    root, _, _, ids = registered(tmp_path)
    document = build_project_service().open(root)
    before = (root / "project.json").read_bytes()

    def fail(_):
        raise OSError("Synthetic failure before atomic replacement")

    store = LocalProjectStore(fault_hooks=PersistenceFaultHooks(before_replace=fail))
    service = ProjectService(store, build_builtin_registry())
    draft = participation_draft(document, ids, {ids[0]}, included=False)
    with pytest.raises(ProjectError, match="before atomic replacement"):
        service.save(root, draft)
    assert (root / "project.json").read_bytes() == before
    assert not build_project_service().open(root).source_participation.excluded_source_ids


def test_cli_reads_participation_and_explicit_prepare_uses_same_contract(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from splatforge.cli.app import app

    value = harness(tmp_path)
    change(value.root, {value.source_ids[0]})
    runner = CliRunner()
    shown = runner.invoke(app, ["project", "show", str(value.root)])
    assert shown.exit_code == 0
    assert json.loads(shown.output)["source_participation"]["excluded_source_ids"] == [
        str(value.source_ids[0]),
    ]
    monkeypatch.setattr("splatforge.cli.app.build_views_service", lambda **_: value.service)
    args = [
        "views", "prepare", str(value.root), "--target-fps", "1", "--candidate-fps", "2",
        "--image-format", "png",  # The injected materializer emits PNG fixtures.
    ]
    refused = runner.invoke(app, [*args, "--source-id", str(value.source_ids[0])])
    assert refused.exit_code == 1 and "Restore excluded" in refused.output
    allowed = runner.invoke(app, [*args, "--source-id", str(value.source_ids[1])])
    assert allowed.exit_code == 0, allowed.output
    assert json.loads(allowed.output)["candidate_count"] == 1


def payload_snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes() for p in (root / "artifacts").rglob("*")
            if p.is_file()}


def test_prepare_consumes_effective_set_identity_restore_cache_and_history(tmp_path):
    value = harness(tmp_path)
    first = prepare(value)
    assert first.status == "succeeded"
    history = payload_snapshot(value.root)
    runs = {str(p.relative_to(value.root)): p.read_bytes()
            for p in (value.root / "runs").rglob("run.json")}
    excluded = value.source_ids[0]  # Video: exclusion must prevent frame extraction.
    saved = change(value.root, {excluded})
    assert payload_snapshot(value.root) == history
    assert all((value.root / p).read_bytes() == data for p, data in runs.items())
    second = prepare(value)
    assert second.status == "succeeded" and second.candidate_count == 1
    assert first.candidate_artifact.recipe_key != second.candidate_artifact.recipe_key
    snapshot = json.loads((value.root / "runs" / str(second.run_id) / "run.json").read_text())
    assert {s["source_id"] for s in snapshot["route"]["sources"]} == {str(value.source_ids[1])}
    saved.label = "Label is not a numerical input"
    build_project_service().save(value.root, saved)
    third = prepare(value)
    assert third.cache_hits == ("candidate_views", "selected_views")
    assert third.candidate_artifact.recipe_key == second.candidate_artifact.recipe_key
    change(value.root, {excluded}, included=True)
    restored = prepare(value)
    assert restored.cache_hits == ("candidate_views", "selected_views")
    assert restored.candidate_artifact.recipe_key == first.candidate_artifact.recipe_key
    assert all((value.root / p).read_bytes() == data for p, data in history.items())


def test_explicit_prepare_subset_validates_excluded_and_empty_before_run_creation(tmp_path):
    value = harness(tmp_path)
    change(value.root, {value.source_ids[0]})
    kwargs = dict(candidate_settings=candidate_settings(), selection_settings=FixedFpsSettings(
        target_fps=parse_fps("1")), resource_limits=limits(),
        verification_policy=VerificationPolicyId.BALANCED_LOCAL)
    with pytest.raises(ProjectError, match="Restore excluded"):
        value.service.prepare(value.root, source_ids={value.source_ids[0]}, **kwargs)
    result = value.service.prepare(value.root, source_ids={value.source_ids[1]}, **kwargs)
    assert result.status == "succeeded" and result.candidate_count == 1
    change(value.root, set(value.source_ids))
    before = set((value.root / "runs").iterdir())
    with pytest.raises(ProjectError, match="No included sources"):
        prepare(value)
    assert set((value.root / "runs").iterdir()) == before
    resolved = resolve_effective_sources(value.source_ids, SourceParticipationIntent())
    with pytest.raises(ValueError, match="Unknown source"):
        resolved.processing_source_ids({uuid4()})
