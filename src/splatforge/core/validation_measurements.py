"""Deterministic streaming M9 measurements over normalized public records."""

from __future__ import annotations

import hashlib
import heapq
import math
from collections import Counter
from collections.abc import Callable
from uuid import UUID

from splatforge.core.features import digest_json
from splatforge.core.reconstruction import (
    ReconstructionCamera,
    ReconstructionComponent,
    ReconstructionSet,
    numerical_bytes,
)
from splatforge.core.reconstruction_validation import (
    MAX_VALIDATION_METADATA_BYTES,
    CameraModelCount,
    ComponentCoverage,
    ComponentGeometryIdentity,
    ComponentMetrics,
    GroupCoverage,
    Measurement,
    MeasurementSettings,
    MetricAvailability,
    MetricValue,
    ReconstructionMetrics,
    SamplingEvidence,
    TrackLengthBin,
    ValidationCamera,
    ValidationComponentInput,
    ValidationGeometryInput,
    ValidationGeometrySource,
    ValidationPoint,
    ValidationResourceLimits,
    ValidationUniverse,
    coverage,
    exact,
    require_measurement_resources,
    unavailable,
)
from splatforge.core.views import canonical_json_bytes

SUPPORTED_PROJECTIONS = frozenset(
    {
        "SIMPLE_PINHOLE",
        "PINHOLE",
        "SIMPLE_RADIAL",
        "RADIAL",
        "OPENCV",
        "FULL_OPENCV",
    }
)


def point_digest(point: ValidationPoint) -> bytes:
    digest = hashlib.sha256(b"validation.point.v1\0" + numerical_bytes(point.xyz))
    digest.update(b"no_tracks" if point.observations is None else b"tracks")
    for observation in point.observations or ():
        digest.update(observation.view_id.bytes)
        digest.update(observation.keypoint_index.to_bytes(8, "little"))
        digest.update(numerical_bytes(observation.xy))
    return digest.digest()


def _component_geometry_hasher(component_digest: str, data: ValidationComponentInput):
    digest = hashlib.sha256(b"validation.geometry.v1\0")
    digest.update(bytes.fromhex(component_digest))
    digest.update(bytes((data.points_available, data.tracks_available)))
    return digest


def _reference_digest(data: ValidationComponentInput) -> str:
    digest = hashlib.sha256(b"validation.frozen_camera_references.v1\0")
    for prior in sorted(data.priors, key=lambda p: p.view_id.int):
        digest.update(prior.view_id.bytes + prior.model.encode("ascii") + b"\0")
        digest.update(numerical_bytes((prior.width, prior.height, *prior.parameters)))
    sharing: dict[tuple[bool, UUID], list[str]] = {}
    for prior in sorted(data.priors, key=lambda p: p.view_id.int):
        sharing.setdefault(prior.sharing_key(), []).append(str(prior.view_id))
    digest.update(bytes.fromhex(digest_json(sorted(sharing.values()))))
    return digest.hexdigest()


def geometry_identity(
    reconstruction: ReconstructionSet,
    source: ValidationGeometrySource,
    checkpoint: Callable[[], None] = lambda: None,
    progress: Callable[[int, int], None] = lambda _p, _o: None,
) -> ValidationGeometryInput:
    components = []
    scanned = observations = 0
    for component in reconstruction.components:
        data = source.component(component.component_id)
        require_component(component, data)
        digest = _component_geometry_hasher(component.semantic_digest, data)
        member_ids = set(component.registered_view_ids)
        count = 0
        previous = b""
        if data.points_available:
            for point in source.points(component.component_id):
                checkpoint()
                identity = point_digest(point)
                if identity < previous:
                    raise ValueError("validation.corrupt_geometry: noncanonical point stream")
                previous = identity
                if data.tracks_available != (point.observations is not None):
                    raise ValueError("validation.corrupt_geometry: track capability mismatch")
                if any(o.view_id not in member_ids for o in point.observations or ()):
                    raise ValueError("validation.corrupt_geometry: unknown observation view")
                digest.update(identity)
                count += 1
                scanned += 1
                observations += len(point.observations or ())
                progress(scanned, observations)
            if component.point_count is not None and count != component.point_count:
                raise ValueError("validation.corrupt_geometry: point count mismatch")
        checkpoint()
        components.append(
            ComponentGeometryIdentity(
                component_id=component.component_id,
                component_semantic_digest=component.semantic_digest,
                content_digest=digest.hexdigest(),
                reference_digest=_reference_digest(data),
                points_available=data.points_available,
                tracks_available=data.tracks_available,
                point_count=count if data.points_available else component.point_count,
            )
        )
    return ValidationGeometryInput(
        reconstruction_digest=reconstruction.semantic_digest, components=tuple(components)
    )


