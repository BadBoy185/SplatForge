SplatForge — UX/UI Product Specification v1

0. Purpose of this document

This document defines the intended user experience, navigation, screen structure, processing flow, states, recovery behavior, exports, timing/ETA behavior, and interaction principles for the SplatForge desktop application.

Treat this document as the primary UX/UI source of truth.

Do not redesign the application into a generic technical frontend around the existing backend.

The application must expose the capabilities of the backend through a clear professional workflow understandable to users who do not know COLMAP, feature matching, Gaussian Splatting internals, or SplatForge artifact names.

At the same time, advanced users must be able to inspect and control technical parameters when needed.

⸻

1. Core product principle

SplatForge should feel like:

A professional reconstruction workspace that guides a normal user through the correct workflow while allowing an expert to access the underlying controls.

The default interface should answer four questions at every stage:

1. What do I have?
2. What is SplatForge going to do?
3. How long will it approximately take?
4. What should I do next?

The UI must not expose implementation terminology unless the user explicitly opens advanced controls.

Internal concepts such as:

* CandidateViewSet
* PairSet
* LocalFeatureSet
* artifact digest
* M7/M8/M9
* ALIKED
* LoMa
* LightGlue
* COLMAP Mapper
* bundle adjustment
* cache identity

must not appear as primary Standard UI terminology.

They may appear inside Advanced / Technical Details where appropriate.

⸻

2. Global UX principles

2.1 Progressive disclosure

Default interface:

* simple;
* result-oriented;
* minimal settings;
* recommended automatic choices;
* understandable descriptions.

Advanced settings:

* actual methods;
* algorithms;
* thresholds;
* matching modes;
* camera models;
* resource limits;
* expert diagnostics.

Never require an ordinary user to configure technical reconstruction parameters to complete a normal project.

⸻

2.2 One screen = one primary task

Each major screen should have one obvious main purpose.

Examples:

Sources:

Add the data you want to reconstruct.

Prepare:

Turn the source data into a clean image dataset.

Reconstruction:

Calculate camera positions and scene geometry.

Gaussian Splat:

Train a 3D Gaussian Splat from the reconstruction.

Do not create screens containing many unrelated actions competing for attention.

⸻

2.3 Human language before algorithm names

Prefer:

Find connections between images.

Instead of:

Feature Matching.

Prefer:

Calculate camera positions.

Instead of:

Incremental Mapper.

Prefer:

Try to recover unaligned images.

Instead of exposing fallback matcher configuration.

Advanced users can access the underlying technical details separately.

⸻

2.4 No false precision

Estimated processing time before a run should normally be presented as a range:

≈ 18–25 min

not:

21 min 37 sec

During execution, once sufficient runtime data exists, the estimate may become more precise.

⸻

2.5 Non-destructive workflow

Never destroy successful results automatically because the user:

* changes settings;
* runs a new reconstruction;
* retrains;
* excludes images;
* changes an upstream dataset.

Previous successful results should remain available until explicitly deleted or cleaned.

⸻

2.6 No pipeline lock-in

SplatForge must not force users to complete the entire pipeline inside SplatForge.

Users must be able to export useful intermediate results.

In particular:

Prepared Data → export cleaned image dataset.

Reconstruction → export training-ready reconstruction.

Gaussian Splat → export final 3D result.

Reconstruction must be treated as a valid final product, not merely an internal prerequisite for SplatForge training.

⸻

3. Application-level navigation

The application has two primary levels:

Projects / Recent projects (legacy internal name: Home)

Used to:

* create a project;
* open a project;
* access recent projects.

Project Workspace

Primary workspace tabs (selected direction, 2026-10-28):

Materials / Reconstruction / Splat / Results

Projects is the normal first window after launch, even when a previous project/page
is remembered. An explicit project launch argument remains an explicit Open request,
not an implicit restoration. The existing backend Open checks still apply.

A visible text button **Projects / Проекты** stays in the upper-left client header
beside the product/project name in Materials, Reconstruction, Splat and Results.
It is global navigation, never hidden in More/Settings or reduced to a logo click.
Project tabs appear only while viewing the project workspace; Projects shows a
compact retained-session row when one exists. Settings remains globally available.

Materials combines the
source catalog, current photo/video viewer and contextual tools, with transport
below. List/Grid and batch selection share the catalog; current viewer actions
apply to the displayed material only. Prepare remains a processing step within
the Materials-to-Reconstruction flow, not an additional primary destination.
Reconstruction owns camera reconstruction and review. Splat owns training. Results
owns outputs/export; dataset preparation/export remains accessible there through
the existing dataset screen. Overview, history, diagnostics and settings are
secondary actions. Existing screen implementations remain available during this
bounded migration; future controls are not presented as implemented.

