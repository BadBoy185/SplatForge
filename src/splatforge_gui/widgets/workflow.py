"""Goal-oriented workflow pages. Only controllers execute application use cases."""

import traceback
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from splatforge.core.dataset import DatasetSettings
from splatforge.core.execution import TrainingRuntime
from splatforge.core.pairs import ExhaustiveSettings, SequentialSettings
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
)
from splatforge.core.sfm_profiles import SfmQualityProfile
from splatforge.core.training import (
    DefaultStrategySettings,
    MCMCStrategySettings,
    TrainingSettings,
)
from splatforge_gui.tasks import TaskError
from splatforge_gui.widgets.common import Details, JsonEditor


def button(layout, text, name, action):
    value = QPushButton(text)
    value.setObjectName(name)

    def guarded():
        try:
            action()
        except Exception as exc:
            owner = layout.parentWidget()
            owner.controller.error.emit(
                TaskError(str(exc), type(exc).__name__, traceback.format_exc(), name)
            )

    value.clicked.connect(guarded)
    layout.addWidget(value)
    return value


def refill_runs(combo, overview, kind):
    selected = combo.currentData()
    seen = set()
    runs = []
    for artifact in overview.index.artifacts:
        if (
            artifact.values["artifact_type"] == kind
            and artifact.values["storage_status"] != "evicted"
        ):
            run = artifact.values["producer_run_id"]
            if run not in seen:
                runs.append(UUID(run))
                seen.add(run)
    if [combo.itemData(i) for i in range(combo.count())] == [None, *runs]:
        return
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("Choose an explicit published run", None)
    for run in runs:
        combo.addItem(str(run), run)
    for i in range(combo.count()):
        if combo.itemData(i) == selected:
            combo.setCurrentIndex(i)
            break
    combo.blockSignals(False)
    if combo.currentData() != selected:
        combo.currentIndexChanged.emit(combo.currentIndex())


class WorkflowPage(QWidget):
    def __init__(self, controller, preferences, title, parent=None) -> None:
        super().__init__(parent)
        self.controller, self.preferences = controller, preferences
        self.layout = QVBoxLayout(self)
        self.summary = QLabel(f"Empty — open a project to use {title}.")
        self.summary.setWordWrap(True)
        self.layout.addWidget(self.summary)
        self.form = QFormLayout()
        self.layout.addLayout(self.form)
        self.details = Details()
        self.details.setObjectName(title.lower() + "Details")
        self.advanced = []
        self.controller.completed.connect(self.completed)
        self.controller.error.connect(self.failed)

    def tool(self, key):
        value = self.preferences.get(key, "")
        return Path(value) if value else None

    def set_advanced(self, enabled):
        for widget in self.advanced:
            widget.setVisible(enabled)

    def failed(self, error):
        if error.stage in self.actions:
            self.summary.setText(f"Error — {error.stage}: {error.message}")

    def completed(self, name, value):
        pass


