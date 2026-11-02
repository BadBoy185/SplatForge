# Saved video usage / Trim integration

The backend and Materials / Trim editor are implemented; user acceptance remains
open. Processing semantics belong to
[PIPELINE](PIPELINE.md#used-video-intervals); persistence/versioning belongs to
[PROJECT_FORMAT](PROJECT_FORMAT.md#video-usage-intent).

Preparation admits exact sampled PTS before scratch image encoding. Restricted
videos currently use a bounded metadata-only pass followed by an image pass over
the same original sampling grid; both can decode the full clip. Plan/run bounds
use saved intervals, candidate density and the supported encoding allowance. See
the [processing/storage contract](PIPELINE.md#used-video-intervals).

## QML boundary

`desktop.videoUsage` is a constant QObject (`VideoUsageViewModel`). Its notified
`state: QVariantMap` uses the **current preview video UUID**, never batch selection:

| Key | Meaning |
| --- | --- |
| `sourceId` | Registered current source UUID, empty when unavailable |
| `available`, `canEdit` | Video context and ordinary project mutation permission |
| `restricted` | Entry exists, including an explicitly empty interval list |
| `intervals` | Canonical list of `{start: string, end: string}` in source seconds |
| `timelineStart` | Exact selected-stream start string, or null |
| `playbackStart` | Exact container/player origin string, or null |
| `duration` | Exact selected-stream duration string, or null |
| `dirty` | Video usage differs from committed document (whole usage envelope) |
| `error` | Empty map, or `{code: string, message: string}` |
| `contextKey` | Opaque project-generation string; combine with sourceId for transient UI lifetime |
| `timeline` | Read-only display/seek projection described below; never a second persisted intent |

One `changed()` signal notifies the map after edits, errors, source/project changes,
Save/readback, Discard and mutation availability. The later Materials / Trim visual
components use this API; interval business logic stays in core. Time strings are integer/decimal/fraction values;
canonical output is an integer or reduced `numerator/denominator`. Strings avoid
JavaScript's 53-bit integer precision limit. Do not convert persisted endpoints via
binary float, player FPS or `Number` and then serialize them back.

| Slot | Return and behavior |
| --- | --- |
| `addInterval(start: string, end: string)` | bool; unrestricted becomes this restriction; unions with existing used sections |
| `updateInterval(index: int, start: string, end: string)` | bool; replaces current canonical item, then sorts/merges |
| `removeInterval(index: int)` | bool; removing last item leaves explicit empty |
| `excludeInterval(start: string, end: string)` | bool; subtracts a section, splitting used intervals as necessary |
| `clearIntervals()` | bool; explicit empty used set |
| `resetIntervals()` | bool; removes restriction, also explicitly clears a stale identity binding |
| `sourceTime(playerMilliseconds: string)` | exact source-seconds string, or empty string on error |
| `playerPosition(sourceSeconds: string)` | integer millisecond string for seek, or empty on error |
| `intervalIndex(sourceSeconds: string)` | int; exact canonical used row containing this point, or -1; no mutation/notification |
| `clearError()` | void; dismiss local edit/conversion errors; notify only if one existed; identity/version errors still require correction |
| `requestThumbnails(start: double, end: double, count: int)` | void; optional bounded real frames for the visible player-ms window |

Indexes address the current canonical projection only: re-read after every successful
edit because a union/replacement can merge/reorder entries. Successful edit/conversion
clears the local error. Validation failure returns false/empty, emits changed and
does not mutate the draft. Current source/project changes, Discard and successful
Save clear old local errors.

Core/application errors: `not_video`, `invalid_interval`, `out_of_bounds`,
`invalid_interval_index`, `source_identity_changed`, `unsupported_video_usage_version`,
`timeline_origin_unknown`, `duration_unknown`, `invalid_position`.
VM mutation refusal: `editing_unavailable`. Controller Plan/Prepare refusal before
unsaved interval changes: TaskError category `UnsavedVideoUsage` via existing error
signal. Other Save/revision/storage failures use the existing controller errors.

## Editing and Trim integration

All interval algebra/validation is in core; `application.video_usage.video_usage_draft`
builds a ProjectDocument from the trusted registered VideoSource context. The GUI
adapter obtains that context from the inventory-backed current row, not editable
QML identity fields. Use existing `desktop.save()` and existing unsaved
Save/Discard/Cancel navigation. There is no implicit Save per handle drag and no
second settings store. Successful saved readback drives the same projection.

The Materials / Trim implementation follows the saved
[reference](design/references/04-video-trim.png). The current video and batch selection
remain independent. All mutations still use the slots above and ordinary Save.
There is no QML interval normalization or independent persisted range list.

### Read-only timeline projection

`state.timeline.available` is true only when the selected stream's origin/duration
and container/player origin are known, convertible, and representable as safe
integer milliseconds. Otherwise `reason` explains the missing evidence or precision
limit, and the finite exact input fields remain usable where core validation permits.
Never replace missing bounds/origins with zero or the player's reported duration.

When available, `start`/`end` retain the **exact source-second strings** of the full
extent; `startPosition`/`endPosition` are rounded player milliseconds.
`ranges` and `gaps` contain `{start: int, end: int}` in player milliseconds for
drawing and approximate playback. `ranges` follows canonical interval indexes,
including submillisecond ranges whose display bounds can collapse. Unrestricted
intent projects one full range; explicit empty intent projects no ranges.
The ruler labels elapsed clip time from `startPosition`; transport uses Qt player
elapsed time. The precise inputs always show original source PTS seconds.

Use `sourceTime` for interior gesture coordinates and the exact projected `start`/
`end` strings at the full clip boundaries. Unchanged endpoints keep their original
canonical strings. `intervalIndex` reselects the normalized result after a typed
edit, including when no player origin is known. Do not compare source fractions
with JavaScript floats or use FPS to derive saved boundaries. Projection updates
do not call notifying conversion slots from a property binding.

### Editor and transport behavior

Review/Trim share one original-file player. Photos show why Trim is unavailable.
The strip represents the full original extent, with real optional thumbnails,
hatched excluded gaps, saved used bands, a separate playhead and transient selection.
Drag the strip to select; drag selection handles to adjust. Existing-range handle
edits commit to draft on release. A new selection changes no intent until Include
or Exclude. Click/drag the ruler or playhead to seek on release. Exact fields accept
seconds/decimals/fractions; Enter or Apply bounds confirms an existing-range edit.
Set start/Set end and I/O put the current position into the selection; Apply/Include/
Exclude determines its use. Escape cancels unfinished field/handle/scrub edits.
Removing the final used row leaves the explicit empty state; Use entire clip resets
the restriction. Source Exclude remains independent.

Fit timeline, +/- (up to 64x), Ctrl+wheel and the horizontal scrollbar/wheel change
only the viewport. Space controls playback when the focused control does not consume
it; Left/Right seek by a second in Trim and navigate materials in Review. Normal Qt
key bubbling gives text fields, sliders, checkboxes and modal dialogs first use.
Playhead movement, viewport changes and used-only playback never dirty the project.

Play used ranges only defaults off and never concatenates or renumbers source time.
When on, one pending seek skips gaps, stops after the last interval and restarts on
explicit Play. Pause, workspace exit and source/project generation changes revoke
resume intent and unfinished scrubs. A seek must move off its old position and into
the destination used range before resuming; one 2.5-second deadline fails paused,
without automatic retries. Empty and millisecond-collapsed unions cannot play in
this mode. This is approximate Qt playback, not a frame-accurate boundary guarantee;
exact saved intent and frame preparation retain their rational contract.

### Optional filmstrip

`desktop.videoUsage.thumbnails` is a constant QObject with notified `state` and
`changed()`. `state.frames` contains `{position: int, url: string}` for the requested
player-ms samples; pending/failed samples have empty URLs. `state.message` explains
an unavailable filmstrip. `stop()` cancels the current context and clears requests.
The trusted current row supplies path/stream, never editable QML locator/identity.

The application `VideoPreview` port is injected by bootstrap; its FFmpeg adapter
input-seeks one frame, uses an owned contained process, an 8-second timeout and
256 KiB output cap. It does not prepare/scrape an entire clip or publish artifacts.
The GUI keeps one worker, at most 12 latest visible requests, 32 rasters of at most
160×90, cancellation and project/source/namespace delivery guards. Missing FFmpeg or
codec failure stops further probes for that context; the ruler and editor remain
functional. No tools are installed automatically. These preview milliseconds/images
have no effect on recipe identity, exact intervals or processing.

For historical probes without a known origin, do not infer zero: show unavailable
time mapping. Re-ingesting with current probing creates a new, unrestricted occurrence;
in-place historical probe refresh is not part of this slice. Duration can also be
unknown; finite explicit source-time intervals are supported, while subtracting
from an unknown full extent is refused. Editing such intervals does not remove
the existing preparation requirement for a bounded source duration: full-stream
decoding still refuses unknown duration, even with a finite used union.
No masks, tracking or 360 behavior is added.

Acceptance and exact local evidence are recorded in the
[ACTIVE handoff](plans/active/2026-10-28-materials-workspace.md).
