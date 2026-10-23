"""Tiny analytically defined M9 fixtures, no backend or original media needed."""

from uuid import UUID

from mapping_helpers import mapping_for
from test_reconstruction_identity import make_set

from splatforge.core.geometry import ViewCameraPrior
from splatforge.core.reconstruction import (
    ReconstructionCamera,
    ReconstructionComponent,
    ReconstructionPose,
    RegisteredView,
    component_semantic_digest,
    membership_id,
)
from splatforge.core.reconstruction_validation import (
    MeasurementSettings,
    ValidationComponentInput,
    ValidationObservation,
    ValidationPoint,
    ValidationUniverse,
    ValidationView,
)
from splatforge.core.validation_measurements import (
    geometry_identity,
    measure_reconstruction,
    point_digest,
    project,
)


class MemoryGeometry:
    def __init__(self, data, points):
        self.data, self.records = data, points

    def component(self, component_id):
        return self.data[component_id]

    def points(self, component_id):
        return iter(sorted(self.records[component_id], key=point_digest))


def scene(
    assignments=None,
    components=None,
    *,
    model="PINHOLE",
    parameters=None,
    baseline=1.0,
    errors=(0.0,),
    lengths=None,
    points_available=True,
    tracks_available=True,
    prior=True,
):
    assignments = assignments or [(1, 10), (3, 10), (5, 10)]
    members = components or [list(range(len(assignments)))]
    ids = tuple(UUID(int=i + 1) for i in range(len(assignments)))
    universe = ValidationUniverse(
        views=tuple(
            ValidationView(
                view_id=v,
                source_id=UUID(int=1000 + source),
                source_group_id=UUID(int=2000 + group),
                camera_group_id=UUID(int=3000 + source),
                media_type="video" if source % 2 else "photo",
            )
            for i, (v, (source, group)) in enumerate(zip(ids, assignments, strict=True))
        )
    )
    parameters = (
        parameters
        or {
            "SIMPLE_PINHOLE": (100, 50, 40),
            "PINHOLE": (100, 100, 50, 40),
            "SIMPLE_RADIAL": (100, 50, 40, 0),
            "RADIAL": (100, 50, 40, 0, 0),
            "OPENCV": (100, 100, 50, 40, 0, 0, 0, 0),
            "FULL_OPENCV": (100, 100, 50, 40, 0, 0, 0, 0, 0, 0, 0, 0),
        }[model]
    )
    component_records, data, sparse = [], {}, {}
    for indices in members:
        indices = sorted(indices)
        view_ids = tuple(ids[i] for i in indices)
        component_id = membership_id(view_ids)
        cameras = tuple(
            sorted(
                (
                    ReconstructionCamera(
                        camera_id=membership_id((ids[i],), "camera"),
                        model=model,
                        width=100,
                        height=80,
                        parameters=parameters,
                    )
                    for i in indices
                ),
                key=lambda c: c.camera_id.int,
            )
        )
        views = tuple(
            RegisteredView(
                view_id=ids[i],
                camera_id=membership_id((ids[i],), "camera"),
                pose=ReconstructionPose(
                    quaternion_wxyz=(1, 0, 0, 0), translation=(-i * baseline, 0, 0)
                ),
            )
            for i in indices
        )
        by_camera = {c.camera_id: c for c in cameras}
        records = []
        for index, error in enumerate(errors):
            xyz = (index * 0.01, 0.2, 10.0)
            count = lengths[index] if lengths else len(indices)
            observations = []
            for v in views[:count]:
                t = v.pose.translation
                uv = project(by_camera[v.camera_id], (xyz[0] + t[0], xyz[1], xyz[2]))
                observations.append(
                    ValidationObservation(
                        view_id=v.view_id, keypoint_index=index, xy=(uv[0] + error, uv[1])
                    )
                )
            records.append(
                ValidationPoint(
                    xyz=xyz, observations=tuple(observations) if tracks_available else None
                )
            )
        count = len(records) if points_available else None
        digest = component_semantic_digest(cameras, views, point_count=count)
        component_records.append(
            ReconstructionComponent(
                component_id=component_id,
                semantic_digest=digest,
                registered_view_ids=view_ids,
                registered_view_count=len(view_ids),
                camera_count=len(cameras),
                point_count=count,
                native_payload="sparse/0",
            )
        )
        data[component_id] = ValidationComponentInput(
            component_id=component_id,
            cameras=cameras,
            views=views,
            priors=tuple(
                ViewCameraPrior(
                    view_id=v.view_id,
                    model=model,
                    width=100,
                    height=80,
                    parameters=parameters,
                    camera_group_id=universe.views[v.view_id.int - 1].camera_group_id,
                    prior_focal_length=True,
                )
                for v in views
            )
            if prior
            else (),
            points_available=points_available,
            tracks_available=tracks_available,
        )
        sparse[component_id] = records if points_available else []
    reconstruction = make_set(
        mapping_for(ids), tuple(sorted(component_records, key=lambda c: c.component_id.int))
    )
    return reconstruction, universe, MemoryGeometry(data, sparse)


def measured(*args, settings=None, **kwargs):
    reconstruction, universe, source = scene(*args, **kwargs)
    geometry = geometry_identity(reconstruction, source)
    metrics = measure_reconstruction(
        reconstruction, universe, geometry, source, settings or MeasurementSettings()
    )
    return reconstruction, universe, source, metrics
