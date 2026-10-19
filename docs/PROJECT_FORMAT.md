# Project format and execution state

Status: target contract for M1 and later milestones. No project persistence currently
exists. Version numbers for project, pipeline settings, state database, manifests and
individual methods are separate; the prototype `PipelineConfig.schema_version = 1`
is not a project format declaration.

## Storage layout and ownership

Use a local writable project directory, separate from the source repository:

```text
project/
  project.json                         # Authoritative saved intent, format and revision
  sources/
    <inventory-id>.jsonl                # Immutable inventory revisions; no originals
  state.sqlite                         # Run/attempt/artifact index and execution state
  artifacts/
    <stage>/<artifact-id>/
      manifest.json                    # Contract, provenance, digests, relative files
      ...                              # Native payloads, images, reports or models
  work/
    <run-id>/<attempt-id>/              # Unpublished adapter-owned scratch data
  runs/
    <run-id>/run.json                   # Frozen resolved plan and environment snapshot
    <run-id>/events.jsonl               # Structured operational events
    <run-id>/logs/<attempt-id>/...      # Raw backend stdout/stderr and invocation metadata
  checkpoints/
    <run-id>/<attempt-id>/...           # Explicitly retained trainer checkpoints
  exports/
    <export-id>/...                     # User-facing deliveries; never generic cache
  backups/
    <migration-id>/...                  # Consistent pre-migration copies
```

Create the empty ownership directories at M1a; create inventory/run/artifact files
only when needed. Payload details are adapter-owned. Reconstruction and training
results use the same manifest convention rather than separate mutable "latest"
directories. Stable IDs provide deterministic naming, not identical run IDs on rerun.

The application owns `project.json`, inventory revisions, `state.sqlite`, manifests
and publication. An adapter owns only its assigned workspace and native payload
format. Published artifacts are immutable. Originals are external read-only references;
future managed copies require an explicit import mode and separate provenance.

## Authoritative records

| Record | Required meaning |
| --- | --- |
| Project document | Format version, project ID, revision, label, creation/update times, current inventory reference, saved stage settings and preset provenance |
| Source inventory | Source ID and digest/size, original locator/name, media type/probe result, source group, camera group and calibration policy; add view lineage as artifacts |
| Pipeline settings | Separate stage selections with method/settings schema versions and resolved values; no runtime statuses |
| Run snapshot | Project revision, resolved settings, dependency plan, source verification, environment/capabilities, seeds and resource policy |
| Stage attempt | Run/stage/attempt IDs, recipe fingerprint, consumed artifact IDs, status, timestamps, workspace, process/log references, failure and retry relation |
| Artifact manifest | Manifest/contract versions, artifact ID/type, producer attempt, recipe key, semantic content digest, input lineage, relative payload paths with sizes/digests and validation result |
| Checkpoint manifest | Trainer/version, dataset and settings identity, completed work, resume requirements, retained files and integrity checks |

`project.json` is authoritative for editable intent; `state.sqlite` is authoritative
for attempt history and indexed publications. Run snapshots preserve what actually
executed. Editing intent creates a new revision and future run; it does not rewrite
an active run. No requirement for a distributed transaction between JSON and SQLite:
read a complete project revision under the writer lock, freeze it into a new run,
then persist that run's state. On restart reconcile only complete frozen snapshots.

Ingest is an application operation that can run recorded probe/hash attempts. Its
inventory is a versioned project input, published by the inventory/project-save
protocol below, rather than by the derived-artifact publication protocol.

The SQLite schema can start with metadata at M1a and add runs, attempts, artifact
indexes and their relationships at M1b. Do not put descriptor arrays, media or raw
log streams into application state. JSONL events support diagnosis, not event-sourced
reconstruction of the whole database.

## Paths and source identity

Store project-owned paths as project-relative paths with a canonical separator;
resolve them with `Path` at the storage boundary. Reject absolute/drive-qualified
paths, `..` traversal and symlink/junction escapes in owned manifests. Preserve
external Windows/UNC source locators separately; they may legitimately be absolute.
Do not lowercase arbitrary paths to derive identity or assume case distinguishes files.

Assign source IDs independently of names and locations. Stream a full content digest
at ingest with progress/cancellation. Equal content may be deduplicated for processing
while preserving distinct source occurrences and provenance. Size/mtime are useful
change hints, not sufficient evidence for cache correctness.

