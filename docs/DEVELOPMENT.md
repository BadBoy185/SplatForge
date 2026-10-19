# Development, testing and diagnostics

[AGENTS.md](../AGENTS.md) is the engineering constitution. This guide defines the
verification strategy for planned implementation; only three foundation tests exist.
Use the project virtual environment and the [README commands](../README.md#current-status).
At the 2026-10-19 review baseline, `pytest` passes three tests and Ruff finds 18
pre-existing violations (17 E501 and one UP037). Keep documentation-only diffs free
of incidental code fixes. Python 3.12 is the baseline; wider `requires-python` metadata
is not evidence of testing on every later Python release.

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
including training-only changes, feature-independent pairs, camera priors, masks,
validation gates, corrupt/missing payloads and source relocation. Test cancellation
and publication races, not merely the happy path. Architecture/import checks must
prevent core/UI dependencies on backend libraries and direct process execution.

## External process contract

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
children holding CUDA/file resources. A Windows Job Object is a candidate mechanism;
prove behavior under nesting and forced termination before relying on it. Do not
assume POSIX signals or killing the parent handles children. Microsoft documents Job
Objects as a way to manage process groups: [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

Heavyweight in-process libraries stay behind adapters. If they cannot cancel safely
or can crash the host, run the adapter in a managed worker process. Avoid adding a
service or network protocol just to isolate one library. Resolve approved executables
explicitly rather than searching a project-controlled working directory first.

## Structured events and diagnostics

Operational events contain a schema version, UTC time, monotonic sequence/duration,
project/run/attempt/stage IDs, severity, stable event/error code, message and bounded
structured fields. Progress includes completed/total units when known. Raw backend
logs remain separate. Emit capability checks, cache hit/miss reasons, resolved method
choices, start/finish, resource estimates, retries, cancellation and output validation.

A future `doctor`/project diagnostics command should report:

- Project/config/state versions, migration status, missing/corrupt artifacts, incomplete
  attempts, missing/relinked sources, free space and unsupported storage locations.
- Binary/library/model identity, supported operations, probe evidence, GPU/device,
  runtime/driver health, available VRAM estimates and actionable capability failures.
- Per-group selected/registered images, pair-graph coverage, verified match statistics,
  reconstruction components, track lengths, reprojection distributions and camera
  plausibility. Report denominators, units and unknown values explicitly.
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
| Case collisions, junctions and symlinks | Stable content/view IDs, collision checks and resolved-root containment before writes/cleanup; never derive identity solely from spelling |
| Antivirus, open handles, disk-full or power loss during rename | Bounded sharing-error retry, closed handles, same-volume publication, transactions and failure-injection recovery tests |
| SQLite on shares/sync folders or simultaneous CLI/GUI writers | Local active storage and one writer initially; tested backups and locking; no blind copy of an open database |
| Missing DLLs, unsupported CPU/GPU/runtime combinations | Isolated probes and tiny functional smoke checks per selected backend; do not infer health from a CUDA version banner |
| CUDA memory exhaustion or desktop GPU contention | Preflight estimates, configurable feature/image/batch budgets, bounded concurrency and actionable failures; setting changes create a new recorded plan |
| COLMAP command/schema/camera changes | Verify operation/help/schema capability, isolate command builders and native ID conversion; support named tested builds rather than every version |
| Descriptor-family/weight mismatch | Validate representation and model identity; isolated native databases; refuse unsafe conversion or reuse |
| Mutable native databases and WAL sidecars | Close/checkpoint before snapshot/publication; never share a published writable database between stages; verify snapshot integrity |
| Variable-frame-rate video, EXIF rotation, zoom/stabilization and rolling shutter | Preserve time bases/transforms, separate calibration groups, flag unsupported assumptions; do not claim rolling-shutter correction without an implementation |
| Exhaustive pairs and large frame/image collections | Estimate pair count and disk demand, use streaming/chunks and bounded logs, enforce budgets, add retrieval only with measured coverage |
| Insufficient overlap, repetitive texture, vegetation, moving objects or weak baseline | Per-group quality/coverage diagnostics and later masks/adaptive selection; process exit zero cannot imply scene quality |
| Model/weight drift and incompatible Python packages | Optional versioned environments, recorded model digests and explicit provisioning; preserve resolved settings and report nondeterminism |

SQLite documents locking and file-copy failure modes, supporting the conservative
local-storage and backup policy: [SQLite corruption guidance](https://sqlite.org/howtocorrupt.html).
COLMAP commands and feature support must be checked against the installed build:
[COLMAP CLI](https://colmap.github.io/cli.html) and [COLMAP FAQ](https://colmap.github.io/faq.html).
These upstream references were reviewed on 2026-10-19; they are not a substitute for
runtime evidence from the user's machine.

## Definition of done

Run scoped tests, full pytest and `ruff check .`; report exact failures/skips and
which integrations were actually executed. Review public contracts, migrations,
fingerprint changes, diagnostics and user-data safety for each behavioral change.
Inspect the final diff for unrelated files and generated data. Documentation work
also checks relative links, terminology, milestone/prompt alignment and accurate
implemented/planned claims. No automatic commit or dependency/model installation.
