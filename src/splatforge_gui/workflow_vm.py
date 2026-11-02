"""Typed reconstruction/dataset/training state behind the QML presentation."""

from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from splatforge.core.dataset import DatasetSettings
from splatforge.core.execution import TrainingRuntime
from splatforge.core.features import descriptor_signature, resolve_extraction_settings
from splatforge.core.matching import resolve_matching_settings, validate_matcher_compatibility
from splatforge.core.pairs import ExhaustiveSettings, SequentialSettings
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
    MappingCalibrationPolicy,
    ViewGraphCalibrationSettings,
)
from splatforge.core.sfm_profiles import FeatureMatchingChoice, SfmQualityProfile
from splatforge.core.training import DefaultStrategySettings, MCMCStrategySettings, TrainingSettings
from splatforge_gui.presentation import guarded, plain, published_runs, render


_EXTRACTORS = (
    ("SIFT", "SIFT"),
    ("ALIKED N16ROT", "ALIKED_N16ROT"),
    ("ALIKED N32", "ALIKED_N32"),
    ("LoMa B", "LOMA_B"),
    ("LoMa B128", "LOMA_B128"),
)

_MATCHERS = {
    "SIFT": (
        ("SIFT brute-force", "SIFT_BRUTEFORCE"),
        ("LightGlue SIFT", "SIFT_LIGHTGLUE"),
    ),
    "ALIKED_N16ROT": (
        ("LightGlue ALIKED", "ALIKED_LIGHTGLUE"),
        ("ALIKED brute-force", "ALIKED_BRUTEFORCE"),
    ),
    "ALIKED_N32": (
        ("LightGlue ALIKED", "ALIKED_LIGHTGLUE"),
        ("ALIKED brute-force", "ALIKED_BRUTEFORCE"),
    ),
    "LOMA_B": (
        ("LoMa B", "LOMA_B"),
        ("LoMa R", "LOMA_R"),
        ("LoMa L", "LOMA_L"),
        ("LoMa G", "LOMA_G"),
        ("LoMa brute-force", "LOMA_BRUTEFORCE"),
    ),
    "LOMA_B128": (
        ("LoMa B128", "LOMA_B128"),
        ("LoMa brute-force", "LOMA_BRUTEFORCE"),
    ),
}

