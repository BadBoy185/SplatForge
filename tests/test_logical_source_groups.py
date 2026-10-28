"""Portable group intent through the existing writer, plus actual numerical reuse."""

import json
import shutil
from uuid import UUID, uuid4

import pytest
from test_source_participation import change, payload_snapshot, registered
from test_views_execution import candidate_settings, harness, prepare

from splatforge.application.logical_source_groups import logical_groups_draft
from splatforge.application.projects import ProjectError, StaleProjectRevisionError
from splatforge.bootstrap import build_gui_facade, build_project_service
from splatforge.core.logical_source_groups import LogicalSourceGroup, LogicalSourceGroups


def edit(root, *, document=None, **kwargs):
    projects = build_project_service()
    document = document or projects.open(root)
    ids = [r.identity for r in build_gui_facade().overview(root).sources]
    draft = logical_groups_draft(document, ids, **kwargs)
    return projects.save(root, draft)


def test_create_rename_move_ungroup_delete_reopen_and_participation_independence(tmp_path):
    root, service, _, ids = registered(tmp_path)
    first, second = uuid4(), uuid4()
    original = service.list(root)
    state = (root / "state.sqlite").read_bytes()
    edit(root, action="create", group_id=first, label="Drone")
    edit(root, action="create", group_id=second, label="Interior")
    edit(root, action="assign", group_id=first, source_ids=frozenset(ids[:2]))
    change(root, {ids[0]})
    saved = edit(root, action="rename", group_id=first, label="Exterior Drone")
    assert saved.logical_source_groups.label_for(ids[0]) == "Exterior Drone"
    assert saved.source_participation.excluded_source_ids == (ids[0],)
    edit(root, action="assign", group_id=second, source_ids=frozenset({ids[0]}))
    saved = edit(root, action="assign", source_ids=frozenset({ids[1]}))
    assert saved.logical_source_groups.label_for(ids[1]) is None
    saved = edit(root, action="delete", group_id=second)
    assert not saved.logical_source_groups.source_assignments
    assert [g.group_id for g in saved.logical_source_groups.groups] == [first]
    assert service.list(root) == original
    assert (root / "state.sqlite").read_bytes() == state
    assert saved == build_project_service().open(root)


def test_relocation_relink_reimport_keep_occurrence_organization(tmp_path):
    root, service, paths, ids = registered(tmp_path)
    group = uuid4()
    edit(root, action="create", group_id=group, label="Exterior ž")
    edit(root, action="assign", group_id=group, source_ids=frozenset({ids[0]}))
    other = tmp_path / "Disk ž other project"
    shutil.copytree(root, other)
    assert (
        build_project_service().open(other).logical_source_groups.label_for(ids[0]) == "Exterior ž"
    )
    moved = tmp_path / "Relinked photo.png"
    paths[0].rename(moved)
    service.relink(root, ids[0], moved)
    saved = build_project_service().open(root)
    assert saved.logical_source_groups.label_for(ids[0]) == "Exterior ž"
    assert service.list(root).sources[0].original_filename == paths[0].name
    added = service.add(root, [moved]).added_sources[0]
    assert added.source_id != ids[0]
    assert (
        build_project_service().open(root).logical_source_groups.label_for(added.source_id) is None
    )


def test_cas_failure_unknown_references_and_future_envelope(tmp_path):
    root, _, _, ids = registered(tmp_path)
    stale = build_project_service().open(root)
    group = uuid4()
    saved = edit(root, action="create", group_id=group, label="Drone")
    with pytest.raises(StaleProjectRevisionError):
        edit(root, document=stale, action="create", label="Stale")
    before = (root / "project.json").read_bytes()
    for kwargs in [
        dict(action="assign", group_id=uuid4(), source_ids=frozenset({ids[0]})),
        dict(action="assign", group_id=group, source_ids=frozenset({uuid4()})),
        dict(action="rename", group_id=uuid4(), label="No"),
        dict(action="delete", group_id=uuid4()),
    ]:
        with pytest.raises(ProjectError):
            edit(root, **kwargs)
    assert (root / "project.json").read_bytes() == before
    intent = LogicalSourceGroups.model_validate(
        {
            **saved.logical_source_groups.model_dump(),
            "future": {"opaque": True},
            "source_assignments": {uuid4(): group, ids[0]: uuid4()},
        }
    )
    saved.logical_source_groups = intent
    saved = build_project_service().save(root, saved)
    assert build_gui_facade().overview(root).sources[0].values["logicalGroupLabel"] is None
    saved.logical_source_groups = intent.model_copy(update={"schema_version": 9})
    saved = build_project_service().save(root, saved)
    with pytest.raises(ProjectError, match="Unsupported"):
        logical_groups_draft(saved, ids, action="create", label="No")
    saved.label = "Unrelated save"
    saved = build_project_service().save(root, saved)
    assert saved.logical_source_groups.model_extra == {"future": {"opaque": True}}
    assert build_gui_facade().overview(root).participation.processing_source_ids() == set(ids)


