"""Run/artifact inspection, local diagnostics and explicit storage controls."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableView,
    QTabWidget,
)

from splatforge_gui.models import ARTIFACT_COLUMNS, RUN_COLUMNS, RecordModel
from splatforge_gui.widgets.point_preview import PointPreview
from splatforge_gui.widgets.workflow import WorkflowPage, button


class ResultsPage(WorkflowPage):
    actions = {"inspect", "run_details", "pin"}

    def __init__(self, controller, preferences, parent=None):
        super().__init__(controller, preferences, "Results", parent)
        self.inspection = None
        self.tabs = QTabWidget()
        self.artifacts = RecordModel(ARTIFACT_COLUMNS, self)
        self.runs = RecordModel(RUN_COLUMNS, self)
        self.artifact_table, self.run_table = QTableView(), QTableView()
        for table, model, name in (
            (self.artifact_table, self.artifacts, "artifactTable"),
            (self.run_table, self.runs, "runTable"),
        ):
            table.setObjectName(name)
            table.setModel(model)
            table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tabs.addTab(self.artifact_table, "Results / artifacts")
        self.tabs.addTab(self.run_table, "Run history")
        self.layout.addWidget(self.tabs)
        button(self.layout, "Inspect selected item", "inspectResult", self.inspect)
        button(self.layout, "Open Folder", "openResultFolder", self.open_folder)
        button(self.layout, "Copy Path", "copyResultPath", self.copy_path)
        self.preview = PointPreview()
        self.layout.addWidget(self.preview)
        button(self.layout, "Reset view (R)", "resetPointPreview", self.preview.reset)
        self.advanced.extend(
            [
                button(self.layout, "Pin artifact", "pinArtifact", lambda: self.pin(True)),
                button(self.layout, "Unpin artifact", "unpinArtifact", lambda: self.pin(False)),
            ]
        )
        self.layout.addWidget(
            QLabel(
                "Pins protect generated payloads from cleanup. "
                "Implicit current/lineage protection remains authoritative."
            )
        )
        self.layout.addWidget(self.details)

    def overview(self, value):
        if self.inspection and self.inspection.artifact_id not in {
            a.identity for a in value.index.artifacts
        }:
            self.inspection = None
            self.preview.points, self.preview.cameras = (), ()
            self.preview.label = "Empty — inspect an output in this project."
            self.preview.reset()
            self.details.setPlainText("Empty — inspect an output in this project.")
        self.artifacts.replace(value.index.artifacts, self.artifact_table)
        self.runs.replace(value.index.runs, self.run_table)
        self.summary.setText(
            f"Ready — {len(value.index.artifacts)} artifacts, "
            f"{len(value.index.runs)} runs. "
            + (
                "Showing most recent 2000 records; older history is available via CLI."
                if value.index.truncated
                else "Select an output to inspect."
            )
        )

    def selected_artifact(self):
        return self.artifact_table.currentIndex().data(Qt.ItemDataRole.UserRole)

    def inspect(self):
        if self.tabs.currentIndex() == 1:
            run = self.run_table.currentIndex().data(Qt.ItemDataRole.UserRole)
            if run:
                self.controller.inspect_run(run)
        else:
            artifact = self.selected_artifact()
            if artifact:
                self.summary.setText("Loading — reading bounded artifact preview…")
                self.controller.inspect_artifact(artifact)

    def open_folder(self):
        if (
            not self.controller.root
            or not self.inspection
            or not (self.inspection.directory.is_relative_to(self.controller.root))
        ):
            return
        if (
            self.inspection
            and self.tabs.currentIndex() == 0
            and (self.selected_artifact() == self.inspection.artifact_id)
        ):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.inspection.directory)))

    def copy_path(self):
        if (
            not self.controller.root
            or not self.inspection
            or not (self.inspection.directory.is_relative_to(self.controller.root))
        ):
            return
        if (
            self.inspection
            and self.tabs.currentIndex() == 0
            and (self.selected_artifact() == self.inspection.artifact_id)
        ):
            QApplication.clipboard().setText(str(self.inspection.directory))

    def pin(self, pinned):
        artifact = self.selected_artifact()
        if artifact:
            self.controller.pin(artifact, pinned)

    def completed(self, name, value):
        if name == "inspect":
            if value.artifact_id != self.selected_artifact():
                return
            self.inspection = value
            self.details.show_value(value.metadata)
            self.preview.set_data(value)
            self.summary.setText(
                f"Ready — {len(value.points)} sampled centers, "
                f"{len(value.cameras)} camera centers. {value.label}"
            )
        elif name == "run_details":
            self.details.setPlainText(value)


class DiagnosticsPage(WorkflowPage):
    actions = {"doctor", "cleanup_preview", "cleanup_apply", "recovery", "run_details"}

    def __init__(self, controller, preferences, parent=None):
        super().__init__(controller, preferences, "Diagnostics", parent)
        self.plan = None
        self.paths = {}
        for key, label in (
            ("colmap", "Optional local COLMAP path"),
            ("model_directory", "Optional local learned-model directory"),
            ("lichtfeld", "Optional local LichtFeld path"),
        ):
            field = QLineEdit(preferences.get(key, ""))
            field.setObjectName(key + "Path")
            field.textChanged.connect(lambda value, name=key: self.preferences.set(name, value))
            self.paths[key] = field
            self.form.addRow(label, field)
        button(self.layout, "Doctor / capabilities", "doctor", lambda: self.diagnose(False))
        self.advanced.append(
            button(
                self.layout,
                "Deep disposable capability probes",
                "deepDoctor",
                lambda: self.diagnose(True),
            )
        )
        self.layout.addWidget(
            QLabel(
                "FFmpeg/media: unknown until actual ingest/view preparation.\n"
                "COLMAP, learned methods and GPU are reported separately. "
                "GPU presence does not prove "
                "a runnable trainer. Probe gsplat on the Train page. No dependencies are installed."
            )
        )
        self.recovery = QComboBox()
        self.recovery.setObjectName("recoveryRun")
        self.form.addRow("Active/interrupted run", self.recovery)
        button(self.layout, "Inspect run", "inspectRecoveryRun", self.inspect_run)
        button(self.layout, "Cancel active run", "cancelRecoveryRun", self.controller.cancel)
        button(self.layout, "Recover interrupted publication", "recoverRun", self.recover)
        self.advanced.append(
            button(self.layout, "Preview cleanup", "previewCleanup", self.controller.cleanup)
        )
        self.apply = button(
            self.layout, "Apply exact cleanup preview…", "applyCleanup", self.apply_cleanup
        )
        self.apply.setEnabled(False)
        self.advanced.append(self.apply)
        self.layout.addWidget(self.details)

    def overview(self, value):
        if self.plan and self.plan.project_id != value.document.project_id:
            self.plan = None
            self.apply.setEnabled(False)
        selected = self.recovery.currentData()
        self.recovery.clear()
        self.recovery.addItem("Choose a run to inspect/recover", None)
        for run in value.index.runs:
            if run.values["status"] in {"running", "interrupted"} or "unresolved" in (
                run.values.get("teardown") or ""
            ):
                self.recovery.addItem(
                    f"{run.values['status'].title()} · {run.identity}", run.identity
                )
        for i in range(self.recovery.count()):
            if self.recovery.itemData(i) == selected:
                self.recovery.setCurrentIndex(i)
        self.summary.setText(
            "Recovery required — inspect active/interrupted ownership and teardown."
            if self.recovery.count() > 1
            else "Ready — run Doctor for current capability evidence."
        )
        if value.index.state_version < 4:
            self.summary.setText(
                f"Legacy state v{value.index.state_version}. Open is read-only; "
                "use 'splatforge project upgrade-state <project>' before media processing. "
                "The application creates a validated backup before upgrade."
            )

    def diagnose(self, deep):
        self.summary.setText("Loading — probing local capabilities…")
        self.controller.doctor(
            self.tool("colmap"), self.tool("model_directory"), deep, self.tool("lichtfeld")
        )

    def inspect_run(self):
        run = self.recovery.currentData()
        if run:
            self.controller.inspect_run(run)

    def recover(self):
        run = self.recovery.currentData()
        if run:
            self.controller.recover_run(run)

    def apply_cleanup(self):
        if (
            self.plan
            and QMessageBox.warning(
                self,
                "Apply exact cleanup preview",
                f"Remove the listed generated payloads: {self.plan.total_bytes:,} bytes?\n"
                f"Exact preview digest: {self.plan.preview_digest}\n"
                "Pinned/current/active outputs and their protected lineage stay protected.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.controller.cleanup(self.plan)
            self.apply.setEnabled(False)

    def completed(self, name, value):
        if name in {"doctor", "cleanup_preview", "cleanup_apply", "recovery"}:
            self.details.show_value(value)
            self.summary.setText("Ready — exact diagnostics/cleanup/recovery evidence shown below.")
        if name == "cleanup_preview":
            self.plan = value
            self.apply.setEnabled(bool(value.candidates))
        elif name == "run_details":
            self.details.setPlainText(value)