class ReconstructionPage(WorkflowPage):
    actions = {
        "request",
        "reconstruction",
        "reconstruction_plan",
        "validation_details",
        "selection",
    }

    def __init__(self, controller, preferences, parent=None):
        super().__init__(controller, preferences, "Reconstruct", parent)
        self.request = None
        self.intent_signature = None
        self.mapper = QComboBox()
        self.mapper.setObjectName("mapperChoice")
        self.mapper.addItems(["Global", "Incremental", "Hierarchical"])
        self.form.addRow("Mapper (Plan verifies capability)", self.mapper)
        self.profile = QComboBox()
        self.profile.addItem("Explicit saved feature/matching methods", None)
        for profile in SfmQualityProfile:
            self.profile.addItem(f"M7 stage profile: {profile.value}", profile)
        self.form.addRow("Features and matching", self.profile)
        self.pairing = QComboBox()
        self.pairing.addItems(
            [
                "Sequential",
                "Exhaustive reference (bounded)",
                "Advanced configured pairing (see exact settings)",
            ]
        )
        self.form.addRow("Pairing", self.pairing)
        self.notice = QLabel(
            "Production multi-video retrieval remains pending. Sequential connects "
            "within clips; Exhaustive is a reference route, not production retrieval."
        )
        self.notice.setWordWrap(True)
        self.layout.addWidget(self.notice)
        self.layout.addWidget(
            QLabel("Operational settings apply to this run only until saved as intent.")
        )
        button(self.layout, "Plan", "planReconstruction", self.plan)
        self.run = button(self.layout, "Run Reconstruction", "runReconstruction", self.execute)
        self.run.setEnabled(False)
        exact = button(
            self.layout,
            "Advanced exact reconstruction settings…",
            "reconstructionJson",
            self.edit_exact,
        )
        self.advanced.append(exact)
        self.advanced.append(
            button(
                self.layout,
                "Stage current method settings as project intent",
                "stageProjectIntent",
                self.controller.stage_request_as_intent,
            )
        )
        self.validation_run = QComboBox()
        self.validation_run.setObjectName("validationRun")
        self.validation_run.currentIndexChanged.connect(self._validation_changed)
        self.form.addRow("Published validation", self.validation_run)
        button(self.layout, "Inspect validation / components", "inspectValidation", self.inspect)
        button(self.layout, "Request policy selection", "recommendComponents", self.recommend)
        self.manual = button(
            self.layout, "Select components manually…", "manualComponents", self.manual_select
        )
        self.report, self.metrics = None, None
        self.components = Details()
        self.components.setObjectName("componentEvidence")
        self.layout.addWidget(self.components)
        self.layout.addWidget(self.details)
        for combo in (self.mapper, self.profile, self.pairing):
            combo.currentIndexChanged.connect(self.options_changed)

    def _validation_changed(self):
        self.report, self.metrics = None, None

    def options_changed(self):
        if self.request is None:
            return
        mappers = (GlobalMapperSettings, IncrementalMapperSettings, HierarchicalMapperSettings)
        mapper_type = mappers[self.mapper.currentIndex()]
        mapper = (
            self.request.mapper if isinstance(self.request.mapper, mapper_type) else mapper_type()
        )
        pairing = self.request.pairing
        if self.pairing.currentIndex() != 2:
            pairing_type = (SequentialSettings, ExhaustiveSettings)[self.pairing.currentIndex()]
            if not isinstance(pairing, pairing_type):
                pairing = pairing_type()
        self.request = self.request.model_copy(
            update={"mapper": mapper, "profile": self.profile.currentData(), "pairing": pairing}
        )
        self.controller.request = self.request
        self.run.setEnabled(False)

    def overview(self, value):
        self.summary.setText(
            f"Ready — {len(value.sources)} sources. Frame/method settings are "
            "resolved from saved intent; Plan checks the exact backend."
        )
        refill_runs(self.validation_run, value, "validation.reconstruction_report")
        if not value.sources:
            self.summary.setText(
                "Empty — add sources or configure an explicit historical views run."
            )
        signature = (self.controller.draft or value.document).settings.model_dump_json()
        if self.request is None or signature != self.intent_signature:
            self.intent_signature = signature
            self.request = self.controller.request = None
            self.controller.reconstruction_plan = None
            self.run.setEnabled(False)
            self.controller.configure_reconstruction()

    def plan(self):
        self.summary.setText("Loading — checking methods and capabilities…")
        self.controller.reconstruct(self.tool("colmap"), self.tool("model_directory"), True)

    def execute(self):
        self.controller.reconstruct(self.tool("colmap"), self.tool("model_directory"), False)

    def edit_exact(self):
        if self.request:
            editor = JsonEditor("Exact reconstruction run settings", self.request, self)
            if editor.exec() == QDialog.DialogCode.Accepted:
                self.request = self.controller.request = editor.value
                self.sync_controls()
                self.run.setEnabled(False)
                self.details.show_value(editor.value)

    def sync_controls(self) -> None:
        value = self.request
        indices = (
            (
                self.mapper,
                {
                    "mapping.colmap_global": 0,
                    "mapping.colmap_incremental": 1,
                    "mapping.colmap_hierarchical": 2,
                }[value.mapper.method_id],
            ),
            (self.profile, self.profile.findData(value.profile)),
            (
                self.pairing,
                0 if isinstance(value.pairing, SequentialSettings)
                else 1 if isinstance(value.pairing, ExhaustiveSettings) else 2,
            ),
        )
        for combo, index in indices:
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def inspect(self):
        run = self.validation_run.currentData()
        if run:
            self.controller.validation_details(run)

    def recommend(self):
        run = self.validation_run.currentData()
        if run:
            self.controller.select_components(run)

    def manual_select(self):
        run = self.validation_run.currentData()
        if self.report is None or self.metrics is None or run is None:
            self.summary.setText("Inspect the chosen validation before selecting components.")
            return
        dialog = ComponentDialog(self.report, self.metrics, self.is_advanced, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            ids, issues, reason = dialog.request()
            self.controller.select_components(run, ids, issues, reason)

    def set_advanced(self, enabled):
        super().set_advanced(enabled)
        self.is_advanced = enabled

    def completed(self, name, value):
        if name == "request_unavailable":
            self.summary.setText(f"Saved reconstruction settings unavailable: {value}")
            self.run.setEnabled(False)
        elif name == "request":
            self.request = value
            self.sync_controls()
            self.details.show_value(value)
        elif name == "reconstruction_plan":
            self.details.show_value(value)
            self.run.setEnabled(
                value.get("runnable", False)
                and self.request is not None
                and value["request"] == self.request.model_dump(mode="json")
            )
            self.summary.setText("Ready — plan verified. Review its exact route before running.")
        elif name in {"reconstruction", "selection"}:
            self.details.show_value(value)
            self.summary.setText("Result — review validation/selection evidence below.")
        elif name == "validation_details":
            if value[0] != self.validation_run.currentData():
                return
            self.report, self.metrics = value[1:]
            self.components.show_value(
                {
                    "report": value[1].model_dump(mode="json"),
                    "metrics": value[2].model_dump(mode="json"),
                }
            )
            self.summary.setText(
                f"Validation: {self.report.status.value.upper()} · "
                f"{self.metrics.registration.registered_views}/"
                f"{self.metrics.registration.input_views} "
                f"registered views · {self.metrics.component_count} components"
            )


class ComponentDialog(QDialog):
    def __init__(self, report, metrics, advanced=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Explicit component selection")
        self.resize(850, 620)
        self.report = report
        layout = QVBoxLayout(self)
        self.notice = QLabel(
            "Choose components. Separate coordinate systems produce separate datasets/scenes."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.list = QListWidget()
        self.list.setObjectName("componentChoices")
        self.list.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection
            if advanced
            else QListWidget.SelectionMode.SingleSelection
        )
        statuses = {c.component_id: c.status for c in report.components}
        coverage = {
            g.group_id: {c.component_id: c.coverage.registered_views for c in g.components}
            for g in metrics.source_groups
        }
        component_issues = {}
        for issue in report.issues:
            component_issues.setdefault(issue.scope.component_id, []).append(issue.message)
        for component in metrics.components:
            status = statuses[component.component_id]
            groups = [
                f"{g.group_id}: "
                + str(coverage[g.group_id].get(component.component_id, "unavailable"))
                + f"/{g.overall.input_views}"
                for g in metrics.source_groups
            ]
            warnings = component_issues.get(component.component_id, [])
            item = QListWidgetItem(
                f"{component.component_id} · {status.value.upper()} · "
                f"{component.registration.registered_views}/"
                f"{component.registration.input_views} views\n"
                + " | ".join(groups)
                + "\n"
                + "; ".join(warnings)
            )
            item.setData(Qt.ItemDataRole.UserRole, component.component_id)
            self.list.addItem(item)
        layout.addWidget(self.list)
        self.issues = QListWidget()
        self.issues.setObjectName("overrideIssues")
        for issue in report.issues:
            if issue.severity == "failure":
                item = QListWidgetItem(
                    f"FAIL {issue.issue_id}\n"
                    f"Scope: {issue.scope.kind} · component {issue.scope.component_id or 'all'} · "
                    f"source group {issue.scope.source_group_id or 'all'}\n"
                    f"{issue.code}: {issue.message}"
                )
                item.setData(Qt.ItemDataRole.UserRole, issue)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.issues.addItem(item)
        layout.addWidget(QLabel("Exact applicable FAIL issues require individual acknowledgment:"))
        layout.addWidget(self.issues)
        self.reason = QLineEdit()
        self.reason.setObjectName("overrideReason")
        self.reason.setPlaceholderText("Required reason for exact failure overrides")
        layout.addWidget(self.reason)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.confirm)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.list.itemSelectionChanged.connect(self.update_state)
        self.issues.itemChanged.connect(self.update_state)
        self.reason.textChanged.connect(self.update_state)
        self.update_state()

    def request(self):
        ids = tuple(item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems())
        issues = tuple(
            self.issues.item(i).data(Qt.ItemDataRole.UserRole).issue_id
            for i in range(self.issues.count())
            if self.issues.item(i).checkState() == Qt.CheckState.Checked
        )
        return ids, issues, self.reason.text().strip() if issues else None

    def update_state(self):
        ids, issues, reason = self.request()
        applicable = {
            issue.issue_id
            for issue in self.report.issues
            if issue.severity == "failure"
            and (issue.scope.component_id is None or issue.scope.component_id in ids)
        }
        valid = bool(ids) and set(issues) == applicable and (not applicable or bool(reason))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
        self.notice.setText(
            f"{len(ids)} separate datasets/scenes. Components use separate coordinate "
            "systems; they are not merged."
        )

    def confirm(self):
        _, issues, _ = self.request()
        if (
            issues
            and QMessageBox.warning(
                self,
                "Confirm exact failure overrides",
                "Publish this exact component choice and the listed reasoned FAIL overrides?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.accept()


class DatasetPage(WorkflowPage):
    actions = {"dataset", "dataset_plan"}

    def __init__(self, controller, preferences, parent=None):
        super().__init__(controller, preferences, "Dataset", parent)
        self.run = QComboBox()
        self.run.setObjectName("datasetSelectionRun")
        self.form.addRow("Explicit selection run", self.run)
        self.maximum = QSpinBox()
        self.maximum.setObjectName("maxImageSize")
        self.maximum.setRange(0, 32768)
        self.maximum.setSpecialValueText("Native/full")
        self.form.addRow("Maximum image side (this run only)", self.maximum)
        button(self.layout, "Plan", "planDataset", lambda: self.execute(True))
        button(self.layout, "Prepare Dataset", "prepareDataset", lambda: self.execute(False))
        self.advanced.append(
            button(self.layout, "Advanced exact DatasetSettings…", "datasetJson", self.edit_exact)
        )
        self.layout.addWidget(self.details)

    def edit_exact(self):
        editor = JsonEditor(
            "DatasetSettings (this run only)",
            DatasetSettings(max_image_size=self.maximum.value() or None),
            self,
            defaults=DatasetSettings(),
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.maximum.setValue(editor.value.max_image_size or 0)

    def overview(self, value):
        refill_runs(self.run, value, "reconstruction.selection")
        self.summary.setText(
            "Ready — choose an explicit selection. Multiple components produce "
            "separate datasets. M10 consumes historical published pixels."
        )
        if self.run.count() <= 1:
            self.summary.setText(
                "Empty — validate a reconstruction and explicitly select components first."
            )

    def execute(self, planning):
        run = self.run.currentData()
        if run:
            self.summary.setText(
                "Loading — planning dataset…" if planning else "Running — preparing dataset…"
            )
            self.controller.dataset(
                run,
                DatasetSettings(max_image_size=self.maximum.value() or None),
                self.tool("colmap"),
                planning,
            )

    def completed(self, name, value):
        if name in {"dataset_plan", "dataset"}:
            self.details.show_value(value)
            self.summary.setText(
                f"Dataset: {value.status.title()}"
                if name == "dataset"
                else "Dataset plan — exact capability/cache/resource evidence below."
            )


class TrainingPage(WorkflowPage):
    actions = {"training", "training_plan", "trainer_capability", "resume_check"}

    def __init__(self, controller, preferences, parent=None):
        super().__init__(controller, preferences, "Train", parent)
        self.settings = TrainingSettings()
        self.resume_token = None
        self.runtime_environment = {}
        self.dataset_run, self.checkpoint = QComboBox(), QComboBox()
        self.dataset_run.setObjectName("trainingDatasetRun")
        self.checkpoint.setObjectName("trainingCheckpointRun")
        self.form.addRow("Published dataset run", self.dataset_run)
        self.form.addRow("Published checkpoint run", self.checkpoint)
        self.strategy = QComboBox()
        self.strategy.setObjectName("trainingStrategy")
        self.strategy.addItems(["Default", "MCMC", "Default + AbsGrad"])
        self.form.addRow("Strategy", self.strategy)
        self.steps, self.factor, self.cap = QSpinBox(), QSpinBox(), QSpinBox()
        for widget, name, low, high, value in (
            (self.steps, "trainingSteps", 1, 1000000, self.settings.max_steps),
            (self.factor, "dataFactor", 1, 64, self.settings.data_factor),
            (self.cap, "mcmcCap", 4, 10000000, MCMCStrategySettings().cap_max),
        ):
            widget.setObjectName(name)
            widget.setRange(low, high)
            widget.setValue(value)
        self.form.addRow("Steps (this run only)", self.steps)
        self.form.addRow("Data factor", self.factor)
        self.form.addRow("MCMC cap", self.cap)
        self.strategy.currentIndexChanged.connect(self._strategy_changed)
        self._strategy_changed()
        self.python = QLineEdit(preferences.get("trainer_python", ""))
        self.python.setObjectName("trainerPython")
        self.form.addRow("Local trainer Python", self.python)
        self.layout.addWidget(QLabel("No production quality preset has been adopted yet."))
        button(self.layout, "Probe trainer runtime", "probeTrainer", self.probe)
        button(self.layout, "Plan", "planTraining", lambda: self.execute(True))
        button(self.layout, "Run Training", "runTraining", lambda: self.execute(False))
        button(self.layout, "Check checkpoint compatibility", "checkResume", self.check_resume)
        self.resume = button(self.layout, "Resume", "resumeTraining", self.resume_training)
        self.resume.setEnabled(False)
        exact = button(
            self.layout, "Advanced exact TrainingSettings…", "trainingJson", self.edit_exact
        )
        self.advanced.extend([exact])
        self.advanced.append(
            button(self.layout, "Advanced exact trainer runtime…", "runtimeJson", self.edit_runtime)
        )
        self.layout.addWidget(self.details)
        for widget in (self.strategy, self.dataset_run, self.checkpoint):
            widget.currentIndexChanged.connect(self.invalidate_resume)
        for widget in (self.steps, self.factor, self.cap):
            widget.valueChanged.connect(self.invalidate_resume)
        self.python.textChanged.connect(self.invalidate_resume)

    def _strategy_changed(self):
        applicable = self.strategy.currentIndex() == 1
        self.cap.setVisible(applicable)
        self.form.labelForField(self.cap).setVisible(applicable)

    def invalidate_resume(self):
        self.resume_token = None
        self.resume.setEnabled(False)

    def runtime(self):
        self.preferences.set("trainer_python", self.python.text())
        return TrainingRuntime(python=self.python.text(), environment=self.runtime_environment)

    def edit_runtime(self):
        editor = JsonEditor(
            "Machine-local trainer runtime (this session only)", self.runtime(), self
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.python.setText(editor.value.python)
            self.runtime_environment = dict(editor.value.environment)
            self.invalidate_resume()

    def resolved(self):
        value = self.settings.model_dump(mode="json")
        old = self.settings.strategy
        if self.strategy.currentIndex() == 1:
            strategy = old if isinstance(old, MCMCStrategySettings) else MCMCStrategySettings()
            value["strategy"] = {**strategy.model_dump(), "cap_max": self.cap.value()}
        else:
            strategy = (
                old if isinstance(old, DefaultStrategySettings) else DefaultStrategySettings()
            )
            value["strategy"] = {
                **strategy.model_dump(),
                "absgrad": self.strategy.currentIndex() == 2,
            }
        value.update(max_steps=self.steps.value(), data_factor=self.factor.value())
        return TrainingSettings.model_validate(value)

    def overview(self, value):
        refill_runs(self.dataset_run, value, "dataset.prepared_set")
        refill_runs(self.checkpoint, value, "training.checkpoint")
        latest = next(
            (
                str(a.identity)
                for a in value.index.artifacts
                if a.values["artifact_type"] == "training.checkpoint"
            ),
            "none",
        )
        self.summary.setText(
            "Ready — choose dataset and probe the exact trainer runtime. "
            "Settings apply to this run only; pose/world normalization stay explicit."
            f"\nLatest published checkpoint: {latest}"
        )
        if self.dataset_run.count() <= 1:
            self.summary.setText("Empty — prepare a published dataset before training.")

    def probe(self):
        self.summary.setText("Loading — probing the exact trainer runtime…")
        self.controller.trainer_capability(self.runtime())

    def execute(self, planning):
        run = self.dataset_run.currentData()
        if run:
            self.summary.setText(
                "Loading — planning training…"
                if planning
                else "Running — validating runtime and training…"
            )
            self.controller.training(run, self.runtime(), self.resolved(), planning)

    def check_resume(self):
        run, checkpoint = self.dataset_run.currentData(), self.checkpoint.currentData()
        if run and checkpoint:
            self.summary.setText("Loading — checking exact checkpoint compatibility…")
            self.resume_token = uuid4().hex
            self.controller.resume_check(
                run, checkpoint, self.runtime(), self.resolved(), self.resume_token
            )

    def resume_training(self):
        self.controller.training(
            self.dataset_run.currentData(),
            self.runtime(),
            self.resolved(),
            False,
            self.checkpoint.currentData(),
        )

    def edit_exact(self):
        editor = JsonEditor(
            "Exact TrainingSettings (this run only)",
            self.resolved(),
            self,
            defaults=TrainingSettings(),
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.settings = editor.value
            self.steps.setValue(self.settings.max_steps)
            self.factor.setValue(self.settings.data_factor)
            self.strategy.setCurrentIndex(
                1
                if self.settings.strategy.strategy == "mcmc"
                else 2
                if self.settings.strategy.absgrad
                else 0
            )
            if isinstance(self.settings.strategy, MCMCStrategySettings):
                self.cap.setValue(self.settings.strategy.cap_max)
            self.invalidate_resume()

    def completed(self, name, value):
        if name in {"training_plan", "training", "trainer_capability", "resume_check"}:
            self.details.show_value(value)
            self.summary.setText(
                f"Training: {value.status.title()}"
                if name == "training"
                else "Trainer capability/plan — exact evidence below."
            )
        if name == "resume_check":
            self.resume.setEnabled(
                value["compatible"]
                and self.resume_token is not None
                and value.get("request_token") == self.resume_token
            )
            self.resume.setToolTip(value["reason"])
        if name == "trainer_capability":
            features = set(value.features)
            for i, feature in ((0, "default"), (1, "mcmc"), (2, "absgrad")):
                item = self.strategy.model().item(i)
                item.setEnabled(feature in features)
                item.setToolTip(
                    "Verified"
                    if feature in features
                    else f"Trainer does not positively support {feature}"
                )
