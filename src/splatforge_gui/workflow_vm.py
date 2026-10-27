"""Typed reconstruction/dataset/training state behind the QML presentation."""

from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from splatforge.core.dataset import DatasetSettings
from splatforge.core.execution import TrainingRuntime
from splatforge.core.pairs import ExhaustiveSettings, SequentialSettings
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
)
from splatforge.core.sfm_profiles import SfmQualityProfile
from splatforge.core.training import DefaultStrategySettings, MCMCStrategySettings, TrainingSettings
from splatforge_gui.presentation import guarded, plain, published_runs, render


class WorkflowViewModel(QObject):
    changed = Signal()

    def __init__(self, desktop) -> None:
        super().__init__(desktop)
        self.desktop, self.controller = desktop, desktop.controller
        self.dataset_settings, self.training_settings = DatasetSettings(), TrainingSettings()
        self.runtime_environment = {}
        self._inputs = {
            k: "" for k in ("validation", "selection", "dataset", "checkpoint", "views")
        }
        self._choices = {k: [] for k in self._inputs}
        self._report, self._metrics = None, None
        self._signature, self._project_id = None, None
        self._resume_token, self._resume_ready, self._resume_reason = None, False, "Not checked"
        self._capability = None
        self._plans, self._details, self._messages = {}, {}, {}
        self._pending = {}
        self.controller.changed.connect(self.overview)
        self.controller.completed.connect(self.completed)
        self.controller.error.connect(self.failed)
        desktop._exact.applied.connect(self.apply_exact)
        desktop._components.accepted.connect(self.accept_components)

    def tool(self, key: str) -> Path | None:
        value = self.desktop._machine.get(key, "")
        return Path(value) if value else None

    def invalidate_runtime(self) -> None:
        self.invalidate_resume()
        self._capability = None
        self._plans.pop("training", None)
        self.controller.reconstruction_plan = None
        self.changed.emit()

    def invalidate_resume(self) -> None:
        self._resume_token, self._resume_ready = None, False
        self._resume_reason = "Check compatibility for these exact settings"

    def _snapshot(self) -> str:
        return render(
            {
                "generation": self.controller.generation,
                "inputs": self._inputs,
                "machine": self.desktop._machine,
                "runtime_environment": self.runtime_environment,
                "request": plain(self.controller.request) if self.controller.request else None,
                "dataset": plain(self.dataset_settings),
                "training": plain(self.training_settings),
            }
        )

    @Property("QVariantMap", notify=changed)
    def state(self) -> dict:
        request = self.controller.request
        mapper = request.mapper.method_id.rsplit("_", 1)[-1] if request else ""
        plan = self.controller.reconstruction_plan
        tools = {
            "colmap": str(self.tool("colmap")) if self.tool("colmap") else None,
            "models": str(self.tool("model_directory")) if self.tool("model_directory") else None,
        }
        runnable = bool(
            plan
            and request
            and plan.get("runnable")
            and plan["request"] == request.model_dump(mode="json")
            and plan["tools"] == tools
        )
        strategy = self.training_settings.strategy
        return {
            "inputs": self._inputs,
            "choices": self._choices,
            "requestAvailable": request is not None,
            "mapper": mapper,
            "profile": request.profile.value if request and request.profile else "",
            "profiles": [{"label": "Explicit saved methods", "value": ""}]
            + [
                {"label": p.value.title() + " · features / matching", "value": p.value}
                for p in SfmQualityProfile
            ],
            "pairing": request.pairing.method_id if request else "",
            "extractor": request.features.extractor.method_id if request else "Unavailable",
            "matcher": request.features.matcher.method_id if request else "Unavailable",
            "frameSelection": (
                "Sharpest interval"
                if hasattr(request.selection, "reject_duplicates")
                else "Fixed interval"
            )
            if request
            else "Unavailable",
            "canReconstruct": runnable,
            "canSelect": self._report is not None,
            "datasetMaximum": self.dataset_settings.max_image_size or 0,
            "strategy": "mcmc"
            if isinstance(strategy, MCMCStrategySettings)
            else "absgrad"
            if strategy.absgrad
            else "default",
            "steps": self.training_settings.max_steps,
            "factor": self.training_settings.data_factor,
            "cap": strategy.cap_max
            if isinstance(strategy, MCMCStrategySettings)
            else MCMCStrategySettings().cap_max,
            "capability": plain(self._capability) if self._capability else {},
            "strategyChoices": [
                {
                    "label": label,
                    "value": feature,
                    "supported": self._capability is None or feature in self._capability.features,
                }
                for label, feature in (
                    ("Default", "default"),
                    ("MCMC", "mcmc"),
                    ("Default + AbsGrad", "absgrad"),
                )
            ],
            "resumeReady": self._resume_ready,
            "resumeReason": self._resume_reason,
            "plans": self._plans,
            "details": self._details,
            "messages": self._messages,
        }

    @Slot(str, str)
    def chooseInput(self, kind: str, identity: str) -> None:
        if kind not in self._inputs or identity not in {r["value"] for r in self._choices[kind]}:
            return
        self._inputs[kind] = identity
        if kind == "validation":
            self._report = self._metrics = None
        if kind in {"dataset", "checkpoint"}:
            self.invalidate_resume()
        self._plans.clear()
        self.changed.emit()

    @Slot(str, str)
    @guarded
    def setReconstruction(self, key: str, value: str) -> None:
        request = self.controller.request
        if request is None:
            return
        update = {}
        if key == "mapper":
            cls = {
                "global": GlobalMapperSettings,
                "incremental": IncrementalMapperSettings,
                "hierarchical": HierarchicalMapperSettings,
            }[value]
            update[key] = request.mapper if request.mapper.method_id == cls().method_id else cls()
        elif key == "pairing":
            cls = {"sequential": SequentialSettings, "exhaustive": ExhaustiveSettings}[value]
            update[key] = request.pairing if isinstance(request.pairing, cls) else cls()
        elif key == "profile":
            update[key] = SfmQualityProfile(value) if value else None
        self.controller.request = type(request).model_validate(
            request.model_copy(update=update).model_dump()
        )
        self.controller.reconstruction_plan = None
        self._plans.pop("reconstruction", None)
        self.changed.emit()

    @Slot(int)
    @guarded
    def setDatasetMaximum(self, value: int) -> None:
        self.dataset_settings = DatasetSettings(max_image_size=value or None)
        self._plans.pop("dataset", None)
        self.changed.emit()

    @Slot(str, str)
    @guarded
    def setTraining(self, key: str, value: str) -> None:
        data = self.training_settings.model_dump(mode="json")
        old = self.training_settings.strategy
        if key == "strategy":
            if value == "mcmc":
                data["strategy"] = (
                    old if isinstance(old, MCMCStrategySettings) else MCMCStrategySettings()
                ).model_dump()
            else:
                strategy = (
                    old if isinstance(old, DefaultStrategySettings) else DefaultStrategySettings()
                )
                data["strategy"] = {**strategy.model_dump(), "absgrad": value == "absgrad"}
        elif key == "cap":
            data["strategy"]["cap_max"] = int(value)
        elif key in {"max_steps", "data_factor"}:
            data[key] = int(value)
        self.training_settings = TrainingSettings.model_validate(data)
        self.invalidate_resume()
        self._plans.pop("training", None)
        self.changed.emit()

    def runtime(self) -> TrainingRuntime:
        return TrainingRuntime(
            python=str(self.tool("trainer_python") or ""), environment=self.runtime_environment
        )

    @Slot(str)
    @guarded
    def editExact(self, kind: str) -> None:
        values = {
            "reconstruction": self.controller.request,
            "dataset": self.dataset_settings,
            "training": self.training_settings,
        }
        if kind == "runtime":
            value = self.runtime()
        elif kind == "intent":
            value = (self.controller.draft or self.controller.overview.document).settings
        else:
            value = values[kind]
        if value is not None:
            default = {"dataset": DatasetSettings(), "training": TrainingSettings()}.get(kind)
            self.desktop._exact.begin(kind, "Exact " + kind + " settings", value, default)
            self.desktop.dialogRequested.emit("exact")

    def apply_exact(self, kind: str, value) -> None:
        if kind == "reconstruction":
            self.controller.request = value
            self.controller.reconstruction_plan = None
        elif kind == "dataset":
            self.dataset_settings = value
        elif kind == "training":
            self.training_settings = value
            self.invalidate_resume()
        elif kind == "runtime":
            self.runtime_environment = dict(value.environment)
            self.desktop.setMachine("trainer_python", value.python)
            self.invalidate_runtime()
        elif kind == "intent":
            document = self.controller.draft or self.controller.overview.document
            self.controller.edit(document.model_copy(update={"settings": value}))
            self.overview(self.controller.overview)
        self._plans.clear()
        self.changed.emit()

    @Slot(str)
    @guarded
    def action(self, name: str) -> None:
        reply = {
            "planReconstruction": "reconstruction_plan",
            "planDataset": "dataset_plan",
            "planTraining": "training_plan",
            "probeTrainer": "trainer_capability",
        }.get(name)
        if reply:
            if any(job[0] == reply for job in self.controller.jobs.values()):
                return
            self._pending[reply] = self._snapshot()
        if name == "probeTrainer":
            self._capability = None
        if name in {"planReconstruction", "runReconstruction"}:
            self.controller.reconstruct(
                self.tool("colmap"), self.tool("model_directory"), name == "planReconstruction"
            )
        elif name == "stageIntent":
            self.controller.stage_request_as_intent()
        elif name == "inspectValidation" and self._inputs["validation"]:
            self.controller.validation_details(UUID(self._inputs["validation"]))
        elif name == "policySelection" and self._inputs["validation"]:
            self.controller.select_components(UUID(self._inputs["validation"]))
        elif name == "manualSelection" and self._report is not None:
            self.desktop._components.begin(
                self._report, self._metrics, self.desktop.state["mode"] == "Advanced"
            )
            self.desktop.dialogRequested.emit("components")
        elif name in {"planDataset", "prepareDataset"} and self._inputs["selection"]:
            self.controller.dataset(
                UUID(self._inputs["selection"]),
                self.dataset_settings,
                self.tool("colmap"),
                name == "planDataset",
            )
        elif name == "probeTrainer":
            self.controller.trainer_capability(self.runtime())
        elif name in {"planTraining", "runTraining", "resumeTraining"} and self._inputs["dataset"]:
            if name == "resumeTraining" and not self._resume_ready:
                raise ValueError("Check exact checkpoint compatibility before Resume")
            self.controller.training(
                UUID(self._inputs["dataset"]),
                self.runtime(),
                self.training_settings,
                name == "planTraining",
                UUID(self._inputs["checkpoint"]) if name == "resumeTraining" else None,
            )
        elif name == "checkResume" and all(self._inputs[k] for k in ("dataset", "checkpoint")):
            self._resume_token, self._resume_ready = uuid4().hex, False
            self.controller.resume_check(
                UUID(self._inputs["dataset"]),
                UUID(self._inputs["checkpoint"]),
                self.runtime(),
                self.training_settings,
                self._resume_token,
            )
        self.changed.emit()

    def accept_components(self, ids, issues, reason) -> None:
        if self._report is not None and self._inputs["validation"]:
            self.controller.select_components(UUID(self._inputs["validation"]), ids, issues, reason)

    def overview(self, value) -> None:
        if self._project_id != value.document.project_id:
            self._project_id = value.document.project_id
            self._signature = None
            self._report = self._metrics = None
            self._plans, self._details, self._messages = {}, {}, {}
            self._inputs = dict.fromkeys(self._inputs, "")
            self.invalidate_resume()
        for key, kind in {
            "validation": "validation.reconstruction_report",
            "selection": "reconstruction.selection",
            "dataset": "dataset.prepared_set",
            "checkpoint": "training.checkpoint",
            "views": "views.selected_set",
        }.items():
            self._choices[key] = published_runs(value, kind)
            if self._inputs[key] not in {r["value"] for r in self._choices[key]}:
                self._inputs[key] = ""
                if key in {"dataset", "checkpoint"}:
                    self.invalidate_resume()
        signature = (self.controller.draft or value.document).settings.model_dump_json()
        if self._signature != signature or self.controller.request is None:
            self._signature = signature
            self.controller.request = self.controller.reconstruction_plan = None
            self.controller.configure_reconstruction()
        self.changed.emit()

    def completed(self, name: str, value) -> None:
        if (
            name in {"reconstruction_plan", "dataset_plan", "training_plan", "trainer_capability"}
            and self._pending.pop(name, None) != self._snapshot()
        ):
            return
        if name == "request_unavailable":
            self._messages["reconstruction"] = "Saved methods unavailable: " + str(value)
        elif name == "request":
            self._messages["reconstruction"] = (
                "Saved methods loaded. Plan verifies runtime capability."
            )
        elif name == "validation_details":
            if str(value[0]) != self._inputs["validation"]:
                return
            self._report, self._metrics = value[1:]
            self._messages["validation"] = (
                f"{self._report.status.value.upper()} · "
                f"{self._metrics.registration.registered_views} / "
                f"{self._metrics.registration.input_views} registered views · "
                f"{self._metrics.component_count} components"
            )
            self._details["validation"] = render(
                {"report": plain(self._report), "metrics": plain(self._metrics)}
            )
        elif name in {"reconstruction_plan", "dataset_plan", "training_plan"}:
            key = name.removesuffix("_plan")
            data = plain(value)
            self._plans[key] = data
            self._details[key] = render(value)
            self._messages[key] = "Plan ready" if data.get("runnable") else "Plan needs attention"
        elif name in {"reconstruction", "selection", "dataset", "training"}:
            self._details[name] = render(value)
            data = plain(value)
            status = data.get("status", "Finished — inspect published evidence")
            self._messages[name] = str(status).replace("_", " ").capitalize()
        elif name == "trainer_capability":
            self._capability = value
            self._details["runtime"] = render(value)
        elif (
            name == "resume_check"
            and self._resume_token is not None
            and value.get("request_token") == self._resume_token
        ):
            self._resume_ready = bool(value["compatible"])
            self._resume_reason = value["reason"]
        self.changed.emit()

    def failed(self, error) -> None:
        self._pending.pop(error.stage, None)
        page = (
            "training"
            if error.stage in {"trainer_capability", "resume_check"}
            else error.stage.removesuffix("_plan")
        )
        self._messages[page] = error.message
        self.changed.emit()