def require_component(component: ReconstructionComponent, data: ValidationComponentInput) -> None:
    from splatforge.core.reconstruction import component_semantic_digest

    if (
        data.component_id != component.component_id
        or tuple(v.view_id for v in data.views) != component.registered_view_ids
        or component_semantic_digest(data.cameras, data.views, point_count=component.point_count)
        != component.semantic_digest
    ):
        raise ValueError("validation.corrupt_geometry: camera/pose/component evidence differs")


def project(
    camera: ReconstructionCamera | ValidationCamera, xyz: tuple[float, float, float]
) -> tuple[float, float] | None:
    """COLMAP ordinary perspective equations; unsupported/undefined stays unknown."""
    if camera.model not in SUPPORTED_PROJECTIONS or xyz[2] <= 0:
        return None
    x, y = xyz[0] / xyz[2], xyz[1] / xyz[2]
    p = camera.parameters
    dual = camera.model in {"PINHOLE", "OPENCV", "FULL_OPENCV"}
    fx, fy = p[0], p[1] if dual else p[0]
    cx, cy = p[2:4] if dual else p[1:3]
    r2 = x * x + y * y
    radial = 1.0
    dx = dy = 0.0
    if camera.model in {"SIMPLE_RADIAL", "RADIAL"}:
        radial += p[3] * r2
        if camera.model == "RADIAL":
            radial += p[4] * r2 * r2
    elif camera.model in {"OPENCV", "FULL_OPENCV"}:
        k1, k2, p1, p2 = p[4:8]
        radial += k1 * r2 + k2 * r2**2
        if camera.model == "FULL_OPENCV":
            k3, k4, k5, k6 = p[8:12]
            denominator = 1 + k4 * r2 + k5 * r2**2 + k6 * r2**3
            if denominator == 0:
                return None
            radial = (radial + k3 * r2**3) / denominator
        dx = 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        dy = 2 * p2 * x * y + p1 * (r2 + 2 * y * y)
    result = (fx * (x * radial + dx) + cx, fy * (y * radial + dy) + cy)
    return result if all(math.isfinite(v) for v in result) else None


