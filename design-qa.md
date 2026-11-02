# Materials workspace visual QA

2026-10-28 clarification: this is the previous agent's bounded implementation
report. The user subsequently said the visual result is unsatisfactory and requested
reference alignment before any further code. It is not current visual approval;
the full default verification was interrupted and remains incomplete. The new
[reference-led specification](docs/GUI_DESIGN.md#reference-led-interface-contract--2026-10-28)
and [reference catalog](docs/design/references/README.md) own the next target.

Historical agent result: passed for the bounded implemented workspace. User UX acceptance is
pending; this does not accept M12b3 or the complete future reference toolset.

Source: the user-selected media-editor attachment in this chat. Current layout and
states are owned by [GUI design](docs/GUI_DESIGN.md#selected-materials-workspace--2026-10-28);
scope/evidence are recorded in the [active plan](docs/plans/active/2026-10-28-materials-workspace.md).

Reviewed real exposed Windows QQuickWindow captures at 1440×900 and 1024×640,
Dark/Light, actual DPR 1.0 and 1.5. The local manifests and original captures are
under ignored `sample_data/ui-review/materials-1/` and `materials-1.5/`.
Overview sheets are assembled only from those actual captures; no generated UI
image substitutes for running the application. Input photos are existing local
Ignatius originals, read-only; the short H.264 video and corrupt files are explicitly
named owned review fixtures. No training/reconstruction is started by capture.

The reference and rendered app were compared together. The implemented composition
keeps a compact left catalog, dominant image/video, contextual right properties,
bottom transport, neutral graphite, blue selection and thin separators. Exact future
mask/trim controls, 360 projection, tracking and timeline intervals are intentionally
absent. This is a layout/interaction comparison, not a pixel comparison of the
reference apartment/masks against a different source photo.

Fixed during review: Grid minimum-width overflow hid All under the viewer; catalog
row action hit areas overlapped normal selection; expanded Grid left unused width;
unchanged video-source reassignment reset playback; review shortcuts interfered with
modal group editing; automatic metadata failures interrupted review; sparse preview
shutdown could disconnect an already destroyed context. Bright blue Dark controls
use graphite foreground for readable contrast; Light retains white on deep blue.

Photo Fit, loaded-pixel zoom limit and mouse pan were exercised. Video Play/Pause
and seek by clicking the actual slider were exercised on installed Windows Qt,
including reported position/duration and invalid codec/file presentation. Batch,
empty, photo error, video error and expanded Grid were reviewed in both themes.
Both themes retain useful media area at the minimum window; secondary processing
forms remain accessible through the shell and their own scrolling.

No unresolved P0/P1/P2 visual defect was identified in this bounded slice. Remaining
scope limitations: review raster is capped at 4096px/64MP input, only ordinary H.264
MP4 playback was validated here, video poster generation and audio coverage are not
claimed, and the existing processing screens are connected rather than redesigned.

## Materials / Trim — 2026-10-28

Bounded implementation review, not user acceptance. The saved source is
`docs/design/references/04-video-trim.png` (1487×1058). Actual exposed Qt captures
are in `sample_data/trim-ui/native-reviewed/`: 1440×900 and 1024×640, DPR 1.0,
Dark/Light. Native title-bar flags are retained; grabWindow captures client content.
The reference imitates app chrome and uses different media/aspect ratio, so comparison
normalizes width and does not claim pixel-identical images or Windows title bars.

Evidence opened and compared: the final labelled side-by-side
`sample_data/trim-ui/reference-comparison-final.png`, seven-capture overview
`native-reviewed-overview.png`, full selected-range Dark capture and minimum Light
capture. The preceding full-size whole/two-range/Light/compact-inspector captures
were also inspected. The final layout is unchanged by the last keyboard modifier guard.
The filmstrip contains actual FFmpeg frames of the explicitly labelled six-second
still-photo H.264 fixture; these are neither random images nor a moving-video proof.
The separate real VFR integration checks changing colored frames and source origin.

Findings corrected during this slice:

- [P1] Window shortcuts took Space from a focused checkbox. Normal Qt key bubbling
  now gives controls first use; explicit Materials focus restores Review arrows after
  Settings. Final native and regression checks cover these interactions.
- [P2] Narrow/fallback-font inspector content could grow outside its pane; wrapped
  action grids and bounded interval-row content fix overflow and size loops.
- [P2] Early captures caught thumbnails still loading after resize and a stale hover
  tooltip. Final captures wait for actual bounded requests and move the pointer to
  media. No fabricated filmstrip or screenshot was substituted.

Required fidelity surfaces:

- Typography: existing Segoe UI/Variable, 16px panel headings, restrained 14px controls
  and smaller ruler/captions; readable full-size fields and interval rows in both themes.
- Spacing/layout: existing 280px catalog/300px inspector, dominant center media,
  compact 48px mode header and lower transport/timeline. The timeline stays below the
  center viewer, preserving the accepted independent catalog rather than spanning
  beneath it as in the mockup. The minimum inspector uses the existing scrollable
  overlay; persistent Projects/import/panel controls remain reachable.
- Tokens: shared neutral surfaces, thin separators, blue selection/playhead/used
  bounds and hatched gaps. Light retains contrast without copying reference gradients.
- Images: real read-only media, aspect-preserving Fit and bounded real frame samples.
  Black margins follow the source aspect ratio. No masks, 360 views or fake media.
- Copy: Include range/Exclude range/Remove from used/Use entire clip state the result;
  exact source-second fields differ intentionally from rounded mockup timecodes.
  Entire/limited/empty usage is explicit; source Exclude stays independent.

No unresolved P0/P1/P2 visual defect was found in this bounded comparison. Optional
follow-up: moving VFR/alternate codec/audio, high DPI, long timelines and compact
keyboard/resize stress remain Sol's expanded review, not claimed visual acceptance.

final result: passed