The selected layout, full screen map, proposed dimensions and capability boundaries
are specified in [GUI design](GUI_DESIGN.md#reference-led-interface-contract--2026-10-28)
and the [13-image reference catalog](design/references/README.md).
Each workspace fills the available area; scrolling belongs to an individual panel.

3.1 Return to Projects and session lifetime

Returning to Projects is a presentation transition, not Close/Open or a project
switch. Retain one current project session, its last section, draft and owned work.
Stop/unload media playback and hidden presentation requests using existing lifetime
guards; processing ownership and polling continue. Do not reread/reset the project
just to show recents. This decision extends the existing navigate-without-switch
behavior into an explicit visible contract, implemented by the bounded Projects
entry slice on 2026-10-28. The active plan records Projects/Create layout acceptance;
Materials/Trim and corrected M12b3 user acceptance remain separate and open.

* Unsaved changes: preserve the in-memory draft and show the current project with
  “Unsaved changes”, Save and Return to project on Projects. No silent Save/Discard.
  Opening/creating another project or closing the app uses existing Save/Discard/
  Cancel. Save must succeed, read back and release the mutation slot before switching;
  failure stays in the current session with its error. Discard requires the user's
  explicit choice and discards only that draft. Cancel leaves everything in place.
* Active task or source mutation: Projects remains reachable and shows project name,
  actual operation/progress and Return to task. Existing cancellation is available
  only when canCancel allows it; navigation never requests it. Opening/creating a
  different project is blocked with “Finish or cancel active work before switching
  projects”. Cancellation remains pending until confirmed teardown. No background
  multi-project processing or detached daemon is introduced.
* Same project: activating the current-session row (or the matching recent entry)
  resumes the retained section, draft, selection and task without a second Open.
  Resolve identity through existing validated identity/path evidence; a same name
  alone is insufficient. If the path now denotes another project, treat it as a
  different Open request and apply the guards. Explicit refresh/reload is a separate
  action, never an incidental consequence of Return.
* Unresolved lifecycle: keep a visible recovery entry and existing retry/publication
  blocks. Projects cannot suppress ownership checks. Closing the application still
  follows existing active-close/dirty/reader-drain behavior; returning to Projects
  is not permission to terminate workers or lose drafts.

These choices reuse the single controller/session and
[save/ownership contracts](PROJECT_FORMAT.md#storage-layout-and-ownership).
The retained-session surface and same-project resume are explicit in the entry
slice; no multi-project background-switch contract is introduced.

Reconstruction Viewer opens within Reconstruction → Reconstruction Result / Review → 3D Reconstruction Viewer. A separate primary Viewer destination is not required in v1. Fullscreen remains tied to the inspected reconstruction and component; a universal Viewer may be considered later.

Do not expose every internal processing artifact as a navigation item.

⸻

4. Projects screen

New Project and Open Existing Project precede a calm list of recent projects.
Each row shows the persisted project name, location, known last-opened time and
honest availability/error text. Default rows have no preview. A missing thumbnail
does not reserve a large blank card. Unknown timestamps are omitted or labeled
unknown; no fabricated source counts, size, preview or processing-readiness badges.
Future workflow status is optional and requires real indexed evidence; historical
completion must not imply compatibility with current intent.

An empty list explains that no recent projects are recorded and keeps New/Open
available. Loading is distinct from empty. Unavailable entries stay visible with
Locate and Remove from list. Locate uses ProjectService and verifies saved project
identity; legacy entries without identity require the existing explicit confirmation.
Remove affects only recents, never project/source files. Distinguish unavailable
project directory, invalid/newer-format project, different identity and missing
original media; a recent-path check does not verify every original source.

After a normal successful Create/Open, enter Materials. A retained current-session
activation follows section 3.1 instead. Errors remain on Projects with the old
session accessible, and recents update only on validated success. Replacing the
overview-as-Home presentation must not remove history/recovery/dataset access.

⸻

5. Create Project

User selects:

Project name
[ Colorado Cabin ]
Location
[ D:\SplatForge Projects ] [ Browse... ]

SplatForge creates:

D:\SplatForge Projects\Colorado Cabin\

Do not require the user to manually compose the final directory path.

Always show:

Project will be created at:
D:\SplatForge Projects\Colorado Cabin

Prevent accidental silent overwrite of existing projects.

Use the existing Windows-safe single directory-name validator and absolute parent
Location. Reject empty names, separators/control characters, reserved Windows names,
trailing dot/space and excessive UTF-16 length as the current helper does. Destination
preview is computed without I/O; ProjectService/storage performs actual validation,
including nonempty-destination refusal, permissions and supported format rules.
No new defaults silently rewrite existing projects. Originals remain in place.

Before submission, Cancel/Esc returns to Projects without creating anything.
Submit shows pending state, prevents duplicate submission and keeps the form/fields
until success or error. Do not close the dialog optimistically. During the submitted
Create/Open, do not offer a false cancellation contract; wait for result and retain
existing app-close ownership checks. Show field errors locally and backend errors
with a useful explanation, keeping inputs for correction. Successful persisted
readback enters empty Materials, then updates recents/last successful parent.

Primary action:

[ Create Project ]

⸻

6. First-run workflow

The initial workflow is lightly guided:

Projects → Create or Open Project
      ↓
Materials / Sources
      ↓
Prepare
      ↓
Reconstruction
      ↓
Gaussian Splat

The application should recommend the next logical action without locking the user into a strict wizard.

The first implementation gate covers Projects → Create/Open → Materials → Projects.
The bounded entry slice is implemented; further Materials redesign remains separate.
The [active interface plan](plans/active/2026-10-28-materials-workspace.md) records
its verification and keeps older incomplete verification/user-acceptance gates open.

After the project has been processed at least once, the project should behave like a normal workspace and allow free navigation between stages.

⸻

7. Sources

Sources is the catalog within Materials (section 3). In the selected workspace,
the source list/grid stays on the left, the current original photo/video occupies
the center, contextual properties/tools sit on the right and transport/navigation
sits below. Panels resize/collapse and own their scrolling. The main viewer is
embedded; modal photo review remains a secondary published-view/detail route.
The batch selection is independent of the displayed material. The viewer's action
affects that material alone; batch actions display their selected count. No mask,
tracking or saved interval control is shown as working before its persistence and
processing contracts exist. Exact layout, palettes and review limits are owned by
[GUI design](GUI_DESIGN.md#selected-materials-workspace--2026-10-28).

Materials / Trim now edits saved video usage through the
[exact interval API](VIDEO_USAGE.md): select a range, Include/Exclude, edit precise
bounds, remove from used, or Use entire clip. The original timeline and video remain
intact; current media, temporary range selection and batch membership are distinct.
Empty usage stays empty until explicitly changed. Review includes the entire source
by default; Play used ranges only is an explicit transient playback option.
The full-duration ruler supports seek, handles, zoom/scroll and Fit timeline.
Fields/gestures confirm into draft; project Save remains explicit. Photos cannot Trim.
User acceptance is still open; implementation evidence belongs to the active plan.

7.1 Empty state

After project creation:

Step 1 — Add source data
Add the photos and videos you want to use.
[ + Add Photos ]     [ + Add Video ]
or drop files and folders here
More source types ▾

Supporting text:

SplatForge will detect cameras and organize files automatically.

Do not expose SourceSet terminology to the normal user.

⸻

8. Source types

Architecture should support extensible source types.

Current/future examples include:

* photos;
* videos;
* 360° imagery;
* 360° video;
* LiDAR;
* point clouds;
* trajectories / positioning data;
* other reconstruction inputs.

Do not prominently advertise source types that the application cannot yet meaningfully process.

Unsupported/future source capabilities may exist internally without appearing as production-ready UI functionality.

⸻

9. Adding files

Users should have multiple valid workflows.

Explicit import

+ Add Photos
+ Add Video

Photos should support:

* individual files;
* multiple files;
* folders;
* drag and drop.

Videos should support the same where appropriate.

Avoid separate primary buttons such as:

Add Photo
Add Photo Folder

unless platform limitations require it.

⸻

10. Importing mixed folders

Users may drag a mixed folder into SplatForge.

Example:

Colorado/
├── DJI/
├── iPhone/
├── Scan/
└── misc/

SplatForge should automatically inspect and classify the contents.

Example result:

Detected
Photos                 642
Videos                    4
Point clouds              1
Unsupported files         3
[ Review Details ]
[ Import ]

If classification is confident, do not require manual confirmation for every file.

If classification is uncertain, ask only about the ambiguous items.

⸻

11. Source grouping

Source type and capture device are different concepts.

Example:

Photos
 ├── DJI Mavic Pro
 ├── iPhone
 └── Sony A7
Videos
 ├── DJI Mavic Pro
 └── iPhone

SplatForge should use metadata such as EXIF when available to identify logical capture groups.

Example resulting UI:

Drone photos
DJI Mavic Pro
418 photos
✓ Ready
Ground photos
Apple iPhone
224 photos
✓ Ready
Drone video
3 videos · 11m 42s
✓ Ready

The underlying architecture may represent these as Source Sets.

User-visible source groups are presentation concepts. Group labels, colors and viewer filters must not automatically change calibration groups, camera_group_id or historical processing semantics.

⸻

12. Original media storage

Do not automatically duplicate all original media into the project directory by default.

Normal behavior:

Original media
D:\Datasets\Colorado\...

SplatForge stores references to originals.

Project directory contains:

* project metadata;
* database;
* generated frames;
* artifacts;
* cache;
* reconstructions;
* splats;
* thumbnails;
* other derived data.

A future Collect / Package Project function may explicitly copy source media when requested.

⸻

13. Missing or moved sources

Because originals may remain external, source relinking is mandatory.

Example:

⚠ Some source files are missing
Drone photos
D:\OldDisk\Colorado\Drone
418 files unavailable
[ Locate Folder ]
[ Ignore for Now ]

After selecting a new location:

418 / 418 files matched
[ Relink ]

If SplatForge can confidently discover the files automatically after a drive-letter or directory change:

Possible source location found:
E:\Colorado\Drone
418 files matched.
[ Use This Location ]

Do not make the user relink hundreds of individual files.

The implemented M12b4 route is Materials → catalog menu → Locate source folder.
Users explicitly choose the recorded/replacement folders, inspect complete content
matches and confirm one atomic relink. Relative subpaths must stay the same;
automatic location search and renamed-file inference remain unimplemented.
See [presentation](GUI_DESIGN.md#folder-relinking-m12b4) and
[identity/publication](PROJECT_FORMAT.md#folder-relinking-m12b4).

⸻

14. Sources completed state

After import:

Sources
────────────────────────
Drone photos
DJI Mavic Pro
418 photos
✓ Ready
iPhone photos
Apple iPhone
224 photos
✓ Ready
Drone videos
3 videos · 11m 42s
✓ Ready
[ + Add More ]
                    [ Continue → ]

Primary user understanding:

* what was imported;
* how SplatForge grouped it;
* whether anything is wrong;
* what to do next.

⸻

15. Prepare Data

Prepare transforms raw source media into the image dataset used for reconstruction.

The user-facing stage name should be:

Prepare Data

Do not name the primary stage after one backend operation such as Frame Extraction or Candidate Views.

Implementation boundary (M12c1): the first desktop slice now provides explicit
Prepare Data using saved frame intent and existing services, persisted result counts
and read-only Selected image browsing. See [delivered behavior](GUI_DESIGN.md#prepare-data-and-selected-images-m12c1).
Subsequent bounded Image Review and source-context work adds saved manual decisions
and provenance. The 2026-10-29 decision below replaces Prepare profiles with direct
settings; older profile examples do not define current behavior. Human acceptance
remains separate from implementation evidence.

⸻

16. Prepare screen

Decision — 2026-10-29: expose direct working settings; do not implement Fast / Medium /
High / Max or their former Balanced/Maximum aliases for Prepare Data.

Basic controls are visible immediately in the existing compact inspector:

* one exclusive method selector: uniform Fixed FPS or Sharpest per interval;
* one editable video target interval in exact seconds, with corresponding read-only FPS;
* candidate sampling FPS, distinct from the final target density;
* JPEG/PNG and the applicable encoding parameter.

Use the current saved Included sources and used video intervals. Editing never starts
processing. Save settings, Check saved plan and Prepare Data remain explicit actions.
Do not invent processing-time estimates, quality guarantees or unsupported controls.

⸻

17. Direct preparation settings

The application parses decimal/fraction strings into the existing exact rational
time model. Do not maintain two editable target interval/FPS fields. Fixed FPS
requires candidate FPS >= target FPS and does not run quality assessment. Sharpest
ranks candidates within each target interval; videos require candidate FPS >= 2 x
target FPS, so inspection density and saved-frame density are different settings.
More sampling does not guarantee better reconstruction.

Defaults come from actual saved intent or the existing typed backend defaults:
legacy target 2 fps, derived candidates 2 fps for Fixed / 4 fps for Sharpest,
JPEG qscale 2 / yuvj444p or PNG compression 6, analysis maximum side 1024.
Existing projects retain saved intent; opening them applies no new numerical defaults.
There is no preset layer or Reset to Balanced operation.

⸻

18. Video and photo applicability

Videos remain source assets; extracted frames are derived data. Target/candidate
rates apply only to included video with used footage. Photos are prepared once per
source; time fields are disabled with an explanation for photo-only input. Saved
video intent is retained for future mixed input, while the resolved photo-only request
uses canonical inactive video settings. Original PTS/time_base and absolute Trim
intervals remain unchanged.

⸻

19. Optional filters and analysis

An explicit disclosure contains two independent functions supported by Sharpest:

* Minimum sharpness: checkbox off means no threshold (None); enabling requires an
  explicit nonnegative value. Zero is a valid entered threshold, not a substitute
  for absence. Edge variance measures high-frequency image content, not universal
  blur or reconstruction suitability.
* Suppress similar video frames: checkbox, Hamming distance 0..64 (default 4) and
  recent accepted-frame lookback 1..64 (default 8). Existing Sharpest default is on.
  dHash compares image appearance within each source video, not geometric viewpoint
  redundancy. It does not suppress photographs or compare different sources.

The required Sharpest analysis proxy maximum side is an ordinary parameter,
64..4096 px, default 1024. It does not change saved-image resolution. Fixed disables
these filters and analysis with an explanation, and consumes no quality report.
Disabled/inapplicable values do not affect the resolved request or create different
recipes; resolved artifact metadata uses the same canonical values.

Show field/validation/save errors with no success claim. Invalid raw input participates
in the existing Save/Discard/Cancel decision; Save cannot silently persist an earlier
valid value. A running operation pins saved request/revision and refuses form edits.
Historical prepared sets disclose their own frozen settings, distinct from the form.

Exposure, learned metrics, adaptive/geometry-informed selection, count caps and masks/
tracking have no placeholder controls. Their actual status and integration gates are
in the [technical backlog](TECHNOLOGY_STRATEGY.md#prepare-data-technical-backlog--2026-10-29).
See [GUI behavior](GUI_DESIGN.md#direct-prepare-settings-m12c) and
[saved intent](PROJECT_FORMAT.md#direct-prepare-settings-m12c).

⸻

20. Dataset size warning

Before processing, SplatForge should estimate output scale.

Example:

Estimated result
642 original photos
~1,380 frames from video
Estimated usable images
~1,200–1,600

If the resulting dataset is unusually large:

⚠ Large dataset
This project may create more than 3,000 images
and require substantial processing time and disk space.
[ Reduce Dataset Automatically ]

⸻

21. Processing UI

During Prepare:

Preparing Data
✓ Reading source metadata
✓ Extracting frames
● Checking image quality
○ Removing redundant images
○ Building final image set
742 / 1,246
Elapsed
4 min
Remaining
≈ 3 min
[ Show Technical Details ]

Do not use raw console output as the main progress interface.

⸻

22. Prepare result

Example:

✓ Preparation Complete
Original photos
642
Frames extracted from video
1,284
Removed
96 blurry
213 duplicate / redundant
18 unsupported
Selected for reconstruction
1,599 images
✓ Dataset looks good
[ Review Images ]
                    [ Continue → ]

⸻

23. Image Review

Review tabs:

Selected
Rejected
All

Display images as a thumbnail grid.

Rejected images should show the reason where known:

* Blur
* Duplicate
* Low quality
* Unsupported
* Exposure issue
* Other

User actions:

Selected:

Exclude

Rejected:

Keep Anyway

Changes must be non-destructive and reversible.

The delivered bounded [image-review contract](GUI_DESIGN.md#prepared-image-decisions-m12c-review)
defines page-local batch scope, independent preview, immediate confirmed saves and
stable-UUID navigation. Keep Anyway is a forced include; Reset to automatic is a
separate operation that removes the manual override and may restore rejection.
The [persistence contract](PROJECT_FORMAT.md#prepared-image-decisions-m12c-review)
defines exact-set identity and immutable effective input. This does not complete all M12c.

The bounded [source-context review](GUI_DESIGN.md#prepared-source-scopes-and-provenance-m12c)
adds source/group display scopes and per-frame provenance. Scopes clear the current
page batch/preview and never change saved participation or decisions. The inspector
distinguishes original source time, historical preparation locator and current saved
locator; unavailable metadata is not inferred from names or gallery positions.

⸻

24. Reconstruction

Reconstruction user goal:

Calculate where the cameras were and reconstruct the spatial relationship between the images.

The Standard UI must not require the user to understand feature extraction or matching algorithms.

⸻

25. Reconstruction start screen

Example:

Step 3 — Reconstruction
Build camera reconstruction
SplatForge will find connections between your images
and calculate camera positions.
1,599 images ready
Reconstruction Quality
○ Fast
● Balanced        Recommended
○ High
○ Maximum
Estimated processing time
≈ 18–25 min
[ Advanced Settings ▾ ]
               [ Start Reconstruction ]

⸻

26. Reconstruction presets

Presets must map to real processing strategies.

Higher presets may use:

* more robust feature methods;
* broader pair search;
* stronger recovery;
* more expensive matching;
* additional reconstruction passes.

Do not claim higher quality without corresponding backend behavior.

⸻

27. Reconstruction Advanced Settings

Potential controls:

Features
[ Automatic ▼ ]
Matching
[ Automatic ▼ ]
Pair strategy
[ Automatic ▼ ]
Camera model
[ Automatic ▼ ]
GPU
RTX 5080
✓ Ready

Advanced algorithm options may include, when actually supported:

* LoMa variants;
* ALIKED;
* LightGlue;
* SIFT;
* Sequential;
* Retrieval;
* Exhaustive;
* Hybrid;
* camera model overrides.

Automatic should normally be the recommended default.

⸻

28. Reconstruction progress

User-facing phases:

Reconstructing Scene
✓ Analyzing cameras
✓ Finding connections between images
● Calculating camera positions
○ Optimizing reconstruction
Camera positions found
742 / 1,599
Elapsed
14 min
Remaining
≈ 7 min
[ Technical Details ]

Technical Details may expose real backend phases.

⸻

29. Reconstruction result

Example:

✓ Reconstruction Complete
RECONSTRUCTION HEALTH
GOOD
1,536 / 1,599 cameras aligned
96.1%
Drone
418 / 418
✓ Excellent
iPhone
207 / 224
⚠ Needs attention
Video frames
911 / 957
✓ Good
1 connected scene
312,482 sparse points
[ Open 3D Reconstruction Viewer ]
63 images not aligned
[ Review Issues ]
[ Export Reconstruction ▾ ]
          [ Continue to Gaussian Splat → ]

⸻

30. Reconstruction Health

Do not use aligned-camera percentage as the only quality indicator.

Health may consider:

* camera alignment;
* image connectivity;
* geometric support;
* component structure;
* scene coverage;
* reconstruction stability;
* other validated metrics.

Possible high-level statuses:

Excellent
Good
Fair
Poor
Needs Attention

Do not pretend to measure qualities the backend cannot actually support.

⸻

31. Disconnected components

If the scene splits:

⚠ Scene reconstructed in 2 separate parts
Drone
418 / 418 aligned
✓ Good
iPhone
203 / 224 aligned
✓ Good
The two groups could not be connected.
[ Try to Connect Automatically ]
[ Review ]

Never expose only:

2 sparse models generated.

The user needs to understand what those components represent.

Show each component separately in the Reconstruction Viewer, with its own coordinate system. Never arrange disconnected components together as though they share a spatial frame. Component switching and summaries are specified in section 59.

Reconstruction Review must clearly identify the component(s) selected for export and training through the existing [ReconstructionSelection / validation flow](PIPELINE.md#reconstruction-component-selection). Viewing a component does not select it for downstream use. Do not introduce a second selection mechanism or silently choose the largest component. If the existing flow selects several components, they remain separate datasets/scenes.

⸻

32. Unaligned images

Example:

178 images could not be positioned.
[ Review Issues ]

Reconstruction Review should support:

Aligned
Not Aligned
All

For an unaligned image:

IMG_3849.jpg
Not aligned
Possible reason:
Low overlap with nearby images
[ Try to Recover ]
[ Exclude ]

Unlike Prepare Review, do not use Keep Anyway for an unregistered camera.

A camera either has a valid pose or it does not.

Unaligned images have no valid reconstructed pose and must never appear as fictitious cameras in 3D. Show their count and Review Issues action in Reconstruction Review (for example, “63 images not aligned”), with the separate Aligned / Not Aligned / All image review above. Show possible causes only when supported by backend evidence.

⸻

33. Automatic recovery

Provide a simple user action:

[ Try to Recover ]

Internally SplatForge may use additional strategies such as:

* wider pair retrieval;
* alternate matching;
* LoMa;
* ALIKED + LightGlue;
* SIFT fallback;
* additional registration attempts.

Standard user should not need to configure this sequence.

Example result:

Recovery Complete
Before
1,421 aligned
After
1,536 aligned
+115 images recovered

⸻

34. 3D Reconstruction Review

A fully integrated Reconstruction Viewer is a required v1 capability and M12f deliverable:

Reconstruction
→ Reconstruction Result / Review
→ 3D Reconstruction Viewer

A 3D review is required before the user proceeds to training. It stays in the context of the specific reconstruction/component, including in fullscreen mode; it does not require a primary Viewer navigation destination.

Default scene layers:

☑ Cameras
☑ Sparse point cloud
☐ World axes

Cameras and sparse points must be independently toggleable. Render cameras as camera frustums / orientation indicators, not only points: position, orientation and the capture's spatial arrangement must be understandable. A connected camera path is optional and requires reliable ordering (section 60).

Use trustworthy reconstructed RGB point colors by default when available; otherwise use a neutral display color without implying a quality metric. World axes are optional. Do not show a large metric ground grid by default: ordinary SfM reconstruction can have arbitrary orientation and scale.

Camera colors should distinguish user-visible source groups by default when reliable source provenance is available. Provide independent source visibility controls, for example:

Sources
☑ Drone photos
☑ iPhone
☑ Video frames

The specific colors are a visual design decision; do not hard-code semantic meaning around one fixed palette. These controls filter camera presentation only. They must not alter calibration groups, camera_group_id, historical processing semantics, reconstruction content or downstream selection. Do not infer sparse-point source ownership from camera groups without trustworthy evidence.

Optional image thumbnails may complement the review. Required component/navigation controls and bounded rendering are specified in section 59.

⸻

35. Camera inspection

Selecting a camera frustum must open the corresponding camera/image details using stable identities. Show the following when supplied by the backend:

Image filename
Source
Device metadata, if available
Status
Resolution
Camera model

Actions:

[ View Image ]
[ Look Through Camera ]
[ Focus ]

Do not invent missing metadata, per-camera quality or failure reasons. Mark unavailable fields/actions honestly; View Image uses the actual available image. Unaligned-image details belong in image review (section 32), not on fictitious 3D cameras.

Look Through Camera is a required target capability: where the viewer architecture supports the camera model and pose conventions correctly, set the virtual view from the reconstructed camera pose. Provide [ Back to Orbit View ] to restore the previous orbit context. Implement and validate this as a separate bounded slice after the base viewer if necessary; do not replace it with an approximate view presented as exact.

⸻

36. Export after Reconstruction

Reconstruction is a first-class export point.

Primary action:

[ Export Reconstruction ▾ ]

User should be able to export a training-ready dataset for external Gaussian Splat / NeRF / reconstruction software.

⸻

37. Reconstruction export workflow

Example:

Export Reconstruction
What do you want to do?
● Train in another application
  Export images and camera reconstruction.
○ Export reconstruction only
○ Custom export

Then:

Target Format
● Generic COLMAP
○ Nerfstudio
○ LichtFeld Studio
○ Other supported target
○ Custom

Only expose application-specific targets that are truly supported.

⸻

38. Generic training dataset export

Default behavior:

Images
● Aligned images only       1,536
○ All prepared images       1,599
Include
☑ Camera poses
☑ Camera intrinsics
☑ Sparse point cloud
☑ Source metadata
Sources
☑ Drone
☑ iPhone
☑ Video
Destination
D:\Exports\Colorado\
Estimated size
7.8 GB
[ Export ]

Aligned images only should normally be the default.

⸻

39. Generic COLMAP compatibility

Support a standard COLMAP-compatible dataset representation where applicable, such as:

Export/
├── images/
└── sparse/
    └── 0/
        ├── cameras.bin
        ├── images.bin
        └── points3D.bin

Text variants may also be supported where needed.

The exact implementation must remain compatible with downstream consumers.

⸻

40. Prepared Data export

After Prepare, users should optionally be able to export:

Prepared Dataset

This may include:

* selected images;
* extracted video frames;
* useful metadata.

Purpose:

Allow users to use a completely different reconstruction pipeline outside SplatForge.

⸻

41. Gaussian Splat

Standard training UI should focus on desired result quality rather than raw training parameters.

Example:

Step 4 — Create Gaussian Splat
Reconstruction ready
1,536 cameras
Health: Good
Quality
○ Fast
● Balanced        Recommended
○ High
○ Maximum
Estimated processing time
≈ 32–45 min
Estimated GPU memory
≈ 12 GB / 16 GB
[ Advanced Settings ▾ ]
               [ Create Gaussian Splat ]

⸻

42. Hardware awareness

Before heavy execution, check relevant resources.

Example:

System Check
GPU
NVIDIA RTX 5080
16 GB VRAM
✓ Ready
Dataset
1,536 images
✓ Ready
Estimated GPU memory
~12.4 GB
✓ Fits available memory

If settings exceed available resources:

⚠ Current settings may exceed GPU memory.
Estimated
18.2 GB
Available
16 GB
[ Adjust Automatically ]

Avoid allowing predictable CUDA OOM failures when the application can detect the risk in advance.

⸻

43. Gaussian Splat training progress

Example:

Creating Gaussian Splat
Training scene
██████████████░░░░ 72%
Current stage
Improving scene detail
Gaussians
2.8M
Elapsed
28 min
Remaining
≈ 11 min
[ Technical Details ▾ ]

Only expose a percentage when it has meaningful backend semantics. Show iteration/step, loss, Gaussian count, elapsed time and ETA when useful trustworthy trainer evidence is available; leave unavailable metrics absent or explicitly unavailable.

⸻

44. Training feedback

v1 training feedback uses status, progress and the numerical metrics described in section 43. Spatial live Gaussian rendering and checkpoint spatial preview are not required in v1 or M12; they are deferred with the built-in Gaussian Splat Viewer (section 60.1).

Checkpoint availability and compatible resume may still be shown through the existing backend contracts. Cancellation remains available through the normal operation flow; neither progress monitoring nor cancellation requires spatial preview.

⸻

45. Gaussian Splat result

Example:

✓ Gaussian Splat Ready
Training preset
High
Gaussians
3.4M
[ Export Result ]
[ Open Output Folder ]

View the exported result in your preferred Gaussian Splat viewer.

The preset and metrics must reflect the actual run; this example does not establish a new backend preset or assert visual quality. Provide external browser/local viewer handoff through the exported result and its output folder. Do not promise built-in visualization or silently upload local output to a browser service.

⸻

46. Gaussian Splat review

v1 result review retains:

* training status and available training metrics;
* run/history and result provenance;
* export and Open Output Folder;
* external browser/local viewer handoff;
* retry/retrain through the existing workflow, preserving previous successful results.

Internal Gaussian spatial review, splat + sparse overlays, Gaussian problem-area visualization, Gaussian rendering and checkpoint spatial preview are outside required M12/v1 scope. They belong to the future built-in Gaussian Splat Viewer (section 60.1). Do not infer spatial quality from training completion or expose diagnostics as authoritative without reliable evidence.

⸻

47. Gaussian Splat Advanced Settings

Possible controls:

Training method
[ Automatic ]
Resolution
[ Full ]
Iterations
[ 30,000 ]
Spherical Harmonics
[ 3 ]
Densification
[ Automatic ]
Pruning
[ Automatic ]
Max Gaussians
[ Automatic ]
GPU memory limit
[ Auto ]

Actual available options depend on supported trainers.

Automatic remains the default.

⸻

48. Time estimation

Every computationally expensive operation must expose estimated cost before execution.

At minimum:

Estimated processing time
≈ 18–25 min

Where meaningful, also show:

Estimated disk usage
Estimated VRAM requirement

⸻

49. ETA during execution

Once processing begins:

Elapsed
14 min
Remaining
≈ 7 min
Expected finish
≈ 15:42

ETA should update using real observed runtime performance.

Do not allow fake progress bars that stay at 99% for long periods because the underlying stage cannot actually be estimated.

When ETA confidence is low, communicate uncertainty.

Example:

Estimated remaining time
≈ 15–30 min
Estimate will improve as processing continues.

⸻

50. ETA learning

Where practical, estimates should consider:

* CPU;
* GPU;
* RAM;
* disk;
* image count;
* resolution;
* video length;
* candidate pair count;
* selected preset;
* selected algorithms;
* previous runs on this machine.

Historical local performance may be used to improve estimates.

Example:

≈ 18–24 min
Based on previous runs on this computer.

⸻

51. Project Overview

Once a project exists, Overview becomes its main landing screen.

Example:

Colorado Cabin
────────────────────────────────
Project Status
READY FOR TRAINING
Sources
3 sources
✓ Ready
Prepared Data
1,599 images
✓ Ready
Reconstruction
1,536 / 1,599 aligned
✓ Good
Gaussian Splat
Not created
Recommended Next Step
Create Gaussian Splat
Estimated time
≈ 32–45 min
[ Create Gaussian Splat ]

⸻

52. Overview priorities

The user should understand within a few seconds:

* current project state;
* completed stages;
* warnings;
* next recommended action;
* current result quality.

Avoid cluttering Overview with diagnostic graphs and technical metrics.

⸻

53. Repeat opening / Welcome Back

When opening an existing project:

Colorado Cabin
Welcome back.
Reconstruction is ready.
1,536 / 1,599 cameras aligned
Health: Good
Next
Create Gaussian Splat
Estimated time
≈ 32–45 min
[ Continue ]

Do not automatically resume or start heavy processing without user action.

⸻

54. Interrupted work

If an operation was interrupted:

Reconstruction was interrupted.
Progress was preserved where possible.
[ Resume ]
[ Restart Stage ]

Only show Resume when true backend resume is supported.

If exact resume is impossible:

Reconstruction was interrupted.
Reusable completed work was preserved,
but this stage cannot resume from the exact point.
[ Restart Stage ]

Never misrepresent restart-from-cache as exact resume.

⸻

55. Reusing completed work

When restarting:

Existing work will be reused:
✓ Camera analysis
✓ Feature extraction
○ Matching
○ Camera reconstruction
Estimated remaining work
≈ 12–18 min
[ Restart ]

Caching should translate into visible user benefit.

⸻

56. Upstream changes and stale results

If Prepared Data changes after a Reconstruction has been created:

Reconstruction
⚠ Out of Date
The prepared image set changed after this
reconstruction was created.
[ Rebuild Reconstruction ]
[ Keep Current Result ]

Do not delete the old result.

If a Gaussian Splat depends on that Reconstruction:

Gaussian Splat
⚠ Based on an older reconstruction

The system should internally track dependency lineage.

⸻

57. Result history

Successful runs should not overwrite one another.

Example Reconstruction history:

Reconstruction Runs
#3  High
1,536 aligned
Good
26 min
ACTIVE
#2  Balanced
1,498 aligned
Good
17 min
#1  Fast
1,372 aligned
Fair
8 min

Possible actions:

Compare
Make Active
Export
Delete

⸻

58. Gaussian Splat history

Likewise:

Gaussian Splat Runs
High
3.4M Gaussians
42 min
ACTIVE
Balanced
2.1M
23 min
Fast
1.3M
11 min

Never silently destroy an older successful training result when retraining.

⸻

59. Reconstruction Viewer

The v1 viewer is part of Reconstruction Result / Review (section 34), with clear reconstruction/run and component context. It is a bounded sparse/camera viewer, not a general-purpose Blender/CloudCompare workspace.

When multiple components exist, provide a selector, for example:

Component
● Main component
○ Component 2
○ Component 3

Show only the viewed component in its own coordinate system. “Main component” is an illustrative user-visible label, not a largest-component policy or an automatic downstream choice. Each component must expose camera count and sparse point count, plus source breakdown when trustworthy and validation/health summary when available. Unknown evidence stays unavailable. Keep the component selected for export/training visible through the existing selection flow (section 31); switching the viewed component changes presentation only.

Required navigation:

* Orbit;
* Pan;
* Zoom;
* Select camera;
* Fit Scene;
* Reset View;
* Fullscreen.

Camera picking must resolve the stable camera/view identity and open section 35's details/actions. Preserve reconstruction/component identity and layer/source visibility in fullscreen and when returning to review. Look Through Camera and Back to Orbit View are the required target capability described in section 35.

Keep secondary/advanced display controls compact:

* Camera size;
* Point size;
* Camera opacity.

These controls affect presentation only. Optional World axes and the default Cameras / Sparse point cloud layers follow section 34; no default metric ground grid is implied.

Rendering and loading must remain bounded and responsive. If display data is sampled or capped, disclose that limitation and retain correct IDs, layer/source membership and camera picking. Component counts describe the reconstruction, not just the displayed sample. Existing PointPreview is a prototype/reuse candidate, not proof that these requirements are met; the implementation must support the necessary IDs, layers and picking.

⸻

60. Reconstruction Viewer enhancements

The following are useful additions, not blockers for the base Reconstruction Viewer:

☐ Camera path

May show a sequential capture trajectory only when ordering is reliable. Never connect cameras using an unverified order.

Show connections

An advanced diagnostic may show matched/reliable neighbours of the selected camera when supported by trustworthy evidence. It is outside the MVP viewer.

Future camera color modes:

* By source (the v1 default when source groups are known);
* Uniform;
* Registration quality;
* Reprojection error.

A color-mode chooser is an enhancement. Registration quality and Reprojection error require reliable per-camera metrics; never manufacture them from aggregate reconstruction health.

60.1 Future — Built-in Gaussian Splat Viewer

A built-in Gaussian renderer/viewer is a separate future capability/milestone after M12, with no milestone number assigned here. It does not block M12 completion or the first production-ready release. v1 users inspect exported Gaussian Splats in an external browser/local viewer.

Future scope may include internal Gaussian spatial review, splat + sparse overlays, reliable problem-area visualization, spatial live training preview and checkpoint spatial preview. A universal Viewer destination may be added later if useful. Do not choose renderer technology now or introduce CUDA ownership into the Qt process for this future capability.

⸻

61. Exports page

Export history should be visible.

Example:

Exports
────────────────────────
Colorado_Nerfstudio
Training Dataset
COLMAP
7.8 GB
Oct 26
[ Open Folder ]
[ Export Again ]
Colorado_High.ply
Gaussian Splat
3.6 GB
Oct 26
[ Open Folder ]
[ Export Again ]
[ New Export ]

Users should not have to remember where previous exports were written.

⸻

62. New Export

Generic workflow:

Export From
○ Prepared Data
● Reconstruction
○ Gaussian Splat

The available export types then change according to selected stage.

This preserves a unified export UX while retaining stage-specific meaning.

⸻

63. Errors

Errors should always answer:

1. What happened?
2. What does it affect?
3. What should the user do next?

Do not make raw tracebacks the primary error UI.

⸻

64. GPU memory error

Instead of:

CUDA_ERROR_OUT_OF_MEMORY

show:

Not Enough GPU Memory
This operation is expected to require
approximately 18 GB of GPU memory.
Your GPU has
16 GB.
Recommended action:
Reduce memory usage automatically.
[ Adjust Settings & Retry ]
[ Technical Details ]

⸻

65. Disk space

Before execution:

⚠ Not Enough Disk Space
Required
~42 GB
Available
19 GB
[ Clean Project Cache ]
[ Change Cache Location ]

Heavy operation should not start when failure is predictable.

⸻

66. Runtime dependencies

If a required processing component is unavailable:

Reconstruction Engine Unavailable
A required processing component is missing
or not configured correctly.
[ Set Up Automatically ]
[ Configure Manually ]
[ Technical Details ]

Where possible, SplatForge should own and validate its runtime dependencies rather than requiring users to manually edit PATH.

⸻

67. Cancellation

Cancelling should not imply destructive deletion.

Example:

Stop Reconstruction?
Completed reusable work will be kept.
You can continue from the saved project state later.
[ Keep Running ]
[ Stop ]

After stopping:

Reconstruction stopped.
Reusable work was preserved.
[ Continue Later ]

⸻

68. Concurrent edits

If the user modifies an upstream dataset while a downstream job is running:

Reconstruction is currently using this dataset.
Changing the selected images will create a new dataset version
and will not modify the running reconstruction.
[ Create New Version ]
[ Cancel ]

Do not mutate inputs underneath a running job.

⸻

69. Deleting dependent results

If a result is referenced:

Delete Reconstruction #2?
This result is used by:
Gaussian Splat #3
Nerfstudio Export
Deleting it may make these results
non-reproducible.
[ Cancel ]
[ Delete Anyway ]

Dependency relationships must be respected.

⸻

70. Project Settings

Project Settings should contain project-level behavior, not reconstruction algorithm configuration.

Example:

Project Settings
Project name
Colorado Cabin
Project location
D:\SplatForge Projects\Colorado Cabin
Cache location
Project Default
Default export location
D:\Exports\
Interface
Show advanced controls
OFF

⸻

71. Storage Management

Provide understandable storage breakdown:

Project Storage
Original media
Referenced externally
126 GB
Generated project data
63 GB
Prepared frames
14 GB
Reconstructions
8 GB
Gaussian Splats
23 GB
Temporary cache
18 GB
[ Clean Temporary Files ]

Clearly distinguish:

* safe to remove;
* required by active result;
* externally referenced originals.

Never allow a cache cleanup action to silently destroy required active project data.

⸻

72. Standard vs Advanced

Do not create two separate products.

Standard mode is the normal UI.

Advanced controls may be opened locally using:

Advanced Settings ▾

Project Settings may include:

Show advanced controls
OFF / ON

When ON, expert controls may be easier to access but should not destroy the overall information hierarchy.

⸻

73. Notifications

Long operations should generate desktop notifications when appropriate.

Success:

SplatForge
Reconstruction complete
1,536 / 1,599 images aligned
Health: Good
[ Open Result ]

Needs attention:

SplatForge
Reconstruction needs attention
Scene was split into 2 components.
[ Review ]

⸻

74. Global running-task indicator

The user should be able to navigate within the project while long work is running.

Example global task strip:

Reconstruction
62% · ~9 min remaining
[ View ]
[ Stop ]

The active workspace tab may also show:

Reconstruction
● 62%

Do not force the user to stare at a blocking modal progress dialog for long operations.

⸻

75. Project status model

Overview should expose one clear project status.

Examples:

READY TO PREPARE
PREPARING DATA
READY FOR RECONSTRUCTION
RECONSTRUCTING
RECONSTRUCTION NEEDS ATTENTION
READY FOR TRAINING
TRAINING
GAUSSIAN SPLAT READY

Avoid backend state codes in user-facing UI.

⸻

76. Recommended next action

Whenever possible, Overview should show one recommended action.

Examples:

Recommended next step
Prepare your source data
Estimated time
≈ 6–9 min
[ Prepare Data ]

or:

Recommended next step
Review reconstruction issues
63 images were not aligned.
[ Review Issues ]

⸻

77. UI density

The application is professional but should not feel like a debug console.

Avoid putting all of the following simultaneously on Overview:

* GPU utilization;
* VRAM chart;
* CPU chart;
* logs;
* feature counts;
* pair counts;
* reprojection error distribution;
* camera-model tables;
* backend artifact IDs.

Such information belongs in Advanced / Diagnostics.

⸻

78. Visual hierarchy

Primary visual hierarchy:

1. Current stage / project status.
2. Main result or problem.
3. Estimated cost.
4. Primary action.
5. Secondary review/export options.
6. Technical details.

Do not give equal visual prominence to all controls.

⸻

79. Button hierarchy

Each primary screen should normally have one dominant primary CTA.

Examples:

Create Project
Continue
Prepare Data
Start Reconstruction
Try to Recover
Create Gaussian Splat
Export

Secondary actions should be visually quieter.

Avoid rows of six equally emphasized buttons.

⸻

80. Warnings

Use warnings for actionable problems, not for every technical irregularity.

Good:

⚠ 63 images could not be aligned.

Unhelpful:

⚠ Camera model OPENCV detected.

Do not alarm the user over normal internal behavior.

⸻

81. Validation before execution

Heavy actions should perform a lightweight preflight where possible.

Check relevant:

* source availability;
* free disk space;
* required runtime;
* GPU availability;
* VRAM estimate;
* valid reconstruction inputs.

If a predictable blocking problem exists, show it before execution.

⸻

82. Empty states

Every page must have a useful empty state.

Example Reconstruction before Prepare exists:

Reconstruction
Prepare your image dataset before building a reconstruction.
[ Go to Prepare ]

Do not show disabled empty technical panels without explanation.

⸻

83. No dead-end states

Every warning/error screen should provide an obvious next step.

Examples:

Locate Folder
Adjust Automatically
Retry
Review Issues
Return to Prepare
Change Cache Location

Never present only:

Operation failed.

⸻

84. Architecture/UI separation

Backend may remain highly modular and artifact-driven.

UI should present stable user concepts:

Sources
Prepared Data
Reconstruction
Gaussian Splat
Exports

Backend milestones and artifact types must not dictate navigation structure.

⸻

85. Minimum stage outputs

Conceptually:

Sources output:

Source media references and metadata.

Prepare output:

Clean selected image dataset.

Reconstruction output:

Registered cameras + intrinsics + poses + sparse geometry.

Gaussian Splat output:

Trainable/trained Gaussian representation.

These outputs should behave as durable project results.

⸻

86. Reproducibility

For every run, retain enough provenance to understand:

* source dataset version;
* preset;
* advanced overrides;
* backend method/version where relevant;
* runtime result;
* duration;
* status.

Normal UI may show only simplified information.

Technical details may expose full provenance.

⸻

87. Performance philosophy

The application should feel responsive even while heavy tasks run.

UI navigation, review, settings, and viewer interactions should not unnecessarily block because a backend job is executing.

Heavy processing should be isolated from the main UI thread.

⸻

88. First release priority

Do not delay the entire product trying to implement every future diagnostic.

Prioritize excellent implementation of:

1. Create Project.
2. Sources.
3. Prepare.
4. Image Review.
5. Reconstruction.
6. Reconstruction Review.
7. ETA / progress.
8. Reconstruction export.
9. Gaussian Splat training, metrics, export and external viewer handoff.
10. Project Overview.
11. Resume/restart/recovery states.
12. Reconstruction Viewer within Reconstruction Review (M12f).
13. Exports.
14. Project Settings.
15. Clear error handling.

Advanced automated diagnostics may improve incrementally. Built-in Gaussian visualization is outside the first production release.

88.1 M12 implementation direction

The [M12 sub-milestone plan](../ROADMAP.md#m12--desktop-gui) defines M12a–M12j. M12f delivers Reconstruction Review + Sparse 3D Viewer; M12h delivers Gaussian Splat Training UX without a built-in Gaussian viewer. The future built-in Gaussian Splat Viewer is a separate milestone after M12 and is not a completion gate for this plan.

⸻

89. UX acceptance criteria

Before considering the primary UX complete, verify the following scenarios.

Scenario A — New user with photos

User can:

Create Project
→ Add Photos
→ Continue
→ Prepare
→ Review rejected images
→ Reconstruction
→ Review cameras
→ Export or train

without needing to understand technical reconstruction terminology.

Scenario B — Mixed drone + phone + video

SplatForge:

* detects sources;
* groups devices;
* extracts video frames;
* reports quality separately by source;
* preserves source identity through reconstruction;
* allows source-based filtering/export.

Scenario C — Poor images

Prepare identifies rejected images.

User can inspect:

Selected / Rejected / All

and override decisions.

Scenario D — Split reconstruction

User receives a clear explanation that the scene is split into components and can attempt recovery. They can view each component independently, inspect counts and available source/health evidence, and identify the component(s) selected for export/training through ReconstructionSelection. Viewing another component never merges coordinate frames or changes downstream selection.

Scenario E — External training

User can stop after Reconstruction and export a training-ready dataset without running SplatForge Gaussian training.

Scenario F — Interrupted processing

Application restart does not lose completed project work.

User is offered true Resume only when supported, otherwise Restart using reusable cached work.

Scenario G — Moved source files

User can relink a folder instead of locating every file individually.

Scenario H — Insufficient VRAM

User receives a human-readable warning and automatic remediation instead of raw CUDA failure.

Scenario I — Upstream dataset modified

Existing Reconstruction and Gaussian Splat remain preserved but are marked out-of-date.

Scenario J — Repeat experimentation

User may create multiple Reconstruction / Gaussian Splat runs and select which result is active.

Scenario K — Reconstruction Viewer

User can independently toggle cameras and sparse points, inspect camera orientation and spatial arrangement, filter visible cameras by known source group, pick a camera and inspect available metadata/image, and navigate with Orbit / Pan / Zoom / Focus / Fit Scene / Reset View / Fullscreen. Trustworthy point RGB is used by default. Unaligned images remain in image review. Look Through Camera / Back to Orbit View must use the reconstructed pose correctly; this target may be delivered as the bounded follow-up described in section 35.

Scenario L — Gaussian result handoff

After training, the user sees status and available metrics, retains run/history and provenance, exports the result, opens its output folder and inspects it in an external browser/local viewer. Retry/retrain preserves successful results. No built-in Gaussian renderer or spatial training/checkpoint preview is needed to complete this v1 workflow.

⸻

90. Final intended experience

The ideal SplatForge experience should feel like:

I add my data.
SplatForge understands what it is.
It tells me what it will do.
It tells me approximately how long it will take.
It cleans and prepares the data.
I can review what it rejected.
It reconstructs the cameras.
It tells me whether the reconstruction is actually healthy.
If something failed, it helps me fix it.
I can inspect reconstructed cameras and sparse geometry in 3D.
I can export at any important stage.
I can use another trainer if I want.
I can train a Gaussian Splat inside SplatForge if I want.
I can export it and view it in my preferred external Gaussian Splat viewer.
My previous successful results are never silently destroyed.
If I close the application, I can continue later.
If something goes wrong, the application explains what happened and what I should do next.

That is the target UX.

⸻

91. Implementation instruction for Codex

When implementing or revising the SplatForge UI:

* preserve existing backend contracts unless UI requirements genuinely require an architectural extension;
* do not bypass the artifact/cache/recovery architecture merely to simplify the frontend;
* build the UI around stable user-facing concepts defined in this document;
* reuse backend state instead of duplicating processing logic in the frontend;
* keep Standard UI simple;
* retain advanced controls where expert access is useful;
* ensure every long-running operation supports visible progress and ETA where available;
* ensure stage results survive navigation and application restart;
* ensure previous successful runs are preserved;
* ensure exports are treated as first-class workflow actions;
* do not introduce UI controls that imply unsupported functionality;
* do not expose internal milestone names or implementation objects as normal user-facing terminology.

When the current implementation conflicts with this UX specification, identify the conflict explicitly before changing backend behavior.

Prefer incremental implementation that preserves working behavior over large uncontrolled UI rewrites.

The resulting application should be understandable to a first-time user while remaining powerful enough for professional mixed-camera photogrammetry and Gaussian Splatting workflows.

⸻

92. Immediate instruction for the current audit

Historical initial specification-capture instructions (later authorized updates have their own scope):

1. Create:
    docs/UX_UI_SPEC.md
2. Save this complete specification there without semantic changes.
3. Do not modify production code.
4. Do not stage or commit anything.
5. Confirm that the file now exists at:
    C:\Dev\SplatForge\docs\UX_UI_SPEC.md
6. Show the relevant git status --short entry for the new file.
7. Only after that, continue the full audit requested in the previous prompt.
8. Treat this document as the primary UX/UI source of truth.
9. Re-check any preliminary audit conclusions against this complete specification.
10. Explicitly flag conflicts between this specification and existing documented/backend contracts rather than silently resolving them.


92.1 Audit scope update — 2026-10-27

Reclassify the earlier “Full Gaussian viewer — MISSING” conclusion as a future capability, not a blocker or required M12 backend gap. Internal Gaussian rendering and spatial training/result/checkpoint review are deferred to section 60.1.

Conversely, the bounded sparse/camera Reconstruction Viewer is a required M12f deliverable. Assess existing PointPreview as a prototype/reuse candidate against sections 34–35 and 59, including stable IDs, layers, source presentation filtering, camera picking and separate component context. Its existence alone does not close this gap. Preserve the existing ReconstructionSelection / validation flow and processing semantics; this scope update does not claim viewer implementation is complete.
