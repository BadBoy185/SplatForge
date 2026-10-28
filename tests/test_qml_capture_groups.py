"""Actual Qt grouping controls, saved Details and bounded List/Grid browsing."""

import json
import os
from threading import Event
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtQml import QQmlExpression  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_capture_metadata import capture_photo  # noqa: E402
from test_media import FakeProbe  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_source_participation import idle  # noqa: E402
from test_qml_sources import inject_media  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.adapters.capture_metadata import read_photo_capture  # noqa: E402
from splatforge.application.desktop import IndexRow  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge.core.capture_metadata import CaptureMetadata  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


class CaptureProbe(FakeProbe):
    def probe(self, path, media_type, **kwargs):
        evidence = (
            read_photo_capture(path)
            if media_type == "photo"
            else CaptureMetadata(origin="container_tags")
        )
        return (
            super()
            .probe(path, media_type, **kwargs)
            .model_copy(
                update={
                    "capture": evidence,
                    "duration": "123.5" if media_type == "video" else None,
                }
            )
        )


def populated(vm, tmp_path):
    root = open_project(vm, tmp_path)
    inject_media(vm, root, CaptureProbe())
    paths = [capture_photo(tmp_path / f"DJI_{i}.jpg") for i in range(2)]
    paths += [
        capture_photo(tmp_path / "phone.jpg", make="Apple", model="iPhone 16 Pro"),
        capture_photo(tmp_path / "DJI_unknown.jpg", make=None, model=None),
    ]
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"synthetic video")
    vm.addFiles([str(p) for p in [*paths, video]])
    idle(vm)
    return root, paths, tuple(vm.sources.rows)


def choose(engine, control, value):
    expression = QQmlExpression(
        engine.rootContext(),
        control,
        "currentIndex = indexOfValue(" + json.dumps(value) + "); activated(currentIndex)",
    )
    expression.evaluate()
    assert not expression.hasError(), expression.error().toString()


def test_identical_labels_do_not_merge_distinct_group_sections(app):
    from splatforge_gui.qml_media import SourceBrowserModel

    model = SourceBrowserModel()
    a, b = str(uuid4()), str(uuid4())
    model.group_labels = {a: "Drone", b: "Drone"}
    model.replace(
        tuple(
            IndexRow(
                identity=uuid4(),
                values={
                    "filename": "source.mp4",
                    "type": "video",
                    "logicalGroupId": identity,
                    "logicalGroupLabel": "Drone",
                },
            )
            for identity in (a, b)
        )
    )
    assert {model.data(model.index(i, 0), model.SectionRole) for i in range(2)} == {
        "group/" + a,
        "group/" + b,
    }


@pytest.mark.parametrize("view", ["List", "Grid"])
def test_device_sections_scope_both_browsers_and_saved_details(desktop, tmp_path, view):
    root, paths, rows = populated(desktop, tmp_path)
    desktop.setSourceView(view)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        names = [s.get("name") for s in desktop.state["sourceSections"]]
        assert names == [None, "Apple iPhone 16 Pro", "DJI FC220", "Unknown device", "Videos"]
        picker = visual_item(window.contentItem(), "sourceSectionPicker")
        choose(engine, picker, "device/dji fc220")
        assert desktop.sources.count == 2
        assert all(r.values["device"] == "DJI FC220" for r in desktop.sources.rows)
        row = desktop.sources.rows[0]
        prefix = "source-" if view == "List" else "tile-"
        until(lambda: visual_item(window.contentItem(), prefix + str(row.identity)) is not None)
        item = visual_item(window.contentItem(), prefix + str(row.identity))
        item.forceActiveFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(window, Qt.Key.Key_Space)
        assert desktop.sources.selectedId == str(row.identity)
        for p in paths:
            p.unlink()  # Human Details must read persisted metadata while originals are offline.
        click(window, "sourceDetails")
        until(lambda: len(desktop.media.state["sourceDetails"]["fields"]) > 0)
        assert (
            visual_item(window.contentItem(), "sourceHumanDevice").property("text") == "DJI FC220"
        )
        assert visual_item(window.contentItem(), "sourceHumanGroup").property("text") == "Ungrouped"
        fields = desktop.media.state["sourceDetails"]["fields"]
        assert {r["label"]: r["value"] for r in fields}["Exposure"] == "1/800 s"
        assert not visual_item(window.contentItem(), "sourceTechnicalDetails").property("expanded")
        click(window, "closeSourceDetails")
        choose(engine, picker, "unknown")
        desktop.media.selectSource(str(desktop.sources.rows[0].identity))
        click(window, "sourceDetails")
        idle(desktop)
        assert (
            visual_item(window.contentItem(), "sourceHumanDevice").property("text")
            == "Unknown device"
        )
        click(window, "closeSourceDetails")
        choose(engine, picker, "videos")
        desktop.media.selectSource(str(desktop.sources.rows[0].identity))
        click(window, "sourceDetails")
        idle(desktop)
        assert visual_item(window.contentItem(), "sourceHumanType").property("text") == "Video"
        assert "02:03" in visual_item(window.contentItem(), "sourceHumanDuration").property("text")
        assert (
            "Capture evidence: container_tags" in desktop.media.state["sourceDetails"]["technical"]
        )
        assert not engine.load_errors
    finally:
        dispose(engine)