_DEFAULT_MATCHER = {
    "SIFT": "SIFT_BRUTEFORCE",
    "ALIKED_N16ROT": "ALIKED_LIGHTGLUE",
    "ALIKED_N32": "ALIKED_LIGHTGLUE",
    "LOMA_B": "LOMA_B",
    "LOMA_B128": "LOMA_B128",
}


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
        self._prepared_context = {}
        self._report, self._metrics = None, None
        self._signature, self._project_id = None, None
        self._source_intent = None
        self._resume_token, self._resume_ready, self._resume_reason = None, False, "Not checked"
        self._capability = None
        self._plans, self._details, self._messages = {}, {}, {}
        self._pending = {}
        self.controller.changed.connect(self.overview)
        self.controller.dirty_changed.connect(self._intent_changed)
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
                "sourceParticipation": self._source_signature(),
                "inputs": self._inputs,
                "machine": self.desktop._machine,
                "runtime_environment": self.runtime_environment,
                "request": plain(self.controller.request) if self.controller.request else None,
                "dataset": plain(self.dataset_settings),
                "training": plain(self.training_settings),
            }
        )

    @staticmethod
    def _matcher_choices(extractor) -> list[dict]:
        result = []
        for label, variant in _MATCHERS.get(extractor.variant, ()):
            try:
                matcher = resolve_matching_settings(variant, use_gpu=extractor.use_gpu)
                validate_matcher_compatibility(descriptor_signature(extractor), matcher)
            except ValueError:
                continue
            result.append({"label": label, "value": variant})
        return result

    @staticmethod
    def _mapping_value(settings, name: str, default=0):
        if hasattr(settings, name):
            return getattr(settings, name)
        cluster = getattr(settings, "cluster", None)
        return getattr(cluster, name, default) if cluster is not None else default

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
        extractor = request.features.extractor if request else None
        matcher = request.features.matcher if request else None
        verification = request.features.verification if request else None
        incremental = request.mapper if request and isinstance(request.mapper, IncrementalMapperSettings) else None
        prepared = {
            **self._prepared_context,
            "runId": str(request.views_run) if request and request.views_run else "",
        }
        if request and request.views_run and not prepared.get("label"):
            prepared["label"] = next(
                (v["label"] for v in self._choices["views"] if v["value"] == str(request.views_run)),
                "Published prepared set",
            )
        return {
            "inputs": self._inputs,
            "choices": self._choices,
            "requestAvailable": request is not None,
            "hasPreparedInput": bool(request and request.views_run),
            "preparedInput": prepared,
            "mapper": mapper,
            "profile": request.profile.value if request and request.profile else "",
            "profiles": [{"label": "Explicit methods", "value": ""}]
            + [
                {"label": p.value.title() + " · legacy profile", "value": p.value}
                for p in SfmQualityProfile
            ],
            "pairing": request.pairing.method_id if request else "",
            "pairingMode": (
                "exhaustive" if request and isinstance(request.pairing, ExhaustiveSettings)
                else "sequential" if request and isinstance(request.pairing, SequentialSettings)
                else "advanced"
            ),
            "pairForwardNeighbors": (
                request.pairing.forward_neighbors
                if request and isinstance(request.pairing, SequentialSettings) else 5
            ),
            "extractor": extractor.method_id if extractor else "Unavailable",
            "extractorVariant": extractor.variant if extractor else "",
            "extractorChoices": [{"label": label, "value": value} for label, value in _EXTRACTORS],
            "featureDevice": "gpu" if extractor and extractor.use_gpu else "cpu",
            "featureMaxFeatures": extractor.max_features if extractor else 0,
            "featureMaxImageSize": extractor.max_image_size if extractor else 0,
            "matcher": matcher.method_id if matcher else "Unavailable",
            "matcherVariant": matcher.variant if matcher else "",
            "matcherChoices": self._matcher_choices(extractor) if extractor else [],
            "matchingDevice": "gpu" if matcher and matcher.use_gpu else "cpu",
            "matchingThreads": matcher.num_threads if matcher else 1,
            "matchingMaxMatches": matcher.max_num_matches if matcher else 0,
            "verificationMinInliers": verification.min_num_inliers if verification else 0,
            "verificationMaxError": verification.max_error if verification else 0.0,
            "mappingThreads": getattr(request.mapper, "num_threads", 1) if request else 1,
            "mappingMinMatches": self._mapping_value(request.mapper, "min_num_matches", 0)
            if request else 0,
            "mappingMinModelSize": self._mapping_value(request.mapper, "min_model_size", 0)
            if request else 0,
            "baBackend": incremental.ba_global_backend.lower() if incremental else "",
            "baGpuIndex": incremental.ba_gpu_index if incremental else -1,
            "calibrationPolicy": request.calibration_policy.value if request else "preserve_priors",
            "frameSelection": (
                "Sharpest interval"
                if request and hasattr(request.selection, "reject_duplicates")
                else "Fixed interval"
            ) if request else "Unavailable",
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

    def _replace_request(self, **update) -> None:
        request = self.controller.request
        if request is None:
            return
        if any(key in update for key in ("features", "pairing", "mapper", "calibration_policy",
                                         "calibration_settings")):
            update.setdefault("profile", None)
        self.controller.request = type(request).model_validate(
            request.model_copy(update=update).model_dump()
        )
        self.controller.reconstruction_plan = None
        self._plans.pop("reconstruction", None)
        self._details.pop("reconstruction", None)
        self._messages["reconstruction"] = "Settings changed. Check the pipeline again."

    @Slot(str, int)
    @guarded
    def usePreparedRun(self, identity: str, selected_count: int) -> None:
        request = self.controller.request
        if request is None or not identity:
            return
        run_id = UUID(identity)
        self._inputs["views"] = identity
        self._prepared_context = {
            "selectedCount": max(0, int(selected_count)),
            "label": next(
                (v["label"] for v in self._choices["views"] if v["value"] == identity),
                "Reviewed prepared set",
            ),
        }
        update = {"views_run": run_id}
        pair_count = selected_count * (selected_count - 1) // 2
        if selected_count >= 2 and pair_count <= request.pair_limits.max_pairs:
            update["pairing"] = ExhaustiveSettings()
        self._replace_request(**update)
        self.changed.emit()

    @Slot(str, str)
    def chooseInput(self, kind: str, identity: str) -> None:
        if kind not in self._inputs or identity not in {r["value"] for r in self._choices[kind]}:
            return
        self._inputs[kind] = identity
        if kind == "views":
            self._prepared_context = {
                "label": next((r["label"] for r in self._choices[kind] if r["value"] == identity),
                              "Published prepared set")
            }
            self._replace_request(views_run=UUID(identity))
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
        if key == "mapper":
            cls = {
                "global": GlobalMapperSettings,
                "incremental": IncrementalMapperSettings,
                "hierarchical": HierarchicalMapperSettings,
            }[value]
            mapper = request.mapper if request.mapper.method_id == cls().method_id else cls()
            self._replace_request(mapper=mapper)
        elif key == "pairing":
            cls = {"sequential": SequentialSettings, "exhaustive": ExhaustiveSettings}[value]
            pairing = request.pairing if isinstance(request.pairing, cls) else cls()
            self._replace_request(pairing=pairing)
        elif key == "extractor":
            extractor = resolve_extraction_settings(
                value,
                max_image_size=request.features.extractor.max_image_size,
                use_gpu=request.features.extractor.use_gpu,
            )
            matcher_variant = request.features.matcher.variant
            if matcher_variant not in {item[1] for item in _MATCHERS.get(value, ())}:
                matcher_variant = _DEFAULT_MATCHER[value]
            matcher = resolve_matching_settings(
                matcher_variant,
                use_gpu=request.features.matcher.use_gpu,
                num_threads=request.features.matcher.num_threads,
                max_num_matches=request.features.matcher.max_num_matches,
            )
            self._replace_request(features=FeatureMatchingChoice(
                extractor=extractor, matcher=matcher, verification=request.features.verification
            ))
        elif key == "matcher":
            matcher = resolve_matching_settings(
                value,
                use_gpu=request.features.matcher.use_gpu,
                num_threads=request.features.matcher.num_threads,
                max_num_matches=request.features.matcher.max_num_matches,
            )
            self._replace_request(features=FeatureMatchingChoice(
                extractor=request.features.extractor,
                matcher=matcher,
                verification=request.features.verification,
            ))
        elif key == "feature_device":
            extractor = request.features.extractor.model_copy(update={"use_gpu": value == "gpu"})
            self._replace_request(features=FeatureMatchingChoice(
                extractor=extractor,
                matcher=request.features.matcher,
                verification=request.features.verification,
            ))
        elif key == "matching_device":
            matcher = request.features.matcher.model_copy(update={"use_gpu": value == "gpu"})
            self._replace_request(features=FeatureMatchingChoice(
                extractor=request.features.extractor,
                matcher=matcher,
                verification=request.features.verification,
            ))
        elif key == "ba_backend":
            if not isinstance(request.mapper, IncrementalMapperSettings):
                raise ValueError("Bundle-adjustment backend is configurable for Incremental mapping")
            backend = value.upper()
            mapper = request.mapper.model_copy(update={
                "ba_local_backend": backend,
                "ba_global_backend": backend,
                "ba_gpu_index": 0 if backend == "CASPAR" else -1,
            })
            self._replace_request(mapper=mapper)
        elif key == "calibration":
            policy = MappingCalibrationPolicy(value)
            calibration = request.calibration_settings
            if policy == MappingCalibrationPolicy.VIEW_GRAPH and calibration is None:
                calibration = ViewGraphCalibrationSettings()
            self._replace_request(calibration_policy=policy, calibration_settings=calibration)
        elif key == "profile":
            self._replace_request(profile=SfmQualityProfile(value) if value else None)
        self.changed.emit()

    @Slot(str, int)
    @guarded
    def setReconstructionInt(self, key: str, value: int) -> None:
        request = self.controller.request
        if request is None:
            return
        if key in {"feature_max_features", "feature_max_image_size"}:
            field = "max_features" if key == "feature_max_features" else "max_image_size"
            extractor = request.features.extractor.model_copy(update={field: int(value)})
            self._replace_request(features=FeatureMatchingChoice(
                extractor=extractor,
                matcher=request.features.matcher,
                verification=request.features.verification,
            ))
        elif key in {"matching_threads", "matching_max_matches"}:
            field = "num_threads" if key == "matching_threads" else "max_num_matches"
            matcher = request.features.matcher.model_copy(update={field: int(value)})
            self._replace_request(features=FeatureMatchingChoice(
                extractor=request.features.extractor,
                matcher=matcher,
                verification=request.features.verification,
            ))
        elif key == "pair_forward_neighbors":
            if not isinstance(request.pairing, SequentialSettings):
                raise ValueError("Forward neighbors apply only to Sequential pairing")
            self._replace_request(pairing=request.pairing.model_copy(update={"forward_neighbors": int(value)}))
        elif key == "verification_min_inliers":
            verification = request.features.verification.model_copy(update={"min_num_inliers": int(value)})
            self._replace_request(features=FeatureMatchingChoice(
                extractor=request.features.extractor,
                matcher=request.features.matcher,
                verification=verification,
            ))
        elif key in {"mapping_threads", "mapping_min_matches", "mapping_min_model_size"}:
            mapper = request.mapper
            if key == "mapping_threads":
                updates = {"num_threads": int(value)}
                if isinstance(mapper, HierarchicalMapperSettings):
                    updates["num_workers"] = min(mapper.num_workers, int(value))
                mapper = mapper.model_copy(update=updates)
            else:
                field = "min_num_matches" if key == "mapping_min_matches" else "min_model_size"
                if isinstance(mapper, HierarchicalMapperSettings):
                    mapper = mapper.model_copy(
                        update={"cluster": mapper.cluster.model_copy(update={field: int(value)})}
                    )
                else:
                    mapper = mapper.model_copy(update={field: int(value)})
            self._replace_request(mapper=mapper)
        elif key == "ba_gpu_index":
            if not isinstance(request.mapper, IncrementalMapperSettings):
                raise ValueError("GPU index applies only to Incremental Caspar")
            self._replace_request(mapper=request.mapper.model_copy(update={"ba_gpu_index": int(value)}))
        self.changed.emit()

    @Slot(str, float)
    @guarded
    def setReconstructionFloat(self, key: str, value: float) -> None:
        request = self.controller.request
        if request is None:
            return
        if key == "verification_max_error":
            verification = request.features.verification.model_copy(update={"max_error": float(value)})
            self._replace_request(features=FeatureMatchingChoice(
                extractor=request.features.extractor,
                matcher=request.features.matcher,
                verification=verification,
            ))
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
            if not self.controller.request or self.controller.request.views_run is None:
                self._pending.pop("reconstruction_plan", None)
                self._messages["reconstruction"] = (
                    "Choose a published prepared set before reconstruction. Prepare Data will not run again."
                )
                self.changed.emit()
                return
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
            self._prepared_context = {}
            self.invalidate_resume()
        for key, kind in {
            "validation": "validation.reconstruction_report",
            "selection": "reconstruction.selection",
            "dataset": "dataset.prepared_set",
            "checkpoint": "training.checkpoint",
            "views": "views.selected_set",
        }.items():
            self._choices[key] = published_runs(value, kind)
            allowed = {r["value"] for r in self._choices[key]}
            if self._inputs[key] not in allowed:
                self._inputs[key] = ""
                if key == "views" and self.controller.request and self.controller.request.views_run:
                    if str(self.controller.request.views_run) not in allowed:
                        self._replace_request(views_run=None)
                        self._prepared_context = {}
                if key in {"dataset", "checkpoint"}:
                    self.invalidate_resume()
        if self.controller.request and self.controller.request.views_run:
            identity = str(self.controller.request.views_run)
            if identity in {r["value"] for r in self._choices["views"]}:
                self._inputs["views"] = identity
        signature = (self.controller.draft or value.document).settings.model_dump_json()
        source_intent = self._source_signature()
        if self._source_intent != source_intent:
            self._source_intent = source_intent
            if self.controller.request is None or self.controller.request.views_run is None:
                self.controller.reconstruction_plan = None
                self._plans.pop("reconstruction", None)
                self._details.pop("reconstruction", None)
                self._messages["reconstruction"] = "Source selection changed. Check the pipeline again."
        if self._signature != signature or self.controller.request is None:
            self._signature = signature
            existing_views = self.controller.request.views_run if self.controller.request else None
            self.controller.request = self.controller.reconstruction_plan = None
            self._plans.pop("reconstruction", None)
            self.controller.configure_reconstruction()
            if existing_views and self.controller.request:
                self._replace_request(views_run=existing_views)
        self.changed.emit()

    def _source_signature(self) -> tuple:
        overview = self.controller.overview
        if overview is None or (self.controller.request is not None
                                and self.controller.request.views_run is not None):
            return ()
        document = self.controller.draft or overview.document
        return (document.source_participation.model_dump_json(),
                document.video_usage.model_dump_json(),
                tuple(str(s.identity) for s in overview.sources))

    def _intent_changed(self, _dirty: bool) -> None:
        if self.controller.overview is not None:
            self.overview(self.controller.overview)

    def completed(self, name: str, value) -> None:
        if (
            name in {"reconstruction_plan", "dataset_plan", "training_plan", "trainer_capability"}
            and self._pending.pop(name, None) != self._snapshot()
        ):
            if name == "reconstruction_plan":
                self.controller.reconstruction_plan = None
                self.changed.emit()
            return
        if name == "request_unavailable":
            self._messages["reconstruction"] = "Saved methods unavailable: " + str(value)
        elif name == "request":
            self._messages["reconstruction"] = (
                "Explicit reconstruction settings loaded. Choose a prepared set and check the pipeline."
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
            self._messages[key] = "Pipeline ready" if data.get("runnable") else "Pipeline needs attention"
        elif name in {"reconstruction", "selection", "dataset", "training"}:
            self._details[name] = render(value)
            data = plain(value)
            if name == "reconstruction" and data.get("validation_run"):
                self._inputs["validation"] = str(data["validation_run"])
                self._messages[name] = "Reconstruction complete. Review validation and select components."
            else:
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
