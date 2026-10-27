"""Ephemeral session evidence over immutable source identity; never filesystem monitoring."""

from datetime import UTC, datetime

from splatforge_gui.presentation import timestamp


class SourceSession:
    def __init__(self) -> None:
        self.context = None
        self.evidence = {}

    def enter(self, context) -> bool:
        if context == self.context:
            return False
        self.context = context
        self.evidence.clear()
        return True

    def imported(self, result) -> None:
        for source in result.added_sources:
            key = str(source.source_id), source.source_revision, source.content_sha256
            self.evidence[key] = dict(
                availability="Available",
                availabilityState="available",
                availabilityDetail="Checked during import",
                checkedLabel="Checked during import",
                checkedAt=datetime.now(UTC).isoformat(),
            )

    def verified(self, results) -> None:
        for result in results:
            success = (
                result.outcome == "unchanged"
                and result.assurance in {"metadata_unchanged", "content_verified"}
                and result.current_evidence is not None
            )
            missing = result.outcome == "missing"
            key = str(result.source_id), result.source_revision, result.expected_content_sha256
            self.evidence[key] = dict(
                availability="Available"
                if success
                else "Missing"
                if missing
                else "Needs attention",
                availabilityState="available" if success else "missing" if missing else "warning",
                availabilityDetail=result.diagnostic_message,
                checkedLabel=timestamp(result.checked_at),
                checkedAt=result.checked_at.isoformat(),
            )

    def project(self, row) -> dict:
        key = str(row.identity), row.values.get("sourceRevision", 1), row.values.get("sha256", "")
        return self.evidence.get(
            key,
            dict(
                availability="Not checked this session",
                availabilityState="neutral",
                availabilityDetail=(
                    "Check Source Files checks the originals at their saved locations."
                ),
                checkedLabel="Not checked this session",
                checkedAt="",
            ),
        )

    def uncertain(self, rows, reason: str) -> None:
        for row in rows:
            key = (
                str(row.identity),
                row.values.get("sourceRevision", 1),
                row.values.get("sha256", ""),
            )
            self.evidence[key] = dict(
                availability="Needs attention",
                availabilityState="warning",
                availabilityDetail=reason,
                checkedLabel="Check did not finish",
                checkedAt="",
            )
