"""Folder organization joins inventory publication without changing processing IDs."""

import shutil
from threading import Event

import pytest
from test_media import media_service

from splatforge.application.logical_source_groups import logical_groups_draft
from splatforge.application.media import CallbackCancellation, MediaOperationCancelled
from splatforge.bootstrap import build_project_service


def fixture(tmp_path):
    root, folder = tmp_path / "Project", tmp_path / "Originals ž"
    build_project_service().create(root, "Folders")
    names = ["a.jpg", "Drone/d1.jpg", "Drone/d2.jpg", "Phone/p1.jpg", "Videos/v1.mp4",
             "Drone/Flight 1/a.jpg", "Drone/Flight 2/a.jpg", "Other/Flight 1/a.jpg"]
    paths = [folder / n for n in names]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tiny synthetic source")
    return root, folder, paths, media_service(root)


def test_folder_groups_publish_once_reopen_relink_collision_and_metadata(tmp_path):
    root, folder, paths, (service, _, _) = fixture(tmp_path)
    projects = build_project_service()
    initial = projects.open(root)
    result = service.add(root, paths, folder_root=folder)
    saved = projects.open(root)
    assert saved.revision == initial.revision + 1
    ids = [s.source_id for s in result.added_sources]
    assert saved.logical_source_groups.label_for(ids[0]) is None
    assert [saved.logical_source_groups.label_for(s) for s in ids[1:]] == [
        "Drone", "Drone", "Phone", "Videos", "Drone / Flight 1", "Drone / Flight 2",
        "Other / Flight 1",
    ]
    sources = service.list(root).sources
    assert all(s.probe.capture is None for s in sources)
    assert all(s.source_group_id != s.camera_group_id for s in sources)
    second = service.add(root, paths[1:2], folder_root=folder).added_sources[0]
    saved = projects.open(root)
    assert saved.logical_source_groups.label_for(second.source_id) == "Drone (2)"
    assert saved.logical_source_groups.label_for(ids[1]) == "Drone"
    copied = tmp_path / "Relocated project"
    shutil.copytree(root, copied)
    assert projects.open(copied).logical_source_groups == saved.logical_source_groups
    moved = tmp_path / "Relinked.jpg"
    paths[1].rename(moved)
    service.relink(root, ids[1], moved)
    assert projects.open(root).logical_source_groups == saved.logical_source_groups


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_folder_import_publishes_no_groups_or_assignments(tmp_path, cancel):
    root, folder, paths, (service, _, probe) = fixture(tmp_path)
    before = (root / "project.json").read_bytes()
    stop = Event()
    original = probe.probe

    def fail(path, media_type, *, cancellation=None):
        if path == paths[2]:
            if cancel:
                stop.set()
            else:
                raise OSError("Cannot read media")
        return original(path, media_type, cancellation=cancellation)

    probe.probe = fail
    with pytest.raises(MediaOperationCancelled if cancel else OSError):
        service.add(root, paths, folder_root=folder, cancellation=CallbackCancellation(stop.is_set))
    assert (root / "project.json").read_bytes() == before
    assert service.list(root) is None


def test_create_and_assign_is_one_validated_draft(tmp_path):
    root, _, paths, (service, _, _) = fixture(tmp_path)
    ids = frozenset(s.source_id for s in service.add(root, paths).added_sources)
    projects = build_project_service()
    before = projects.open(root)
    draft = logical_groups_draft(before, ids, action="create", label="Batch", source_ids=ids)
    saved = projects.save(root, draft)
    assert saved.revision == before.revision + 1
    assert len(saved.logical_source_groups.groups) == 1
    assert set(saved.logical_source_groups.source_assignments) == ids
