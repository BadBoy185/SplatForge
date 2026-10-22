"""Opt-in phone/drone perspective-view comparison with explicitly supplied edges."""

import json
import os
from pathlib import Path

import pytest
from PIL import Image
from pydantic import Field, model_validator
from test_matching_integration import ROUTES
from test_pairs_execution import build as build_pairs
from test_views_execution import FakeProbe, FakeSourceFiles, Harness, prepare

from splatforge.adapters.colmap_features import ColmapFeatureAdapter, hash_file
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.media_storage import LocalMediaRepository
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.view_workspace import LocalViewWorkspace
from splatforge.application.features import FeaturesService
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.application.matching import MatchingService
from splatforge.application.media import MediaService
from splatforge.application.views import ViewsService
from splatforge.application.views_contracts import MaterializedFrame
from splatforge.bootstrap import build_project_service
from splatforge.core.features import resolve_extraction_settings
from splatforge.core.matching import resolve_matching_settings
from splatforge.core.pairs import SequentialSettings, canonical_pair
from splatforge.core.views import CandidateResourceLimits, FrozenModel


class FixtureView(FrozenModel):
    path: str = Field(min_length=1, max_length=4096)
    source: str = Field(pattern="^(phone|drone)$")
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class CrossSourceFixture(FrozenModel):
    fixture_version: int = Field(default=1, ge=1, le=1)
    views: tuple[FixtureView, ...] = Field(min_length=2, max_length=32)
    pairs: tuple[tuple[int, int], ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def explicit_cross_edges(self):
        if not any(
            self.views[a].source != self.views[b].source
            for a, b in self.pairs
            if 0 <= a < b < len(self.views)
        ):
            raise ValueError("Fixture requires explicit phone/drone overlap edges")
        if any(not 0 <= a < b < len(self.views) for a, b in self.pairs):
            raise ValueError("Fixture pairs must reference canonical zero-based view indices")
        return self


@pytest.mark.integration
@pytest.mark.parametrize("extractor,matcher", ROUTES)
def test_external_cross_source_pair_universe(tmp_path, extractor, matcher, record_property):
    configured = os.environ.get("SPLATFORGE_TEST_CROSS_SOURCE_FIXTURE")
    colmap = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured or not colmap:
        pytest.skip(
            "Set SPLATFORGE_TEST_CROSS_SOURCE_FIXTURE to the bounded v1 JSON manifest "
            "and SPLATFORGE_TEST_COLMAP to a native executable"
        )
    if (
        extractor != "SIFT" or matcher == "SIFT_LIGHTGLUE"
    ) and os.environ.get("SPLATFORGE_TEST_COLMAP_LEARNED") != "1":
        pytest.skip(f"{matcher}: enable SPLATFORGE_TEST_COLMAP_LEARNED=1 and local model directory")
    if matcher in ("LOMA_L", "LOMA_G") and os.environ.get("SPLATFORGE_TEST_COLMAP_HEAVY") != "1":
        pytest.skip(f"{matcher}: enable SPLATFORGE_TEST_COLMAP_HEAVY=1")
    manifest = Path(configured)
    assert manifest.stat().st_size <= 64 * 1024
    fixture = CrossSourceFixture.model_validate_json(manifest.read_bytes())
    root = tmp_path / "cross-source-project"
    build_project_service().create(root, "Explicit phone/drone fixture")
    source_paths = []
    for index, view in enumerate(fixture.views):
        source = Path(view.path)
        if not source.is_absolute():
            source = manifest.parent / source
        assert source.stat().st_size <= 16 * 1024**2 and hash_file(source) == view.sha256
        with Image.open(source) as image:
            assert image.width * image.height <= 16_000_000
            image.load()
            output = tmp_path / f"input-{index}.png"
            image.convert("RGB").save(output)
            source_paths.append(output)

    class Probe(FakeProbe):
        def probe(self, path, media_type, **kwargs):
            with Image.open(path) as image:
                width, height = image.size
            return (
                super()
                .probe(path, media_type, **kwargs)
                .model_copy(update={"width": width, "height": height})
            )

    class Photos:
        from test_views_execution import BACKEND

        def identity(self, cancellation=None):
            return self.BACKEND

        def materialize(self, source_path, source, output_directory, settings, **kwargs):
            output_directory.mkdir(parents=True)
            target = output_directory / "frame-00000000.png"
            target.write_bytes(source_path.read_bytes())
            return (MaterializedFrame(target, 0, None, None),)

    store = LocalProjectStore()
    media = LocalMediaRepository(project_store=store)
    sources = FakeSourceFiles()
    added = MediaService(media, sources, Probe()).add(root, source_paths)
    execution = LocalExecutionRepository(project_store=store)
    service = ViewsService(execution, media, sources, Photos(), LocalViewWorkspace())
    value = Harness(
        root,
        execution,
        media,
        sources,
        Photos(),
        service,
        tuple(s.source_id for s in added.added_sources),
        tuple(source_paths),
    )
    views = prepare(
        value,
        resource_limits=CandidateResourceLimits(
            max_candidates=32,
            max_candidate_bytes=2 * 1024**3,
        ),
    )
    selected = execution.load_selected_views(root, views.selected_artifact)
    ids = {v.source_id: v.view_id for v in selected.selected_views}
    supplied = tuple(
        canonical_pair(ids[added.added_sources[a].source_id], ids[added.added_sources[b].source_id])
        for a, b in fixture.pairs
    )
    pairs = build_pairs(value, views, settings=SequentialSettings(), explicit=supplied)
    model_root = Path(v) if (v := os.environ.get("SPLATFORGE_COLMAP_MODEL_DIR")) else None
    native = None if colmap == "1" else Path(colmap)
    try:
        features = FeaturesService(execution, ColmapFeatureAdapter()).extract(
            root,
            views_run_id=views.run_id,
            settings=resolve_extraction_settings(extractor),
            colmap=native,
            model_directory=model_root,
        )
        matching = MatchingService(execution, ColmapMatchingAdapter())
        raw = matching.match(
            root,
            features_run_id=features.run_id,
            pairs_run_id=pairs.run_id,
            settings=resolve_matching_settings(matcher),
            colmap=native,
            model_directory=model_root,
        )
        verified = matching.verify(root, matches_run_id=raw.run_id, colmap=native)
    except FeatureCapabilityError as exc:
        if extractor == "SIFT":
            raise
        pytest.skip(f"{extractor}+{matcher}: {exc}")
    assert raw.pair_count == len(set(supplied))
    record_property(
        "cross_source_result",
        json.dumps(
            {
                "matcher": matcher,
                "pairs": raw.pair_count,
                "raw_matches": raw.raw_matches,
                "verified_pairs": verified.accepted_pairs,
                "inliers": verified.verified_inliers,
            }
        ),
    )


def test_sift_lightglue_cross_source_requires_learned_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("SPLATFORGE_TEST_CROSS_SOURCE_FIXTURE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("SPLATFORGE_TEST_COLMAP", str(tmp_path / "colmap.exe"))
    monkeypatch.delenv("SPLATFORGE_TEST_COLMAP_LEARNED", raising=False)
    with pytest.raises(pytest.skip.Exception, match="SPLATFORGE_TEST_COLMAP_LEARNED=1"):
        test_external_cross_source_pair_universe(
            tmp_path, "SIFT", "SIFT_LIGHTGLUE", lambda *_: None
        )
