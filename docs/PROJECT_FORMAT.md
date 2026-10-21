# Project format and execution state

Status: M1b2 local persistence/execution, M2 media/process containment and the M3
candidate-view/fixed-FPS route are implemented. Version numbers for
the project, pipeline settings, state database,
manifests and individual methods are separate; the prototype
`PipelineConfig.schema_version = 1` is not a project format declaration.

## Storage layout and ownership

Use a local writable project directory, separate from the source repository:

```text
project/
  project.json                         # Authoritative saved intent, format and revision
  sources/
    <inventory-id>.jsonl                # Immutable inventory revisions; no originals
  state.sqlite                         # Run/attempt/artifact index and execution state
  project.lock                         # Stable file for the OS-held writer lock
  artifacts/
    <stage>/<artifact-id>/
      manifest.json                    # Contract, provenance, digests, relative files
      ...                              # Native payloads, images, reports or models
  work/
    <run-id>/<attempt-id>/              # Unpublished adapter-owned scratch data
  runs/
    <run-id>/run.json                   # Frozen resolved plan and environment snapshot
    <run-id>/events.jsonl               # Structured operational events
    <run-id>/cancel.request             # Atomic request carrying this run's ownership token
    <run-id>/logs/<attempt-id>/...      # Raw backend stdout/stderr and invocation metadata
  checkpoints/
    <run-id>/<attempt-id>/...           # Explicitly retained trainer checkpoints
  exports/
    <export-id>/...                     # User-facing deliveries; never generic cache
  backups/
    <migration-id>/...                  # Consistent pre-migration copies
```

The layout reserves ownership names, not an eager directory skeleton. Project
creation writes the project document and state database; M1b creates run, work and
artifact directories only during execution. Checkpoint, export and log paths remain
lazy until their features exist. Payload details are adapter-owned.
Stable IDs provide deterministic naming, not identical run IDs on rerun.

The application owns `project.json`, inventory revisions, `state.sqlite`, manifests
and publication. An adapter owns only its assigned workspace and native payload
format. Published artifacts are immutable. Originals are external read-only references;
future managed copies require an explicit import mode and separate provenance.

## Authoritative records

| Record | Required meaning |
| --- | --- |
| Project document | Format version, project ID, revision, label, creation/update times, current inventory reference, saved stage settings and preset provenance |
| Source inventory | Source ID and digest/size, last full-hash time and evidence snapshot, original locator/name, media type/probe result, source group, camera group and calibration policy |
| Pipeline settings | Separate versioned method/settings envelopes with resolved values; current known configs plus preserved opaque settings, no speculative future schemas or runtime statuses |
| Run snapshot | Project revision, resolved settings, selected target/route and node/output references, source policy/preflight evidence, expected environment, seeds, resource policy and run ownership token |
| Stage attempt | Run/node/attempt IDs, recipe key, bound input artifact IDs, actual environment/source-verification evidence, status, cancellation acceptance, expected publication identity, timestamps, process/log references, failure and retry relation |
| Artifact manifest | Manifest/contract versions, artifact ID/type, producer attempt, recipe key, semantic content digest, input lineage, relative payload paths with sizes/digests and validation result |
| ReconstructionSelection artifact | Referenced ReconstructionSet, chosen component IDs, manual/policy mode, policy/version/settings, validation evidence, reasons and decision fingerprint; published under the normal artifact convention |
| Checkpoint manifest | Trainer/version, dataset and settings identity, completed work, resume requirements, retained files and integrity checks |

`project.json` is authoritative for editable intent; `state.sqlite` is authoritative
for attempt history and indexed publications. Run snapshots preserve intended execution; attempts record what actually executed. Save intent only while no run owns the writer lock in the initial release;
other saves return busy and may leave an unsaved UI draft. Freeze the complete revision
into run.json, then persist the run's state; do not attempt a distributed transaction.
Future outputs are node/output references in that snapshot. Attempts bind real input
artifact IDs and record actual runtime/verification evidence before consuming inputs;
new evidence never edits run.json. A complete orphan snapshot with no state/attempts
can be inspected, not assumed executed. On restart reconcile complete records only.

