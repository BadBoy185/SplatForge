# SplatForge desktop design

The M12 desktop uses PySide6 6.12.0 / Qt Quick 6.12. The client area belongs to
SplatForge; the operating system owns the native title bar, resizing and window
management. This migration does not start M13 or introduce Gaussian rasterization.
The [primary UX/UI specification](UX_UI_SPEC.md), sections 34–35 and 59–60, requires
Reconstruction Review + Sparse 3D Viewer in M12f. Built-in Gaussian visualization is
reserved for a separate future milestone after M12 and is not a v1 completion gate.

## Presentation architecture

Materials Review/Trim share the original-file viewer. The saved interval editor,
full-extent timeline and optional used-only playback use the
[Trim integration API](VIDEO_USAGE.md). The user accepted the latest Materials/Trim
visual refinement on 2026-10-29; functional manual scenarios remain unconfirmed.

```text
app.py -> QGuiApplication + QQmlApplicationEngine -> qml/Main.qml
    QML pages and app-owned Basic controls
        -> DesktopViewModel / WorkflowViewModel / MediaViewModel / InspectionViewModel
        -> ProjectController -> GuiFacade -> existing Application services
```

QML receives notified properties, strings, numbers, booleans, QVariant maps/lists and
Qt models. Typed requests, Pydantic classes, artifact data and validation decisions
remain in Python. QML never reads project JSON, SQLite or manifests and never starts
processes. Only the existing adapters run processing. The base CLI has no GUI import.

`ProjectController` retains fresh worker facades, queued results, project generations,
reserved cancellation/progress workers and asynchronous polling. View models discard
obsolete gallery, plan, capability, selection and resume responses. Recovery owns an
exclusive mutation slot but remains reachable during unresolved lifecycle state.
An interrupted historical run with confirmed teardown does not itself block new work.
Unresolved teardown still blocks it. Backend writer leases remain authoritative.
Atomic project Save and source ingest reserve the controller mutation slot, drain owned reads
and pause metadata polling until replacement finishes. This avoids Windows sharing
violations caused by the UI's own readers. Processing progress/cancellation keeps its
reserved pool; no persistence retry or backend contract is introduced.
Save-to-project-switch callbacks wait for the mutation slot's confirmed release;
result delivery alone is not worker completion.

`PresentationModel` extends the stable-UUID table model with `recordId`, `record`
and `cellText` roles. ListView, GridView and TableView instantiate bounded visible
delegates. Run/artifact history retains the existing 2000-row index bound. Pages load
on first visit and retain their contexts, avoiding destruction of incubating delegates
during navigation. Hidden pages do not render. The inspection projection is cached
until its notification signal, so bindings do not repeatedly serialize metadata.

Images use the existing bounded thumbnail workers and a QQuickImageProvider. Ordinary
source video review uses installed Qt Multimedia in the presentation layer. Gallery
delegates distinguish loading, ready and unavailable
previews. Source verification explains metadata reuse without calling it a fresh hash.
The first preview path is a QQuickPaintedItem using the
existing bounds: 20,000 point centers and 2,000 camera centers. Orbit, zoom and reset
change only presentation. The label always says **Point-center preview — not final
Gaussian rasterization**. Sparse preview retains the first-component-only label.
These are current prototype limits, not M12f acceptance. PointPreview may be reused,
but the required viewer must support stable IDs, independent layers, camera frustums
and picking, source presentation filtering and explicit per-component viewing.
Downstream selection stays in the existing ReconstructionSelection / validation flow.

The v1 navigation target in UX/UI specification section 3 has no required primary
Viewer destination. Open Reconstruction Viewer from Reconstruction Result / Review;
fullscreen preserves that reconstruction/component context. Gaussian training/results
use metrics, history, export and external browser/local viewer handoff. Spatial live
training and checkpoint previews are deferred with the future Gaussian viewer;
no renderer technology or Qt-process CUDA ownership is introduced for that scope.

## Theme and typography

`qml/theme/Theme.qml` is the central singleton for both designed palettes. System
resolves through Qt's system color scheme. Dark is the flagship; Light uses pale blue
gray surroundings, white cards, dark text and a restrained blue selection surface.
Do not invert individual pages or introduce page-specific color literals.

| Token | Dark | Light |
| --- | --- | --- |
| Background | `#1B1D20` | Pale blue gray |
| Sidebar | `#202226` | Slightly deeper blue gray |
| Surface | `#222529` | White |
| Raised / hover | `#282C31` / `#30353B` | Subtle pale surfaces |
| Primary text | `#F2F5F8` | Deep graphite |
| Secondary / tertiary | `#A7B1BC` / `#707C89` | Slate blue grays |
| Accent | `#429BFF` | Stronger blue for white surfaces |
| Success / warning / danger | Green / amber / muted red | Darker readable counterparts |

The singleton contains implemented values; the table describes design intent. The
reference-led target below labels its proposed values separately. Python-painted
viewport colors live together in `point_preview.py`, with corresponding dark/light
values. No processing value depends on these tokens.

Use Segoe UI Variable when installed, otherwise Segoe UI. Project/page titles are
22 px, sections 18 px, body 14 px, secondary 12 px and captions 11 px.
Use Consolas only for paths, IDs and exact
evidence. The spacing rhythm is 4/8/12/16/20/24/32/40; shared controls are 32 px high,
shell bar 50 px, panel headings 40 px and inspector insets 12 px. Control corners
are 2 px, menus/dialogs 4 px, and workspace panel boundaries remain square.

### Visual density calibration — 2026-10-29

Fresh native Projects/Materials/Trim captures and catalog images
[Materials Review](design/references/03-materials-review.png) and
[Trim](design/references/04-video-trim.png) ground this refinement. The DaVinci
direction is a professional-workspace style preference; no separate DaVinci image
was supplied or used to claim an exact match. The catalog references are dark;
Light is an adaptation of the same hierarchy using its existing palette.

The observed interface was already flat with square panels, modest corners and no
decorative shadows/gradients/nested cards. Its repeated tall semibold controls,
48 px panel headings, 88 px catalog rows and wide inspector gaps made the chrome
visually heavy. No UI text/icon blur was reproduced. Enlarged low-resolution
synthetic video is media evidence, not a font-rendering defect; font rendering,
palettes, media Fit behavior and SVG assets remain unchanged.

`Theme.qml` now owns 32 px controls with 10 px horizontal text inset, 20 px icons,
40 px panel headings, 12 px inspector inset, 8 px metadata gaps, 80 px source rows
with the existing 80×60 thumbnails, and 48 px used-range rows. Primary buttons keep
semibold labels; ordinary secondary/quiet actions use normal weight. Body/secondary
text stays 14/12 px. Used ranges have an unframed selection surface and accent edge;
keyboard focus keeps its distinct 2 px outline. Checkboxes, fields and button roles
retain their existing interaction/state semantics. Shared controls inherit the same
appearance on Projects/Create without rearranging those accepted screens.

