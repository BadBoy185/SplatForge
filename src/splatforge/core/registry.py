from __future__ import annotations

from collections import defaultdict

from splatforge.core.models import MethodSpec, PipelineConfig, StageKind


class MethodRegistry:
    def __init__(self) -> None:
        self._methods: dict[str, MethodSpec] = {}
        self._by_stage: dict[StageKind, list[str]] = defaultdict(list)

    def register(self, method: MethodSpec) -> None:
        if method.id in self._methods:
            raise ValueError(f"Method already registered: {method.id}")
        self._methods[method.id] = method
        self._by_stage[method.stage].append(method.id)

    def get(self, method_id: str) -> MethodSpec:
        try:
            return self._methods[method_id]
        except KeyError as exc:
            raise KeyError(f"Unknown method: {method_id}") from exc

    def list(self, stage: StageKind | None = None) -> tuple[MethodSpec, ...]:
        if stage is None:
            return tuple(self._methods.values())
        return tuple(self._methods[mid] for mid in self._by_stage[stage])

    def validate_pipeline(self, config: PipelineConfig) -> None:
        extractor = self.get(config.sfm.feature_extractor_id)
        pair_selector = self.get(config.sfm.pair_selector_id)
        matcher = self.get(config.sfm.feature_matcher_id)
        mapper = self.get(config.sfm.mapper_id)
        trainer = self.get(config.training.trainer_id)
        frame_selector = self.get(config.frame_selection.method_id)

        expected = (
            (extractor.id, StageKind.FEATURE_EXTRACTION),
            (pair_selector.id, StageKind.PAIR_SELECTION),
            (matcher.id, StageKind.FEATURE_MATCHING),
            (mapper.id, StageKind.MAPPING),
            (trainer.id, StageKind.TRAINING),
            (frame_selector.id, StageKind.FRAME_SELECTION),
        )
        for method_id, stage in expected:
            method = self.get(method_id)
            if method.stage is not stage:
                raise ValueError(f"{method_id} belongs to {method.stage}, expected {stage}")

        family = extractor.descriptor_family
        if matcher.accepts_descriptor_families and family not in matcher.accepts_descriptor_families:
            accepted = ", ".join(sorted(matcher.accepts_descriptor_families))
            raise ValueError(
                f"Incompatible feature pipeline: extractor {extractor.id} outputs "
                f"'{family}', but matcher {matcher.id} accepts: {accepted}"
            )
