"""Retrieval numerical identity, production recipe and provenance are separate contracts."""

import json
from uuid import UUID, uuid4

import pytest
from test_pairs_core import universe, view
from test_retrieval_core import export_for

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
    RetrievalRepresentationSet,
    RetrievalRepresentationSettings,
    RetrievalResourceLimits,
    retrieval_recipe_key,
    retrieval_semantic_digest,
)
from splatforge.core.retrieval_pairs import retrieval_pair_recipe_key, search_pairs

INTERPRETATION = {
    "descriptor_dtype",
    "descriptor_dimension",
    "normalization",
    "metric",
    "index_method",
    "index_version",
    "accumulation",
}
RECIPE_ONLY = {
    "method_id",
    "method_version",
    "settings_schema_version",
    "models",
    "preprocessing",
    "backend_id",
    "runtime_identity",
    "inference_device",
}
PROVENANCE_ONLY = {"inference_provenance"}


def sample():
    return export_for(universe(*(view(i, None, source=i) for i in range(1, 4))))[0]


def test_every_settings_field_has_an_explicit_identity_classification():
    assert (
        set(RetrievalRepresentationSettings.model_fields)
    ) == INTERPRETATION | RECIPE_ONLY | PROVENANCE_ONLY
    assert not INTERPRETATION & RECIPE_ONLY
    assert not PROVENANCE_ONLY & (INTERPRETATION | RECIPE_ONLY)
    assert set(RetrievalModelIdentity.model_fields) == {
        "role",
        "sha256",
        "size",  # Recipe-only byte identity.
        "name",
        "source",  # Provenance-only labels/locators.
    }
    # Every preprocessing field freezes production, without redefining identical output bytes.
    assert set(RetrievalPreprocessing.model_fields) == {
        "schema_version",
        "identity",
        "color",
        "orientation",
        "resize_policy",
        "width",
        "height",
        "crop_policy",
        "interpolation",
        "antialias",
        "pixel_scale",
        "mean",
        "std",
    }


@pytest.mark.parametrize("field", ["source", "name"])
def test_model_provenance_does_not_change_either_identity(field):
    export = sample()
    changed = export.model_copy(
        update={
            "settings": export.settings.model_copy(
                update={
                    "models": (
                        export.settings.models[0].model_copy(update={field: "other locator"}),
                    ),
                }
            )
        }
    )
    assert changed.settings.models != export.settings.models
    assert retrieval_semantic_digest(changed) == retrieval_semantic_digest(export)
    assert retrieval_recipe_key(changed) == retrieval_recipe_key(export) == export.recipe_key()


@pytest.mark.parametrize(
    "field,changed",
    [
        ("descriptor_dtype", "float32_be"),
        ("descriptor_dimension", 1),
        ("normalization", "unnormalized"),
        ("metric", "euclidean_distance"),
        ("index_method", "other_interpretation"),
        ("index_version", 2),
        ("accumulation", "float32_sum"),
    ],
)
def test_each_numerical_interpretation_field_participates(field, changed):
    export = sample()
    # Projection probes also cover version-pinned fields; they do not enable new formats.
    other = export.model_copy(
        update={
            "settings": export.settings.model_copy(
                update={field: changed},
            )
        }
    )
    assert retrieval_semantic_digest(other) != retrieval_semantic_digest(export)
    assert other.recipe_key() != export.recipe_key()
    with pytest.raises(ValueError):
        RetrievalExport.model_validate(other.model_dump())


@pytest.mark.parametrize(
    "update",
    [
        {"method_id": "retrieval.boq"},
        {"method_version": "other-version"},
        {"backend_id": "other-numerical-adapter"},
        {"runtime_identity": "d" * 64},
        {"inference_device": "gpu:0"},
    ],
)
def test_production_dependencies_change_recipe_but_not_identical_numerical_output(update):
    export = sample()
    other = export.model_copy(update={"settings": export.settings.model_copy(update=update)})
    assert other.recipe_key() != export.recipe_key()
    assert retrieval_semantic_digest(other) == retrieval_semantic_digest(export)


