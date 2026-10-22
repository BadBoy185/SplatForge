"""Synthetic vectors prove contracts/policy only, never image retrieval quality."""

import hashlib
import struct
from uuid import UUID

import pytest
from test_pairs_core import endpoints, universe, view

from splatforge.core.pairs import (
    ExhaustiveSettings,
    HybridPairSettings,
    PairResourceLimits,
    RetrievalPairSettings,
    SequentialSettings,
    canonical_pair,
    generate_pairs,
    pair_graph_digest,
)
from splatforge.core.retrieval import (
    RetrievalExport,
    RetrievalModelIdentity,
    RetrievalPreprocessing,
    RetrievalRepresentationSettings,
    RetrievalResourceLimits,
    RetrievalView,
    corpus_digest,
    retrieval_semantic_digest,
)
from splatforge.core.retrieval_pairs import (
    NoRetrievalEdgesError,
    plan_retrieval_pairs,
    retrieval_pair_recipe_key,
    search_pairs,
)


def export_for(value, rows=None, *, pixels=None, method="retrieval.megaloc"):
    rows = rows if rows is not None else [(1.0, 0.0)] * len(value.views)
    data = b"".join(struct.pack(f"<{len(row)}f", *row) for row in rows)
    pixels = pixels or tuple(
        RetrievalView(
            view_id=v.view_id,
            image_sha256="a" * 64,
            pixel_transform_digest="e" * 64,
            width=192,
            height=192,
        )
        for v in value.views
    )
    roles = ("vocabulary", "weights") if method == "retrieval.anyloc" else ("weights",)
    return RetrievalExport(
        settings=RetrievalRepresentationSettings(
            method_id=method,
            method_version="synthetic-contract-1",
            models=tuple(
                RetrievalModelIdentity(
                    role=role, name="synthetic", source="test", sha256="b" * 64, size=1
                )
                for role in roles
            ),
            preprocessing=RetrievalPreprocessing(
                identity="test-rgb", resize_policy="stretch", width=322, height=322
            ),
            descriptor_dimension=len(rows[0]),
            backend_id="synthetic-contract-only",
            runtime_identity="c" * 64,
            inference_device="cpu",
        ),
        universe=value,
        views=pixels,
        corpus_semantic_digest=corpus_digest(value, pixels),
        descriptor_sha256=hashlib.sha256(data).hexdigest(),
        descriptor_bytes=len(data),
    ), data


def search(value, rows, settings=None, *, explicit=(), limits=None, **kwargs):
    export, _ = export_for(value, rows)
    return search_pairs(
        export,
        rows,
        settings or RetrievalPairSettings(top_k=1),
        limits or PairResourceLimits(),
        RetrievalResourceLimits(),
        explicit,
        **kwargs,
    )


def test_exact_top_k_uuid_ties_self_exclusion_dedup_evidence():
    value = universe(*(view(i, None, source=i) for i in range(1, 5)))
    pairs = search(value, [(1, 0)] * 4)
    assert endpoints(pairs) == [(1, 2), (1, 3), (1, 4)]
    assert [e.query_view_id.int for e in pairs[0].reasons[0].evidence] == [1, 2]
    assert all(e.rank == 1 for p in pairs for r in p.reasons for e in r.evidence)
    more = search(value, [(1, 0)] * 4, RetrievalPairSettings(top_k=2))
    assert endpoints(more) == [(1, 2), (1, 3), (1, 4), (2, 3), (2, 4)]


def test_cross_clip_and_photo_connections_ignore_camera_device_groups():
    value = universe(
        view(1, 0),
        view(2, 10),
        view(3, 0, source=200),
        view(4, 10, source=200),
        view(5, None, source=300),
    )
    pairs = search(
        value,
        [(1, 0)] * 5,
        HybridPairSettings(
            sequential=SequentialSettings(forward_neighbors=1),
            retrieval=RetrievalPairSettings(top_k=1),
        ),
        explicit=(canonical_pair(UUID(int=1), UUID(int=3)),),
    )
    assert (1, 2) in endpoints(pairs) and (3, 4) in endpoints(pairs) and (1, 5) in endpoints(pairs)
    bridge = next(p for p in pairs if (p.left_view_id.int, p.right_view_id.int) == (1, 3))
    assert [r.kind for r in bridge.reasons] == ["explicit", "retrieval"]
    assert all(
        not any(r.kind == "retrieval" for r in p.reasons)
        for p in pairs
        if (p.left_view_id.int, p.right_view_id.int) in ((1, 2), (3, 4))
    )


def test_long_range_policy_suppresses_selected_neighbors_and_keeps_loops():
    value = universe(*(view(i, i * 10) for i in range(1, 6)))
    settings = HybridPairSettings(
        sequential=SequentialSettings(forward_neighbors=1),
        retrieval=RetrievalPairSettings(
            top_k=1, same_clip_policy="long_range", same_clip_suppression_window=2
        ),
    )
    pairs = search(value, [(1, 0)] * 5, settings)
    loops = [p for p in pairs if any(r.kind == "retrieval" for r in p.reasons)]
    assert endpoints(loops) == [(1, 4), (1, 5), (2, 5)]
    assert all(abs(p.left_view_id.int - p.right_view_id.int) > 2 for p in loops)


