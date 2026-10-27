"""Small, deterministic presentation projections; backend values stay in Python."""

import json
import traceback
from datetime import UTC, datetime
from functools import wraps

from splatforge.application.desktop import IndexRow
from splatforge_gui.tasks import TaskError


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return json.loads(json.dumps(value, default=str))


def render(value) -> str:
    return json.dumps(plain(value), indent=2, ensure_ascii=False)


def guarded(action):
    @wraps(action)
    def call(self, *args, **kwargs):
        try:
            return action(self, *args, **kwargs)
        except Exception as exc:
            self.controller.error.emit(
                TaskError(str(exc), type(exc).__name__, traceback.format_exc(), action.__name__)
            )

    return call


def project_name_error(name: str) -> str:
    """Validate one Windows directory component without touching the filesystem."""
    if not name:
        return "Enter a project name."
    if name in {".", ".."}:
        return "The project name cannot be . or .."
    if any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name):
        return 'Use a single folder name without < > : " / \\ | ? * or control characters.'
    if name.endswith((".", " ")):
        return "Project names cannot end with a dot or a space."
    base = name.split(".", 1)[0].rstrip(" ").upper()
    if base in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or (
        len(base) == 4 and base[:3] in {"COM", "LPT"} and base[3] in "123456789¹²³"
    ):
        return "This name is reserved by Windows. Choose another project name."
    if len(name.encode("utf-16-le", errors="surrogatepass")) > 510:
        return "Project names must be at most 255 UTF-16 characters long."
    return ""


def duration(seconds) -> str:
    if seconds is None:
        return "Not available"
    total = max(0, int(seconds))
    return f"{total // 3600:02}:{total // 60 % 60:02}:{total % 60:02}"


def timestamp(value) -> str:
    if not value:
        return "Date unavailable"
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            return str(value)
        return parsed.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return str(value)


def verification_label(value: str) -> str:
    """Format the facade's verified evidence without upgrading its assurance."""
    parts = value.split(" · ")
    if len(parts) != 3:
        return value
    outcome, assurance, checked = parts
    description = {
        "metadata_unchanged": "Metadata unchanged; no fresh content hash",
        "content_verified": "Content hash verified",
        "unavailable": "Verification evidence unavailable",
    }.get(assurance, assurance.replace("_", " "))
    return f"{outcome.replace('_', ' ').capitalize()} · {description} · {timestamp(checked)}"


def source_availability(value: str) -> str:
    """Describe recorded availability, without claiming a current filesystem check."""
    parts = value.split(" · ")
    if len(parts) != 3:
        return "Not checked recently"
    return {
        "unchanged": "Available at last check",
        "missing": "Missing at last check",
        "changed": "File changed",
    }.get(parts[0], "Could not check")


def source_description(values: dict) -> str:
    """Project stored metadata only; unknown duration stays absent."""
    parts = [str(values["type"]).capitalize(), values.get("dimensions", "")]
    if values["type"] == "video" and values.get("duration") is not None:
        try:
            seconds = float(values["duration"])
            if 0 <= seconds < float("inf"):
                parts.append(duration(seconds).removeprefix("00:"))
        except (ValueError, TypeError, OverflowError):
            pass
    return " · ".join(p for p in parts if p)


def source_summary(rows: tuple[IndexRow, ...]) -> dict:
    """Cheap inventory projection, with no source reads or verification side effects."""
    photos = sum(r.values["type"] == "photo" for r in rows)
    videos = sum(r.values["type"] == "video" for r in rows)
    statuses = [source_availability(r.values["verification"]) for r in rows]
    missing = statuses.count("Missing at last check")
    unknown = statuses.count("Not checked recently")
    issues = sum(s in {"File changed", "Could not check"} for s in statuses)
    if missing:
        noun = "source file was" if missing == 1 else "source files were"
        message = f"{missing} {noun} missing at last check."
    elif issues:
        noun = "source file needs" if issues == 1 else "source files need"
        message = f"{issues} {noun} attention. See their recorded check in Details."
    elif not statuses or unknown:
        message = "File availability has not been checked recently."
    else:
        message = "All source files were available at their last check."
    return {"photos": photos, "videos": videos, "checkMessage": message}


def progress_state(controller, metrics: dict) -> dict:
    active = controller.active
    result = {
        "visible": bool(active) or controller.mutating,
        "title": {"ingest": "Adding source files…", "verify": "Checking source files…"}.get(
            controller.operation, (controller.operation or "Processing").replace("_", " ").title()
        ),
        "phase": "Waiting for application progress",
        "fraction": -1.0,
        "work": "",
        "elapsed": "",
        "eta": "",
        "cancelling": controller.ingest_cancel.is_set() and bool(active or controller.mutating),
        "canCancel": controller.can_cancel,
        "metrics": [],
        "runId": "",
    }
    if not active:
        return result
    run = active[0]
    result.update(runId=str(run.run_id), elapsed=duration(run.elapsed_seconds))
    stage = next(
        (s for s in run.stages if s.status in {"running", "stopping", "failed", "interrupted"}),
        run.stages[-1] if run.stages else None,
    )
    if stage:
        result.update(
            title=stage.work.stage_id.replace("_", " ").title(),
            phase=(stage.phase_id or run.status).replace("_", " "),
            work=f"{stage.completed:g} / "
            + (f"{stage.work.total:g}" if stage.work.total is not None else "?")
            + f" {stage.work.unit}",
            eta=duration(stage.eta.likely_seconds) if stage.eta.likely_seconds is not None else "",
            fraction=stage.fraction
            if stage.fraction is not None
            and stage.status in {"running", "cached", "succeeded", "skipped"}
            else -1.0,
        )
    result["metrics"] = [
        {"name": m["name"], "value": str(m["value"])}
        for observation in metrics.values()
        for m in observation.get("diagnostics", [])
    ][:24]
    return result


ARTIFACT_NAMES = {
    "views.selected_set": "Prepared views",
    "geometry.verified_geometry_set": "Verified matches",
    "mapping.reconstruction_set": "Sparse reconstruction",
    "validation.reconstruction_report": "Validation report",
    "reconstruction.selection": "Component selection",
    "dataset.prepared_set": "Training dataset",
    "dataset.prepared_component": "Component dataset",
    "training.checkpoint": "Training checkpoint",
    "training.gaussian_scene": "Gaussian scene",
    "training.gaussian_scene_set": "Gaussian scenes",
}


def artifact_name(kind: str) -> str:
    return ARTIFACT_NAMES.get(kind, kind.split(".")[-1].replace("_", " ").title())


def published_runs(overview, kind: str) -> list[dict]:
    runs, seen = [{"label": "Choose a published result", "value": ""}], set()
    if overview:
        history = {str(r.identity): r.values for r in overview.index.runs}
        for row in overview.index.artifacts:
            value = row.values
            identity = str(value["producer_run_id"])
            if value["artifact_type"] != kind or value["storage_status"] == "evicted":
                continue
            if identity not in seen:
                started = timestamp(history.get(identity, {}).get("started_at"))
                runs.append({"label": f"{artifact_name(kind)} · {started}", "value": identity})
                seen.add(identity)
    return runs
