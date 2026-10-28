"""Batch organization drafts; existing ProjectService owns Save/CAS/publication."""

from collections.abc import Iterable
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from splatforge.application.projects import ProjectError
from splatforge.core.logical_source_groups import LogicalSourceGroup, LogicalSourceGroups
from splatforge.core.media import SourceOccurrence
from splatforge.core.project import ProjectDocument


def logical_groups_draft(
    document: ProjectDocument,
    registered_source_ids: Iterable[UUID],
    *,
    action: Literal["create", "rename", "assign", "delete"],
    group_id: UUID | None = None,
    label: str = "",
    source_ids: frozenset[UUID] = frozenset(),
) -> ProjectDocument:
    intent = document.logical_source_groups
    if intent.schema_version != 1:
        raise ProjectError("Unsupported logical group version; cannot edit groups")
    groups = {g.group_id: g for g in intent.groups}
    assignments = dict(intent.source_assignments)
    if action == "create":
        identity = group_id or uuid4()
        if identity in groups:
            raise ProjectError("Logical group already exists")
        groups[identity] = LogicalSourceGroup(group_id=identity, label=label)
        if source_ids - set(registered_source_ids):
            raise ProjectError("Select registered sources to group")
        assignments.update({source: identity for source in source_ids})
    elif action in {"rename", "delete"}:
        if group_id not in groups:
            raise ProjectError("Unknown logical group")
        if action == "rename":
            groups[group_id] = LogicalSourceGroup.model_validate({
                **groups[group_id].model_dump(), "label": label,
            })
        else:
            del groups[group_id]
            assignments = {s: g for s, g in assignments.items() if g != group_id}
    elif action == "assign":
        if group_id is not None and group_id not in groups:
            raise ProjectError("Unknown logical group")
        if not source_ids or source_ids - set(registered_source_ids):
            raise ProjectError("Select registered sources to move")
        for source in source_ids:
            if group_id is None:
                assignments.pop(source, None)
            else:
                assignments[source] = group_id
    else:
        raise ProjectError("Unknown logical group action")
    replacement = LogicalSourceGroups.model_validate({
        **intent.model_dump(), "groups": tuple(groups.values()),
        "source_assignments": assignments,
    })
    return ProjectDocument.model_validate({
        **document.model_dump(), "logical_source_groups": replacement,
    })


def folder_group_label(path: Path, root: Path) -> str:
    """Import-time relative parent only; never infer a device from a locator."""
    try:
        relative = path.absolute().relative_to(root.absolute()).parent
    except ValueError as exc:
        raise ProjectError("Imported source is outside the selected folder") from exc
    return " / ".join(relative.parts)


def folder_groups_draft(
    document: ProjectDocument, sources: Iterable[SourceOccurrence], root: Path,
) -> ProjectDocument:
    """All new folder assignments join the inventory's single metadata CAS."""
    intent = document.logical_source_groups
    if intent.schema_version != 1:
        raise ProjectError("Unsupported logical group version; cannot import folder groups")
    groups = list(intent.groups)
    assignments = dict(intent.source_assignments)
    occupied = {g.label.casefold() for g in groups}
    by_folder = {}
    for source in sources:
        parent = folder_group_label(Path(source.external_locator), root)
        if not parent:
            continue
        if parent not in by_folder:
            # Keep the full relative identity as the key even when a display label
            # needs shortening. Never silently merge equal labels or case variants.
            base = " ".join(parent.split())[:110]
            label, suffix = base, 2
            while label.casefold() in occupied:
                label = f"{base} ({suffix})"
                suffix += 1
            occupied.add(label.casefold())
            group = LogicalSourceGroup(group_id=uuid4(), label=label)
            groups.append(group)
            by_folder[parent] = group.group_id
        assignments[source.source_id] = by_folder[parent]
    replacement = LogicalSourceGroups.model_validate({
        **intent.model_dump(), "groups": groups, "source_assignments": assignments,
    })
    return ProjectDocument.model_validate({
        **document.model_dump(), "logical_source_groups": replacement,
    })