def test_model_preprocessing_and_output_changes_have_separate_identities():
    export = sample()
    model = export.model_copy(
        update={
            "settings": export.settings.model_copy(
                update={
                    "models": (export.settings.models[0].model_copy(update={"sha256": "d" * 64}),),
                }
            )
        }
    )
    preprocessing = export.model_copy(
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
    output, _ = export_for(export.universe, [(0.0, 1.0)] * len(export.views))
    for changed in (model, preprocessing):
        assert changed.recipe_key() != export.recipe_key()
        assert retrieval_semantic_digest(changed) == retrieval_semantic_digest(export)
        changed_output = changed.model_copy(update={"descriptor_sha256": output.descriptor_sha256})
        assert changed_output.recipe_key() != changed.recipe_key()
        assert retrieval_semantic_digest(changed_output) != retrieval_semantic_digest(export)
    assert retrieval_semantic_digest(output) != retrieval_semantic_digest(export)
    other_corpus, _ = export_for(universe(view(1, None, source=1), view(4, None, source=4)))
    assert retrieval_semantic_digest(other_corpus) != retrieval_semantic_digest(export)


def test_publication_provenance_and_json_formatting_do_not_affect_identity():
    export = sample()
    semantic = retrieval_semantic_digest(export)
    assert semantic != export.recipe_key()
    formatted = RetrievalExport.model_validate_json(json.dumps(export.model_dump(mode="json")))
    assert retrieval_semantic_digest(formatted) == semantic
    assert formatted.recipe_key() == export.recipe_key()
    for _ in range(2):
        published = RetrievalRepresentationSet(
            **export.model_dump(),
            semantic_digest=semantic,
            candidate_artifact_id=uuid4(),
            candidate_semantic_digest="a" * 64,
            selected_artifact_id=uuid4(),
            selected_semantic_digest="b" * 64,
        )
        assert retrieval_semantic_digest(published) == semantic
        assert published.recipe_key() == export.recipe_key()
    # Pre-main exports using the former recipe-as-semantics must be rebuilt, never rewritten.
    with pytest.raises(ValueError, match="semantic digest mismatch"):
        RetrievalRepresentationSet.model_validate(
            {
                **published.model_dump(),
                "semantic_digest": export.recipe_key(),
            }
        )


@pytest.mark.parametrize(
    "update",
    [
        {"top_k": 2},
        {"minimum_similarity": 0.6},
        {"source_policy": "prefer_cross_source"},
        {"query_view_ids": (UUID(int=1),)},
        {"corpus_view_ids": (UUID(int=2),)},
        {"same_clip_policy": "long_range"},
        {"same_clip_suppression_window": 10},
    ],
)
def test_numerical_query_settings_still_change_pair_recipe(update):
    export = sample()
    settings = RetrievalPairSettings(top_k=1)
    digest = retrieval_semantic_digest(export)
    for current, changed in (
        (settings, settings.model_copy(update=update)),
        (
            HybridPairSettings(retrieval=settings),
            HybridPairSettings(
                retrieval=settings.model_copy(update=update),
            ),
        ),
    ):
        assert retrieval_pair_recipe_key(export.universe, digest, current, ()) != (
            retrieval_pair_recipe_key(export.universe, digest, changed, ())
        )


def test_retrieval_evidence_uses_semantics_and_all_producers_keep_m6_graph_identity():
    export = sample()
    settings = RetrievalPairSettings(top_k=2)
    edges = search_pairs(
        export, [(1, 0)] * 3, settings, PairResourceLimits(), RetrievalResourceLimits()
    )
    assert all(
        reason.representation_semantic_digest == retrieval_semantic_digest(export)
        for edge in edges
        for reason in edge.reasons
    )
    exhaustive = generate_pairs(
        export.universe, settings=ExhaustiveSettings(), limits=PairResourceLimits()
    )
    explicit = tuple(canonical_pair(p.left_view_id, p.right_view_id) for p in exhaustive)
    sequential_explicit = generate_pairs(
        export.universe,
        settings=SequentialSettings(),
        limits=PairResourceLimits(),
        explicit_pairs=explicit,
    )
    hybrid = search_pairs(
        export,
        [(1, 0)] * 3,
        HybridPairSettings(retrieval=settings),
        PairResourceLimits(),
        RetrievalResourceLimits(),
        explicit,
    )
    for graph in (exhaustive, sequential_explicit, hybrid):
        assert [p.pair_id for p in graph] == [p.pair_id for p in edges]
        assert pair_graph_digest(export.universe, graph) == pair_graph_digest(
            export.universe, edges
        )


def test_resource_limit_belongs_to_execution_not_pair_settings():
    assert "max_retrieval_pairs" in RetrievalResourceLimits.model_fields
    assert "max_retrieval_pairs" not in RetrievalPairSettings.model_fields
    with pytest.raises(ValueError):
        RetrievalPairSettings.model_validate({"max_retrieval_pairs": 20_000})
