"""Explicit hybrid-throughput estimator v1; no wall-clock rate calculations."""

from __future__ import annotations

import math
from collections import deque
from statistics import median

from splatforge.core.progress import (
    Confidence,
    EstimatorEvidence,
    EtaEstimate,
    EvidenceMode,
    PerformanceSample,
    PlannedStage,
    ProgressMode,
    StageProgressObservation,
)


def quantile(values: list[float], fraction: float) -> float:
    """Linear empirical quantile, including deterministic singleton behavior."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    left = math.floor(position)
    right = math.ceil(position)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def workload_similarity(stage: PlannedStage, sample: PerformanceSample) -> float:
    """Exact categories, then mean log2 distance; 2x scale alone scores 0.8."""
    if sample.signature != stage.signature or stage.work.total is None:
        return 0
    historical = {metric.name: metric.value for metric in sample.workload}
    remaining_work = stage.work.total - stage.work.initial_completed
    distances = [abs(math.log2(max(remaining_work, 1e-9) / sample.total_work))]
    for metric in stage.workload:
        previous = historical.get(metric.name)
        if previous is None:
            return 0
        if previous == metric.value == 0:
            continue
        distances.append(abs(math.log2(max(metric.value, 1e-9) / max(previous, 1e-9))))
    return 1 / (1 + sum(distances) / len(distances) / 4)


def zero_eta() -> EtaEstimate:
    return EtaEstimate(
        likely_seconds=0,
        lower_seconds=0,
        upper_seconds=0,
        confidence=Confidence.HIGH,
        evidence_mode=EvidenceMode.LIVE,
        reasons=("complete",),
    )


class HybridThroughputEstimator:
    """Rules are frozen by deterministic tests; changes require a new estimator ID.

    History: exact categorical signature; similarity >= .25, median and q10/q90.
    Live: at least 1s, cumulative rate blended 50/50 with EWMA(alpha=.2).
    Interval spikes clamp to [previous/4, previous*4]; recent contribution additionally
    clamps to [cumulative/2, cumulative*2]. Prior weight decays with fraction, time,
    and observation count. Planning ranges widen for dispersion and weak similarity.
    """

    def __init__(self, stage: PlannedStage, samples: tuple[PerformanceSample, ...] = ()) -> None:
        self.stage = stage
        self._matched = [
            (sample, workload_similarity(stage, sample))
            for sample in samples
            if workload_similarity(stage, sample) >= 0.25
        ]
        self._last: StageProgressObservation | None = None
        self._recent: float | None = None
        self._rates: deque[float] = deque(maxlen=16)
        self._intervals = 0
        self._last_positive_elapsed = 0.0

    def observe(self, observation: StageProgressObservation) -> None:
        if observation.work != self.stage.work:
            raise ValueError("Observation differs from the stable work plan; revise explicitly")
        previous = self._last
        if previous is not None:
            if observation.elapsed_seconds < previous.elapsed_seconds:
                raise ValueError("Monotonic elapsed evidence went backwards")
            if observation.completed < previous.completed:
                raise ValueError("Completed work went backwards within a stable plan")
            duration = observation.elapsed_seconds - previous.elapsed_seconds
            delta = observation.completed - previous.completed
            if duration > 0 and delta > 0:
                self._last_positive_elapsed = observation.elapsed_seconds
                raw = delta / duration
                bounded = (
                    raw
                    if self._recent is None
                    else min(self._recent * 4, max(self._recent / 4, raw))
                )
                self._recent = (
                    bounded if self._recent is None else (0.8 * self._recent + 0.2 * bounded)
                )
                self._rates.append(raw)
                self._intervals += 1
        self._last = observation

    @property
    def throughput(self) -> float | None:
        observation = self._last
        if observation is None or observation.elapsed_seconds < 1:
            return None
        performed = observation.completed - self.stage.work.initial_completed
        if performed <= 0:
            return None
        cumulative = performed / observation.elapsed_seconds
        recent = self._recent if self._recent is not None else cumulative
        recent = min(cumulative * 2, max(cumulative / 2, recent))
        return (recent + cumulative) / 2

    def estimate(self) -> EtaEstimate:
        work = self.stage.work
        phase_job = work.mode == ProgressMode.PHASE and work.historical_job_duration
        if (work.mode != ProgressMode.DETERMINATE and not phase_job) or work.total is None:
            return EtaEstimate(reasons=("unknown_total",))
        observation = self._last
        completed = observation.completed if observation is not None else 0
        if completed >= work.total:
            return zero_eta()
        fraction = completed / work.total if work.total else 0
        live = self.throughput if work.mode == ProgressMode.DETERMINATE else None
        count = len(self._matched)
        similarity = median([score for _, score in self._matched]) if count else 0
        rates = [sample.throughput for sample, _ in self._matched]
        central = median(rates) if rates else None
        spread = quantile(rates, 0.9) / max(quantile(rates, 0.1), 1e-9) if rates else None
        reasons: list[str] = []
        if central is None and live is None:
            return EtaEstimate(reasons=("no_compatible_history", "live_warmup"))
        weight = 0.0
        if live is not None:
            weight = (
                1
                if central is None
                else min(0.95, fraction * 1.5)
                * min(1, observation.elapsed_seconds / 5)
                * min(1, self._intervals / 3)
            )
        rate = (central or live) * (1 - weight) + (live or central) * weight
        remaining = work.total - completed
        likely = remaining / rate
        if central is not None:
            # Sparse history must never look like a precise interval.
            widening = max(1.1 if count >= 5 else 1.5 if count >= 2 else 2, 1 / similarity)
            historical_lower = quantile(rates, 0.1) / widening
            historical_upper = quantile(rates, 0.9) * widening
            reasons.append("few_samples" if count < 5 else "historical_evidence")
            if similarity < 0.9:
                reasons.append("scaled_workload")
            if spread > 2:
                reasons.append("variable_history")
        else:
            historical_lower = historical_upper = live
        live_spread = (
            quantile(list(self._rates), 0.9) / max(quantile(list(self._rates), 0.1), 1e-9)
            if self._rates
            else 1
        )
        stalled = (
            observation is not None
            and live is not None
            and (
                observation.elapsed_seconds - self._last_positive_elapsed
                > max(5, observation.elapsed_seconds * 0.1)
            )
        )
        live_widening = max(
            1.2, min(4, live_spread), 2 if self._intervals < 3 else 1.2, 4 if stalled else 1
        )
        lower_rate = historical_lower * (1 - weight) + (live or rate) / live_widening * weight
        upper_rate = historical_upper * (1 - weight) + (live or rate) * live_widening * weight
        confidence = Confidence.LOW
        if count >= 3 and similarity >= 0.65 and spread <= 2:
            confidence = Confidence.MEDIUM
        if count >= 8 and similarity >= 0.9 and spread <= 1.3:
            confidence = Confidence.HIGH
        stable_live = self._intervals >= 4 and live_spread <= 1.5 and fraction >= 0.2
        if stable_live:
            reasons.append("stable_live")
            confidence = Confidence.MEDIUM
            if fraction >= 0.6 and self._intervals >= 8 and live_spread <= 1.2:
                confidence = Confidence.HIGH
        if live is not None and live_spread > 3 and weight >= 0.5:
            confidence = Confidence.LOW
            reasons.append("variable_live")
        if stalled:
            confidence = Confidence.LOW
            reasons.append("live_stalled")
        if self.stage.signature.hardware.cpu_family == "unknown" or (
            self.stage.signature.hardware.device == "unknown"
        ):
            confidence = Confidence.LOW
            reasons.append("hardware_unknown")
        if work.mode == ProgressMode.PHASE:
            confidence = min(confidence, Confidence.MEDIUM,
                             key=(Confidence.UNAVAILABLE, Confidence.LOW, Confidence.MEDIUM,
                                  Confidence.HIGH).index)
            reasons.append("phase_only_historical_planning")
        return EtaEstimate(
            likely_seconds=likely,
            lower_seconds=min(likely, remaining / upper_rate),
            upper_seconds=max(likely, remaining / lower_rate),
            confidence=confidence,
            evidence_mode=(
                EvidenceMode.HYBRID
                if central is not None and live is not None
                else EvidenceMode.HISTORICAL
                if central is not None
                else EvidenceMode.LIVE
            ),
            sample_count=count,
            reasons=tuple(reasons),
            evidence=EstimatorEvidence(
                similarity_score=similarity,
                historical_median_throughput=central,
                historical_spread=spread,
                live_throughput=live,
                live_completed_fraction=fraction,
                live_weight=weight,
            ),
        )