class Distribution:
    """O(bound) bottom-k sample; exact deterministic canonical-stream moments."""

    def __init__(self, bound: int) -> None:
        self.bound = bound
        self.count = 0
        self.total = self.squares = 0.0
        self.minimum = self.maximum = None
        self.sample: list[tuple[int, float]] = []

    def add(self, identity: bytes, value: float) -> None:
        if not math.isfinite(value):
            raise ValueError("validation.corrupt_geometry: non-finite derived measurement")
        self.count += 1
        self.total += value
        self.squares += value * value
        if not math.isfinite(self.total) or not math.isfinite(self.squares):
            raise ValueError("validation.corrupt_geometry: measurement accumulator overflow")
        self.minimum = value if self.minimum is None else min(value, self.minimum)
        self.maximum = value if self.maximum is None else max(value, self.maximum)
        item = (-int.from_bytes(hashlib.sha256(identity).digest(), "big"), value)
        if len(self.sample) < self.bound:
            heapq.heappush(self.sample, item)
        elif item > self.sample[0]:
            heapq.heapreplace(self.sample, item)

    def values(self, *, approximation: SamplingEvidence | None = None) -> dict[str, MetricValue]:
        if not self.count:
            return {
                n: unavailable("empty_population")
                for n in ("min", "max", "mean", "rms", "median", "p90", "p95", "p99")
            }

        def value(v, sampling=None):
            return (
                MetricValue(availability=MetricAvailability.SAMPLED, value=v, sampling=sampling)
                if sampling
                else exact(v)
            )

        result = {
            "min": value(self.minimum, approximation),
            "max": value(self.maximum, approximation),
            "mean": value(self.total / self.count, approximation),
            "rms": value(math.sqrt(self.squares / self.count), approximation),
        }
        ordered = sorted(v for _key, v in self.sample)
        sampled = self.count > len(ordered)
        sampling = (
            SamplingEvidence(
                method="sha256_bottom_k_v1",
                sample_count=len(ordered),
                population_count=self.count,
                upstream=approximation,
            )
            if sampled
            else approximation
        )
        for name, q in (("median", 0.5), ("p90", 0.9), ("p95", 0.95), ("p99", 0.99)):
            result[name] = value(ordered[max(0, math.ceil(q * len(ordered)) - 1)], sampling)
        return result


def camera_measurements(
    data: ValidationComponentInput, universe: ValidationUniverse
) -> dict[str, MetricValue]:
    cameras = {c.camera_id: c for c in data.cameras}
    priors = {p.view_id: p for p in data.priors}
    ratios, principal, extra, changes = [], [], [], []
    supported = all(c.model in SUPPORTED_PROJECTIONS for c in data.cameras)
    final_groups: dict[UUID, set[tuple[bool, UUID]]] = {}
    original_groups: dict[tuple[bool, UUID], set[UUID]] = {}
    missing_sharing = False
    for c in data.cameras:
        if c.model not in SUPPORTED_PROJECTIONS:
            continue
        dual = c.model in {"PINHOLE", "OPENCV", "FULL_OPENCV"}
        p = c.parameters
        ratios.extend(f / max(c.width, c.height) for f in (p[:2] if dual else p[:1]))
        cx, cy = p[2:4] if dual else p[1:3]
        principal.append(max(abs(cx / c.width - 0.5), abs(cy / c.height - 0.5)))
        # Only declared ordinary models have these extra distortion parameters.
        extra.append(max((abs(v) for v in p[4 if dual else 3 :]), default=0.0))
    missing_prior = False
    for v in data.views:
        c, prior = cameras[v.camera_id], priors.get(v.view_id)
        if prior is None:
            missing_sharing = True
        else:
            group = prior.sharing_key()
            final_groups.setdefault(v.camera_id, set()).add(group)
            original_groups.setdefault(group, set()).add(v.camera_id)
        if prior is None or prior.model != c.model or c.model not in SUPPORTED_PROJECTIONS:
            missing_prior = True
        else:
            dual = c.model in {"PINHOLE", "OPENCV", "FULL_OPENCV"}
            changes.extend(
                abs(c.parameters[i] / prior.parameters[i] - 1) for i in range(2 if dual else 1)
            )
    result = {
        "camera.focal_ratio_min": exact(min(ratios))
        if supported
        else unavailable("unknown_camera_interpretation"),
        "camera.focal_ratio_max": exact(max(ratios))
        if supported
        else unavailable("unknown_camera_interpretation"),
        "camera.principal_offset_max": exact(max(principal))
        if supported
        else unavailable("unknown_camera_interpretation"),
        "camera.distortion_abs_max": exact(max(extra))
        if supported
        else unavailable("unknown_camera_interpretation"),
        "camera.focal_change_max": exact(max(changes))
        if changes and not missing_prior
        else unavailable("missing_camera_prior"),
        "camera.sharing_mismatch_count": exact(
            sum(len(g) > 1 for g in final_groups.values())
            + sum(len(g) > 1 for g in original_groups.values())
        )
        if not missing_sharing
        else unavailable("missing_camera_prior"),
    }
    return result