@pytest.mark.parametrize("with_participation", [False, True])
def test_old_project_open_no_save_and_additive_save(tmp_path, with_participation):
    root, service, _, ids = registered(tmp_path)
    if with_participation:
        change(root, {ids[0]})
    path = root / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("logical_source_groups")
    if not with_participation:
        raw.pop("source_participation")  # M12b2; otherwise accepted M12b2a with exclusions.
    path.write_text(json.dumps(raw), encoding="utf-8")
    inventory_path = root / raw["inventory_reference"]
    lines = [json.loads(line) for line in inventory_path.read_text().splitlines()]
    for row in lines[1:]:
        row.pop("original_filename", None)
        row["probe"].pop("capture", None)
    inventory_path.write_text("\n".join(json.dumps(row) for row in lines) + "\n")
    before = {p: p.read_bytes() for p in (path, inventory_path, root / "state.sqlite")}
    overview = build_gui_facade().overview(root)
    assert not overview.document.logical_source_groups.groups
    assert set(overview.participation.excluded_source_ids) == (
        {ids[0]} if with_participation else set()
    )
    assert all(r.values["device"] == "Unknown device" for r in overview.sources)
    assert all(p.read_bytes() == data for p, data in before.items())
    saved = edit(root, action="create", label="User change")
    assert saved.revision == raw["revision"] + 1
    assert service.list(root).sources[0].probe.capture is None
    assert inventory_path.read_bytes() == before[inventory_path]
    assert build_gui_facade().source_details(root, ids[0])["capture"] == {}
    assert saved.source_participation == overview.document.source_participation


def test_actual_failed_atomic_save_retains_committed_groups(tmp_path):
    from splatforge.adapters.project_storage import LocalProjectStore, PersistenceFaultHooks
    from splatforge.application.projects import ProjectService
    from splatforge.core import build_builtin_registry

    root, _, _, ids = registered(tmp_path)
    document = build_project_service().open(root)
    draft = logical_groups_draft(document, ids, action="create", label="Never published")
    before = (root / "project.json").read_bytes()

    def fail(_):
        raise OSError("Synthetic before-replace fault")

    projects = ProjectService(
        LocalProjectStore(fault_hooks=PersistenceFaultHooks(before_replace=fail)),
        build_builtin_registry(),
    )
    with pytest.raises(ProjectError, match="before-replace"):
        projects.save(root, draft)
    assert (root / "project.json").read_bytes() == before


def test_logical_changes_reuse_actual_prepare_and_preserve_numerical_history(tmp_path):
    value = harness(tmp_path)
    first = prepare(value)
    historical = payload_snapshot(value.root)
    run = value.root / "runs" / str(first.run_id) / "run.json"
    frozen = run.read_bytes()
    inventory = value.media.load_current_inventory(
        value.root, build_project_service().open(value.root)
    )
    group = uuid4()
    for action in [
        dict(action="create", group_id=group, label="Drone"),
        dict(action="assign", group_id=group, source_ids=frozenset(value.source_ids)),
        dict(action="rename", group_id=group, label="Exterior Drone"),
        dict(action="delete", group_id=group),
    ]:
        edit(value.root, **action)
        reused = prepare(value)
        assert reused.cache_hits == ("candidate_views", "selected_views")
        assert reused.candidate_artifact.recipe_key == first.candidate_artifact.recipe_key
        assert run.read_bytes() == frozen
        assert all((value.root / p).read_bytes() == b for p, b in historical.items())
    assert (
        value.media.load_current_inventory(
            value.root,
            build_project_service().open(value.root),
        )
        == inventory
    )
    document = build_project_service().open(value.root)
    document.logical_source_groups = document.logical_source_groups.model_copy(
        update={"schema_version": 9},
    )
    build_project_service().save(value.root, document)
    assert prepare(value).cache_hits == ("candidate_views", "selected_views")
    assert run.read_bytes() == frozen
    change(value.root, {value.source_ids[0]})
    excluded = prepare(value)
    assert excluded.candidate_count == 1
    assert excluded.candidate_artifact.recipe_key != first.candidate_artifact.recipe_key


def test_group_serialization_is_canonical():
    a, b = UUID(int=1), UUID(int=2)
    groups = [LogicalSourceGroup(group_id=i, label=str(i)) for i in (a, b)]
    first = LogicalSourceGroups(groups=tuple(groups), source_assignments={a: b, b: a})
    second = LogicalSourceGroups(groups=tuple(reversed(groups)), source_assignments={b: a, a: b})
    assert first.model_dump_json() == second.model_dump_json()


def test_descriptive_capture_fields_are_not_prepare_recipe_inputs(tmp_path):
    from splatforge.core.capture_metadata import CaptureMetadata
    from splatforge.core.views import candidate_recipe_key

    root, service, _, _ = registered(tmp_path, count=1)
    source = service.list(root).sources[0]
    modified = source.model_copy(
        update={
            "original_filename": "Descriptive name.jpg",
            "probe": source.probe.model_copy(
                update={
                    "capture": CaptureMetadata(
                        origin="exif",
                        make="DJI",
                        model="FC220",
                        focal_length_mm=4.5,
                    )
                }
            ),
        }
    )
    kwargs = {"settings": candidate_settings(), "backend": source.probe.backend}
    assert candidate_recipe_key(sources=(source,), **kwargs) == candidate_recipe_key(
        sources=(modified,),
        **kwargs,
    )
