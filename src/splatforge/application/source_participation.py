"""Edit portable participation intent through the existing project Save contract."""

from collections.abc import Iterable
from uuid import UUID

from splatforge.application.projects import ProjectError
from splatforge.core.project import ProjectDocument
from splatforge.core.source_participation import (
    SourceParticipationIntent,
    resolve_effective_sources,
)


def participation_draft(
    document: ProjectDocument,
    registered_source_ids: Iterable[UUID],
    source_ids: set[UUID],
    *,
    included: bool,
) -> ProjectDocument:
    """Build one atomic batch edit; ProjectService.save supplies revision/CAS/publication."""
    resolved = resolve_effective_sources(registered_source_ids, document.source_participation)
    if not resolved.supported:
        raise ProjectError("Unsupported source participation version; cannot edit participation")
    if not source_ids:
        raise ProjectError("Select at least one registered source")
    unknown = source_ids - set(resolved.registered_source_ids)
    if unknown:
        raise ProjectError("Unknown source IDs: " + ", ".join(sorted(map(str, unknown))))
    excluded = set(document.source_participation.excluded_source_ids)
    excluded = excluded - source_ids if included else excluded | source_ids
    intent = SourceParticipationIntent.model_validate({
        **document.source_participation.model_dump(mode="json"),
        "excluded_source_ids": sorted(map(str, excluded)),
    })
    return ProjectDocument.model_validate({
        **document.model_dump(mode="json"), "source_participation": intent.model_dump(mode="json"),
    })