def _track_quantile(histogram: Counter, q: float) -> int:
    target, total = math.ceil(sum(histogram.values()) * q), 0
    for length, count in sorted(histogram.items()):
        total += count
        if total >= target:
            return length
    raise ValueError("Empty track histogram")


def _measure_component(
    data: ValidationComponentInput,
    source: ValidationGeometrySource,
    settings: MeasurementSettings,
    universe: ValidationUniverse,
    checkpoint: Callable[[], None],
    progress: Callable[[int, int], None],
    geometry_hasher,
):
    metrics = camera_measurements(data, universe)
    hist: Counter[int] = Counter()
    reprojection, angles = (
        Distribution(settings.quantile_sample_bound),
        Distribution(settings.quantile_sample_bound),
    )
    cameras = {c.camera_id: c for c in data.cameras}
    views = {v.view_id: v for v in data.views}
    centers = {v.view_id: v.pose.camera_center() for v in data.views}
    points = observations = undefined = unsupported = low = 0
    bounded = False
    sample_pairs = population_pairs = 0
    if data.points_available:
        for point in source.points(data.component_id):
            checkpoint()
            points += 1
            identity = point_digest(point)
            geometry_hasher.update(identity)
            if data.tracks_available:
                track = point.observations
                if track is None:
                    raise ValueError("validation.corrupt_geometry: declared tracks absent")
                hist[len(track)] += 1
                rays = []
                for o in track:
                    checkpoint()
                    observations += 1
                    view = views[o.view_id]
                    camera = cameras[view.camera_id]
                    r, t = view.pose.rotation_matrix(), view.pose.translation
                    xyz = tuple(
                        sum(a * b for a, b in zip(row, point.xyz, strict=True)) + offset
                        for row, offset in zip(r, t, strict=True)
                    )
                    if camera.model not in SUPPORTED_PROJECTIONS:
                        unsupported += 1
                    else:
                        try:
                            uv = project(camera, xyz)
                        except (OverflowError, ZeroDivisionError):
                            uv = None
                        if uv is None:
                            undefined += 1
                        else:
                            error = math.hypot(uv[0] - o.xy[0], uv[1] - o.xy[1])
                            reprojection.add(
                                identity + o.view_id.bytes + o.keypoint_index.to_bytes(8, "little"),
                                error,
                            )
                    ray = tuple(a - b for a, b in zip(point.xyz, centers[o.view_id], strict=True))
                    norm = math.hypot(*ray)
                    if norm > 0:
                        key = -int.from_bytes(hashlib.sha256(o.view_id.bytes).digest(), "big")
                        candidate = (key, tuple(x / norm for x in ray))
                        if len(rays) < settings.triangulation_ray_bound:
                            heapq.heappush(rays, candidate)
                        elif candidate > rays[0]:
                            heapq.heapreplace(rays, candidate)
                # Work is O(track length log K + K^2), never O(track length^2).
                candidates = sorted(rays)
                population_pairs += len(track) * (len(track) - 1) // 2
                sample_pairs += len(candidates) * (len(candidates) - 1) // 2
                bounded |= len(track) > len(candidates)
                if len(candidates) >= 2:
                    angle = max(
                        math.degrees(
                            math.acos(
                                min(1, abs(sum(a * b for a, b in zip(left, right, strict=True))))
                            )
                        )
                        for i, (_key, left) in enumerate(candidates)
                        for _other, right in candidates[i + 1 :]
                    )
                    angles.add(identity, angle)
                    low += angle < settings.low_angle_degrees
            progress(points, observations)
    metrics["point.count"] = exact(points) if data.points_available else unavailable("no_points")
    reason = "no_tracks" if not data.tracks_available else "empty_population"
    metrics["track.observation_count"] = (
        exact(observations) if data.tracks_available else unavailable(reason)
    )
    metrics["track.observations_per_view"] = (
        exact(observations / len(views)) if data.tracks_available else unavailable(reason)
    )
    track_values = {
        "min": min(hist) if hist else None,
        "max": max(hist) if hist else None,
        "mean": observations / points if points else None,
        "median": _track_quantile(hist, 0.5) if hist else None,
        "p90": _track_quantile(hist, 0.9) if hist else None,
        "two_view_count": hist[2],
        "two_view_fraction": hist[2] / points if points else None,
        "long_count": sum(
            n for length, n in hist.items() if length >= settings.long_track_min_length
        ),
    }
    track_values["long_fraction"] = track_values["long_count"] / points if points else None
    for name, v in track_values.items():
        metrics["track." + name] = (
            exact(v) if v is not None and data.tracks_available else unavailable(reason)
        )
    reproj_values = reprojection.values()
    metrics["reprojection.supported_observation_count"] = (
        exact(reprojection.count) if data.tracks_available else unavailable("no_tracks")
    )
    metrics["reprojection.undefined_observation_count"] = (
        exact(undefined) if data.tracks_available else unavailable("no_tracks")
    )
    for name, v in reproj_values.items():
        metrics["reprojection_supported." + name] = (
            v if data.tracks_available else unavailable("no_tracks")
        )
        metrics["reprojection." + name] = (
            unavailable("no_tracks")
            if not data.tracks_available
            else unavailable("partial_projection_support")
            if unsupported
            else unavailable("undefined_projection")
            if undefined
            else v
        )
    approximation = (
        SamplingEvidence(
            method="uuid_bounded_rays_v1",
            sample_count=sample_pairs,
            population_count=population_pairs,
        )
        if bounded and sample_pairs
        else None
    )
    for name, v in angles.values(approximation=approximation).items():
        metrics["triangulation." + name] = v if data.tracks_available else unavailable("no_tracks")
    metrics["triangulation.point_count"] = (
        exact(angles.count) if data.tracks_available else (unavailable("no_tracks"))
    )
    metrics["triangulation.unmeasurable_point_count"] = (
        exact(points - angles.count) if data.tracks_available else unavailable("no_tracks")
    )
    for name, value in (
        ("low_angle_count", low),
        ("low_angle_fraction", low / angles.count if angles.count else None),
    ):
        metrics["triangulation." + name] = (
            unavailable(reason)
            if value is None or not data.tracks_available
            else MetricValue(availability="sampled", value=value, sampling=approximation)
            if approximation
            else exact(value)
        )

    def unit(name):
        if name.endswith("count") or name in {
            "track.min",
            "track.max",
            "track.mean",
            "track.median",
            "track.p90",
        }:
            return "count"
        if name.startswith("reprojection"):
            return "pixels"
        if name == "track.observations_per_view":
            return "observations_per_view"
        if name.startswith("triangulation.") and not name.endswith("fraction"):
            return "degrees"
        return "ratio"

    return (
        tuple(Measurement(name=k, unit=unit(k), evidence=v) for k, v in sorted(metrics.items())),
        tuple(TrackLengthBin(length=k, count=v) for k, v in sorted(hist.items())),
        tuple(
            CameraModelCount(model=k, count=v)
            for k, v in sorted(Counter(c.model for c in data.cameras).items())
        ),
    )