Ingest is an application operation that can run recorded probe/hash attempts. Its
inventory is a versioned project input, published by the inventory/project-save
protocol below, rather than by the derived-artifact publication protocol.

The SQLite schema starts with metadata at M1a1 and adds runs, attempts, artifact
indexes and their relationships at M1b. Do not put descriptor arrays, media or raw
log streams into application state. JSONL events support diagnosis, not event-sourced
reconstruction of the whole database.

### Implemented project and state formats through M4

`project.json` uses `project_format_version: 1`, a UUID `project_id`, `revision`,
`label`, UTC `created_at`/`updated_at`, nullable `inventory_reference`, nullable
`preset_provenance` and `settings`. Revision starts at **0**. A successful save
compares the committed revision under the writer lock, publishes exactly the next
revision and returns it to the caller. Stale saves are refused. Save refreshes
`updated_at` while retaining project identity and creation time.

`settings.config_schema_version` is **1**, independent of the project format.
Its six required slots are `frame_selection`, `feature_extraction`,
`pair_selection`, `feature_matching`, `mapping` and `training`.
Each contains an envelope:

```json
{
  "method_id": "frame_selection.sharpest_interval",
  "settings_schema_version": 1,
  "settings": {
    "target_fps": 2.0,
    "max_frames": 1800,
    "reject_blur": true,
    "reject_duplicates": true
  }
}
```

The four SfM slots currently have empty settings objects and their saved method IDs.
Training retains the prototype's `preset` value as a setting; M1a1 does not invent
trainer parameters or perform future training-preset translation. All existing
prototype values are copied explicitly at creation. `PipelineConfig` stays unchanged.

Default creation records `preset_provenance` as
`{"name": "recommended_flat_video_profile", "version": 1}`; custom prototype
configuration has null provenance. Provenance is descriptive only. Opening a
project reads its saved resolved values without consulting defaults or presets.

Envelope settings and extra envelope fields preserve nested JSON values, including
unknown method IDs and settings-schema versions, through open/save/reopen. This
guarantees equivalent JSON data, not original formatting. The outer project/settings
structures reject unrecognized fields instead of silently discarding them. Unsupported
project/config/state versions are refused without rewriting either store. Envelope
recognition or execution compatibility is not required for open/show/save.

New projects use `state_schema_version = "4"`. Alongside `metadata`, SQLite contains
`runs`, `attempts`, `artifacts`, `run_outputs` and `source_verifications`; recipe keys are
indexed but are not unique artifact identities. State v3 fields remain unchanged. State
v4 adds only bounded source verification policy, evidence, digest, assurance, stability,
outcome and diagnostics records indexed by source revision/content/check time. It stores
neither media, full FFprobe JSON nor unbounded logs. M3 and M4 do not change this schema:
attempt `environment_json` and `source_verification_json` store bounded FFmpeg and
per-source consumption provenance already supported by v4; M4 quality and pure-Python
selection provenance use those existing bounded attempt fields.

Existing state v1/v2/v3 projects remain supported by open/show/save without implicit
writes; historical runs remain inspectable. The fake M1b route works on v3 and v4; M2
mutation/verification and M3/M4 execution require v4. Historical fake snapshots remain
valid because run snapshot schema 1 now discriminates the existing `fake.two_node`
and `views.prepare_fixed_fps` routes from `views.prepare_sharpest_interval`. The M3
snapshot freezes inventory identity,
selected source records, exact candidate/target FPS settings, verification policy,
resource limits and FFmpeg identity, but only typed future output references—not
guessed artifact UUIDs. The M4 snapshot additionally freezes Pillow/method identity,
quality preprocessing and explicit sharpest-selection policy. Historical snapshots and
artifacts are not rewritten. Explicit upgrade rechecks under the writer lock and
publishes one validated backup. v1 creates the final execution plus verification schema,
v2 adds M1b2 columns plus verification state, and v3 adds only verification state, each
in one transaction. All become v4 without rewriting `project.json` or its revision.
After backup and `PRAGMA foreign_keys=ON`, an explicit `BEGIN IMMEDIATE` precedes
the first CREATE/ALTER. DDL and the version update commit together; a failure rolls
both back and leaves the backup available for inspection and a clean upgrade retry.
Calling upgrade on v4 is a read-only no-op; unsupported newer versions remain untouched.

