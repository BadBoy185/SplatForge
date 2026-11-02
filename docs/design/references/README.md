# Interface reference catalog — 2026-10-28

Evidence catalog, not implemented capability or runtime acceptance. All 13 images
attached to the request were visually inspected and copied byte-for-byte from the
user's Downloads directory without replacing existing files. Original filenames,
attachment numbers and SHA-256 values are in [manifest.json](manifest.json).
The links below are the actual repository copies. All twelve requested scenarios
are represented; Masks has two variants.

## Roles and precedence

1. Explicit user requirements and data correctness take precedence.
2. The previously selected media-editor composition owns the visual language:
   left catalog, dominant media/scene, right contextual tools, lower transport.
   Its original attachment identity was not recorded in the previous plan. No
   separate file is unambiguously identified as that original in this request.
   Image #4 is a compatible mask-editor variant, not a proven identification of
   the original. Image #1 is the concrete Review anchor for the same composition.
3. The numbered journey below supplies the arrangement of individual scenarios.
4. Existing application code supplies available behavior, not a mandatory layout.

None of the 13 attachments is labeled or identifiable as the separate current-app
screenshot mentioned in the request. That comparison attachment is **missing**.
The historical native capture at
`sample_data/ui-review/materials-1/Dark-1440-photo.png` was inspected as supplementary
prior evidence; it is not a fresh capture of today's tree and is not copied here.
The Downloads file `splat-image.png` shows a 3D street scene, not the application
shell, and is not used as a substitute. No current visual acceptance is claimed.

## Screen inventory and capability boundary

