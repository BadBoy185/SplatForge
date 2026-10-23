"""Bounded generated perspective M7 fixture; no representative quality claims."""

from pathlib import Path
from uuid import UUID

import test_views_execution as upstream
from test_mapping_integration import perspective_pixels
from test_pairs_execution import build as build_pairs

from splatforge.adapters.colmap_features import ColmapFeatureAdapter
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.application.features import FeaturesService
from splatforge.application.matching import MatchingService
from splatforge.application.views_contracts import MaterializedFrame
from splatforge.core.features import SiftExtractionSettings
from splatforge.core.geometry import CameraPriorSet, VerificationSettings, ViewCameraPrior
from splatforge.core.matching import SiftBruteforceSettings
from splatforge.core.pairs import ExhaustiveSettings
from splatforge.core.views import RationalValue


def real_mapping_input(tmp_path, monkeypatch, executable: Path, count: int = 12):
    original = upstream.FakeProbe.probe
    monkeypatch.setattr(
        upstream.FakeProbe,
        "probe",
        lambda self, *args, **kwargs: original(self, *args, **kwargs).model_copy(
            update={"width": 640, "height": 480, "duration": str(count / 10)}
        ),
    )
    value = upstream.harness(tmp_path, mixed=False)

    def materialize(source_path, source, output_directory, settings, **kwargs):
        assert source_path.absolute() in value.sources.active
        output_directory.mkdir(parents=True)
        frames = []
        for index in range(count):
            path = output_directory / f"frame-{index:08d}.png"
            path.write_bytes(perspective_pixels(-0.66 + 1.32 * index / (count - 1)))
            frames.append(
                MaterializedFrame(path, index, index, RationalValue(numerator=1, denominator=10))
            )
        return tuple(frames)

    monkeypatch.setattr(value.materializer, "materialize", materialize)
    views = upstream.prepare(
        value,
        target="10",
        candidate_fps="10",
        resource_limits=upstream.limits(byte_count=100000000),
    )
    assert views.selected_count == count
    pairs = build_pairs(value, views, settings=ExhaustiveSettings())
    features = FeaturesService(value.execution, ColmapFeatureAdapter()).extract(
        value.root,
        views_run_id=views.run_id,
        settings=SiftExtractionSettings(max_image_size=640),
        colmap=executable,
    )
    feature_set = value.execution.load_local_features(value.root, features.feature_artifact)
    matching = MatchingService(value.execution, ColmapMatchingAdapter())
    raw = matching.match(
        value.root,
        features_run_id=features.run_id,
        pairs_run_id=pairs.run_id,
        settings=SiftBruteforceSettings(),
        colmap=executable,
    )
    cameras = CameraPriorSet(
        cameras=tuple(
            ViewCameraPrior(
                view_id=v.view_id,
                camera_group_id=UUID(int=1),
                model="SIMPLE_PINHOLE",
                width=640,
                height=480,
                parameters=(400, 320, 240),
                prior_focal_length=True,
            )
            for v in feature_set.views
        )
    )
    verified = matching.verify(
        value.root,
        matches_run_id=raw.run_id,
        settings=VerificationSettings(compute_relative_pose=True),
        cameras=cameras,
        colmap=executable,
    )
    geometry = value.execution.load_verified_geometry(value.root, verified.artifact)
    return value, verified, geometry