Creation accepts a missing or empty destination and creates `project.json`,
`project.lock` and `state.sqlite`. The destination is checked again after acquiring
the OS-held lock; lock-file existence or contents do not establish ownership.
The Windows lock opens without truncation or following a reparse point, validates
the actual handle as a disk file at the owned lock path with exactly one hard link,
and refuses directories, links and redirected/aliased objects before diagnostics.
Delete sharing is denied while held; byte-range ownership stays non-blocking.
Diagnostic writes recheck that handle. Release errors cannot falsify a committed save.
Saving flushes, closes and validates a temporary sibling before same-volume replacement.
`os.replace` is the project-document commit point: a failed pre-commit step retains
the previous document, while reopen after a completed replacement observes the new
revision. This is not an atomic multi-file or blanket power-loss guarantee. There is
no general partial-create recovery framework.
The persisted owned-path field `inventory_reference` is null initially or a canonical
`sources/<inventory-id>.jsonl` path. Absolute/drive-qualified/traversal/alternate-stream
paths and symlink/junction redirection are refused at publication/read boundaries.

## Paths and source identity

Store project-owned paths as project-relative paths with a canonical separator;
resolve them with `Path` at the storage boundary. Reject absolute/drive-qualified
paths, `..` traversal and symlink/junction escapes in owned manifests. Preserve
external Windows/UNC source locators separately; they may legitimately be absolute.
Do not lowercase arbitrary paths to derive identity or assume case distinguishes files.
Reject device/alternate-stream names and ambiguous owned path components. A lexical
prefix check or Path.resolve at project open is not a lifetime guarantee: validate
containment/reparse points at each create, publish and cleanup boundary. Own the root
and generated names; fail closed on changes during an operation. Do not claim a
security boundary against another hostile process with write access to the same root.
Backend Unicode/long-path support must be tested independently of Python's Path support.

Assign source IDs independently of names and locations. Stream a full content digest
at initial ingest with progress/cancellation; save the size, metadata/identity evidence
and verification time alongside it. Equal content may be deduplicated for processing
while preserving distinct source occurrences, camera/timeline metadata and provenance.
Equal bytes do not authorize merging observations or calibration groups. A relink preserves
identity only after a full digest match; different bytes are a new source revision.

M2 inventory schema 1 is JSONL. Its first strict record contains record type, inventory
ID/schema/revision, project ID, parent inventory ID, UTC creation time and source count.
Each following strict source record contains an occurrence UUID/revision, external
locator and display filename, media type/extension/size/SHA-256, full-hash time/evidence,
independent source and camera group IDs, calibration policy and normalized probe result.
Probe data preserves backend identity, selected stream, codec/dimensions/orientation and
nullable rational video timing/rotation fields. Revisions publish new files; old files
are never rewritten. External originals are neither copied nor made project-owned.
New PNG probes read bounded eXIf chunk metadata without pixel decode and record
orientation 1 when EXIF is absent. Historical PNG records with `orientation=null`
remain inspectable but cannot prepare views: use `media add` to re-ingest, then
`views prepare --source-id` to select the new occurrence with orientation evidence.
No inventory/state migration or implicit metadata reinterpretation
occurs. Historical candidate contract 1 remains readable, subject to decode integrity;
corrected FFmpeg adapter version 2 uses a different recipe from version 1.

## Source verification policies

Media verification chooses a versioned policy per operation; future source-consuming
runs will freeze that choice in run provenance. Do not unconditionally reread every
multi-gigabyte source. Record per source: policy, prior digest and full-hash time,
current metadata/identity/change indicators, evidence availability, check time, rehash
reason/result and assurance.

