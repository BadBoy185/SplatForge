"""Validated dialog state. No domain validation is implemented in JavaScript."""

from pydantic import ValidationError
from PySide6.QtCore import Property, QObject, Signal, Slot


class ExactSettingsModel(QObject):
    changed = Signal()
    applied = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = {"title": "", "text": "", "errors": [], "valid": False, "hasDefaults": False}
        self._kind, self._type, self._value, self._defaults = "", None, None, None

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        return self._state

    def begin(self, kind: str, title: str, value, defaults=None) -> None:
        self._kind, self._type, self._defaults = kind, type(value), defaults
        self._state.update(title=title, hasDefaults=defaults is not None)
        self.setText(value.model_dump_json(indent=2))

    @Slot(str)
    def setText(self, text: str) -> None:
        self._value = None
        self._state.update(text=text, valid=False, errors=[])
        self.changed.emit()

    @Slot(result=bool)
    def validate(self) -> bool:
        self._value = None
        errors = []
        if len(self._state["text"].encode("utf-8")) > 4 * 1024**2:
            errors = [{"path": "$", "message": "Settings JSON exceeds the 4 MiB editor limit"}]
        elif self._type is not None:
            try:
                self._value = self._type.model_validate_json(self._state["text"])
            except ValidationError as exc:
                errors = [
                    {"path": ".".join(map(str, e["loc"])) or "$", "message": e["msg"]}
                    for e in exc.errors()
                ]
        self._state.update(valid=self._value is not None, errors=errors)
        self.changed.emit()
        return self._value is not None

    @Slot()
    def restore(self) -> None:
        if self._defaults is not None:
            self.setText(self._defaults.model_dump_json(indent=2))

    @Slot()
    def apply(self) -> None:
        if self._value is not None and self._state["valid"]:
            self.applied.emit(self._kind, self._value)


class ComponentSelectionModel(QObject):
    changed = Signal()
    accepted = Signal(object, object, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.report = None
        self._components, self._issues, self._selected, self._checked = [], [], [], []
        self._reason, self._advanced = "", False

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        applicable = (
            {
                str(i.issue_id)
                for i in self.report.issues
                if i.severity == "failure"
                and (i.scope.component_id is None or str(i.scope.component_id) in self._selected)
            }
            if self.report
            else set()
        )
        valid = bool(self._selected) and set(self._checked) == applicable
        valid = valid and (not applicable or bool(self._reason.strip()))
        return {
            "components": self._components,
            "issues": self._issues,
            "selected": self._selected,
            "checked": self._checked,
            "reason": self._reason,
            "valid": bool(valid),
            "needsConfirmation": bool(applicable),
            "count": len(self._selected),
            "advanced": self._advanced,
        }

    def begin(self, report, metrics, advanced: bool) -> None:
        self.report, self._advanced = report, advanced
        self._selected, self._checked, self._reason = [], [], ""
        statuses = {c.component_id: c.status.value for c in report.components}
        self._components = [
            {
                "id": str(c.component_id),
                "title": f"Component {i + 1}",
                "status": statuses[c.component_id].upper(),
                "views": f"{c.registration.registered_views} / {c.registration.input_views} views",
                "coverage": [
                    (f"Source group {n + 1}" + (f" · {g.group_id}" if advanced else "") + ": ")
                    + str(
                        next(
                            (
                                v.coverage.registered_views
                                for v in g.components
                                if v.component_id == c.component_id
                            ),
                            "Unavailable",
                        )
                    )
                    + f" / {g.overall.input_views}"
                    for n, g in enumerate(metrics.source_groups)
                ],
                "issues": [
                    v.message for v in report.issues if v.scope.component_id == c.component_id
                ],
            }
            for i, c in enumerate(metrics.components)
        ]
        self._issues = [
            {
                "id": str(i.issue_id),
                "message": i.message,
                "scope": str(i.scope.component_id or "All components"),
                "code": i.code,
            }
            for i in report.issues
            if i.severity == "failure"
        ]
        self.changed.emit()

    @Slot(str)
    def toggleComponent(self, identity: str) -> None:
        if identity not in {c["id"] for c in self._components}:
            return
        if identity in self._selected:
            self._selected.remove(identity)
        else:
            self._selected = [*self._selected, identity] if self._advanced else [identity]
        self.changed.emit()

    @Slot(str)
    def toggleIssue(self, identity: str) -> None:
        if identity not in {i["id"] for i in self._issues}:
            return
        if identity in self._checked:
            self._checked.remove(identity)
        else:
            self._checked.append(identity)
        self.changed.emit()

    @Slot(str)
    def setReason(self, reason: str) -> None:
        self._reason = reason
        self.changed.emit()

    @Slot(bool, result=bool)
    def confirm(self, acknowledged: bool) -> bool:
        if not self.state["valid"] or (self.state["needsConfirmation"] and not acknowledged):
            return False
        # Preserve the original typed IDs; their contracts need not be UUIDs.
        ids = tuple(
            c.component_id for c in self.report.components if str(c.component_id) in self._selected
        )
        issues = tuple(i.issue_id for i in self.report.issues if str(i.issue_id) in self._checked)
        self.accepted.emit(ids, issues, self._reason.strip() if issues else None)
        return True