Default processing preflight revalidates referenced source content for a new run;
hash once per source per run and reuse that verification during the run. A later fast
trust policy must be explicit, recorded and labeled weaker. Detect changing sources
while reading and fail rather than certify an unstable input. A relink preserves
identity only after a digest match; different bytes are a new source revision.

Missing or changed originals do not prevent project inspection. Block operations
that need those originals with diagnostics. Already materialized, validated artifacts
can support downstream work offline when their contracts do not require source access;
record that originals were unavailable, not freshly verified. Moving the project must
not invalidate artifact fingerprints. Relocating originals is a separate relink action.

## Safe writes and migrations

- Create only at an absent or empty destination. Refuse a non-empty destination;
  there is no overwrite flag in the initial API. Do not remove a failed create target
  unless every removed file is proven to belong to that failed operation.
- Use one local writer lock shared by CLI and GUI. Readers may inspect committed
  state. Lock acquisition must distinguish a live owner from an abandoned process;
  a PID alone is insufficient because it may be reused.
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
- Journal a migration with old/target versions and phase. On interruption, finish a
  verified step or restore the consistent backup before permitting writes. Test
  failures between file replacement and database commit; do not leave mixed versions.
- A newer unsupported project/state format is refused without writes. Unknown method
  IDs/settings in a supported format must round-trip unchanged in an opaque versioned
  settings envelope; opening is allowed, execution is blocked. Known settings are
  validated strictly. Never silently discard fields through permissive model loading.

Initial active project storage is a local filesystem with tested locking/rename
behavior (Windows baseline: NTFS). Network shares and cloud-synced project roots are
unsupported for active writes until tested. External sources may be on removable or
network storage; failures there must remain recoverable.

## Attempts, publication and recovery

Persist attempt states with explicit transitions:

```text
pending -> running -> succeeded
                   -> failed
                   -> cancelled
                   -> interrupted
pending -> cancelled
```

A retry is a new pending attempt linked to the previous one. A preflight failure is a
plan diagnostic before execution. Cache reuse is a run-to-artifact reference, not a
fake successful attempt. Disabled optional stages are represented in the plan, not
as successful processing. "Stale" is a cache eligibility result, not an attempt state.

Publication protocol:

1. Persist the running attempt and create an owned workspace. Stream logs/events.
2. Complete processing, close backend handles/databases, validate required payloads
   and write the completed manifest with content checksums inside the workspace.
3. Move the completed payload directory on the same volume to a new artifact ID.
   Never overwrite an existing artifact; keep scratch and publication storage together.
4. In a SQLite transaction, index the manifest and mark the attempt succeeded.
   Only indexed, validated publications are eligible for automatic reuse.

On open, acquire the writer lock before recovery. Do not mark a live process's attempt
interrupted. After confirming the owner/process tree is gone, interrupted attempts
remain incomplete even if some files exist. A complete unindexed publication can be
validated and adopted only when its producer, manifest and run agree and the attempt
has no failed/cancelled terminal decision. Never promote cancelled or rejected outputs
during recovery; quarantine/report them. A success record with missing/corrupt output loses cache
eligibility and receives a diagnostic; preserve history instead of inventing success.

If cancellation arrives before publication commits, cancel the attempt and leave
outputs unpublished (or report a recoverable orphan after a rename). If publication
already committed, keep success and report cancellation came too late. Stop only
processes belonging to the attempt; never kill all processes named `colmap.exe`.

Retry transient I/O/process failures with bounded policy. Invalid settings, unsupported
capabilities and resource exhaustion require an actionable decision rather than an
infinite loop. A changed method/resource setting creates a new resolved run plan.
Stage-boundary resume reuses eligible artifacts and restarts incomplete stages;
checkpoint resume requires matching dataset, trainer and declared settings plus a
validated checkpoint. An external/manual training handoff is not resumable execution.

## Retention and diagnosis

Invalidation never deletes files. Initially retain all artifacts; later cleanup previews
eligible generated files, their sizes and references, and requires explicit action.
Protect originals, active attempts, pinned artifacts, exports and retained checkpoints.
Resolve every deletion target under the owned root and reject junction/symlink escapes.

If `state.sqlite` is lost, manifests may recover validated artifact inventory, not
complete attempt history. Say so explicitly; do not infer successful runs from folder
names. Missing logs reduce diagnostic evidence and must be reported. Disk-full and
sharing errors must preserve the last committed project and incomplete work for review.
