# SplatForge desktop design

The M12 desktop uses PySide6 6.12.0 / Qt Quick 6.12. The client area belongs to
SplatForge; the operating system owns the native title bar, resizing and window
management. This migration does not start M13 or introduce Gaussian rasterization.

## Presentation architecture

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
Atomic project Save reserves the controller mutation slot, drains already owned reads
and pauses metadata polling until replacement finishes. This avoids Windows sharing
violations caused by the UI's own readers. Processing progress/cancellation keeps its
reserved pool; no persistence retry or backend contract is introduced.

`PresentationModel` extends the stable-UUID table model with `recordId`, `record`
and `cellText` roles. ListView, GridView and TableView instantiate bounded visible
delegates. Run/artifact history retains the existing 2000-row index bound. Pages load
on first visit and retain their contexts, avoiding destruction of incubating delegates
during navigation. Hidden pages do not render. The inspection projection is cached
until its notification signal, so bindings do not repeatedly serialize metadata.

Images use the existing bounded thumbnail workers and a QQuickImageProvider. There
is no video decoder in QML. Gallery delegates distinguish loading, ready and unavailable
previews. Source verification explains metadata reuse without calling it a fresh hash.
The first preview path is a QQuickPaintedItem using the
existing bounds: 20,000 point centers and 2,000 camera centers. Orbit, zoom and reset
change only presentation. The label always says **Point-center preview — not final
Gaussian rasterization**. Sparse preview retains the first-component-only label.

## Theme and typography

`qml/theme/Theme.qml` is the central singleton for both designed palettes. System
resolves through Qt's system color scheme. Dark is the flagship; Light uses pale blue
gray surroundings, white cards, dark text and a restrained blue selection surface.
Do not invert individual pages or introduce page-specific color literals.

| Token | Dark | Light |
| --- | --- | --- |
| Background | `#0B0F14` | Pale blue gray |
| Sidebar | `#0E131A` | Slightly deeper blue gray |
| Surface | `#131922` | White |
| Raised / hover | `#18212B` / `#1E2935` | Subtle pale surfaces |
| Primary text | `#F2F5F8` | Deep graphite |
| Secondary / tertiary | `#A7B1BC` / `#707C89` | Slate blue grays |
| Accent | `#429BFF` | Stronger blue for white surfaces |
| Success / warning / danger | Green / amber / muted red | Darker readable counterparts |

The singleton contains exact values; the table describes design intent. Python-painted
viewport colors live together in `point_preview.py`, with corresponding dark/light
values. No processing value depends on these tokens.

Use Segoe UI Variable when installed, otherwise Segoe UI. Project/page titles are
24–28 px, sections 18 px, body 14 px, secondary 12 px and captions 11 px. The landing
hero has one 38 px display treatment. Use Consolas only for paths, IDs and exact
evidence. The spacing rhythm is 4/8/12/16/20/24/32/40; controls are 36 px high,
shell bar 64 px, card padding 24 px, restrained radii 6–12 px.

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
regular 20 px assets, retrieved 2026-10-24. The geometric SplatForge brand mark is
app-owned. Control icons use Qt's theme-aware tint, without an icon runtime dependency.

Motion is brief (160 ms) and limited to control state/progress. No blur, animated
gradient or decorative continuous animation is used. Indeterminate progress animates
only while active. Automatic Windows reduced-motion preference mapping is not claimed.

## Guided and Advanced

Guided prioritizes task meaning: project dashboard, media, explicit reconstruction
method cards, component comparison, dataset evidence, trainer readiness and outputs.
Advanced exposes exact settings, project intent, IDs, history, lineage, storage and
diagnostic evidence. Both use the same controller and publications.

Home derives its recommendation from indexed workflow evidence and shows the latest
published output. Historical completion is not a promise of compatibility with newly
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

## Accessibility and desktop layout

Keep standard focus/keyboard semantics and meaningful Accessible names/descriptions.
Tab follows visual order; Enter/Space activates controls. Ctrl+N/O/S, F5 and Ctrl+,
are the project/settings shortcuts. Point preview supports arrows, +/− and R.
Use text with status color and preserve visible focus outlines.

QtQuick.Layouts owns sizing. At widths below 1380 px the sidebar becomes icon-only
with tooltips. Cards stack where necessary and long pages scroll vertically. History
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