| Policy | Behavior and recorded assurance |
| --- | --- |
| Balanced/local (default) | Compare size and last-write metadata plus file identity/change indicators where available with the last content-verified snapshot. If trusted indicators are unchanged, accept the stored digest as `metadata_unchanged`; do not label it freshly content-verified. Rehash fully when indicators change, contradict one another, are insufficiently trustworthy, or stronger verification is requested. |
| Strict | Fully hash required source content and consume the same stable byte identity. Reuse the check only while the protected source/snapshot remains valid; reverify when that guarantee ends. Record `content_verified` and the stability mechanism. |
| Any future weaker/faster policy | Explicit selection and versioned rules are required. Record the reduced checks and assurance; never silently substitute it when hashing or metadata access fails. No additional fast policy is required for the initial implementation. |

Balanced/local is a stated trust/performance tradeoff, not cryptographic proof of
unchanged bytes. It can miss edits that preserve the observed indicators. Define the
minimum trusted indicators for the storage type; optional file IDs/change journals
need not exist on every source. Network/removable storage may supply weaker or stale
evidence: record this and require full rehash or block source-dependent work when the
minimum evidence is not met. Metadata access errors are not an unchanged result.

A full preflight hash followed by an unprotected backend reopen is not Strict input
verification. Keep a tested read lease denying writes/replacement through verification
and consumption, or use an explicitly selected, space-budgeted project-owned snapshot
of the bytes read. Never silently copy a huge source. If neither mechanism is supported,
report Strict unavailable for that source/backend. Balanced uses before/after evidence
checks and retains its weaker assurance. These are source-adapter responsibilities,
not a distributed file-watch service.

If rehash confirms the same bytes, record new durable verification evidence in state
and retain content identity/cache eligibility. Do not rewrite an immutable
inventory or bump editable project revision merely to record a check. Later checks use
the latest completed content-verified evidence for that source revision/digest, indexed
in state; a Balanced acceptance does not reset that baseline. Otherwise unchanged
sources would be rehashed forever against obsolete ingest metadata. Changed bytes
require a future explicit replacement workflow and a new source revision; M2 reports
the change without rewriting intent. Stop/replan affected work; never silently replace
a frozen run's inputs. Preserve
historical artifacts. Detect changes during a read and
fail or retry rather than certify unstable input. Hashing remains streamed/cancellable.

Cache keys use the stored content digest; source verification is an additional
eligibility gate. Balanced reuse carries its weaker assurance into run/artifact lineage.
A Strict run must check that source-consuming artifact provenance meets its policy;
rehashing now does not retroactively prove what a previous weakly verified attempt
read. Rebuild affected lineage when assurance cannot be established. A policy change
alone does not invalidate numerical artifacts already supported by sufficient evidence.

Missing or changed originals do not prevent project inspection. Block operations
that need those originals with diagnostics. Already materialized, validated artifacts
can support downstream work offline when their contracts do not require source access;
record that originals were unavailable, not freshly verified. This is explicitly
recorded artifact-only reuse, not a claim that Strict verified the current originals.
Moving the project must not invalidate artifact fingerprints. Relocating originals is a separate relink action.

## Safe writes and migrations

This contract was adopted in two reviewable steps: M1a1 implemented the basic
single-process development slice (document/settings, versions, directories, SQLite
metadata, create/open/save/show and basic validated temporary-file replacement);
M1a2 completed revision/stale-save checks,
writer locking, atomic replacement, migration boundaries and Windows fault recovery.
The rules below describe the completed persistence contract used by future work.

No older production project format exists yet. M1a2 establishes current/unsupported
version dispatch and an internal validated migration-backup preparation boundary
without inventing historical versions or speculative transforms. Prototype
configuration conversion is not a historical project migration. A concrete restore
sequence or migration journal arrives only with a real multi-file format change.

- Create only at an absent or empty destination. Refuse a non-empty destination;
  there is no overwrite flag in the initial API. Do not remove a failed create target
  unless every removed file is proven to belong to that failed operation.