“Existing” below means found in the current working tree/contracts, not that the
new layout or every backend is accepted/runnable. Visual state, text and numbers
in the references are examples. Capability detection and Plan remain authoritative.
Implementation boundaries are in [GUI design](../../GUI_DESIGN.md#presentation-reuse-and-replacement).

| Step / attachment / file | Visible state and composition to retain | Existing behavior to preserve | Separate development / corrections |
| --- | --- | --- | --- |
| 1 · #3 · [Projects](01-projects.png) | New/Open above recent rows; name/path, selected row and unavailable-path action; quiet footer | QSettings recents with identity/name/path/last-opened, asynchronous availability, Locate/Remove | New dedicated Projects presentation and global return. No invented previews, sizes or readiness. Project path availability is not source-file availability. Compact rows without thumbnails are the default. |
| 2 · #2 · [Create](02-create-project.png) | Centered dialog over Projects; name, parent, Browse, computed destination, Cancel/Create | Windows-safe name validation, absolute parent, backend create/nonempty refusal, successful readback and recents | Keep fields/errors visible until success; dismiss back to Projects. Do not copy background table counts/sizes or fabricate a project preview. |
| 3 · #1 · [Materials Review](03-materials-review.png) | Grouped Sources at left, large original preview, Source properties at right, compact local tabs, transport/timeline below; Files/Folder menu | Import/group/selection/Exclude/Restore, bounded photo review, installed Qt video playback, metadata and Save | Prepared-frame workspace and 360 projection remain future. Explicit photo/video/folder actions stay visible. The full-extent filmstrip belongs to implemented Trim below. |
| 4 · #10 · [Trim](04-video-trim.png) | Preview plus start/end inputs, interval list, used/excluded regions and playhead; original preserved | Ordinary video seek/playback, source participation, [saved exact usage/preparation and implemented Trim UI](../../VIDEO_USAGE.md), full-extent timeline, bounded real filmstrip and used-only playback | User acceptance and expanded review remain open. The reference's contradictory “used” list/Exclude wording is resolved with Include range, Exclude range and Remove from used, backed by Python interval operations. |
| 5 · #9 · [Lens coverage](05-lens-coverage.png) | Original dual-fisheye preview; draggable circles and numeric center/radius; lens switch; hatched excluded area | No dual-fisheye preprocessing/editor | M14 camera profiles, coordinate transform, validation and durable coverage. Lens coverage is source preprocessing, not an ordinary perspective camera assumption or object mask. |
| 6 · #8 · [Masks/tracking](06-masks-tracking.png) | Layer list, overlay, brush/restore/polygon, interval scope, tracking and correction marks | No editor/tracking exposed as a working feature | Image-coordinate masks, manual correction persistence, worker progress/cancel, model readiness and tracked intervals. “Find” requires actual configured capability. No implicit model installation. |
| 6 variant · #4 · [Mask layer settings](06b-masks-layer-settings.png) | Layer name/mode, size/hardness/opacity, selected interval, forward tracking and preview | Same boundary as #8 | Reconcile variants: one editor; basic tools first, layer details expandable. Use Results rather than this image's Export primary tab. Different times/counts do not define requirements. |
| 7 · #7 · [Prepared frames](07-prepared-frames.png) | Source scopes left, Grid/Single image, selected frame inspector, mask visibility and inclusion; Continue below | Candidate/selected Views and quality/selection services; secondary published-view browsing | M12c preparation/review UI with saved decisions, provenance, mask integration and explicit published input. Excluding a prepared frame must not silently exclude its source or mutate a publication. |
| 8 · #13 · [Reconstruction running](08-reconstruction-running.png) | Scene dominates, source/layer tree left, method/status/cancel right, compact phase progress below | Existing reconstruction Plan/run/progress/cancel; bounded point-center preview | M12e/f scene layout; actual snapshots only when backend supplies them, marked partial. No simulated incremental geometry, camera path or fabricated registration counters. |
| 9 · #12 · [Reconstruction review](09-reconstruction-review.png) | Components/layers/unregistered frames left, points/camera frustums center, selected-camera evidence and explicit component choice right | Reconstruction artifacts, validation/explicit downstream component selection, prototype point/camera centers | Stable point/camera IDs, frustums/picking/look-through, layer/source filters and per-component viewing. Viewing/checking a layer must not commit downstream selection. |
| 10 · #6 · [Splat training](10-splat-training.png) | Runs and input lineage left; explicitly labeled input image center; progress/log below; settings/cancel right | Dataset/trainer readiness, Plan/run/cancel, recorded progress/checkpoints/history | M12h presentation of real available metrics, previous result link, bounded input filmstrip. Reference image is not live rendering; runtime availability is not implied by gsplat/MCMC labels. |
| 11 · #11 · [Results/export](11-results-export.png) | Results/history left, labeled point-center preview center, export form right; folder/external viewer actions | Published artifacts, dataset/scene export, bounded center preview and existing handoff routes | Recompose Results and handoff UX; only configured/supported actions. A cloud of centers is not final Gaussian rendering. Full Gaussian viewer remains after M12. Never invent export formats or silently overwrite a destination. |
| 12 · #5 · [Settings/diagnostics](12-settings-diagnostics.png) | Modal with category list, selected tool/configuration, local check actions and collapsed technical details | Theme/tool settings, capability/Doctor checks and diagnostic evidence | Consolidated settings presentation; expose categories only with supported content. Detected/Configured/Not checked/Ready are distinct. Green “Detected” in the image must not imply runnable. SAM3 remains future. |

## Shared reading of the images

Retain neutral dark surfaces, blue selection and restrained primary actions, narrow
dividers, moderate corner radii, aligned panel headings and media-first density.
Use one set of tabs, buttons, inputs, row selection and focus rules across screens.
Do not reproduce generated gradients, oversized Projects headings, decorative
status dots, duplicate controls or inconsistent dates/counts. Names, totals,
durations, device identity, timestamps, progress, readiness and all thumbnails
must come from the project or remain absent/unknown.

## Comparison with the delivered presentation

This is a scoped comparison of the inspected historical native Materials capture
and current source structure, not a fresh whole-app visual audit. The capture shows
the real three-panel arrangement and a large photo, but also filled navigation
buttons, a separate full-width import/panel toolbar, many controls above source rows,
small row thumbnails, repeated row metadata/actions and a text-heavy properties
column. The source confirms Home/recents is inside More, and HomePage mixes recent
projects with workflow/metric cards when a project is open. These are the concrete
differences to address; black margins around a photo with a different aspect ratio
are correct Fit behavior, not a reason to crop user content.

The targets use quieter underlined project tabs, actions in panel headers, larger
useful source thumbnails, aligned compact metadata, a contextual right inspector
and content-dependent transport. Projects becomes a dedicated list rather than an
overview/dashboard. Create's arrangement already has the right conceptual fields;
its visual spacing and pending/error lifetime need revision. Target Trim, Masks,
prepared-frame review and camera/frustum tools require real development, so their
absence is a capability gap rather than a styling defect to cover with fake buttons.

Without the separate current-app attachment, differences from that exact screenshot
cannot be claimed. Future implementation must capture the then-current running app
and compare its actual states against these references before visual handoff.

Every project screen also receives the explicitly requested **Projects / Проекты**
button at the upper left, even though the mockups omit it. The actual native
Windows title bar remains above the application navigation. The design decisions,
screen transitions, proposed dimensions and next implementation scope live in
[GUI design](../../GUI_DESIGN.md#reference-led-interface-contract--2026-10-28),
[UX specification](../../UX_UI_SPEC.md) and the
[single interface plan](../../plans/active/2026-10-28-materials-workspace.md).