def test_actual_group_controls_create_rename_assign_ungroup_delete(desktop, tmp_path):
    root, _, rows = populated(desktop, tmp_path)
    desktop.media.selectSource(str(rows[0].identity))
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "sourceGroups")
        name = visual_item(window.contentItem(), "newSourceGroupName")
        name.setProperty("text", "Exterior Drone")
        click(window, "createSourceGroup")
        idle(desktop)
        group = desktop.state["logicalGroups"][1]["value"]
        destination = visual_item(window.contentItem(), "sourceGroupDestination")
        choose(engine, destination, group)
        click(window, "moveSourceToGroup")
        idle(desktop)
        assert desktop.sources.selected["logicalGroupLabel"] == "Exterior Drone"
        manage = visual_item(window.contentItem(), "managedSourceGroup")
        choose(engine, manage, group)
        visual_item(window.contentItem(), "renameSourceGroupName").setProperty("text", "Exterior ž")
        click(window, "renameSourceGroup")
        idle(desktop)
        saved = build_project_service().open(root).logical_source_groups
        assert saved.label_for(rows[0].identity) == "Exterior ž"
        assert saved.groups[0].group_id == UUID(group)
        choose(engine, destination, "")
        click(window, "moveSourceToGroup")
        idle(desktop)
        assert not desktop.sources.selected["logicalGroupLabel"]
        choose(engine, manage, group)
        click(window, "deleteSourceGroup")
        idle(desktop)
        assert not build_project_service().open(root).logical_source_groups.groups
        assert desktop.sources.count == 5
        assert not engine.load_errors
    finally:
        dispose(engine)


def test_filtered_group_counts_and_empty_group_are_truthful(desktop, tmp_path):
    _, _, rows = populated(desktop, tmp_path)
    desktop.createSourceGroup("Exterior")
    idle(desktop)
    group = desktop.state["logicalGroups"][1]["value"]
    for row in rows[:2]:
        desktop.assignSourceGroup(str(row.identity), group)
        idle(desktop)
    desktop.setSourceIncluded(str(rows[0].identity), False)
    idle(desktop)
    desktop.setSourceFilter("All")
    desktop.setSourceSection("group/" + group)
    assert desktop.sources.count == 2
    assert "1 included · 1 excluded" in desktop.state["sourceSectionSummary"]
    desktop.setSourceFilter("Excluded")
    assert (
        desktop.sources.count == 1
        and "0 included · 1 excluded" in desktop.state["sourceSectionSummary"]
    )
    desktop.createSourceGroup("Empty group")
    idle(desktop)
    empty = next(g["value"] for g in desktop.state["logicalGroups"] if g["label"] == "Empty group")
    desktop.setSourceSection("group/" + empty)
    engine = create_engine(desktop)
    try:
        window = engine.rootObjects()[0]
        assert desktop.sources.count == 0
        assert "No sources in this group" in visual_item(
            window.contentItem(),
            "participationEmptyState",
        ).property("text")
        assert "0 photos · 0 videos" in desktop.state["sourceSectionSummary"]
        assert not engine.load_errors
    finally:
        dispose(engine)