- Use an OS-held lock on the stable project.lock file, shared by CLI and GUI; the
  existence of a lock file is not ownership. Do not unlink/recreate a locked file.
  Readers inspect committed state; SQLite transactions stay short, not run-long.
  Record process-instance identity and an owner token for diagnosis; M1b adds a run
  token when runs exist. Never kill by PID alone.
- Save JSON using a validated temporary sibling, flushed writes and same-volume
  atomic replacement. Record a revision and reject stale concurrent saves. Close
  handles before replacement; report Windows sharing violations without losing the
  previous valid file. Do not promise atomicity across separate files.
- Publish a new inventory before atomically updating the project reference. A crash
  can leave an unreferenced inventory, never a reference to a partial file.
- Use SQLite transactions, foreign keys and explicit schema migrations. Native
  COLMAP databases are separate and never receive application schema migrations.
- Migrations are explicit, version-to-version, validated transformations. Preserve
  method IDs, resolved user values and preset provenance. Back up the project,
  referenced inventories and a consistent SQLite snapshot before mutation; a live
  database file copy alone is not a valid backup procedure.
- When a real migration touches multiple stores, record old/target versions and
  its phase. On interruption, finish a verified step or restore a consistent backup
  before writes. Test failure between file replacement and database commit. Atomic
  rename is not a blanket power-loss guarantee; detect/recover incomplete generations.
- A newer unsupported project/state format is refused without writes. Unknown method
  IDs/settings in a supported format must round-trip unchanged in an opaque versioned
  settings envelope; opening is allowed, dependent execution is blocked. Known settings are
  validated strictly. An unknown settings-schema version remains opaque even for a
  known method ID. Unknown top-level fields without an extension contract prevent
  saving rather than being silently dropped. Unknown settings block only a requested
  operation that needs them, not inspection or unrelated targets. IDs are data, never
  instructions to import code. Never rewrite frozen historical runs or native payloads
  during project migration; a payload conversion publishes a new versioned artifact.

Initial active project storage is a local filesystem with tested locking/rename
behavior (Windows baseline: NTFS). Network shares and cloud-synced project roots are
unsupported for active writes until tested. External sources may be on removable or
network storage; failures there must remain recoverable.

## Writer ownership and cancellation

One owner serializes project/state writes for a run. A second CLI can read status and
atomically create the bounded cancel.request file with the run ID/token; it does not
acquire the writer lock or edit SQLite. The owner validates and persists cancellation
acceptance before signalling workers. Request creation means requested, not yet
acknowledged. Repeated requests are idempotent; stale tokens cannot cancel a later run.
This one control file is sufficient; no daemon, general message bus or multiwriter store.

Publication and cancellation acceptance are serialized by the owner. If cancellation
was accepted before success commits, success is forbidden. If success committed first,
report too late. Recovery checks a valid outstanding request before adopting an orphan
publication and never promotes a durably accepted cancellation. Keep the request until
its terminal outcome is durable. A UI thread can use the same application cancellation
use case; widgets do not mutate the state database themselves.

## Attempts, publication and recovery

M1b2 implements cancellation, interruption, recovery and retry for the synchronous,
in-process fake stages. Cache reuse creates a run-output binding and no attempt. An
unfinished run blocks new execution until explicit recovery establishes owner absence.

Persist attempt states with explicit transitions:

```text
pending -> running -> succeeded
                   -> failed
                   -> cancelled
                   -> interrupted
pending -> cancelled
pending -> interrupted
```

A retry is a new pending attempt linked to the previous relevant attempt; a node that
never started has no retry link. M1b2 permits transient fake I/O failures and interrupted
attempts, rejects unclassified historical/non-retryable validation or configuration
failures, and limits each node to three total attempts per run. Valid completed upstream
bindings are reused. A preflight failure is a plan diagnostic before execution. Cache
reuse is a run-to-artifact reference, not a fake successful attempt. Disabled optional
stages are represented in the plan, not as successful processing. "Stale" is a cache
eligibility result, not an attempt state.

Publication protocol:

