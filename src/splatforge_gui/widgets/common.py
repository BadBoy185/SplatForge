"""Reusable presentation widgets; no service execution or backend imports."""

import json

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def render(value) -> str:
    if hasattr(value, "model_dump_json"):
        return value.model_dump_json(indent=2)
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


class JsonEditor(QDialog):
    def __init__(self, title: str, value, parent=None, defaults=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 650)
        self.model_type, self.value, self.defaults = type(value), None, defaults
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(value.model_dump_json(indent=2))
        self.text.setObjectName("settingsJson")
        self.text.setAccessibleName("Exact settings JSON")
        layout.addWidget(self.text)
        self.errors = QLabel("Validate exact JSON before applying. Comments are not accepted.")
        self.errors.setWordWrap(True)
        self.errors.setObjectName("settingsErrors")
        layout.addWidget(self.errors)
        validate = QPushButton("Validate")
        validate.setObjectName("validateSettings")
        validate.clicked.connect(self.validate)
        layout.addWidget(validate)
        if defaults is not None:
            reset = QPushButton("Restore defaults")
            reset.setObjectName("restoreDefaults")
            reset.clicked.connect(
                lambda: self.text.setPlainText(defaults.model_dump_json(indent=2))
            )
            layout.addWidget(reset)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        self.apply = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply.setObjectName("applySettings")
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.text.textChanged.connect(lambda: self.apply.setEnabled(False))
        layout.addWidget(self.buttons)

    def validate(self) -> bool:
        text = self.text.toPlainText()
        if len(text.encode("utf-8")) > 4 * 1024**2:
            self.errors.setText("Settings JSON exceeds the 4 MiB editor limit")
            self.apply.setEnabled(False)
            return False
        try:
            self.value = self.model_type.model_validate_json(text)
        except ValidationError as exc:
            self.errors.setText(
                "\n".join(
                    f"{'.'.join(map(str, e['loc'])) or '$'}: {e['msg']}" for e in exc.errors()
                )
            )
            self.apply.setEnabled(False)
            return False
        self.errors.setText("Valid settings")
        self.apply.setEnabled(True)
        return True


class Details(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(20000)
        self.setPlainText("Empty — select an item or run Plan.")

    def show_value(self, value) -> None:
        self.setPlainText(render(value))


class ErrorDialog(QDialog):
    def __init__(self, error, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Operation failed")
        layout = QVBoxLayout(self)
        summary = QLabel(f"{error.stage}: {error.message}\nCategory: {error.category}")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        details = Details()
        details.setPlainText(error.traceback)
        details.hide()
        layout.addWidget(details)
        show = QPushButton("Show technical details")
        show.clicked.connect(lambda: details.setVisible(not details.isVisible()))
        layout.addWidget(show)
        copy = QPushButton("Copy Details")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(error.traceback))
        layout.addWidget(copy)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)


class ProgressPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.label = QLabel("Ready — no active run")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setObjectName("activeRunStatus")
        self.bar = QProgressBar()
        self.bar.setObjectName("operationProgress")
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)

    def update_progress(self, runs) -> None:
        if not runs:
            self.label.setText("Ready — no active run")
            self.bar.setRange(0, 1000)
            self.bar.setValue(0)
            return
        run = runs[0]
        stage = next(
            (s for s in run.stages if s.status in {"running", "stopping", "failed", "interrupted"}),
            run.stages[-1] if run.stages else None,
        )
        text = f"{run.status.title()} · run {run.run_id} · elapsed {run.elapsed_seconds:.1f}s"
        fraction = None
        if stage:
            text += f"\n{stage.work.stage_id} · {stage.phase_id or 'Waiting'}"
            text += f" · {stage.completed}/{stage.work.total or '?'} {stage.work.unit}"
            if stage.eta.likely_seconds is not None:
                text += f" · ETA {stage.eta.likely_seconds:.0f}s"
            if stage.status in {"cached", "succeeded", "skipped", "running"}:
                fraction = stage.fraction
        self.label.setText(text)
        self.bar.setRange(0, 1000 if fraction is not None else 0)
        if fraction is not None:
            self.bar.setValue(round(fraction * 1000))
