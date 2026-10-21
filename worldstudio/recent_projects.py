"""Small persistent recent-project list for the desktop editor."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


RECENT_PROJECT_LIMIT = 10
RECENT_FILE_FORMAT = "nsmbu-world-studio-recents"


def default_recent_projects_path():
    """Return a per-user config location without placing state in the project."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Local"
    else:
        root = os.environ.get("XDG_CONFIG_HOME")
        base = Path(root) if root else Path.home() / ".config"
    return base / "NSMBUWorldStudio" / "recent-projects.json"


class RecentProjects:
    """Versioned list with a bounded recent-project history per editor kind."""

    def __init__(self, path=None, limit=RECENT_PROJECT_LIMIT):
        self.path = Path(path) if path is not None else default_recent_projects_path()
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("Recent project limit must be a positive integer")
        self.limit = limit

    @staticmethod
    def _canonical(path):
        return str(Path(path).expanduser().resolve())

    @staticmethod
    def _key(path):
        return os.path.normcase(path)

    def list(self, kind=None):
        if kind is not None and kind not in ("native", "preview"):
            raise ValueError("Recent project kind must be 'native' or 'preview'")
        try:
            raw = self.path.read_bytes()
            if len(raw) > 1024 * 1024:
                return []
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        if (not isinstance(value, dict) or value.get("format") != RECENT_FILE_FORMAT or
                value.get("version") != 1 or not isinstance(value.get("projects"), list)):
            return []

        result = []
        seen = set()
        counts = {"native": 0, "preview": 0}
        for item in value["projects"]:
            if not isinstance(item, dict):
                continue
            item_kind, raw_path = item.get("kind"), item.get("path")
            if item_kind not in ("native", "preview") or not isinstance(raw_path, str) or not raw_path:
                continue
            if kind is not None and item_kind != kind:
                continue
            try:
                path = self._canonical(raw_path)
            except (OSError, RuntimeError, ValueError):
                continue
            key = (item_kind, self._key(path))
            if key in seen:
                continue
            if counts[item_kind] >= self.limit:
                continue
            seen.add(key)
            result.append({"kind": item_kind, "path": path})
            counts[item_kind] += 1
        return result

    def record(self, path, kind):
        if kind not in ("native", "preview"):
            raise ValueError("Recent project kind must be 'native' or 'preview'")
        canonical = self._canonical(path)
        key = self._key(canonical)
        entries = [item for item in self.list()
                   if not (item["kind"] == kind and self._key(item["path"]) == key)]
        projects = []
        counts = {"native": 0, "preview": 0}
        for item in [{"kind": kind, "path": canonical}, *entries]:
            item_kind = item["kind"]
            if counts[item_kind] >= self.limit:
                continue
            projects.append(item)
            counts[item_kind] += 1
        value = {"format": RECENT_FILE_FORMAT, "version": 1, "projects": projects}
        data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".worldstudio-recents-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return projects[0]