def test_cross_source_preference_precedes_score_and_eligibility_is_exact():
    value = universe(view(1, None, source=10), view(2, None, source=10), view(3, None, source=20))
    rows = [(1, 0), (1, 0), (0.6, 0.8)]
    settings = RetrievalPairSettings(
        top_k=1, source_policy="prefer_cross_source", query_view_ids=(UUID(int=1),)
    )
    assert endpoints(search(value, rows, settings)) == [(1, 3)]
    assert endpoints(
        search(
            value,
            rows,
            settings.model_copy(
                update={
                    "source_policy": "all",
                    "corpus_view_ids": (UUID(int=2),),
                }
            ),
        )
    ) == [(1, 2)]


def test_threshold_no_overlap_never_falls_back():
    value = universe(view(1, None, source=1), view(2, None, source=2))
    with pytest.raises(NoRetrievalEdgesError, match="no fallback"):
        search(value, [(1, 0), (0, 1)])
    assert endpoints(
        search(value, [(1, 0), (0, 1)], RetrievalPairSettings(minimum_similarity=0, top_k=1))
    ) == [(1, 2)]


def test_planning_bounds_before_search_or_output_materialization():
    value = universe(*(view(i, None, source=i) for i in range(1, 10)))
    export, _ = export_for(value)
    with pytest.raises(ValueError, match="Conservative pair planning"):
        plan_retrieval_pairs(
            export,
            RetrievalPairSettings(top_k=5),
            PairResourceLimits(),
            RetrievalResourceLimits(max_retrieval_pairs=20),
        )
    with pytest.raises(ValueError, match="Conservative pair planning"):
        plan_retrieval_pairs(
            export,
            RetrievalPairSettings(top_k=5),
            PairResourceLimits(max_pairs=40),
            RetrievalResourceLimits(),
        )
    with pytest.raises(ValueError, match="scalar-product"):
        plan_retrieval_pairs(
            export,
            RetrievalPairSettings(),
            PairResourceLimits(),
            RetrievalResourceLimits(max_scalar_products=100),
        )
    with pytest.raises(ValueError, match="outside"):
        plan_retrieval_pairs(
            export,
            RetrievalPairSettings(query_view_ids=(UUID(int=99),)),
            PairResourceLimits(),
            RetrievalResourceLimits(),
        )


def test_representation_keys_invalidate_model_preprocessing_corpus_but_not_k_or_local_features():
    value = universe(view(1, None, source=1), view(2, None, source=2))
    export, _ = export_for(value)
    assert RetrievalExport.model_validate_json(export.model_dump_json()).recipe_key() == (
        export.recipe_key()
    )
    changed_model = export.model_copy(
        update={
            "settings": export.settings.model_copy(
                update={
                    "models": (export.settings.models[0].model_copy(update={"sha256": "d" * 64}),),
                }
            )
        }
    )
    changed_pre = export.model_copy(
        update={
            "settings": export.settings.model_copy(
                update={
                    "preprocessing": export.settings.preprocessing.model_copy(
                        update={"width": 336}
                    ),
                }
            )
        }
    )
    other, _ = export_for(universe(view(1, None, source=1), view(3, None, source=3)))
    assert len({x.recipe_key() for x in (export, changed_model, changed_pre, other)}) == 4
    # The public input schema cannot accept a local extractor/matcher/pose at all.
    for forbidden in ("local_features", "matcher", "poses"):
        with pytest.raises(ValueError):
            RetrievalExport.model_validate({**export.model_dump(), forbidden: "SIFT"})
    assert retrieval_pair_recipe_key(
        value, retrieval_semantic_digest(export), RetrievalPairSettings(top_k=1), ()
    ) != retrieval_pair_recipe_key(
        value, retrieval_semantic_digest(export), RetrievalPairSettings(top_k=2), ()
    )


def test_same_graph_m6_semantics_independent_of_retrieval_producer():
    value = universe(*(view(i, None, source=i) for i in range(1, 4)))
    retrieved = search(value, [(1, 0)] * 3, RetrievalPairSettings(top_k=2))
    exhaustive = generate_pairs(value, settings=ExhaustiveSettings(), limits=PairResourceLimits())
    assert pair_graph_digest(value, retrieved) == pair_graph_digest(value, exhaustive)
    assert [p.pair_id for p in retrieved] == [p.pair_id for p in exhaustive]


def test_search_cancellation_is_cooperative():
    value = universe(*(view(i, None, source=i) for i in range(1, 4)))

    def stop():
        raise RuntimeError("cancel")

    with pytest.raises(RuntimeError, match="cancel"):
        search(value, [(1, 0)] * 3, checkpoint=stop)