Comparable native captures, interaction checks, exact conditions and remaining
acceptance limits are recorded in the
[active Materials plan](plans/active/2026-10-28-materials-workspace.md#visual-density-and-control-refinement--2026-10-29).
Agent visual review and automatic checks do not constitute user acceptance.

## Components and interaction

Build from app-owned `SplatButton`, `SplatComboBox`, `SplatTextField`, `SplatCheckBox`,
`SplatCard`, `SplatBadge`, `SplatBanner`, `SplatDialog`, navigation and evidence panels.
Use QtQuick.Controls.Basic. Standard controls retain Qt accessibility and keyboard
behavior; backgrounds, text and indicators use app tokens. Do not mix in platform
Widgets controls, emoji or third-party themes. Native file/folder pickers use
QtQuick.Dialogs.

One primary action per page; Plan is secondary, inspect/refresh/copy are quiet, cancel
and destructive confirmations use the danger role. Every control has disabled,
hover/pressed and visible focus treatment; selection has persistent shape/text as
well as color. ComboBox synchronizes stable values after model replacement, preserves
unsupported current choices and disables unsupported menu entries after a probe.

Microsoft Fluent System Icons are vendored locally as the small used SVG subset.
Their [MIT license](../src/splatforge_gui/qml/icons/LICENSE) accompanies the assets.
Source: [Microsoft Fluent UI System Icons](https://github.com/microsoft/fluentui-system-icons),
regular 20 px assets, retrieved 2026-10-24. The geometric SplatForge brand mark and
compact information/exclusion geometry are app-owned. Control icons use Qt's
theme-aware tint, without an icon runtime dependency.

Motion is brief (160 ms) and limited to control state/progress. No blur, animated
gradient or decorative continuous animation is used. Indeterminate progress animates
only while active. Automatic Windows reduced-motion preference mapping is not claimed.
Button/navigation backgrounds apply theme and selection directly, so their contrast
and selected state do not depend on animation scheduling.

## Guided and Advanced

Guided prioritizes task meaning: project entry, media, explicit reconstruction
method cards, component comparison, dataset evidence, trainer readiness and outputs.
Advanced exposes exact settings, project intent, IDs, history, lineage, storage and
diagnostic evidence. Both use the same controller and publications.

Workspace Overview derives its recommendation from indexed workflow evidence and
shows the latest published output. Historical completion is not a promise of compatibility with newly
edited settings; Plan determines that. Unknown capabilities remain Not checked.
No hardware name, installed package or selected method is promoted to runnable.

M9 starts with no component selected. Advanced permits multiple components in separate
coordinate systems. Exact applicable failure IDs, a reason and confirmation are all
required for a FAIL override. Pydantic JSON validation runs in Python and returns field
paths. Editing revokes validation. There is no generic ignore-validation action.

The global operation surface disappears when idle. Active work shows actual phase,
fraction when known, elapsed time, backend ETA when available and bounded live metrics.
Cancel remains pending until application confirmation. Closing waits for ownership and
teardown. Cleanup follows preview, exact candidates/bytes, confirmation, then apply.

The following M12a–M12b3 sections record the earlier delivered slices. The current
workspace contract below supersedes their layout, popup-only photo review and
no-video restrictions; persistence and processing invariants remain in force.

### M12a project shell

The [UX/UI specification](UX_UI_SPEC.md), sections 3–7, owns the intended Home and
Create/Sources flow. Without an open project, Home shows New Project, Open Existing
Project and recent paths with persisted labels and availability; project navigation
and Guided/Advanced controls appear only in a workspace. The existing dashboard
remains the workspace Overview; subsequent pages retain their current layout.

Create takes one Windows-safe directory name and an absolute parent Location.
The Python presentation helper computes the live destination preview without I/O.
The view model passes the final `Path` to the existing controller/facade/service.
Only successful backend creation plus persisted overview readback opens the Sources
empty state. Create/Open errors retain the current workspace; recents are updated
only after validated success. Existing backend acceptance of an empty destination
and refusal of a nonempty one remain authoritative.

The empty state reuses current photo/video file actions and top-level folder review.
It advertises file drops; directory drops retain their existing project-open meaning.
There is no recursive mixed-folder scanner or additional source type in this slice.
Recent entries use backend identity/name/path and Available/Unavailable, without
inferring processing status. Last-opened timestamps are deferred; QSettings is unchanged.

### M12b1 Sources presentation

Sources keeps explicit Add Photos/Add Video actions, inventory summary, explained
Check Source Files action, a virtualized scrollable list and Continue above the
fold at the supported minimum window size. Standard rows show stored media metadata
and recorded availability; Technical Details retains identity/hash/check evidence.
Labels say "at last check" rather than implying a current filesystem check.

The photo popup shows filename/index, X/Esc, Previous/Next and arrow-key navigation
in the current source-list order, skipping videos without wrap-around. Each bounded
decode request has its own token; navigation/close/project switch invalidates stale
responses. Errors remain inspectable inside the popup. Published-view browsing is
secondary in Source Details, with no empty result picker or irrelevant pagination.
Continue is visibly disabled with an explanation until the Prepare Data screen exists;
it never starts processing. See the [bounded plan](plans/completed/2026-10-27-m12b1-sources-preview.md).

### M12b2 mixed-folder preview and browser

Sources routes mixed drops through a read-only application scanner and filesystem
adapter before explicit confirmation. QML receives scan progress/counts and a
virtualized detail model; it never traverses the filesystem. Scanner limits and
partial/unreadable results are visible. See [M12 behavior and bounds](M12.md#navigation-and-settings).

Empty Sources centers equal primary photo/video actions and secondary Add Folder.
After import, a compact toolbar and List/Grid switch leave the browser central.
Both views share source UUIDs, selection and ordering. Grid-only image roles request
lazy bounded photo thumbnails through MediaProvider; hidden/list views do not preload
them. Video tiles remain source assets with stored metadata and a play marker.
Existing SourcePreviewDialog owns photo preview/navigation. QSettings stores the view
choice and last successful Create parent; neither belongs to portable project intent.

Each thumbnail-model replacement rotates its URL namespace, clears cached/queued
work and rejects late replies from an older generation. Providers serve only current
references. Project Open/Create also revokes large previews and source selection,
on a validated project replacement. The Projects entry slice below adds same-session
resume without this reset. Video tiles have no photo Image component.
Selection has a persistent accent outline; per-card/video-row Details selects and
opens the same source inspector. Human type, dimensions, duration, location and status
come first; identity/hash/codec/evidence stay under collapsed Technical Details.

Availability is session evidence, never monitoring: successful ingest and explicit
checks show Available, reopening shows Not checked this session, missing originals
show Missing, and changed/unreadable/incomplete checks show Needs attention. Text
and semantic indicators accompany color. Historical evidence remains in Details.
Check Source Files explains that it checks originals at their saved locations.

Home shows Recent Projects with or without an open workspace. Existing QSettings
stores label, project identity, path and successful last-opened time. Missing paths
offer Locate and Remove from list; Locate validates through ProjectService and refuses
a different saved identity. Legacy entries without identity require confirmation.
Remove touches only the preference. Import counts completed hash/probe checks and
reports the real current file/phase; M6.5 live throughput supplies ETA only after
stable evidence, with no synthetic progress or persistent performance samples.
M12b2 user UX acceptance passed on 2026-10-27; its
[completed plan](plans/completed/2026-10-27-m12b2-folder-browser.md) retains the evidence.

### M12b2a source participation

Sources defaults to Included, with compact Included/Excluded/All filters and separate
registered/included/excluded counts. Both List and Grid show Excluded text independently
of session availability. Selection offers Exclude/Restore; Details spells out Exclude
from processing. Excluded photos retain Preview, thumbnails and provenance; videos
retain Details. All-excluded Included view offers View Excluded; empty Excluded view
says No excluded sources and contains no import prompt.

The application resolver owns processing membership. Qt filters already-loaded rows
without filesystem reads, verification or thumbnail namespace resets. Existing visible
delegate/queue/cache limits remain. QSettings contains no participation data.

Actions use the existing project draft + Save path and reader-draining mutation slot.
Existing unsaved edits first receive Save/Discard/Cancel. Action rows/counts change
after Save and committed overview readback; failure retains committed rows, clears the
action's transient draft, and shows the existing human-readable error. No destructive
confirmation is needed. Project switch clears selection and resets the filter to Included.
Single selection remains shared by List/Grid/preview; Ctrl/Shift batch selection is
deferred. The application intent edit supports one atomic batch Save.
See [persistence](PROJECT_FORMAT.md#source-participation-intent-m12b2a) and the
[completed plan](plans/completed/2026-10-27-m12b2a-source-participation.md).

### M12b3 capture metadata and groups

Sources organizes saved rows by explicit user group, then reliable captured Make+Model,
then Unknown device (photos) or Videos. These device sections are derived presentation,
not persisted groups or inferred sessions/physical-camera identities. A compact group
navigator scopes either virtualized List or Grid; All groups orders rows by section,
with List section headers and Grid group/device captions. Counts/summaries reflect the
current Included/Excluded/All filter. Empty user groups remain selectable and explained.

Groups opens a small dialog for Create, Rename, Delete and Move to Group/Ungroup of
selected sources. Create from selection creates and assigns in one Save; Move uses
one batch draft. Rename/Delete remain secondary group management. Deleting a group
leaves sources ungrouped. Ungrouped sources
resume derived device presentation. Stable UUID assignment survives Exclude/Restore,
reopen, relocation and relink. Actions use existing draft/Save/reader-drain/readback;
failures never display uncommitted group membership. Existing dirty edits first use
Save/Discard/Cancel. List and Grid share a UUID selection set and anchor. Plain click
replaces it, Ctrl toggles, Shift selects the inclusive visible ordered range (Ctrl+Shift
adds that range), and Ctrl+A selects only visible sources. View switching preserves it;
changing participation/group scope clears it. Refresh intersects it with visible IDs;
project changes clear it. Availability, participation, groups and selection remain
independent. Per-source Exclude/Restore affects the selected set if its source is
selected, otherwise that source alone. Contextual batch controls appear for multiple
selected sources. All mutations use committed readback; there is no optimistic QML state.

List and Grid remain attached to the same source model. Same-ID evidence changes emit
record-role notifications; membership/order changes reset the projection. Hidden Grid
thumbnail requests are disabled independently of model attachment. List puts availability
beside the right-edge compact Preview/Details/Exclude-or-Restore icons; Grid uses the
same icon component. Every icon has a tooltip, accessible name and keyboard focus.
At minimum window height, the check explanation card yields to multi-selection
controls so Grid retains usable thumbnails and fully visible actions. Clearing the
selection restores Check Source Files; active progress remains in the shell panel.

Add Folder previews relative parent folders as import-time logical groups. Root files
stay ungrouped; nested labels use `Drone / Flight 1`. Equal display names never merge
memberships: new UUIDs and `(2)` suffixes distinguish collisions. Inventory reference
and all new groups/assignments publish together in one metadata CAS. Reopen/relink
never recomputes groups from locators, and folder names never become captured devices.

Check Source Files publishes known total, completed persisted checks, current filename,
phase and elapsed time from MediaService through the existing source-operation reporter.
Its M6.5 live estimator starts at Estimating, requires stable completed-work evidence,
suppresses variable/stalled estimates and expires displayed evidence after five seconds.
The existing controller poll only ages observations. Generation/job tokens reject stale
events; failure/cancellation never publish success. No timer advances work.

Photo Preview's compact Exclude/Restore always edits the current photo alone, preserving
the browser selection for visible members. It snapshots ordered photo UUID neighbors
within the current participation/group scope before mutation. After committed readback
it opens the next surviving neighbor, falls back through previous neighbors, or closes
when none remain. This also advances in All scope. Failure leaves the current preview;
an explicit scope/project switch closes it. New image requests clear the old image and
use fresh tokens; late replies cannot replace the new photo. Navigation never decodes
the entire review sequence. Left/Right/Esc retain their existing behavior.

Details leads with type, resolution/duration, user group, captured device, recorded
time and available photographic fields, location and independent availability/
participation. Unknown/partial evidence is honest; container creation is labeled as
creation, and EXIF without an offset does not invent a timezone. Identity/hash,
processing source/camera UUIDs, inventory revision and capture provenance stay under
collapsed Technical Details. Selected-only metadata is read asynchronously from saved
inventory; overview contains compact device/group roles, no EXIF maps. No originals
are opened for metadata on Open/render/Details. Ingest captures bounded metadata before
reporting its checked/succeeded phase through existing progress. No QSettings data,
video player/poster/extraction or Prepare UI is introduced. Lazy thumbnail and project
generation boundaries are unchanged. Group labels/assignments affect no numerical
recipe, calibration ID, published artifact or reconstruction semantics.
See [persistence](PROJECT_FORMAT.md#capture-evidence-and-logical-source-groups-m12b3)
and the [implementation plan](plans/active/2026-10-27-m12b3-capture-metadata-groups.md).

## Selected Materials workspace — 2026-10-28

Historical first implementation, not user-accepted visual direction or full-suite
success. The later reference-led delivery below supersedes its navigation and geometry
where different; media/state/processing safeguards remain required.

The user-selected reference is a professional media editor: source catalog on the
left, the current image/video as the main surface, properties/tools on the right,
and image navigation or video transport below. Future masks/trim controls in the
reference are not implemented controls in this slice. The actual content is always
user media or explicitly labeled review fixtures; no invented masks, tracks or metrics.

Primary tabs are Materials / Reconstruction / Splat / Results. Native Windows title
bar, resize, maximize, snap and DPI are retained. Stable internal IDs remain 0 Home,
1 Materials (formerly Sources), 2 Reconstruction, 3 Dataset, 4 Splat (formerly Train),
5 Results, 6 Diagnostics. In that first implementation, old `page` preferences
restored the same semantic screen; the Projects entry slice below supersedes startup
restoration without renumbering these IDs. In that first implementation,
More exposes Home/recents, Dataset
preparation/export, diagnostics/history, Guided/Advanced and Settings. Existing
processing forms remain functional and scroll within their own workspace panel.

At 1440×900, a 50px shell bar and compact action bar leave almost all remaining
height to media. The catalog defaults to 280px (minimum 248), properties to 278px
(minimum 230); SplitView handles resize them. Buttons collapse either panel. Below
1180px properties start collapsed, keeping the 1024×640 minimum useful for viewing.
Grid can expand for bulk review and returns via Back to viewer. It shares UUIDs,
anchor, ordering, filters and selection with List. Both use the same bounded photo
thumbnail service (192px, 8 active, 100 queued, 128 cached); only visible delegates
request photos. Inactive List/Grid presentations release delegates but retain the same
Python model, selection and cache; inactive pages stop requesting. Video rows do not decode thumbnails.

Current media and batch membership are independent. Clicking a material opens it;
Ctrl/Shift/Ctrl+A preserve catalog semantics. Previous/Next traverse the visible
ordered material scope. The viewer's Exclude/Restore edits only the displayed UUID.
The batch bar spells out its selected count and applies existing atomic Save/readback
actions. After exclusion, choose the next surviving UUID, then a previous one, or
clear the viewer. All scope also advances. Group/device information is presentation
only and never changes processing/calibration IDs. Original files stay in place.

Photo review uses one asynchronous decode plus one latest pending request. Each
request has a unique token; close, scope changes and project switches revoke delivery.
The raster is capped at 4096px along the long side and never upscales smaller inputs;
encoded files over 256MiB and images over 64MP are refused. Qt plugins can transiently
decode up to the 64MP input guard before scaling. The retained raster is at most
64MiB. Fit centers it, zoom stops at one loaded pixel per display logical pixel,
and drag/scroll pan the enlarged image. The visible label states the review limit:
this is not full-original/tiled detail, particularly for sources larger than 4096px.
SourcePreviewDialog reuses PhotoViewport for secondary published-view browsing.
Automatic saved-properties errors stay in the context panel and do not interrupt review.
Closing embedded review revokes its deferred and in-flight property evidence and
clears the inspector projection; a late reply cannot restore an old error there.
Review keyboard shortcuts yield to group/details dialogs; closing waits for owned decodes.

Ordinary perspective video uses Qt Multimedia MediaPlayer / VideoOutput / AudioOutput.
No external processing or decoder subprocess is launched by QML. Play/Pause, Space,
seek, current position and backend-reported duration operate on the original locator.
Leaving Materials unloads playback; changing media/project clears the old source.
Metadata refreshes do not reassign an unchanged player source or reset playback.
Decoder/file errors stay in the viewer and explain checking file/codec support in
the installed Qt runtime. This does not claim every codec/container is supported.
No dependencies or codecs are installed automatically.

Use neutral graphite surfaces, blue selection/primary action, thin separators and
4px radii. Placement, spacing and typography group content; avoid stacked decorative
cards, gradients, glow, giant titles and KPI tiles. Dark/Light share the same tokens
and layout. Properties and source checks disclose details locally. Preserve keyboard
focus and accessible names; unavailable tools must not masquerade as working actions.

Saved video intervals, their Materials / Trim editor and real frame preparation use
the [Trim API](VIDEO_USAGE.md). The editor retains the full source extent, separate
playhead/selection/saved ranges, exact fields and normalized used list in the right
panel. Hatched gaps do not collapse time. The optional real filmstrip is bounded
and asynchronous; unavailable thumbnails do not disable editing. Review/Trim tabs
replace the former static Review title; photos explain why Trim needs a video.
Existing compact transport, resizable/collapsible panels, import and Projects remain.
At the minimum window the right inspector uses the existing scrollable overlay.
Dark/Light use the shared tokens; no masks/360 tabs are advertised.
Interaction, time mapping and playback limits belong to VIDEO_USAGE above;
native visual evidence and remaining review are recorded in the active plan.
Image-coordinate masks with manual correction persistence, SAM3/tracking, full sparse-camera picking
and Gaussian/external-viewer workflow are separately scoped in the
[active plan](plans/active/2026-10-28-materials-workspace.md). 360/fisheye preprocessing
and LiDAR inputs remain future typed viewer extensions, not supported source modes.

Plan resolves current Included sources with the same core resolver as Prepare; an
empty/unsupported participation set is not runnable. An explicit historical `views_run`
uses validated published candidate/selected inputs independently of current exclusions.
Participation/inventory edits revoke readiness for current-source plans, while preserving
explicit historical requests. The controller also refuses execution of a non-runnable Plan.

### Folder relinking (M12b4)

Materials' catalog menu exposes **Locate source folder…**. A compact modal reuses
the current controls and themes. The recorded folder defaults to the selected
source's saved parent; it stays editable so a user can choose an ancestor covering
multiple subfolders. The replacement folder supports a local path or folder picker.

Check folders shows the complete scoped count and a virtualized diagnostic list.
Only a nonempty fully matched scope enables Relink. Checking/applying have progress
and Cancel; cancelled/failed checks can retry. Successful publication shows the
committed source count and restores current-source review from the new locator.
Source availability records a fresh full-content check in this session; a genuine
project reopen retains the normal neutral session status until explicitly checked.

Unsaved changes use existing Save/Discard/Cancel before entering the operation.
Apply reserves the metadata writer and drains owned readers/decoders; playback and
thumbnail delivery resume only after committed overview readback. Project switches
revoke previous preview/progress context. Close during active work uses existing
cancel/close safeguards. No automatic drive search or partial relink is advertised.
The [persistence owner](PROJECT_FORMAT.md#folder-relinking-m12b4) defines matching,
atomicity and recovery; the [plan](plans/active/2026-10-29-m12b4-folder-relink.md)
records checks and native evidence. Existing Projects/Create and Materials/Trim
composition and global tokens are preserved.

### Prepare Data and selected images (M12c1)

Sources exposes a local **Prepare Data** action inside Materials. Returning to Sources
restores the viewed occurrence without changing the catalog selection. The existing
Review/Trim composition and global design tokens are preserved. The first vertical
slice uses saved frame-selection settings; it does not offer cosmetic quality presets.
Unknown saved reconstruction methods do not block preparation.

Check saved plan displays Included photo/video counts, videos with used intervals,
the human-readable selection method/FPS and conservative candidate/storage bounds.
Bounds use full video durations for scratch requirements; saved intervals constrain
published frames. Planning is metadata validation, not proof that originals, FFmpeg
or free space are available. Unsupported/empty/budget-refused plans explain the problem.
Missing time estimates remain absent. Run-time checks stay in the existing service.

Prepare Data executes the existing ViewsService through the worker/controller, after
Save/Discard/Cancel and reader drain. Stage progress and Cancel use persisted attempts
and durable cancellation, including a request arriving before the run handle. Failed
work keeps its error and available older publications; retry creates a new Prepare
run and reuses validated cache. Unresolved work links to existing recovery diagnostics.

Available succeeded runs are read from exact candidate/selection output bindings,
including cache-hit runs. A dropdown shows saved runs, counts/quality evidence and
their explicit run identity. These are historical results, not an automatic current
input or reconstruction selection. The media area displays up to 100 selected images
per page with existing bounded decoding; no publication is edited. Reopen reads the
same saved result. Both gallery success and failure replies carry request tokens;
new set/source/project context revokes earlier delivery. Long errors wrap; the compact
inspector scrolls to all result counts and errors.

The M12c1 boundary was read-only Selected review. The two bounded extensions below
deliver decisions, Single mode and source-context provenance. The direct-settings
contract below replaces the former Prepare-preset intention. Masks remain separate.
No disabled imitation of those capabilities is shown. See
[persistence](PROJECT_FORMAT.md#prepare-data-desktop-entry-m12c1) and the
[delivered slice plan](plans/completed/2026-10-29-m12c1-prepare-data.md) for evidence
and the separate manual acceptance limits.

### Prepared image decisions (M12c review)

The next bounded scenario extends the M12c1 gallery using the existing compact
tokens/components and [prepared-frame reference](design/references/07-prepared-frames.png).
Selected / Rejected / All show effective membership of the exact prepared run.
All contains every materialized candidate, including candidates not sampled by
fixed FPS; absence from automatic selection is not labeled as a measured quality
failure. Known automatic reasons and manual decisions remain separately visible.

Exclude forces omission; Keep Anyway forces inclusion; Reset to automatic removes
the override. Reset may reject a frame that the automatic result rejected. Each
action saves immediately through application services and confirmed readback.
Failures remain visible without a saved notification. No operation deletes a source,
candidate image or publication, or changes source participation.

Checkboxes build an explicitly labeled current-page batch (at most 100 frames).
Opening a frame changes only the viewed frame. Batch controls act on checkbox UUIDs;
tile/preview controls capture their own UUID. Batch selection clears on page/filter/run
change. Usage text/checkbox, viewed image and keyboard focus have distinct meanings.
Icon buttons provide tooltips, accessible names and shared focus treatment.

Quick Exclude in preview advances only after confirmed save to the next stable UUID
in the pre-action full filtered order, including across pages; if none, the previous
UUID is used, and an empty result closes preview. Page offsets clamp after removal.
Actions are blocked while loading/saving/transitioning so an old event cannot address
a frame newly occupying an index. Both read success and error carry revocable tokens;
changing result/project or returning to Sources rejects stale delivery.

The explicit effective run identifies the immutable selected set for subsequent
processing. Historical automatic runs remain exact historical inputs; viewing a run
does not start reconstruction or silently select a global processing input.
See [persistence](PROJECT_FORMAT.md#prepared-image-decisions-m12c-review) and the
[bounded plan](plans/completed/2026-10-29-m12c-image-review.md). The subsequent
source-context extension is specified below. Masks remain separately scoped;
user acceptance stays open.

### Prepared source scopes and provenance (M12c)

This bounded scenario implements source-context review from
[reference #7](design/references/07-prepared-frames.png). View scope is a presentation
filter of one exact prepared run. It offers All sources, individual prepared source
UUIDs and the existing saved source organization: explicit user groups, then reliable
captured device sections for unassigned sources, Videos or Unknown device fallback.
Empty saved groups remain selectable. Current logical labels/assignments are display
organization; frozen processing/calibration groups are separate provenance. Equal
filenames never merge sources. No scope control edits source participation or frame
decisions, or changes the effective run.

Scope intersects Selected / Rejected / All **before** pagination. Whole prepared-set
counts remain explicitly labeled; scope counts refer to that scope before the status
tab, and page totals refer to the current scope/tab intersection. Changing scope resets
to page zero and clears preview and current-page batch. Status-tab changes do the same.
Per-frame actions and preview advance retain captured UUIDs within the full current
scope/tab sequence. Loading success/error, including service-factory errors, carries
a revocable request token. Changing run/project resets scope to All sources.

Single-image review shows a compact scrollable provenance inspector beside or below
the media at small widths. It identifies the source photo/video and original name,
the saved locator at preparation, and separately the current matching inventory
locator. A current locator is saved metadata, not a fresh availability check. Last
recorded source-check outcome/time is labeled as historical evidence and may predate
Relink. Missing/changed inventory details are explicit; browsing never hashes/probes
the original. Prepared pixels remain viewable when originals are missing.

Video time is the original source presentation time, `PTS × time_base`, including
nonzero origins and saved Trim intervals. It is never a gallery position or elapsed
time from Trim start. Photos show time as not applicable. Automatic decision/reason,
available recorded score, manual override and effective membership are separate.
Absent evidence is Not recorded/Unavailable; a recorded zero remains zero. Long
locators wrap or are selectable in full. Exact PTS/time base, UUIDs and run identities
are behind Technical details; they do not dominate the normal inspector.

Only the current bounded page receives image references/provenance. Existing saved
manifest/inventory reads and integrity validation remain authoritative; no original
decode, preparation rerun or new numerical artifact is introduced for browsing.
See the [read-model contract](PROJECT_FORMAT.md#prepared-source-scopes-and-provenance-m12c)
and [bounded plan](plans/completed/2026-10-29-m12c-source-scopes-provenance.md).
Masks and other independent M12c work remain outside this scenario. The user's
later direct-settings decision below replaces the former Prepare-preset intention.

### Direct Prepare settings (M12c)

The 2026-10-29 decision exposes existing working methods directly and removes
Fast/Medium/High/Max Prepare profiles. The compact inspector shows method, target
interval in seconds with read-only FPS, candidate FPS and JPEG/PNG encoding at once.
Uniform Fixed FPS and Sharpest Interval are exclusive selector options. Explain that
Sharpest compares denser candidates within each output interval; video candidates
must be at least twice target FPS. Photo-only time fields are visibly inactive.
Sampling is not a reconstruction-quality guarantee.

Filters and analysis are an explicit disclosure with an active-filter count.
Minimum sharpness and similar-video suppression use independent checkboxes and nearby
parameters. Existing defaults are visible: no minimum threshold; Sharpest video dHash
on with distance4/lookback8; proxy max side1024. The proxy is required Sharpest
analysis, not another toggle or output-image resolution. Fixed disables/explains these
functions and runs no quality assessment. dHash compares appearance within a video;
it does not measure geometric redundancy, suppress photos or merge sources.

The inspector heading and next-set footer remain visible while the body scrolls,
including the compact window. The footer keeps validation, Save settings, Check plan
and Prepare Data (or progress/Cancel) available. An incomplete form keeps
raw input, explains validation, blocks launch and participates in normal Save/Discard/
Cancel. Save cannot substitute a previous valid value. Failed Save retains unsaved
fields; returning a value to its saved baseline must not readopt a failed draft.
Busy state updates disable/re-enable controls; returning to Sources is guarded during
Save. Valid form edits never start processing or modify a running snapshot. Form
edits revoke old plan responses, including factory failures. History reads have
separate current project/request guards and remain independent of editable settings.

A completed check can return a blocked plan: only a runnable plan reports ready.
The pinned footer shows Preparation blocked and a Show reason action scrolls to the
complete cause from any inspector position. Missing candidate counts stay unavailable;
recorded zero stays zero. Resource diagnostics show GiB/counts without source UUIDs
or raw byte/flag text. Explain that storage is a conservative bound, not expected
JPEG/PNG size or free space. Saved Trim bounds extraction images and retained frames;
decoding can still scan the full clip. Expected encoded size remains unknown before
processing. This explanation survives budget refusal. Recovery advice
offers reducing Included sources; FPS/target-interval advice applies only to usable
videos, respecting the chosen method's density. Do not offer an unavailable desktop
budget control or silently alter limits/settings. The
[corrective plan](plans/completed/2026-10-29-m12c-prepare-budget-feedback.md)
records the user's 4K case and verification limits.

Published settings disclose the selected historical run's frozen request independently
of the current form. Editing/saving current settings retains original pixels, Trim,
source participation, immutable automatic/effective runs and exact-set manual review
heads. Scopes/provenance keep their existing presentation-only meaning. No placeholder
operations or unverified technology controls are shown. The
[technical backlog](TECHNOLOGY_STRATEGY.md#prepare-data-technical-backlog--2026-10-29)
records evaluation gates; [persistence](PROJECT_FORMAT.md#direct-prepare-settings-m12c)
owns saved intent and canonical resolution. Manual acceptance remains open.

## Reference-led interface contract — 2026-10-28

This is the reference-led contract, prepared from the complete
[reference catalog](design/references/README.md). Preparation changes documentation
and reference assets only. The previous agent visual review is historical evidence,
not user acceptance; its full default test run was stopped and remains incomplete.
Current working-tree inspection includes changes after the isolated review snapshot.
The branch/HEAD and scoped evidence are recorded in the
[active interface plan](plans/active/2026-10-28-materials-workspace.md).

Precedence: explicit request and data safety; original selected media-editor
composition; scenario references; existing UI as behavior evidence. The original
attachment identity and separate current-app attachment are not established; the
catalog records this rather than assigning those roles to a convenient image.
Use #1 for the concrete Review arrangement and #4/#8 for mask-editor variations.
No generated image text is an instruction or proof of support.

### Projects entry slice delivered — 2026-10-28

The separately authorized steps 1–4 now provide a dedicated Projects list, a 600px
Create dialog and an always-visible Projects button with underlined workspace tabs.
Normal startup stays on Projects; successful Create/Open enters Materials. Legacy
page preferences no longer override this route; internal page IDs remain 0–6.
The normal desktop entrypoint had no explicit project argument; existing programmatic
Open and directory-drop routes still validate through the controller and facade.

Projects retains one session and its last section, draft, selection and owned work.
Return to project does not reload or save. Activating its recent path validates the
on-disk project identity asynchronously before resuming; a replacement identity uses
Save/Discard/Cancel. Switching to another project retains existing mutation guards.
Errors stay beside entry controls; Create keeps its fields until successful readback,
blocks duplicate submission/dismissal while pending and restores input focus on error.
Locate validates identity before updating recents; Remove only edits preferences.
Rows omit previews, expose full paths through tooltip/Copy full path and drop the
optional last-opened column at narrow widths. A separate current-session row remains
even when its recent entry is removed or its location becomes unavailable.

The actual Materials contents and later sections are retained. The active plan
records user acceptance of the Projects/Create layout and, in the 2026-10-29
continuation, the latest Materials/Trim visual refinement. Functional Materials/Trim
and corrected M12b3 manual scenarios remain unconfirmed; M12 is not complete.
Commands, screenshot matrix and limits are recorded in the
[active interface plan](plans/active/2026-10-28-materials-workspace.md).

### Materials composition delivery — 2026-10-28

The subsequent Materials request implements reference-catalog Review geometry while
retaining the accepted Projects/Create shell. The catalog starts at 280 px, with
88 px rows and an 80×60 thumbnail area (aspect-preserving image). The subsequent
import follow-up replaces the heading's plus menu with visible Photos/Video/Folder
actions; they wrap within the catalog. Filters and group scope stay above the
virtualized browser; List/Grid and expansion sit in its footer. Row menus disclose
View, Details and the existing selection-aware Exclude/Restore action. Repeated
normal availability labels are omitted from rows; accessible names retain evidence,
attention/exclusion remains visible, and the current source inspector shows status.

Review owns a 48 px heading, Fit/zoom tools and a 44 px lower navigation strip;
ordinary video adds actual playback/seek transport. A Viewing marker identifies the
displayed UUID independently of batch outlines. The batch action bar appears only
for multiple selected sources. The existing bounded review-limit label stays visible.
No timeline thumbnails, saved intervals, masks, tracking or 360 actions are introduced.

The 300 px Source inspector shows metadata pairs, current-only participation and
Technical details, which opens the existing details/evidence dialog. Source-file
verification is disclosed from the catalog menu. Both dock widths can be dragged;
collapse/reopen retains the width, and the catalog menu provides a width reset.
Below 1180 px, properties open over the workspace at its right edge without changing
viewer width. The source header and close action remain below the global shell.

`media.state.previewSource` now includes its stable string `identity`; an absent
current source still yields an empty map. Existing activation, focus, selection,
save/readback and async token contracts are unchanged. Scope, native evidence and
handoff checks are recorded in the [active plan](plans/active/2026-10-28-materials-workspace.md#materials-redesign-handoff--2026-10-28).

### Materials import entry — 2026-10-28

An inventory with no registered sources shows a compact centered **Add your media**
block: an existing media icon, “Drag photos, videos, or a folder here”, and Add photos,
Add video and Add folder. These and the catalog's always-visible compact actions
share the same QML Actions and existing pickers. Photos/videos selected in a picker
retain the direct ingest route; folder selection and OS URL drops use asynchronous
read-only discovery followed by the existing explicit confirmation. Cancelling that
confirmation leaves project data unchanged. No new registration or duplicate policy.

The page-local DropArea accepts supported local file URL candidates and directories
in empty or populated Materials, including mixed roots and overlapping paths. Its
quiet border and “Drop to add media” label exist only during an admitted drag; leave,
cancel and drop clear them. Directory discovery, limits, link/reparse checks and
duplicate counts stay in the worker scanner. A single dropped folder supplies the
same explicit grouping root as Add folder; mixed roots retain the scanner's existing
unscoped group behavior. Admission performs only URL/extension validation and a
directory metadata check, without enumeration, hashing or media probing. Nonlocal
or relative URLs and unsupported-only files do not start import. The global shell
drop handler yields to Materials; pointer, wheel, photo pan and video controls keep
their ordinary event handling.

No inventory, no visible rows under filters, no current review and decode/playback
errors are separate states. Filter emptiness offers Reset filters (All groups / All
participation). No current review hides Fit/zoom and material navigation, including
0/0. Empty properties explain the next step and omit technical/participation actions.
Preview errors retain their explanation, Retry preview and applicable navigation.
Ordinary video retry explicitly reloads its player source after an error.

Current evidence and remaining Explorer/DPI limits are in the
[import handoff](plans/active/2026-10-28-materials-workspace.md#materials-import-follow-up--2026-10-28).

### Screen map and navigation

The [UX specification](UX_UI_SPEC.md), sections 3–6, owns navigation/lifecycle
semantics. Visible labels are Projects (Проекты), Materials, Reconstruction, Splat,
Results; “Home” remains only a legacy internal ID, not a second destination.
These English labels match the existing UI; the Russian name in the request refers
to the same visible text button, not an icon or logo shortcut.

```text
Normal launch -> Projects / Recent projects
  New -> Create dialog -> successful create/readback -> Materials (empty)
          Cancel / Esc -> Projects
  Open / recent row -> validated open/readback -> Materials
          failed / unavailable -> Projects + local error / Locate
  Resume current session -> retained project section, same draft/task

Project shell: [Projects] [SplatForge / project]  Materials Reconstruction Splat Results
  Materials: Sources {Review / Trim / Masks / source Lens coverage}
             -> Prepare -> Prepared frames {Grid / Single} -> Reconstruction
  Reconstruction: configure -> progress -> review -> explicit component selection
             -> dataset preparation/export -> Splat or Results
  Splat: input/readiness -> training -> history / Results
  Results: saved outputs/history -> export / supported external viewer
  Settings/diagnostics: global entry, close -> originating surface
  Projects button from every section -> Projects, retained session visible
```

Future routes in this map are not enabled until their contracts exist (see catalog).
Prepare stays within Materials; dataset export remains reachable without training.
No automatic component choice and no implicit processing from navigation. Keep
advanced settings, history, recovery and existing dataset operations reachable
during the presentation migration. Settings has a visible, accessible global entry
on Projects as well as the project shell. More is only secondary navigation.

The native Windows title bar remains separate; do not recreate minimize/maximize/
close inside the client header. Preserve resizing, system menu, snap, maximize,
restore and per-monitor DPI behavior. Project tabs use text with an accent underline,
not four competing filled command buttons. Projects is always visible at the upper
left next to the product/project identity, including narrow windows. Ellipsize the
project name before hiding navigation; expose its full name/path accessibly.

### Proposed layout and tokens

The following are logical-pixel targets for implementation and screenshot review,
not exact measurements extracted from the raster references. The 2026-10-29
calibration above updates implemented shared control and Materials density values.
Reuse the Theme singleton as the sole token owner in code; no page-local color system.

| Element | Proposed target |
| --- | --- |
| Client shell / panel headings / status | 48–50 / 40 / 28 px; no permanent empty operation band |
| Spacing | 4 px base; 8 between related controls, 12 panel inset, 24 between sections, 32 outer Projects inset |
| Type | Segoe UI Variable → Segoe UI; body 14, secondary 12, panel heading 16 semibold, dialog/page title 22; no giant title; Consolas only for exact evidence/paths |
| Controls / icons / radius | 32 px control and minimum compact hit area, 20 px icon; 2 px control and 4 px menu/dialog radius, square panel boundaries; 1 px dividers |
| Materials panels at 1440×900 | Sources 280 px (248 minimum), inspector 300 px (260 minimum), flexible media center; resizable split handles |
| Source rows | 80 px with real 80×60 thumbnail when available; filename + one/two metadata lines; no repeated framed cards |
| Transport / future timeline | 44 px transport; 120–160 px resizable timeline only for relevant video tools; photos keep compact Previous/Next, no empty video timeline |
| Projects | One page header/action row and virtualized list; 72 px rows without preview, two text lines for name/path; optional last-opened and availability columns |
| Create | About 560–640 px wide, maximum window width minus 48; field labels above fields, destination wraps, fixed visible action footer |

| Semantic color | Dark proposal | Light proposal |
| --- | --- | --- |
| Background / panel / surface | `#1B1D20` / `#202226` / `#222529` | `#F0F3F7` / `#E8EDF3` / `#FFFFFF` |
| Primary / secondary text | `#F2F5F8` / `#A7B1BC` | `#182434` / `#526375` |
| Divider / hover | `#383E45` / `#30353B` | `#D6DFE9` / `#E4EBF4` |
| Accent / accent foreground | `#429BFF` / `#101820` | `#166BCC` / `#FFFFFF` |
| Selected row | `#182D44`, accent edge | `#DDEAFC`, accent edge |
| Success / warning / error | `#42C982` / `#E7AC43` / `#E57A84` | `#147947` / `#92600A` / `#B22C41` |

These start from current theme values, not pixel-sampled gradient/noise in the
references. Dark, Light and System share structure and semantics. Target readable
contrast (4.5:1 normal text, 3:1 large text and essential control/focus boundaries);
measure during implementation, do not infer compliance from these tables. Disabled
actions keep a readable reason. Error/status always includes text or an icon label.
Selection is persistent, hover transient, focus distinct (proposed 2 px outline).
Use quiet secondary/ghost actions; destructive semantics require an actual risk,
not red styling for every Cancel. Checkboxes express inclusion, not row focus.

### Panels, scaling and keyboard

No global workspace vertical scroll. Source list, inspector, history and dialog
body each scroll independently; headers and the relevant primary footer stay
visible. The center fits the image with honest letterboxing; never crop/stretch
the source to imitate the apartment photo's aspect ratio. Technical evidence is
collapsed locally. Import belongs in the Sources header; avoid an extra full-width
toolbar of duplicate catalog/Properties actions. Panel collapse controls remain
discoverable in their headers and restore focus/width when reopened.

Keep minimum **1024×640 logical px**. Below approximately 1180 px, inspector starts
collapsed and opens as a contextual overlay; Sources can collapse too. Tab labels
and Projects remain visible. At minimum height reduce optional metadata/spacing,
not control hit areas; scroll dialog bodies without losing Cancel/Create. Projects
list drops optional columns before shortening its name/path pair. Long paths wrap
in details or show a full accessible tooltip; keyboard users can copy them.

Review 1024×640, 1280×720, 1440×900 and 1920×1080; Windows 100/125/150/200% scaling
and moving between monitors. Physical screenshot dimensions and logical viewport
size must be recorded separately. If screen work area cannot fit the logical
minimum, critical actions remain reachable through the compact/scrolling layout;
do not multiply logical sizes manually by DPI or cover native window controls.

Tab/Shift+Tab follows header → list/viewer → inspector → contextual actions. Enter
opens a focused recent row; arrows navigate lists, Space activates controls; Enter
submits only a valid Create form. Esc closes an idle dialog/overlay and returns
focus to its invoker. Ctrl+N/O/S and Ctrl+, retain New/Open/Save/Settings behavior
and the same busy/dirty guards as pointer actions. Focus is trapped in modal
dialogs; viewer shortcuts yield to text editing/dialogs. Icon controls require
Accessible names and tooltips. Splitters need keyboard adjustment or equivalent
collapse/reset actions. Verify actual keyboard/screen-reader behavior separately.

### Loading, missing data and unavailable actions

| State | Required presentation and behavior |
| --- | --- |
| Projects loading | Bounded busy indicator and “Loading recent projects”; New/Open remain available unless session switching is blocked; never flash “no projects” before results |
| No recent entries | Calm text plus New/Open; no sample rows, placeholder thumbnails, statistics or readiness badges |
| Recent path unavailable | Keep name/path, explain unavailable versus invalid/different identity; Locate and Remove from list; never delete disk data |
| Create/Open pending | Show actual operation, prevent duplicate submit; preserve entered fields; no success transition until persisted readback |
| Create/Open failed | Human explanation near form/list, retain context and inputs, focus error; technical detail expandable; retry only when ownership allows |
| Source loading/error/empty | Clear the previous image before async load; distinguish no selection, no sources, all excluded and missing/undecodable source; keep appropriate import/Restore/check action |
| No preview/unknown metadata | Neutral media icon or no preview column; unknown fields omitted or labeled unavailable, never invented |
| Processing | Actual phase/fraction/elapsed; indeterminate if unknown; estimated range only with evidence; cancel pending until confirmed; global session status also on Projects |
| Unavailable tool | Brief reason and relevant configuration/recovery route; capability-dependent actions disabled; wholly future tools absent rather than fake interactive buttons |
| Saved/stale/interrupted | Show publication/intent truth and recovery route; navigation is not a fresh source check, validation or publication |

Create/Open operation cancellation is not currently a separate service contract.
Before submission Cancel/Esc returns to Projects without creation. Once submitted,
disable dismissal until completion/error and show the short operation's status;
do not claim it cancelled a filesystem operation. Preserve existing application
shutdown ownership guards. Opening another project does not replace the retained
session until validated success; an error leaves that session accessible.

### Presentation reuse and replacement

| Treatment | Components/responsibility | Behavior boundary |
| --- | --- | --- |
| Reuse and restyle | Theme, SplatButton/ComboBox/TextField/CheckBox/Dialog, Fluent icons, native pickers | One token set, Qt focus/accessibility; cards/badges only where functional |
| Replace composition | Main.qml shell/navigation, HomePage overview-as-home, recent-project row layout, Create form arrangement | Dedicated Projects page; keep internal page IDs or an explicit compatibility mapping; no restored preference may bypass the normal Projects entry |
| Rework | SourcesPage, SourceActions, WorkspacePanel, right-side properties and compact import/group actions | Same UUID models, current versus batch distinction, independent scrolling, no optimistic persistence |
| Reuse rendering/lifetime | MaterialViewer, PhotoViewport, secondary SourcePreviewDialog, thumbnail/media services | Bounded decode/cache, async tokens, no hidden-page preload, stop/unload playback on leaving Materials; do not retain decoders merely to retain a project session |
| Recompose later | Reconstruct/Dataset/Train/Results/Diagnostics pages, WorkflowStrip | Keep existing callable operations reachable; do not treat connected legacy forms as the final reference design |
| Extend only in later scoped slices | PointPreview and future timeline/masks/prepared-frame editor | Prototype point centers are not the required sparse viewer; contracts, stable IDs and genuine output data precede controls |
| Preserve | Desktop/Workflow/Media view models, controller, facade, Core/Application/adapters | Save/CAS/readback, source participation, groups, progress/cancel/recovery, stale-reply guards, current-source versus explicit historical Plan inputs |

The next request may replace QML page/component structure. Only narrow presentation
state routing may need to change in Python (Projects/session return and post-open
destination). There is no justification here for rewriting Core, Application,
processing handlers, project storage or COLMAP/benchmark code. Session-retained
drafts do not become a second persistence store. On an actual project change,
revoke old image/metadata/plan replies and reset selection using existing generation
guards. On a return to the same retained session, keep selection/draft and re-enable
bounded media loading rather than issuing a second Open/reset.

### Delivery order and first implementation gate

1. Common shell and only the base controls needed for the entry flow.
2. Dedicated Projects/recent-projects screen, including empty and unavailable rows.
3. Create/Open with existing validation, errors, identity-safe Locate and readback.
4. Materials entry and global return to Projects with retained session/lifecycle UX.
5. Materials composition polish and regression-preserved catalog/viewer/properties.
6. Remaining sections in roadmap order: preparation/review, currentness,
   reconstruction/progress/review, export, Splat, results/settings/recovery polish.
   Trim/masks require their own contracts; fisheye/360 remains M14.

**This bounded entry request covers steps 1–4 only.** Reuse the current functional Materials
screen as the destination; do not start its full redesign, prepared-frame editor,
timeline, masks, sparse viewer or training redesign in that task. Demonstrate:
launch → recent projects → create or open → Materials → Projects. Include empty
recents, Cancel, invalid name/parent, nonempty destination, failed/unsupported Open,
missing recent path and identity-safe Locate, same-session Resume, dirty Save failure
and active-task return with no cancellation. Check the Projects button from all four
sections; processing forms can retain their old content for this gate.

Capture the running native app in both themes at minimum and normal window sizes,
with high-DPI checks, long Unicode/space paths, keyboard-only operation and visible
focus. Compare against #3/#2 and the shared visual language. Use small owned fixtures
for busy/error scenarios and identify them; no invented product data. Tests/lint are
behavior evidence, screenshots are visual evidence, and user acceptance is a third,
separate gate. Do not mark either older M12b3 or Materials work accepted by completing
this documentation preparation.

## Accessibility and desktop layout

Keep standard focus/keyboard semantics and meaningful Accessible names/descriptions.
Tab follows visual order; Enter/Space activates controls. Ctrl+N/O/S, F5 and Ctrl+,
are the project/settings shortcuts. Point preview supports arrows, +/− and R.
Use text with status color and preserve visible focus outlines.

QtQuick.Layouts owns sizing. The current workspace uses top tabs and collapsible
resizable panels; no global vertical workspace scroll is permitted. Parameter panels
and history own their scroll. History
scrolls horizontally instead of truncating identity data. Design review targets
1280×720, 1440×900, 1920×1080 and high DPI. Minimum window size is 1024×640; it is not
a mobile layout. Preserve native Windows maximize, restore, snap and DPI behavior.

## Screenshot review workflow

Use a real native window, a tiny synthetic published project and isolated UI settings:

```powershell
python scripts/capture_gui.py --project "C:/Scenes/Tiny fixture" --output sample_data/ui-review/1440
$env:QT_SCALE_FACTOR = "1.5"
python scripts/capture_gui.py --project "C:/Scenes/Tiny fixture" --output sample_data/ui-review/150 --width 1280 --height 720
Remove-Item Env:QT_SCALE_FACTOR
```

The script never starts processing or probes. It captures the actual QQuickWindow,
records exposure/DPR and QML warnings, and exercises both themes. An optional
`--synthetic-progress` capture is explicitly named and marked as synthetic in the
manifest; it is presentation evidence, not measured training performance. Normal app
behavior never injects progress. Review screenshots with an image viewer; do not treat
successful capture or offscreen tests as visual approval.

Check hierarchy, alignment, density, font fallback, contrast, clipping, selected/disabled
states, focus, long paths, dialogs, scrolling and light/dark consistency. Fix defects and
capture again. Keep generated projects/screenshots outside Git. Do not add pixel golden
tests. Qt tests cover semantic state/actions, engine warnings and boundaries instead.

The migration review corrected icon sizing/relative URLs, excess source-table height,
misaligned training cards, uneven diagnostic cards, technical clutter in the main output
list, blank initial selections, repeated metadata serialization and delegate lifetime
warnings during fast navigation. The review uses synthetic publications; it makes no
claim about reconstruction quality or production trainer readiness.

Final review also removed raw microsecond timestamps from Guided outputs, added dates
to distinguish publications of the same kind, made missing previews explicit and
kept unrelated preview messages out of Diagnostics. Final native captures cover both
themes at actual DPR 1.0, 1.25 and 1.5, plus five dialogs at 1280×720, without QML warnings.
Native review at the maximum
20,000 points plus 2,000 cameras measured approximately 19 ms median / 34 ms p95 from
update request to frame swap over 90 frames at DPR 1.0. These local synthetic timings
are review evidence, not a GPU benchmark or a frame-rate guarantee.
