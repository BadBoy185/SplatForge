# Development, testing and diagnostics

[AGENTS.md](../AGENTS.md) is the engineering constitution. This guide defines the
verification strategy; foundation, M1b2 execution/recovery and the M2 media/process
boundary have automated coverage.
Use the project virtual environment and the [README commands](../README.md#current-status).
Python 3.12 is the baseline; wider `requires-python` metadata is not evidence of testing
on every later Python release.

## Testing layers

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
Add explicit integration/GPU markers when those tests exist. Tests skip with reasons
when prerequisites are absent; skips are not evidence of backend support. Configure
separate Windows integration runs for supported backend builds and retain capability
reports. Include Windows Server/headless execution before claiming support there.

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
an executable path (or `1` to use configured PATH lookup) for the generated tiny MPEG-4
VFR and explicit-rotation integration test. That test must skip with its exact reason
when unconfigured; a skip is not backend evidence. A future full media-add-to-M3 smoke
test may additionally require `SPLATFORGE_TEST_FFPROBE` as a separate opt-in setting.

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

The process adapter owns executable resolution, argument arrays, working directory,
scoped environment, lifecycle and streamed stdout/stderr. No shell interpolation or
global `PATH` mutation. Record the selected binary identity and invocation; redact
credentials if a future backend introduces them. Return structured exit, timeout,
cancellation and output-validation results, not an unclassified text blob.

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

## Structured events and diagnostics

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
| Exhaustive pairs and large frame/image collections | Budget candidates before decode and include workspaces, native database copies, publication, exports and backups in peak disk estimates. Stream/chunk data, bound logs, require measured M7c retrieval before M10 and manual safe cleanup by M10 |
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

## Definition of done

For implementation changes, run scoped tests, full pytest and `ruff check .`; report
exact failures/skips and integrations actually executed. Review public contracts,
migrations, fingerprint changes, diagnostics and user-data safety for each behavioral
change. Inspect the final diff for unrelated files and generated data. Documentation-only
work checks links, terminology, milestone/prompt alignment and implemented/planned
claims; run code checks when needed to verify such claims or explicitly requested.
No automatic commit or dependency/model installation.