def measure_reconstruction(
    reconstruction: ReconstructionSet,
    universe: ValidationUniverse,
    geometry: ValidationGeometryInput,
    source: ValidationGeometrySource,
    settings: MeasurementSettings,
    checkpoint: Callable[[], None] = lambda: None,
    progress: Callable[[int, int], None] = lambda _p, _o: None,
    *,
    resource_limits: ValidationResourceLimits | None = None,
) -> ReconstructionMetrics:
    universe.require_reconstruction(reconstruction)
    require_measurement_resources(
        reconstruction, universe, resource_limits or ValidationResourceLimits()
    )
    if geometry.reconstruction_digest != reconstruction.semantic_digest:
        raise ValueError("validation.input_mismatch: stale geometry identity")
    all_registered = {v for c in reconstruction.components for v in c.registered_view_ids}
    component_for_view = {
        v: c.component_id for c in reconstruction.components for v in c.registered_view_ids
    }
    total = len(universe.views)
    identities = {c.component_id: c for c in geometry.components}
    components = []
    metadata = {v.view_id: v for v in universe.views}
    scanned = observed = 0
    component_metadata_bytes = 0
    for c in reconstruction.components:
        checkpoint()
        data = source.component(c.component_id)
        require_component(c, data)
        identity = identities[c.component_id]
        if _reference_digest(data) != identity.reference_digest:
            raise ValueError("validation.input_mismatch: frozen camera references changed")
        hasher = _component_geometry_hasher(c.semantic_digest, data)
        measurements, histogram, models = _measure_component(
            data,
            source,
            settings,
            universe,
            checkpoint,
            lambda p, o, s=scanned, n=observed: progress(s + p, n + o),
            hasher,
        )
        if hasher.hexdigest() != identity.content_digest:
            raise ValueError(
                "validation.input_mismatch: detailed geometry changed during measurement"
            )
        if not data.points_available and c.point_count is not None:
            measurements = tuple(
                m.model_copy(update={"evidence": exact(c.point_count)})
                if m.name == "point.count"
                else m
                for m in measurements
            )
        scanned += identity.point_count or 0
        observation = next(m.evidence for m in measurements if m.name == "track.observation_count")
        observed += int(observation.value or 0)
        members = [metadata[v] for v in c.registered_view_ids]
        component_metrics = ComponentMetrics(
            component_id=c.component_id,
            component_semantic_digest=c.semantic_digest,
            geometry_digest=identity.content_digest,
            registration=coverage(total, len(members)),
            source_count=len({v.source_id for v in members}),
            source_group_count=len({v.source_group_id for v in members}),
            camera_group_count=len({v.camera_group_id for v in members}),
            camera_models=models,
            track_histogram=histogram,
            measurements=measurements,
        )
        component_metadata_bytes += len(
            canonical_json_bytes(component_metrics.model_dump(mode="json"))
        )
        if component_metadata_bytes > MAX_VALIDATION_METADATA_BYTES:
            raise ValueError("validation.resource_limit: component metric metadata exceeds 64 MiB")
        components.append(component_metrics)

    def groups(attribute: str) -> tuple[GroupCoverage, ...]:
        inputs: Counter[UUID] = Counter()
        registered: Counter[UUID] = Counter()
        in_component: Counter[tuple[UUID, UUID]] = Counter()
        for v in universe.views:
            group = getattr(v, attribute)
            inputs[group] += 1
            component_id = component_for_view.get(v.view_id)
            if component_id is not None:
                registered[group] += 1
                in_component[group, component_id] += 1

        def group_record(key: UUID) -> GroupCoverage:
            checkpoint()
            return GroupCoverage(
                group_id=key,
                overall=coverage(inputs[key], registered[key]),
                components=tuple(
                    ComponentCoverage(
                        component_id=c.component_id,
                        coverage=coverage(inputs[key], in_component[key, c.component_id]),
                    )
                    for c in reconstruction.components
                ),
            )

        return tuple(group_record(key) for key in sorted(inputs, key=lambda value: value.int))

    sizes = tuple(
        sorted((c.registered_view_count for c in reconstruction.components), reverse=True)
    )
    return ReconstructionMetrics(
        reconstruction_digest=reconstruction.semantic_digest,
        universe_digest=universe.semantic_digest,
        geometry=geometry,
        settings=settings,
        registration=coverage(total, len(all_registered)),
        unregistered_count=total - len(all_registered),
        component_count=len(components),
        component_sizes=sizes,
        largest_component=coverage(total, sizes[0]),
        second_largest_component=coverage(total, sizes[1]) if len(sizes) > 1 else None,
        registered_outside_largest_fraction=(len(all_registered) - sizes[0]) / len(all_registered),
        sources=groups("source_id"),
        source_groups=groups("source_group_id"),
        components=tuple(components),
    )
