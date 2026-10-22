# M7c retrieval foundations and hybrid pairing

Status: neutral contracts, offline representation publication, bounded exact CPU queries,
hybrid PairSet production and an opt-in M7b comparison harness are implemented.
**Production VPR inference and the initial production model are not selected.**
Representative datasets and explicitly provisioned candidate inference runtimes/weights
were unavailable in this working tree. The [candidate audit](M7C_BENCHMARK.md) records
the evidence and decision gap. This is partial M7c delivery, not completion of its
real multi-clip quality acceptance. Simple profiles remain unchanged.

## Representation contract

`retrieval.representation_set` contract 1 publishes `retrieval.json`,
`descriptors.f32` and the normal manifest through existing persisted attempts,
writer leases, validation, atomic publication and recovery. There are no ML base
dependencies, model downloaders or research framework imports in SplatForge.

`RetrievalRepresentationSet` records:

- Exact candidate/selected artifact UUIDs and semantic digests as producer lineage;
  the full canonical M6 selected-view universe, including source/revision/stream,
  chronology, source groups and camera groups.
- Canonical indexed view UUIDs, selected image SHA-256/dimensions and pixel-transform
  digest. `corpus_semantic_digest` hashes these pixel records and universe digest.
- Retrieval method ID and version; weight identity/name/source/size/SHA-256;
  optional backbone identity and mandatory vocabulary identity for AnyLoc VLAD.
- Versioned RGB preprocessing identity, selected-pixel orientation, resize policy,
  width/height, crop policy, interpolation, antialias, pixel scale, mean and std.
- Little-endian FP32 descriptor dimension, L2 unit semantics, cosine similarity,
  exact flat index version 1, Python float64 `math.fsum` accumulation; declared
  external backend/runtime digest and inference device. Model identity is the
  exporter's declaration, not SplatForge evidence of model execution.
- Descriptor payload SHA-256 and exact `views * dimension * 4` storage size, contract
  version and semantic digest. Validation rejects NaN/Inf, incomplete/trailing rows,
  checksum mismatch and squared L2 norm differing from one by more than 1e-4.

The flat descriptor matrix is the index. Backend row numbers are private transport:
rows follow canonical indexed UUID order; public pairs use UUIDs exclusively.
The semantic digest/recipe includes the complete versioned export declaration,
corpus, model/preprocessing/runtime settings and descriptor bytes identity. Publication
IDs and external export paths are separate provenance. The entire pipeline config,
local SIFT/ALIKED/LoMa features, matcher, reconstruction and performance history are
absent from this key. No pose or reconstruction input exists in the export schema.

The implemented builder **validates and imports an offline export**; it does not
compute learned descriptors. It never opens pickle/checkpoints or executes exporter
code. Provision research code, model weights and any heavy ML environment explicitly
outside the product; run inference in a separately owned isolated runtime and export
the fixed neutral transport. Audit that runtime's offline behavior and licenses
before executing it. Normal SplatForge attempts perform no network access.

## Query and hybrid policy

`pair_selection.retrieval` and `pair_selection.hybrid` version 1 consume an exact
published representation and emit ordinary `pairs.pair_set` contract 1. M7b consumes
their canonical graph through its unchanged explicit-pair route. Pair UUIDv5 and
graph semantic digest algorithms are unchanged.

Versioned `RetrievalPairSettings` defaults are K=5, 10,000 maximum retrieval edges,
cosine similarity >=0.5, cross-source policy, same-video exclusion, suppression
window 5 selected observations, all views eligible for queries/corpus and CPU exact
search. These numerical defaults are conservative development limits, not validated
scene thresholds. Advanced JSON supports only the declared typed fields.

For each eligible query, exclude self and ineligible targets before bounded top-K.
Threshold is inclusive. `cross_source` considers distinct source IDs; photos naturally
participate as independent sources. `prefer_cross_source` puts cross-source results
ahead of same-source results, then sorts by decreasing similarity and increasing
unsigned UUID. `all` removes source preference. No source/device type selects a
retrieval model. Inference device is declared in the representation; search supports
CPU only and never changes devices automatically.