1. Persist the running attempt and create an owned workspace. Stream logs/events.
2. Complete processing, close backend handles/databases, validate required payloads
   and write the completed manifest with content checksums inside the workspace.
   Persist the intended artifact ID and completed manifest digest before moving it.
3. Move the completed payload directory on the same volume to a new artifact ID.
   Never overwrite an existing artifact; keep scratch and publication storage together.
4. After checking accepted cancellation, transactionally index the expected manifest
   and mark the attempt succeeded. Only indexed, validated publications are eligible
   for automatic reuse; event/log append failures cannot invent numerical success.

Recovery acquires the writer lock and refuses if it is busy. For the M1b2 in-process fake
backend only, successful acquisition proves no current project writer exists and there
are no external child workers, so the previous fake owner may be treated as gone. A
pending or running attempt without a completed moved publication becomes interrupted;
its workspace is preserved. This narrow guarantee does not prove external-process-tree
death and must not be reused as that proof in M2.

A complete unindexed publication is adopted only when its expected artifact/manifest,
producer run/attempt, node/output, recipe, artifact contract, payload sizes/hashes,
semantic digest and validator all match under owned-path checks. Accepted cancellation
or a valid pending request forbids adoption; cancelled, corrupt or unexpected output is
left unindexed and preserved for diagnosis. If all target bindings are valid, recovery
may finalize the run; otherwise it leaves the run interrupted and never executes stages.

For M4, `views.quality_report` contains only `quality_report.json`; its manifest has the
exact CandidateViewSet lineage. A sharpest `views.selected_set` contains only
`selected_views.json`; its manifest has exact CandidateViewSet and QualityReport lineage.
Adoption revalidates the strict typed payload, semantic digest, recipe and those upstream
bindings. A moved quality artifact with incomplete/wrong candidate coverage or lineage,
and a moved selection artifact that differs from deterministic policy output, are not
adopted. Unmoved partial workspaces remain diagnostic scratch. Valid candidate and
quality publications stay reusable when a later stage is absent or cancelled.

An accepted cancellation becomes terminal cancelled only after fake-stage execution has
unwound and its handles are closed. If injected teardown confirmation fails, M1b2 keeps
the run interrupted with unresolved teardown and blocks retry, adoption and publication;
it does not fabricate cancellation success. Real workers require owned process-tree
termination and bounded waits; M2 implements and proves those process guarantees.
Exceptional process failures also preserve the original cause, forced-termination
evidence and confirmed/unconfirmed tree teardown. FFmpeg maps unconfirmed cleanup to
an interrupted external attempt with unresolved teardown; the existing guard blocks
new processing and publication. A subsequent cleanup error cannot replace the cause
or fabricate confirmation. Doctor likewise retains an unresolved COLMAP workspace.

Retry transient I/O/process failures with bounded policy. Invalid settings, unsupported
capabilities and resource exhaustion require an actionable decision rather than an
infinite loop. A changed method/resource setting creates a new resolved run plan.
Stage-boundary resume reuses eligible artifacts and restarts incomplete stages;
checkpoint resume requires matching dataset, trainer and declared settings plus a
validated checkpoint. An external/manual training handoff is not resumable execution.

## Retention and diagnosis

Invalidation never deletes files. Retain artifacts during foundation work; by M10 add
explicit manual cleanup with a size/reference preview. Historical lineage references
are not automatic retention pins forever. An explicit eviction may remove unpinned
generated payloads from completed runs while retaining manifests and an evicted marker;
those results cease to be cache hits. Protect current selected results, originals,
active attempts, explicit pins, exports and retained checkpoints. Do not delete source
snapshots still needed by a run. Resolve targets under the owned root and reject
junction/symlink escapes. Advanced automatic retention/compaction remains M13d.

If `state.sqlite` is lost, manifests may recover validated artifact inventory, not
complete attempt history. Say so explicitly; do not infer successful runs from folder
names. Missing logs reduce diagnostic evidence and must be reported. Disk-full and
sharing errors must preserve the last committed project and incomplete work for review.
