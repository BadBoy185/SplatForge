# Development, testing and diagnostics

[AGENTS.md](../AGENTS.md) is the engineering constitution. This guide defines the
verification strategy; foundation, M1b2 execution/recovery, the M2 media/process
boundary and M5 capability diagnostics have automated coverage.
Use the project virtual environment and the [README commands](../README.md#current-status).
Python 3.12 is the baseline; wider `requires-python` metadata is not evidence of testing
on every later Python release.

## Verification workflow

Run commands from the repository root with the project environment active (on
Windows: `& .venv/Scripts/Activate.ps1`). Pytest configuration stays in
[pyproject.toml](../pyproject.toml); no second test-selection configuration is needed.

### Fast / affected verification

During development, run the tests for the changed behavior and its actual consumers,
relevant contract tests and lint for changed Python files. Select explicit test paths
or node IDs; never use bare pytest as a placeholder for an undecided fast selection.
For example, for a dependency-boundary change:

```powershell
python -m pytest tests/test_gui_architecture.py
python -m ruff check tests/test_gui_architecture.py
python scripts/check_docs.py
```

Choose other tests for other changes; that example is not a universal smoke suite.
Documentation-only work checks local links/anchors, contract/claim consistency and
diff scope. Harness/script changes also need their affected tests and lint. Expand
verification when failures or uncovered consumers justify it, not after every edit.

### Full verification

Run once for the final tree before milestone completion, merge/release, changes
crossing many boundaries, an explicit user request, or when affected checks cannot
provide confidence. A small bounded change can finish with affected evidence if no
full gate applies. Report that scope explicitly.

```powershell
python -m pytest
python -m ruff check .
python scripts/check_docs.py
```

This is the default suite, not GPU/backend acceptance. Keep integration opt-ins
(`SPLATFORGE_TEST_*`) unset for a default run; explicitly provisioned integrations
remain separate and must be named in the report. GUI-specific checks require the
optional GUI environment described below. Do not install dependencies or run
native/GPU workloads implicitly. Documentation moves alone do not require full pytest.

Record the command, tree/revision plus relevant dirty files, environment, outcome
and skips. User-supplied full results count when those details establish that they
cover the same relevant tree/environment. Attribute them to the user. Reuse valid
results; rerun after changes that invalidate their coverage, not just because a new
internal step occurred. Never claim a check passed without an actual result, and
never present affected checks as full verification.

### Documentation link check

`python scripts/check_docs.py` checks repository Markdown (root, `docs/`, repo-local
skills), local inline links and reference definitions, file existence/exact case and
Markdown heading fragments. It skips fenced examples and remote URLs; it does not
validate remote availability, prose claims or every Markdown extension. Explicit paths
can be supplied for focused checks. A failure must identify the source and target;
do not suppress an inconvenient broken link without checking its intent.

## Durable plans

For substantial bounded work, copy the [template](plans/TEMPLATE.md) into
`docs/plans/active/<task-id>-<name>.md`. Record goal/non-goals, exact contract sections,
affected areas, acceptance, verification, decisions/unknowns and final status.
Small routine edits do not need a plan file. A future roadmap item is not an active
assignment until selected; [legacy prompts](CODEX_PROMPTS.md) are background outlines.

Keep the plan current as evidence arrives. On completion, record actual outcomes and
remaining limitations, move it to `docs/plans/completed/`, repair relative/incoming
links and update the [map](index.md). Do not rewrite dated decisions as if later
knowledge existed then. Old milestone notes remain at their stable paths; no bulk
migration is required. Plans coordinate work, not application contracts.

## Documentation hygiene

- One fact has one authoritative owner, listed in the [map](index.md). Other
  documents link to it instead of copying its normative sections.
- Change the authoritative document when a contract changes. A plan, prompt, README
  summary or research note cannot silently override it.
- Completed plans/implementation notes describe their delivered slice and evidence;
  they are not current assignments or replacement contracts. Research is not
  implemented support. The roadmap plans capability, not proof of implementation.
- Preserve dated findings and results. Add a dated clarification when necessary;
  do not retroactively rewrite a historical decision or test result.
- Check local links after edits/moves, including relative links inside moved files.
  Put new information in an existing owner when it fits; create a new Markdown file
  only for a distinct purpose, durable plan or evidence set, and route it in the map.

## Architecture guardrails

[test_gui_architecture.py](../tests/test_gui_architecture.py) checks static imports:
Core depends only on Core within the product; Application depends only on Core and
Application. Both exclude UI/process/SQLite/backend library imports. GUI checks
exclude direct adapter/process/trainer imports. A disposable base/GUI-entry import
smoke blocks optional heavy libraries (and Qt on the base CLI path).

These are cheap regression checks, not a proof of architectural purity. Dynamic
imports, filesystem I/O through `Path`, indirect process launch and semantic business
rules still need review and appropriate behavioral tests. Next guardrail candidates,
only when a concrete regression warrants them: literal dynamic-import checks and
specific Core I/O-call checks. Do not build a universal linter or ban `Path` values.

For decomposition decisions, follow the [AGENTS coding rules](../AGENTS.md#coding-and-external-execution).

## Testing layers

M12's GUI extra is optional: `python -m pip install -e ".[dev,gui]"` installs the
validated PySide6 6.12.0 target; `splatforge-gui` launches Qt Quick / QML. Base CLI/core
imports remain Qt-free. Run focused acceptance with:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/test_gui.py tests/test_qml.py tests/test_qml_workflows.py tests/test_qml_interaction.py tests/test_gui_architecture.py tests/test_desktop.py
```

Run `pyside6-qmllint -I src/splatforge_gui/qml` over all QML sources.
See [GUI design](GUI_DESIGN.md) for native screenshot capture and review.

These tests use QtTest/direct state assertions, deterministic fake work and tiny
published artifacts. They cover responsiveness, shared project intent/history,
cancel/recovery, exact M9/M10/M11 requests and bounded preview without benchmarking.
GUI milestone completion includes affected application regressions and the full gate
above. Native Windows smoke at 100%/150% DPI
is separate from offscreen tests; do not describe headless testing as manual GUI
validation. The tested baseline is Python 3.12.10, PySide6/Qt 6.12.0, Windows Server
2022 build 20348. See [M12](M12.md) for architecture and scope limitations.

| Layer | What to verify | External requirements |
| --- | --- | --- |
| Core unit | Role validation including repeated IDs in different slots, settings bounds, descriptor/camera/format compatibility, canonical fingerprints and dependency invalidation | None |
| Persistence | Create/save/reopen, unknown methods/versions, round-trip settings, migration backups, stale saves, source relink and writer exclusion | Temporary local filesystem/SQLite |
| Recovery | Fail before/after manifest, rename and database commit; interrupted owners, orphan publication, corrupted payload, full disk and sharing violation | Fault-injected storage/process adapters |
| Application | Fake-stage plans, progress/cancel/retry, gate overrides, snapshots, cache reasons and CLI exit/result semantics | Fakes; no FFmpeg/COLMAP/GPU |
| Adapter contract | Exact argument arrays, supplied working directory/environment, bounded streams, timeout, Unicode, process-tree teardown and output validation | Tiny controlled helper processes |
| Backend integration | FFmpeg timestamp/orientation semantics, native database round-trip, real feature/matching/mapping routes and dataset consumer checks | Explicit configured binaries/models; opt-in |
| Quality/scale benchmark | Registration, components, reprojection/track metrics, runtime, RAM/VRAM/disk, trainer image quality where meaningful | Versioned reference datasets outside Git |

The default full pytest suite must run without tools, GPU, network or model downloads.

M7b.1 device/model regressions live in `test_sfm_devices.py` and `test_local_models.py`.
Simple `auto` probes GPU then CPU inside each candidate; Advanced `auto` retains exact
methods. Use `--device cpu` / `--device gpu:0` for explicit planning; other GPU indices
are not exposed by this adapter. Low-level stage settings remain explicit. Integration
`SPLATFORGE_TEST_COLMAP_DEVICE=auto|cpu|gpu:0` freezes the selected route before work.
Complete local model sets must execute; runtime failures are failures, not missing-model
skips. Missing-model skips carry all roles, expected/observed SHA, checked paths,
configuration and exact pytest rerun commands. No model downloader/installer exists.
Add explicit integration/GPU markers when those tests exist. Tests skip with reasons
when prerequisites are absent; skips are not evidence of backend support. Configure
separate Windows integration runs for supported backend builds and retain capability
reports. Include Windows Server/headless execution before claiming support there.

M5's real integration test is opt-in. Set `SPLATFORGE_TEST_COLMAP` to an absolute
COLMAP executable, or to `1` for `SPLATFORGE_COLMAP`/safe-PATH resolution. The test
records exact version/build identity, commands, mapper evidence and a disposable native
database compatibility result. `SPLATFORGE_TEST_COLMAP_DEEP=1` additionally runs tiny
CPU and GPU SIFT probes. GPU failure is a valid capability result unless a separate
environment explicitly requires GPU. No test downloads binaries, runtimes or models.
Set `SPLATFORGE_TEST_COLMAP_REQUIRE_GPU=1` together with the deep opt-in to make GPU
smoke success mandatory. Exact path/hash/version, mapper, database and ONNX/model
evidence are retained as test properties for optional JUnit output.
Headless CUDA success is valid evidence; an OpenGL-only route without a display is
reported as unavailable while CPU SIFT can remain available.

M7a's opt-in `tests/test_features_integration.py` uses the same
`SPLATFORGE_TEST_COLMAP` selection for real SIFT on tiny textured published selected
views, feature validation, cache reuse and upstream hash comparisons. Add
`SPLATFORGE_TEST_COLMAP_LEARNED=1` and `SPLATFORGE_COLMAP_MODEL_DIR` to request
ALIKED_N16ROT, optional ALIKED_N32, LOMA_B and LOMA_B128. Learned methods run only after
positive disposable variant/model/runtime inference; missing prerequisites skip with
actionable capability reasons. `SPLATFORGE_TEST_COLMAP_FEATURE_GPU=1` requests GPU.
CI needs neither GPU nor network; no command downloads models or installs a toolchain.

Deterministic M7a tests cover settings/signatures, streamed numerical digests,
UUID-to-native mapping, counts/types/dimensions/schema, model/ONNX/version/option gates,
changed executable/model/runtime identities, resource limits, timeout/cancellation/OOM,
cache corruption/invalidation, publication recovery, interruption, upstream immutability,
CLI and Progress/ETA/history degradation. SIFT is the baseline/fallback; LoMa requires
COLMAP >=4.2.1 without raising the global SIFT/ALIKED floor. Source/name/size/SHA-256
supports reproducibility and later installer-license review; commercial redistribution
clearance remains separate. Base dependencies have no PyTorch or Python ML runtime.
M7b implements LoMa-R/L/G matching and separate geometric verification. M7c's neutral
offline representation/hybrid slice is implemented; production inference and model
selection remain pending. See [M7c contracts](M7C.md) and [candidate evidence](M7C_BENCHMARK.md).

M7c tests live in `test_retrieval_core.py`, `test_retrieval_execution.py` and
`test_retrieval_benchmark.py`. They cover exact top-K/ties, graph compatibility,
cross-source/loop policies, budgets, model/preprocess/corpus identity, local-feature
independence, cache corruption, cancellation/recovery, M6.5 progress and fixed-matcher
benchmark accounting. They use synthetic vectors, not real candidate inference.
`test_retrieval_integration.py` separately enables real M7b LoMa-B GPU transport with
`SPLATFORGE_TEST_RETRIEVAL_TRANSPORT=1`, or an operator-owned representative fixture
with `SPLATFORGE_TEST_RETRIEVAL_FIXTURE`. The eight required real categories, model
rights, inference runtime/peak memory and useful-pair quality remain explicit gaps.

M7b's `tests/test_matching_integration.py` uses the same native executable/model
configuration. It proves raw-only explicit PairSet matching, separate geometric
verification, independent caches and byte-identical published inputs for SIFT/BF.
Learned opt-ins cover ALIKED_N16ROT/LightGlue and LoMa-B128/B/R/L/G. Set
`SPLATFORGE_TEST_COLMAP_HEAVY=1` for L/G. Missing learned prerequisites skip with
the exact capability/model reason; configured SIFT failures fail. Mocks do not
establish learned real-backend validation. No test downloads weights.

M7b.2 extends that same fixture to all 13 compatible Advanced combinations: both
SIFT matchers, both matchers for each ALIKED variant, both LoMa-B128 matchers and
all five LoMa-B matchers. `SIFT_LIGHTGLUE` also requires the learned opt-in and
route-specific model preflight. Tests record total features, stage runtimes, frozen
backend/device/model identities and feature/matching/verification cache hits.
These cases never change Simple profile v1 recommendations.

Explicitly authorized operator provisioning is separate from processing: obtain
the exact URL/name/SHA tuple from the verified selected binary, stage the download,
require a matching local SHA-256, then publish it without overwriting different
existing bytes. No downloader is added to SplatForge or its integration tests.
Keep setup scripts, weights and machine-specific reports in ignored local storage.
Inspect missing GPU dependencies only within the selected controlled runtime layout;
do not borrow DLLs from unrelated applications or alter global PATH. An available
ONNX CUDA provider DLL does not prove its cuDNN dependencies are present.

Explicit operator authorization may provision an isolated versioned native runtime
from official NVIDIA archives. Keep the original COLMAP/toolkit installations and
system PATH unchanged, record archive checksums and every bundled DLL, then rerun
functional GPU inference and real integrations. See
[controlled Windows GPU runtime](GPU_RUNTIME.md) for setup and validation commands.
Processing and Doctor still perform no downloads or installation.
M7b.3 validates all thirteen compatible combinations with explicit `gpu:0` on that
bundle, plus CPU ALIKED/LightGlue. Tests pass with a child/session PATH containing
only the bundle and Windows directories. Read-only module observations confirm the
observed ONNX/CUDA/cuDNN DLLs load from the selected bundle. FP32 is supported;
BF16 remains unexposed and untested. See [M7b real results](M7B.md).

`tests/test_matching_cross_source.py` accepts `SPLATFORGE_TEST_CROSS_SOURCE_FIXTURE`
pointing to a bounded manifest of externally prepared phone/drone perspective views,
SHA-256 values and explicit zero-based pair indices. It creates a separate temporary
project and runs each production family on the same supplied pair universe; it does
no retrieval. Larger fixture data stays outside Git. Schema, example, provisioning
and current real results are in [M7B.md](M7B.md).

New deterministic M7b tests cover the full signature compatibility matrix, frozen
Simple/Advanced decisions, unavailable candidates, zero-match requested pairs,
canonical correspondences, malformed indices/F/E/H/pose/configuration, native schema,
SQLite-layout independence, independent camera/verification cache keys, immutable
database copies, stale-state rejection, runtime failures, cancellation, orphan
publication recovery, CLI delegation and successful-only performance history.

The installed Windows COLMAP 4.2.1 help omits extractor enum alternatives. Narrow
`native_options_v2` parsing recognizes its default/options shape and proposes candidate
routes; real validated inference must prove each route. Unknown shapes fail closed.
That build converts image paths with narrow APIs. M7a uses existing ASCII Windows
short aliases for owned workspace transport, creating no links and changing no data
identity. Without such an alias, it fails with guidance to use an ASCII project location.
Only the owned attempt database is checkpointed/sealed; immutable published reads never
create SQLite WAL/SHM files.

The shared executable resolver caches SHA-256 only with concrete file/change evidence.
Windows also reads an existing NTFS/ReFS USN marker to detect rapid same-size writes
with restored modification times; it never enables or alters a journal. If this marker
is unavailable, the resolver rehashes rather than trusting an insufficient cache key.
Future frozen attempts can call `verify_expected_identity()` immediately before launch.

Doctor schema v1 uses five-minute maximum static CLI evidence and thirty-second
resource/functional evidence. The process-local report cache expires at its earliest
evidence expiry and rechecks executable/model identities and configuration on reuse.
Parsing recognizes braced feature/matcher enums, `native_options_v2` and a narrow legacy SIFT profile;
unrecognized formats fail closed. Per-command failure codes/excerpts remain separate.
Learned model roles follow the selected binary's concrete model-path option defaults.
No ONNX inference or model compatibility is certified by recording a readable file.
Native schema probe v1 validates only the required cameras/images/features/matches/
geometry columns, storage types, primary IDs and unique image names, read-only, with
bounded SQLite work. GPU SIFT must produce valid positive native feature records and
advertise actual GPU extractor execution; generic GPU inventory is independent.

Use generated tiny images/videos and synthetic reconstructions for deterministic
expectations. Keep a documented manifest with origin/license, content checksums and
expected metric ranges for larger opt-in datasets stored outside Git. Numerical SfM
and training assertions use justified tolerances and quality ranges, not exact floating
point bytes or a single universal success score. Training comparisons should use
held-out views where meaningful and report the evaluation protocol; training-view
image metrics alone do not establish novel-view quality. Compare presets on the same inputs,
versions and hardware; distinguish quality, time and memory tradeoffs.

Required cache matrix tests follow [PIPELINE.md](PIPELINE.md#invalidation-examples),
including training-only changes, independent retrieval/local features, camera priors,
masks, component choices, validation gates, corrupt/missing payloads and source
relocation. Test cancellation and publication races, not merely the happy path. Architecture/import checks must
prevent core/UI dependencies on backend libraries and direct process execution.

Persistence tests follow the delivery split: M1a1 covers create/open/save/show,
version separation, role validation and known/opaque settings round-trips. M1a2 adds
stale saves, writer exclusion, atomic replacement, backup/dispatch boundaries and
Windows failure injection. M1b1 covers the historical v1-to-v2 state migration, frozen
fake plans, cache integrity and dependency invalidation, publication ordering, writer
serialization and read-only inspection. M1b2 advances current state to v3 and covers
backed-up v1/v2 upgrades, lock-free cancellation requests, durable acceptance,
publication races, stale fake owners, exact orphan adoption, unresolved teardown and
bounded linked retry. For this in-process fake backend only, acquiring the writer lock is
sufficient stale-owner evidence because there are no child workers. These tests do not
establish Windows process-tree containment by themselves.

M2 tests cover immutable inventory revisions, CAS races, durable verification evidence,
FFprobe JSON normalization, bounded dual-stream capture, timeout/cancellation and exact
argument/cwd/environment handling. Windows-only tests prove that cancellation, timeout
and abrupt owner death terminate descendants holding file locks, and that the local
fixed-volume Strict lease blocks modification/replacement/deletion while permitting a
read-only consumer. Non-Windows skips are explicit and are not evidence of support.

M3 default tests use fake materializers and process results to cover exact rational FPS,
VFR timestamp mapping, all EXIF orientations, right-angle video rotations, predecode
count/disk/free-space refusal, Balanced/Strict consumption continuity, two-stage cache
invalidation, streamed multi-file validation, durable cancellation, unresolved teardown
and crash boundaries. No default test requires FFmpeg. Set `SPLATFORGE_TEST_FFMPEG` to
an executable path (or `1` to use configured PATH lookup) and
`SPLATFORGE_TEST_FFPROBE` to a concrete FFprobe executable for the real media tests.
They compare uneven VFR timestamps beginning at source time 5 seconds against an
independent FFprobe frame oracle, real display matrices against asymmetric expected
pixels and FFmpeg autorotation, and PNG EXIF 1..8 against independent pixel transforms.
Original bytes must remain unchanged. Tests skip when unconfigured; configured fixture
failures fail the test. A skip is not backend evidence. Negative PTS and duplicate PTS
are covered by exact metadata tests; the tested MOV muxer rebases/drops negative-origin
frames, so these fixtures do not claim real negative-origin integration coverage.

M4 default tests generate tiny Pillow images locally: a high-frequency pattern, a
blurred form, an exact duplicate and a controlled near-duplicate. They assert exact
rational score persistence, sharp-over-blurred ordering, dHash distance, unchanged
candidate bytes/dimensions and strict QualityReport validation. Synthetic contracts
cover interval/tie decisions, photo behavior, bounded source-local duplicate history,
cache invalidation, corruption, durable cancellation and orphan adoption. No downloaded
fixture, FFmpeg rerun, NumPy/OpenCV or universal blur threshold is required.

Source-verification tests distinguish Balanced/local and Strict: unchanged metadata
must not read the entire source under Balanced; changed/unreliable indicators trigger
rehash; Strict reads complete content. Cover metadata errors, network evidence gaps,
same-content rehash, changed bytes, cancellation and preserved-metadata edits that
Balanced cannot detect. Assert recorded assurance and refusal to silently upgrade weak
artifact lineage. Strict tests must attempt replacement/modification between hashing
and backend consumption and verify the stable-read lease or explicit snapshot prevents
it; unsupported guarantees fail clearly. Use fakes/counting readers for large files,
not giant test fixtures. Verification evidence must not mutate old source artifacts.

M7c retrieval acceptance uses known overlapping regions across multiple drone/phone
clips, bounded neighbor/total-pair budgets and measured retrieval time/memory. Verify
actual cross-clip matches and corpus/model/index invalidation, including duplicate
bursts, repetitive texture and clips with no overlap. Candidate retrieval must not
require the reconstruction it is supposed to enable. Do not confuse ALIKED local
descriptors with retrieval embeddings. M10 adds end-to-end reconstruction
coverage using this route without manual pair lists or all-pairs descriptor matching.

Component-selection tests cover manual and configured policies, report-informed
choices, missing/obsolete IDs, no implicit largest-component fallback, immutable
ReconstructionSet, separate outputs for unaligned components and downstream-only
invalidation. Changed geometry under the same component ID must invalidate consumers.
If policy changes retain the same selected data, test dataset reuse subject to the
quality gate. Check component-scoped versus project-wide failures and exact override
binding; deselecting a bad component cannot waive a project-wide coverage rule.

## External process contract

M2 implements this contract with a one-shot worker that waits for its launch message
until the parent has assigned it to a kill-on-close Windows Job Object. The Job handle is
not inherited. The worker then launches exactly one backend with `shell=False`; the
parent concurrently drains bounded stdout/stderr and confirms the contained tree is gone
before returning. POSIX process-group behavior is a testable fallback, not a claim of the
Windows support baseline.
On Windows the generic resolver and worker accept only native `.exe` entrypoints.
Explicit scripts and script PATHEXT matches are refused before launch, including
`.bat`/`.cmd`; literal ampersands remain argv data for native binaries. `COLMAP.bat`
is accepted only by the COLMAP locator, which resolves native `colmap.exe` first.
Exceptional cleanup returns structured process-level evidence through
`ProcessCleanupError`, preserving the original cause even if termination, confirmation
or reader joining fails. Unconfirmed FFmpeg teardown quarantines the attempt; Doctor
retains unresolved COLMAP workspaces. These errors never return process success.

The process adapter owns executable resolution, argument arrays, working directory,
scoped environment, lifecycle and streamed stdout/stderr. No shell interpolation or
global `PATH` mutation. Record the selected binary identity and invocation; redact
credentials if a future backend introduces them. Return structured exit, timeout,
cancellation and output-validation results, not an unclassified text blob.

M5's Windows COLMAP runtime profile `windows_official_prebuilt_v1` requires an inert
`COLMAP.bat` marker beside native `colmap.exe` or above `bin/colmap.exe`. Supplying that
wrapper path is supported as a locator only; no commands are read or interpreted.
Only existing, nonredirected root/bin/lib directories are prepended to child PATH.
Bounded Qt plugin candidates include plugins, bin/plugins, lib/plugins, lib, bin,
the root, Qt5/plugins, Qt6/plugins and lib/qt5/plugins or lib/qt6/plugins. Only a
positively located `platforms/qwindows.dll` enables child-only `QT_PLUGIN_PATH` and
`QT_QPA_PLATFORM_PLUGIN_PATH`. All help, database and CPU/GPU probes share the same
resolved overrides. Native SHA-256 remains independent of this typed layout evidence;
the full inherited PATH/environment is not included in Doctor output. No system PATH
modification is needed. A system/vcpkg/custom exe without the marker is probed normally,
not rejected or assigned arbitrary sibling libraries. Shape recognition is not package
authenticity verification. Real official packages are not certified by fixture tests;
the `SPLATFORGE_TEST_COLMAP` integration remains opt-in and no package is downloaded.

Use bounded buffers and drain both output streams to avoid hanging on verbose tools.
Preserve raw bytes or use explicit decoding with replacement; parsed progress must
not destroy original logs. Emit indeterminate progress when a backend has no reliable
total. Do not fabricate percentages from elapsed time.

Windows cancellation must terminate and wait for the owned process tree, including
children holding CUDA/file resources. Bound graceful-stop and forced-stop waits; a
failed teardown leaves resources quarantined and blocks retry/publication instead of
claiming successful cancellation. Persist accepted cancellation before signalling the
worker, following [writer ownership](PROJECT_FORMAT.md#writer-ownership-and-cancellation).
Test cancellation against publication, runner death and surviving descendants.

A Windows Job Object with kill-on-close is a candidate containment mechanism. Assign
children before they can escape, control inherited handles and test nesting/breakaway
under supported launchers. Parent termination alone is insufficient. The containment
mechanism must also clean up when the application crashes, not only on a polite cancel:
[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

Native/GPU processing and risky capability probes run in owned disposable worker
processes behind adapters; pure deterministic helpers can stay in-process. The CLI/GUI
host must not initialize CUDA or import an engine merely to list methods/open settings.
Use fresh spawned workers, not inherited CUDA state; PyTorch documents CUDA process
start constraints in its [multiprocessing guidance](https://github.com/pytorch/docs/blob/site/main/notes/multiprocessing.md).
A bounded local worker channel is enough; no service or network protocol is required.
Resolve approved executables explicitly rather than searching a project-controlled
working directory first. Capture worker exit/crash and last durable events. Treat OOM
as a resource failure, not a transient retry loop; changing batch/image/device settings
creates a new resolved plan. Free-VRAM estimates cannot guarantee allocation.

## Progress and ETA foundation

M6.5 diagnostic contracts are independent v1 models in `core/progress.py`. Work units
require a stage/method and versioned work model; quality MP and feature MP are not
interchangeable. Stable plans reject regressing work/elapsed evidence and work above
the total. A changed total requires an explicit plan revision. Determinate, phase and
indeterminate work are distinct; a phase total never implies a whole-stage fraction.
Core imports no storage, process or backend implementation.

`ProgressSession` owns one execution's observations, estimates and aggregation.
`estimate_plan` accepts resolved stage descriptions and explicit cache/skip decisions;
it does no numerical processing or method selection. Pipeline weights use actual
completed durations and estimated active/future durations, excluding cached/skipped
work. Only the display aggregate is clamped monotonically; recalculated evidence and
ETA can change independently. Unknown remaining stages are listed, with a partial
known range at low confidence, or unavailable ETA if nothing can be estimated.

`eta.hybrid_throughput_v1` uses exact categorical stage, method, work-model, backend,
settings and hardware compatibility. Numeric similarity is `1/(1+mean(log2 distance)/4)`
over total work and workload metrics (absolute distances; zero/zero contributes none).
Scores below .25 are excluded; scale mismatch widens the range and reduces confidence.
History uses median throughput and interpolated empirical q10/q90. Range widening is
at least 2x for one sample, 1.5x for 2–4, 1.1x for 5+, and inverse similarity. History
confidence becomes medium at 3 samples, similarity >= .65 and q90/q10 <= 2; high needs
8 samples, similarity >= .9 and spread <= 1.3. Unknown hardware classification caps
confidence at low. Different backend binaries, runtime/model identities or hardware
profiles are not pooled in v1.

Live rates require at least one monotonic second and positive completed work. Use
50/50 cumulative throughput and recent EWMA(alpha=.2); interval rate changes clamp
to a factor of four and recent contribution clamps to half/twice cumulative rate.
Live blending weight is `min(.95,1.5*fraction)*min(1,elapsed/5)*min(1,intervals/3)`;
without history the live weight is one. Recent variability uses at most 16 intervals.
Four stable intervals and >=20% completion permit medium confidence; eight intervals,
>=60% completion and spread <=1.2 permit high confidence. Live stalls exceeding
`max(5s,10% elapsed)` lower confidence and widen the range. Exact rules and boundaries
are frozen in deterministic tests; changing them requires a new estimator version.
These ranges are planning aids, not statistical confidence intervals. No cold speed
is hard-coded: zero history starts unavailable, then uses live evidence.

| Implemented stage | Work model / useful observations |
| --- | --- |
| Candidate preparation | `candidate.output_megapixels_v1`: output MP upper plan, explicit actual-MP revision at validated completion; workload includes retained views, duration, output MP, photo fraction; FPS/encoding/codecs/container families and source-verification policy affect the separate performance settings key |
| Quality | `quality.analyzed_megapixels_v1`: exact bounded analysis MP and completed views; workload also includes full-resolution MP and view count |
| Fixed/sharpest selectors | `selection.candidate_views_v1`: processed candidate views, bounded per-source/slot/interval callbacks |
| Exhaustive pairs | `pairs.emitted_pairs_v1`: known `n*(n-1)/2` total; bounded generation batches |
| Sequential pairs | `pairs.selected_views_v1`: known selected views classified/processed, including photos without invented chronology; successful samples additionally retain actual generated pair count |

FFmpeg uses `-progress` in a private scratch file and generic owner-loop polling (at
most 4 Hz); ProcessRunner knows no FFmpeg syntax. Parsing reads at most 64 KiB per
poll, bounds partial lines/fields and uses complete structured records only. Source
duration progress normalizes integer `out_time_us` to its first report, conservatively
omitting work before that report until `progress=end`. VFR and non-zero/negative PTS
do not become filename-based progress. `showinfo`, pixels, timestamps and recipes are
unchanged. Poll/callback failures disable or degrade telemetry without altering process
containment, timeout, cancellation or numerical output. Scratch is removed after the
owned invocation when possible; it is not an artifact or prediction-history payload.

Persist `progress.snapshot` events at most twice per monotonic second: at least .5s
between updates plus 1% progress, phase change, or a 1s heartbeat. Initial, stage-start,
explicit-plan-revision, cache and terminal boundaries are additive (not per item).
M4's legacy summary is terminal-only. A six-hour stage has at most 43,200 regular
progress snapshots, not millions. Readers inspect at most the last 4 MiB of JSONL,
ignore partial/malformed/old events and reconcile with committed SQLite lifecycle.
Progress older than 5s is marked stale and loses active rate/ETA. Requested/accepted
cancellation immediately suppresses active ETA. An old run with no progress remains
inspectable. Progress never authorizes success, recovery or partial-stage resume.

The executing worker's separate `%LOCALAPPDATA%/SplatForge/performance.sqlite` has
`performance_schema_version=1` (SQLite user_version); it is never project state.
Inject its path in tests; an autouse fixture isolates CLI/integration tests from real
AppData. Retain at most 64 recent samples per exact signature and 4096 globally,
oldest timestamp then insertion order first. Record only committed successful complete
executions with positive work/duration. Cache, failure, cancellation, interruption,
unresolved teardown, Doctor and ingest do not teach this estimator. Missing/empty,
corrupt, locked (50ms busy timeout), malformed, unsupported or unwritable history
degrades to live/unavailable with bounded reason codes. Newer databases are preserved.
`performance show [--json]` returns bounded signature aggregates; explicit
`performance reset` clears samples only, without project/cache changes.

History contains only allowlisted numeric workload, semantic method/work-model,
performance-settings hash, backend adapter/runtime/binary/model identity, OS family,
CPU classification/logical count, RAM bucket, device and optional future GPU/driver
classification, timestamp, successful duration/work/rate. Current hardware observation
uses CPU/RAM facts only, without GPU probes. Never record source/project IDs or labels,
filenames, paths, usernames, hostname, serial/SID/MAC, arbitrary identifiers, raw logs,
environment or secrets. No upload, network, heavy dependency or opaque learned model.

All new estimator/history/progress correctness tests use injected monotonic and UTC
clocks, never sleep thresholds. Cover privacy, retention, exact incompatibility, scale,
dispersion, transient spikes and stalls, learning across executions, terminal/cache
eligibility, history/event failures, cancellation, crash/recovery and old-event reads.
M7a uses `features.selected_views_v1`, exact VIEWS total and views/megapixels workload.
Verified COLMAP 4.2.1 logs supply per-view completion/features through existing process
polling: 64 KiB reads, 4096-byte lines, eight files and 32 MiB total logs. Other formats
keep observed completion at zero until terminal success and may use historical ETA
through the unchanged estimator. Elapsed time never advances the count. Exact native/
runtime/model/settings identities and the existing hardware profile partition history.
M7b uses `matching.explicit_pairs_v1` (all requested PAIRS) and
`verification.raw_match_pairs_v1` (positive raw-match PAIRS, including insufficient
sets the native verifier rejects). It reports real copying/execution/validation phases
and elapsed time through existing process polling; no log parser currently claims
individual pair completion. Counts remain zero until validated terminal success.
Historical estimates are stage-specific, partitioned by exact matcher/descriptor/
settings/model/runtime/precision and existing hardware profile. Unclassified GPU
hardware remains unknown rather than inferred. Cache/failure/cancellation teach no
history. Neither profile labels nor performance history enter numerical recipes.
M8 exposes only reliably supported phases and may leave percent/ETA unavailable
or use wide historical ranges at low/medium confidence. M11 managed trainers report
iterations/steps and their device/runtime/settings identity. No such backend is added
by M6.5, and clients must never fabricate progress for it.

## Structured events and diagnostics

The pre-M7 pass keeps artifact validation operation-scoped. A repository writer lease
creates a fresh `ArtifactValidationContext` for one prepare/build/recover/retry command
and discards it on every exit. Read-only callers can explicitly use
`validation_operation()`; unscoped reads get a fresh traversal context. Memo identity
includes the project root, complete artifact handle, concrete manifest path, indexed
manifest digest and producer attempt. `FULL_DECODE` can satisfy `PAYLOAD_INTEGRITY`,
but the reverse requires a new stronger validation. A recursion-path set detects cycles
separately from the memo. Typed metadata and small integrity results are retained;
candidate image bytes are never cached. A later command always checks bytes again.

Published validation streams each payload hash once and reuses that evidence while
checking typed metadata, image headers and supported full pixel decode. Shared lineage
and loaders reuse the parsed result. PairSet operations still establish exact upstream
byte integrity without pixel decode. Test actual candidate image hash calls for cached
M3/M4/M6 routes, stronger-after-weaker requests, diamond ancestry, recovery and corruption
between operations; do not substitute cache UUID equality for integrity assertions.

Fixed-FPS sorts exact rational times and performs an O(N + K) nearest-neighbor sweep
after O(N log N) sorting. Earlier time, then stable ID, wins ties. Reusing the global
nearest candidate leaves an unsatisfied slot, with no second-nearest fallback. Both
selectors refuse slot/interval counts beyond candidate count plus remaining bounded
unsatisfied capacity before expansion. Keep a deterministic brute-force test oracle
and counting-sequence complexity checks; default tests have no timing thresholds.
Manual 1k/2k/5k/10k timings are evidence, not acceptance limits.

M3 persists each source verification row durably, accumulates only its compact producer
projection, then writes the complete attempt provenance once after every source has
been consumed successfully and cancellation checked. This precedes expected-publication
identity and rename. Failure/cancellation can leave durable source rows with empty
attempt provenance; those attempts cannot publish or become cache eligible. Test write
count and serialized-byte scaling with synthetic 1/10/100/300-source attempts.

`ProcessInvocationEvidence` v1 is an explicit optional evidence callback from FFmpeg,
not automatic ProcessRunner logging. Each materialization invocation records native
identity/version, diagnostic argv, cwd, source/index, elapsed time, exit/timeout/cancel,
tree teardown/forced cleanup, captured sizes/digests and bounded readable excerpts.
Exceptional cleanup retains original cause and cleanup facts; streams unavailable from
the runner remain null. Future callers must explicitly redact secret argv. FFmpeg records
an empty scoped environment; the contract permits only bounded numeric thread/device
overrides. Never serialize inherited environment, API keys, passwords or tokens.

Readable excerpts are at most 16 KiB UTF-8 per stream (smaller when JSON escaping needs
space), records at most 96 KiB and the attempt file at most 4 MiB including a reserved
retention marker. Appends flush/fsync. At the file limit, append one truncation marker,
refuse subsequent detail deterministically and warn without failing computation.
Append failures also warn through the result/events where possible; SQLite attempt
status and artifact publication remain authoritative. `run show` exposes only a bounded
summary. Test append failure before/after earlier records, bounds, secret exclusion,
exceptional teardown and unchanged numerical keys/digests. Doctor and ingest FFprobe
remain outside project attempt logging. The real FFmpeg integration also verifies a
durable record from the complete candidate route and unchanged source bytes.

Operational events contain a schema version, UTC time, monotonic sequence/duration,
project/run/attempt/stage IDs, severity, stable event/error code, message and bounded
structured fields. Progress includes completed/total units when known. Raw backend
logs remain separate. Emit capability checks, cache hit/miss reasons, resolved method
choices, start/finish, resource estimates, retries, cancellation and output validation.

A future `doctor`/project diagnostics command should report:

- Project/config/state versions, migration status, missing/corrupt artifacts, incomplete
  attempts, missing/relinked sources, verification policy/evidence/assurance and
  rehash reasons, free space and unsupported storage locations.
- Binary/library/model identity, supported operations, probe evidence, GPU/device,
  runtime/driver health, available VRAM estimates and actionable capability failures.
- Per-group selected/registered images, pair-graph coverage, verified match statistics,
  reconstruction components, recorded manual/policy selection and exclusion reasons,
  track lengths, reprojection distributions and camera plausibility. Report
  denominators, units and unknown values explicitly.
- Resolved plan, source/model digests, seeds, environment and numerical reproducibility
  limitations. Explain why a stage will rerun or why downstream execution is blocked.

Distinguish input/configuration errors, unsupported capability, source unavailable,
resource exhaustion, transient I/O, backend failure, cancellation and invalid output.
A low-quality reconstruction is a quality result, distinct from process failure.
Support bundles are opt-in, exclude media/model payloads by default and allow path/GPS
redaction. Logs and telemetry remain local unless the user explicitly exports them.

## Windows, CUDA, COLMAP and scale risk register

| Risk | Required response and verification |
| --- | --- |
| Spaces, Unicode, long paths, drive/UNC names and reserved filenames | Use `Path`/argument arrays, generated owned names and tested backend path limits; report unsupported paths before work; never silently move originals |
| Case collisions, junctions and symlinks | Validate resolved containment at each write/cleanup boundary, reject unexpected reparse points in owned trees and check path aliases; never rely on lexical prefixes or a one-time resolve. This is accidental-damage protection, not a hostile same-user sandbox |
| Antivirus, open handles, disk-full or power loss during rename | Explicit sharing-violation reporting without automatic retry, closed handles, same-volume publication, transactions and failure-injection recovery tests; a bounded retry policy remains optional if later justified |
| SQLite on shares/sync folders or simultaneous CLI/GUI writers | Local active storage and one writer initially; tested backups and locking; no blind copy of an open database |
| Missing DLLs, unsupported CPU/GPU/runtime combinations | Isolated probes and tiny functional smoke checks per selected backend; do not infer health from a CUDA version banner |
| CUDA memory exhaustion or desktop GPU contention | Preflight estimates, configurable feature/image/batch budgets, bounded concurrency and actionable failures; setting changes create a new recorded plan |
| COLMAP command/schema/camera changes | Verify operation/help/schema capability, isolate command builders and native ID conversion; support named tested builds rather than every version |
| Descriptor-family/weight mismatch | Validate representation and model identity; isolated native databases; refuse unsafe conversion or reuse |
| Mutable native databases and WAL sidecars | Use consistent snapshots, no writable hardlinks, and private downstream assembly with current camera/ID metadata; verify upstream payloads remain unchanged after matching/mapping |
| Variable-frame-rate video, EXIF rotation, zoom/stabilization and rolling shutter | Preserve time bases/transforms, separate calibration groups, flag unsupported assumptions; do not claim rolling-shutter correction without an implementation |
| Exhaustive pairs and large frame/image collections | Budget candidates before decode and include workspaces, native database copies, publication, exports and backups in peak disk estimates. Stream/chunk data, bound logs, require measured M7c retrieval for production multi-video E2E acceptance and manual safe cleanup in M10 |
| Expensive source rereads or unreliable change indicators | Full hash at ingest; recorded Balanced/local default and Strict option, explicit evidence quality on network storage, no silent downgrade after verification failure |
| Insufficient overlap, repetitive texture, vegetation, moving objects or weak baseline | Per-group quality/coverage diagnostics and later masks/adaptive selection; process exit zero cannot imply scene quality |
| Model/weight drift and incompatible Python packages | Optional versioned environments, recorded model digests and explicit provisioning; preserve resolved settings and report nondeterminism |

SQLite documents locking and file-copy failure modes, supporting the conservative
local-storage and backup policy: [SQLite corruption guidance](https://sqlite.org/howtocorrupt.html).
COLMAP commands and feature support must be checked against the installed build:
[COLMAP CLI](https://colmap.github.io/cli.html) and [COLMAP FAQ](https://colmap.github.io/faq.html).
A Strict source lease must be proved for the actual filesystem/backend combination.
Windows read handles can deny conflicting write/delete access, but an unprotected
reopen cannot establish byte continuity; long-path support is also a per-application
capability, not a consequence of using `Path`:
[CreateFileW sharing and path semantics](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
For an open SQLite store, use a supported consistent backup operation, not raw copies
of database/WAL files: [SQLite backup API](https://sqlite.org/backup.html).
These upstream references were reviewed on 2026-10-19; they are not a substitute for
runtime evidence from the user's machine.

Release packaging should prefer current stable upstream toolchains only after tests,
pin shipped binary/model identities and never auto-trust a new upstream release.
Application updates may ship a newer tested runtime side-by-side; recorded work keeps
the concrete backend identity actually used.

## Definition of done

Choose affected/full checks using the [verification workflow](#verification-workflow);
report exact failures/skips and integrations actually executed. Review public contracts,
migrations, fingerprint changes, diagnostics and user-data safety for each behavioral
change. Inspect the final diff for unrelated files and generated data. Documentation-only
work checks links, terminology, milestone/prompt alignment and implemented/planned
claims; run code checks when needed to verify such claims or explicitly requested.
No automatic commit or dependency/model installation.

## M10 verification

Focused acceptance uses test_dataset_contracts.py, test_dataset_capabilities.py,
test_dataset_execution.py, test_dataset_cli.py and test_cleanup.py. Analytical sparse
fixtures exercise independent reader/hash/dimension/camera/pose/point/track checks and
native-ID-independent identity. Lifecycle fixtures cover exact M9 gate/override and
historical pixels after original relocation, separate components, component cache reuse,
resize-only invalidation, cancellation before/during native work, workspace refusal,
corrupt/partial orphan refusal and restart. Cleanup checks no-op preview, exact apply,
pins/current/active protection, unknown/original IDs, Unicode/space paths, filesystem
redirection and durable interrupted eviction/recompute. Default tests need no native tools.

Set SPLATFORGE_TEST_DATASET=1 and SPLATFORGE_TEST_COLMAP to the provisioned supported
executable for test_dataset_cameras_integration.py and test_dataset_integration.py.
The first actually undistorts all six supported perspective models with native and
bounded dimensions; the second executes tiny M7/M8/M9/M10 transport plus reader/cache/
resize/cancellation. They do not establish production VPR acceptance or mapper quality.
No downloads, model installation, ImageMagick, Python CV or training library are required.
See [M10](M10.md) for exact output and verification contracts.


## M8a verification

M8a tests use synthetic sparse binary files and fake contained native requests independently
of installed COLMAP. They exercise component/set identity, camera/pose convention, legacy and
current rig/frame transport, unavailable points/tracks, all-component publication, numerical
mapping projection, private DB byte integrity, calibration failures, resource gates,
cancellation, malformed cache/orphan refusal, recovery, CLI and phase-only M6.5 history.
`test_mapping_integration.py` is an opt-in M7a -> matching -> verification -> Global route
on deterministic tiny perspective patches with real parallax. Use the provisioned runtime
and optional explicit calibration smoke described in [M8A.md](M8A.md); no installation,
download or system PATH changes occur. Tiny transport does not establish scene quality.

`mapping.global_phases_v1` normalizes historical work as one complete mapping job and
retains phase mode with explicit `historical_job_duration` opt-in. Generic phase totals
retain unavailable ETA. M6.5's existing estimator permits explicit whole-job phase historical planning
at low/medium confidence, with no live rate/percentage. The display aggregate keeps an
unknown fraction even when historical duration is available. Determinate estimator rules
are unchanged. Only committed successful uncached jobs teach history. Actual observable
phases are preparation, optional calibration, input validation, native mapping and output
validation; no Global rotation/positioning/BA log parser is claimed.

## M8b1 verification

M8b1 extends the same path with explicit single-model Incremental Ceres CPU and
capability-gated Caspar local/global BA. Focused suites are `test_incremental_contracts.py`,
`test_incremental_execution.py`, `test_caspar_capabilities.py`, existing reconstruction /
mapping suites, Doctor, CLI and Progress/ETA suites. Real `test_incremental_integration.py`
executes M7 -> Incremental -> ReconstructionSet -> Reader, cache/settings invalidation,
immutable upstream bytes and owned-process cancellation. Opt-in instructions and recorded
local evidence are in [M8B1.md](M8B1.md). Missing compiled Caspar skips with the exact
actionable preflight reason; mocks do not establish real-backend validation.

`mapping.incremental_phases_v1` uses phase-only historical whole-job duration. Separate
settings/runtime/device signatures keep Global CPU, Incremental Ceres CPU and Caspar GPU
history apart. Registered counts are post-validation diagnostics, never a live completion
fraction. Doctor help/build evidence, selected-device runtime evidence and real integration
remain separate. No native build/install or performance-driven method selection is added.


## M8b2 verification

[Hierarchical/Global GPU/comparison contracts and recorded local evidence](M8B2.md)
extend existing M8a/b1 tests. Focused suites include test_hierarchical_contracts.py,
test_hierarchical_capabilities.py, test_hierarchical_execution.py, test_global_gpu.py,
test_global_backward_compatibility.py and test_mapping_comparison.py, plus shared
Reader/cache/recovery/cancellation, Doctor, CLI and M6.5 progress/ETA regressions.

Opt-in test_hierarchical_integration.py uses 12 perspective views and small test-only
leaves, requires observed multiple clusters/native merge, validates final disjoint output
and Reader, checks M7 bytes/cache/settings invalidation, and cancels a launched process.
Global GPU integration tests GP only, BA only and both separately, using 60 views only
when the already provisioned Ceres/device preflight succeeds. Missing Ceres CUDA/cuDSS
or unverified runtime evidence is an explicit skip, never successful GPU validation.
No downloads/builds/runtime replacement are part of testing. Tiny native fixtures establish
transport contracts, not representative quality or a production mapper recommendation.

Hierarchy uses mapping.hierarchical_phases_v1 with observed headings and diagnostic leaf
counts, never a leaf-count percentage. Global GPU retains Global phase semantics and
separates performance signatures for each acceleration axis/device. Incomplete evidence,
CPU fallback and final overlapping Hierarchical hypotheses fail without automatic retries.
M7c production VPR benchmarks remain pending; M9 and technical M10 are documented separately.

## M9 verification

M9a tests use exact historical selected universes, mixed source/group coverage, analytically
known perspective/distorted projection errors, exact integer track histograms, deterministic
bounded quantiles/rays and explicit policy/availability. Native fixtures change point IDs,
image/camera IDs and folder numbering independently of canonical geometry; changed XYZ,
observations, camera poses or frozen camera-sharing priors change the consumed evidence.
Camera sharing compares the actual frozen mapper-prior partition, not possible candidate
grouping. Existing M8 artifacts are read without changing their schema or numerical identity.
Publication/cache/corruption/cancellation and every orphan stage use normal execution storage.

```powershell
python -m pytest tests/test_validation_measurements.py tests/test_validation_geometry.py tests/test_validation_execution.py tests/test_validation_cli.py tests/test_validation_progress.py
```

`validation.reconstruction_points_v1` reports WORK as scanned points, with known native
point totals where available and observation diagnostics. Zero/unknown detailed point work
and policy evaluation are phase-only; component index never supplies an overall fraction.
M6.5 successful history uses points/components and separate method/sampling signatures.
Cold ETA is unavailable until live evidence supports it; history cannot alter methodology.
Native payload integrity revalidation still runs when numerical measurements are cached.

M9b tests cover manual canonical one/multiple choices, legal disjoint mixed phone/drone
coverage tradeoffs, unique dominance, severity/quality tradeoffs, missing ranking evidence,
scoped project/component/source-group failures, exact/stale overrides and changed cameras
or detailed XYZ under identical component UUIDs. Reason/policy/artifact UUID changes retain
selected-content semantics. Cache, indexed/orphan corruption, cancellation and recovery
use normal state. Ambiguity creates no selection artifact. No dataset generation is claimed.

```powershell
python -m pytest tests/test_reconstruction_selection.py tests/test_selection_execution.py tests/test_selection_cli.py
```

The M9 integrity mode has explicit tests proving policy-only reuse does not deserialize
native points/tracks, while changed bytes, hardlinks and unexpected model entries still
fail. Ordinary M8 integrity/cache/recovery is unchanged. This reuses original structural
validation over freshly hash-verified identical bytes, not metadata-only source assurance.
All three scan refusal limits remain outside numerical identity; deterministic sampling
never changes to fit runtime history or machine speed.
Metadata resource tests also reject excessive component/source coverage matrices before
geometry access and enforce the 64 MiB evidence bound before a payload file is written.
Inactive component/cell limits preserve identical measurements/recipes. Metadata grouping
retains cancellation checkpoints and never silently drops sources or components.

## M11 optional managed runtime and tests

The normal Python 3.12 application environment has no Torch/gsplat requirement. All risky
imports, CUDA probes and training execute under an explicit separate Python executable
with `-I`. The worker registers only its own package paths, so application site-packages
cannot shadow trainer dependencies. CLI commands and resolved runtime JSON are documented
in [M11](M11.md). Product commands never pip-install, upgrade packages or download models.

For explicitly authorized development validation, use an ignored isolated local path such
as `sample_data/m11-runtime/`, record exact versions/build hashes and freeze the environment.
Reuse existing toolchains; never change global Python or global PATH. The validated local
profile is Python 3.12.10, Torch 2.7.1+cu128, CUDA 12.8 and gsplat 1.5.3 built unchanged
from its exact release sdist. The pure-wheel MSVC JIT failure and native-wheel hash are
recorded in M11. Capability must positively execute a raster kernel, backward and optimizer
step on the selected GPU before claiming runnable; installation alone is insufficient.

Run focused contracts/protocol/PLY/adapter/lifecycle/progress/CLI tests during changes:

```powershell
python -m pytest tests/test_training_contracts.py tests/test_training_protocol.py tests/test_gaussian_scene.py tests/test_training_adapter.py tests/test_training_execution.py tests/test_training_progress.py tests/test_training_cli.py tests/test_training_comparison.py
```

Real CUDA acceptance is opt-in and requires an explicitly provisioned runtime descriptor:

```powershell
$env:SPLATFORGE_TEST_TRAINING_RUNTIME = 'C:\LocalRuntime\runtime.json'
python -m pytest tests/test_training_integration.py
Remove-Item Env:SPLATFORGE_TEST_TRAINING_RUNTIME
```

These tiny analytical M10 tests exercise Default, AbsGrad and MCMC through real CUDA,
checkpoint at 25/resume to 50, PLY export/independent reader plus `plyfile` consumer,
cache and actual process-tree cancellation. They are transport evidence, not quality.
Native fake-process tests additionally cancel while a descendant holds a partial
checkpoint/PLY file, require handle release and preserve earlier published checkpoints.
Do not enable integration implicitly in the default suite.

Fair candidate comparison requires one exact M10 component and explicit identical held-out
IDs. Report aggregate and recoverable source-group PSNR/SSIM, LPIPS availability, counts,
time, peak **allocated** CUDA bytes and sizes separately; do not call training loss a
validation score. No LPIPS model is downloaded. Russian-dacha uses existing M10 artifacts,
not repeated M7–M10. Frozen settings/evidence and one-scene limitations are in M11.
For training milestone completion, apply the full gate in the
[verification workflow](#verification-workflow); report unrelated pre-existing
failures rather than fixing them in that milestone.