Same-video identity is M6's source/revision/stream tuple. `long_range` explicitly
permits same-video loop candidates outside the suppression window; Hybrid also
excludes any edge covered by its actual Sequential window/time-gap settings. No
visual interpretation or scene understanding is inferred from this policy.

Hybrid merges unchanged M6 Sequential edges inside each ordered video, retrieval
edges and supplied explicit UUID edges. Reasons are sorted/deduplicated by kind;
retrieval reason retains up to both directed queries' rank/score and representation
digest. Explicit edges survive even if retrieval suppresses them. PairSet now accepts
the additive retrieval/hybrid settings, retrieval reason/provenance and up to four
reason kinds. Historical M6 payloads remain readable; graph identity excludes all
producer reasons/settings. Existing M6 Sequential/Exhaustive behavior is unchanged.

## Planning and resource limits

The exact reference search keeps a packed FP32 corpus plus one bounded heap per
query, never a dense similarity matrix. Cost remains O(Q * C * D); it is a bounded
reference/benchmark route, not a scalable vector service. Defaults: 4096 indexed
views, 64 MiB descriptor bytes, 1,000,000 query/corpus comparisons and 100,000,000
scalar products. Structural descriptor maximum is 256 MiB, dimension <=65536.
Typed `RetrievalResourceLimits` exposes bounded adjustments.

Planning calculates eligible directed `sum(min(K, eligible_targets))`, exact Sequential
count and canonical explicit count before emitting graph edges. Their conservative
sum must fit both retrieval and total PairSet budgets. Reciprocal/explicit duplicates
may lower actual counts but do not waive the planning gate. Lower K or restrict
eligibility, or explicitly raise limits. No silent global truncation occurs. The
top-K/tie policy is recorded. Result JSON records indexed views, descriptor bytes,
requested K, candidate upper bound, final deduplicated count and each reason count.

If threshold/policy leaves no edges, the attempt fails with a clear no-fallback
result; M6's nonempty PairSet rule is preserved. Hybrid may still publish valid
Sequential/explicit edges with zero retrieval edges and disconnected coverage
warnings. The benchmark records an empty candidate outcome without inventing an
M7b execution. Neither unavailable retrieval nor no overlap switches to Exhaustive.

## Cache and execution

| Change | Reuse | Recompute |
| --- | --- | --- |
| SIFT / ALIKED / LoMa extractor | Representation and PairSet | Local features and M7b consumers |
| Matcher/settings | Representation and PairSet | Matching and verification |
| K / threshold / query eligibility | Representation/index | Retrieval/hybrid PairSet and graph consumers |
| Sequential window | Representation/index | Hybrid PairSet and graph consumers |
| Retrieval model / preprocessing / runtime / selected corpus | Independent local features | Representation/index and dependent pairs |

Hybrid currently recomputes its bounded queries when Sequential settings change;
there is no separately persisted query-result cache. If the resulting actual graph
is identical, M7b can reuse its graph-compatible cache despite a new pairing recipe.
Cache hits retain original producer lineage; each new run freezes current inputs.
Corruption invalidates immutable cached payloads; rebuilding publishes a new artifact.

Both stages have separate M6.5 work models: `retrieval.imported_views_v1` and
`retrieval.queried_views_v1`, primary unit VIEWS. Import workload includes actual
views/MP, descriptor dimension and bytes. Import progress counts validated/copied
rows, not model inference. Query progress counts completed queries. Only observed
successful attempts teach history; cached/cancelled runs do not. History never
selects a model or changes numerical keys. These pure Python stages use isolated
attempt workspaces and cooperative cancellation; no CUDA state enters the process.
Recovery revalidates published corpus/bytes and recomputes orphan PairSet policy.
Restart the stage command after interruption; checkpoint resume is not claimed.