@pytest.mark.parametrize("fault", ["stale", "write"])
def test_group_save_failure_never_invents_committed_ui_state(desktop, tmp_path, fault):
    root, _, _ = populated(desktop, tmp_path)
    if fault == "stale":
        saved = build_project_service().open(root)
        saved.label = "External change"
        build_project_service().save(root, saved)
    else:
        factory = desktop.controller.factory

        def failing():
            facade = factory()

            def fail(*_):
                raise OSError("Synthetic group save failure")

            facade.save = fail
            return facade

        desktop.controller.factory = failing
    desktop.createSourceGroup("Not saved")
    idle(desktop)
    assert not build_project_service().open(root).logical_source_groups.groups
    assert desktop.state["logicalGroups"] == [{"value": "", "label": "Ungrouped"}]
    assert not desktop.controller.dirty


def test_late_details_and_thumbnails_cannot_cross_project_switch(desktop, tmp_path):
    root, _, rows = populated(desktop, tmp_path)
    started, release = Event(), Event()
    factory = desktop.controller.factory

    def delayed():
        facade = factory()
        original = facade.source_details

        def read(*args):
            started.set()
            assert release.wait(15)
            return original(*args)

        facade.source_details = read
        return facade

    desktop.controller.factory = delayed
    desktop.media.selectSource(str(rows[0].identity))
    desktop.media.inspectSource()
    until(started.is_set)
    token = desktop.media._details_token
    other = tmp_path / "Other project"
    build_project_service().create(other, "Other")
    desktop.openProject(str(other))
    until(lambda: desktop.controller.root == other and not desktop.controller.mutating)
    release.set()
    idle(desktop)
    assert desktop.media._details_token != token
    assert desktop.media.state["sourceDetails"]["fields"] == []
    assert desktop.sources.count == 0 and desktop.sources.thumbnails.cache == {}
    assert desktop.state["sourceSection"] == ""
    assert desktop.controller.root != root


@pytest.mark.parametrize("view", ["List", "Grid"])
def test_1500_grouped_sources_remain_virtualized_in_both_themes(desktop, tmp_path, view):
    open_project(desktop, tmp_path)
    rows = tuple(
        IndexRow(
            identity=uuid4(),
            values={
                "filename": f"photo {i}.jpg",
                "type": "photo",
                "bytes": 10,
                "locator": str(tmp_path / f"missing {i}.jpg"),
                "verification": "Not checked",
                "description": "Photo · 4000 × 3000",
                "dimensions": "4000 × 3000",
                "device": "DJI FC220" if i % 2 else "Apple iPhone 16 Pro",
                "isIncluded": True,
            },
        )
        for i in range(1503)
    )
    desktop.sources.replace(rows)
    desktop.setSourceView(view)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        window.setWidth(1024)
        window.setHeight(640)
        for theme in ("Dark", "Light"):
            desktop.setTheme(theme)
            QTest.qWait(50)
            prefix = "tile-" if view == "Grid" else "source-"

            def count(item, name_prefix=prefix):
                return int(item.objectName().startswith(name_prefix)) + sum(
                    count(c, name_prefix) for c in item.childItems()
                )

            assert 0 < count(window.contentItem()) < 45
            assert len(desktop.sources.thumbnails.pending) <= 100
            assert len(desktop.sources.thumbnails.cache) <= 128
        desktop.setSourceSection("device/dji fc220")
        assert desktop.sources.count == 751
        if view == "List":
            assert not desktop.sources.thumbnails.pending
        assert not engine.load_errors
    finally:
        dispose(engine)
