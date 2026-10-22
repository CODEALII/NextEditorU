"""User-local preferences for the desktop editor layout."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .recent_projects import default_recent_projects_path


PREFERENCES_FORMAT = "nsmbu-world-studio-layout"
MAX_PREFERENCES_BYTES = 4096
# Version 3 defaults older sessions to the integrated 3D graph surface. The
# optional legacy 2D pane remains user-toggleable and its new choice persists.
PREFERENCES_VERSION = 3


def default_editor_layout_preferences_path():
    return default_recent_projects_path().with_name("editor-layout.json")


class EditorLayoutPreferences:
    """Persist the user's 3D/graph view choice outside project files."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_editor_layout_preferences_path()

    def graph_visible(self, default=False):
        try:
            raw = self.path.read_bytes()
            if len(raw) > MAX_PREFERENCES_BYTES:
                return default
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return default
        if (not isinstance(value, dict) or value.get("format") != PREFERENCES_FORMAT or
                value.get("version") != PREFERENCES_VERSION or
                type(value.get("graph_visible")) is not bool):
            return default
        return value["graph_visible"]

    def set_graph_visible(self, visible):
        if type(visible) is not bool:
            raise ValueError("Graph visibility preference must be a boolean")
        value = {"format": PREFERENCES_FORMAT, "version": PREFERENCES_VERSION,
                 "graph_visible": visible}
        data = (json.dumps(value, indent=2) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".worldstudio-layout-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
