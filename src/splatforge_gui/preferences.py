"""Allowlisted machine/UI preferences; no numerical project configuration."""

import json
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QSettings


class Preferences:
    KEYS = {
        "geometry",
        "theme",
        "recent",
        "page",
        "mode",
        "colmap",
        "trainer_python",
        "lichtfeld",
        "model_directory",
        "last_project_parent",
        "source_view_mode",
        "recent_entries",
    }

    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings or QSettings("SplatForge", "Desktop")

    def get(self, key: str, default=None):
        if key not in self.KEYS:
            raise KeyError(key)
        return self.settings.value(key, default)

    def set(self, key: str, value) -> None:
        if key not in self.KEYS:
            raise KeyError(key)
        self.settings.setValue(key, value)

    def recent(self) -> list[str]:
        return [entry["path"] for entry in self.entries()]

    def entries(self) -> list[dict]:
        raw = self.get("recent_entries", "")
        if raw:
            try:
                entries = json.loads(raw)
                if isinstance(entries, list):
                    return [
                        dict(
                            path=e["path"],
                            name=str(e.get("name", Path(e["path"]).name)),
                            projectId=str(e.get("projectId", "")),
                            lastOpened=str(e.get("lastOpened", "")),
                        )
                        for e in entries[:15]
                        if isinstance(e, dict) and isinstance(e.get("path"), str) and e["path"]
                    ]
            except (ValueError, TypeError):
                pass
        value = self.get("recent", [])
        paths = ([value] if isinstance(value, str) else list(value or []))[:15]
        return [dict(path=p, name=Path(p).name, projectId="", lastOpened="") for p in paths]

    def _save_entries(self, entries: list[dict]) -> None:
        seen, unique = set(), []
        for entry in entries:
            path = entry["path"].casefold()
            if path not in seen:
                seen.add(path)
                unique.append(entry)
        entries = unique[:15]
        self.set("recent_entries", json.dumps(entries, ensure_ascii=False))
        self.set("recent", [e["path"] for e in entries])
        self.settings.sync()

    def remember(self, root: Path, *, project_id: str = "", name: str = "") -> None:
        path = str(root.absolute())
        previous = next((e for e in self.entries() if e["path"].casefold() == path.casefold()), {})
        entry = dict(
            path=path,
            name=name or previous.get("name", root.name),
            projectId=project_id or previous.get("projectId", ""),
            lastOpened=datetime.now(UTC).isoformat(),
        )
        others = [
            e
            for e in self.entries()
            if e["path"].casefold() != path.casefold()
            and not (project_id and e["projectId"] == project_id)
        ]
        self._save_entries([entry, *others])

    def describe(self, path: str, project_id: str, name: str) -> None:
        entries = self.entries()
        for entry in entries:
            if entry["path"] == path and entry["projectId"] in {"", project_id}:
                entry.update(projectId=project_id, name=name)
        self._save_entries(entries)

    def relocate(self, old_path: str, new_path: str, project_id: str, name: str) -> None:
        entries = self.entries()
        for entry in entries:
            if entry["path"] == old_path:
                if entry["projectId"] and entry["projectId"] != project_id:
                    raise ValueError("The selected project has a different identity.")
                entry.update(path=new_path, projectId=project_id, name=name)
        self._save_entries(
            [e for e in entries if e["path"] != new_path or e["projectId"] == project_id]
        )

    def remove(self, path: str) -> None:
        self._save_entries([e for e in self.entries() if e["path"] != path])