## CLI and offline export

```powershell
splatforge retrieval capabilities
splatforge retrieval request PROJECT --views-run UUID
splatforge retrieval build PROJECT --views-run UUID --descriptor-export EXPORT/export.json
splatforge pairs build PROJECT --views-run UUID --method hybrid --retrieval-run UUID
splatforge pairs build PROJECT --views-run UUID --method retrieval --retrieval-run UUID --retrieval-settings query.json
splatforge retrieval benchmark fixture.json --colmap COLMAP_EXE --colmap-model-dir LOCAL_MODELS
```

`request` returns exact selected UUID/pixel/transform/corpus metadata and private local
image locators for an external exporter. Copy its `universe`, `views` and
`corpus_semantic_digest` into `RetrievalExport` v1. Add complete typed `settings`,
`descriptor_sha256` and `descriptor_bytes`; write `descriptors.f32` beside `export.json`.
The Python model classes are the strict schema. Files and path ancestors must be
plain, without symlink/junction redirection. Import copies bytes, leaving source
images/exports/models unchanged. Inspect build result JSON for complete representation,
artifact identity and cache state. `run status`/progress/events remain available.

Calling `retrieval build` without an export returns JSON capability code
`retrieval.production_backend_unselected`. There is no hidden model winner or
automatic inference backend. Production selection requires the evidence below.

## Opt-in comparison fixtures

`RetrievalBenchmarkFixture` v1 references an existing local project, succeeded views
run and one shared M7a LOMA_B features run. Up to four distinct candidate exports
and five sorted K values are allowed. All candidates use the same exact LoMa-B
matcher/verifier settings; runtime/model changes during a comparison invalidate it.
The full report retains settings, model/runtime identities, artifact/run references,
stage cache flags and observed import/query/match/verification wall time. Inference
time and trustworthy process RAM/VRAM are explicitly unknown in this import-only slice.

```json
{
  "fixture_version": 1,
  "fixture_id": "phone-drone-overlap-01",
  "category": "phone_drone",
  "data_kind": "real",
  "data_license_evidence": "operator-owned capture; local use authorized",
  "project": "C:/SplatForge Data/scene",
  "views_run_id": "00000000-0000-0000-0000-000000000001",
  "features_run_id": "00000000-0000-0000-0000-000000000002",
  "candidates": [
    {"method_id": "retrieval.megaloc", "descriptor_export": "C:/SplatForge Data/megaloc/export.json"}
  ],
  "top_k_values": [1, 5]
}
```

Required category values: `overlapping_same_device_clips`, `phone_drone`,
`partial_overlap_clips`, `unordered_photos`, `no_overlap`, `repetitive_texture`,
`near_duplicate_bursts`, `large_viewpoint_orientation`. Run separate fixtures for
the eight categories; category labels are declared capture context, not inferred
scene truth. Keep images/models/projects outside Git. Public datasets require
separate size/rights approval; no dataset is downloaded or added to default CI.

The report measures retrieved/raw-matched/verified pairs, raw correspondences,
inliers, useful verified edges per retrieval pair, candidate and verified components
before/after retrieval, source/group components and full verified per-source coverage.
Optional typed `source_devices` records map each source UUID to one declared
`device_label`; reports show selected and verified paired views per device plus
unlabelled views. Missing device labels remain unknown and are never inferred from
camera calibration groups, filenames or source type.
Sequential baseline connectivity uses geometrically verified Sequential edges from
the same M7b run. It does not claim registration/reconstruction quality before M8.

`SPLATFORGE_TEST_RETRIEVAL_FIXTURE` enables the real fixture opt-in.
`SPLATFORGE_TEST_RETRIEVAL_TRANSPORT=1` plus the documented M7b runtime/model variables
enables a tiny native LoMa-B transport check using synthetic vectors/images. That
check proves contracts and cannot rank VPR candidates. See [development](DEVELOPMENT.md)
and [GPU runtime setup](GPU_RUNTIME.md).
