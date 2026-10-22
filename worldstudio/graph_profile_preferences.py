"""Per-source persistence for the editor's explicit static graph check."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .recent_projects import default_recent_projects_path


PREFERENCES_FORMAT = "nsmbu-world-studio-graph-profile-preferences"
MAX_PREFERENCES_BYTES = 1024 * 1024
MAX_SOURCE_PROFILES = 256


def default_graph_profile_preferences_path():
    return default_recent_projects_path().with_name("graph-profiles.json")


class GraphProfilePreferences:
    """Remember explicit profile choices keyed to a source archive SHA-256."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_graph_profile_preferences_path()

    @staticmethod
    def _valid_source_hash(source_hash):
        return (isinstance(source_hash, str) and len(source_hash) == 64 and
                all(char in "0123456789abcdef" for char in source_hash))

    def _read(self):
        try:
            raw = self.path.read_bytes()
            if len(raw) > MAX_PREFERENCES_BYTES:
                return {}
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        profiles = value.get("profiles") if isinstance(value, dict) else None
        if (not isinstance(value, dict) or value.get("format") != PREFERENCES_FORMAT or
                value.get("version") != 1 or not isinstance(profiles, dict)):
            return {}
        result = {}
        for source_hash, profile_path in profiles.items():
            if (self._valid_source_hash(source_hash) and isinstance(profile_path, str) and
                    0 < len(profile_path) <= 4096):
                result[source_hash] = profile_path
        return dict(list(result.items())[-MAX_SOURCE_PROFILES:])

    def get(self, source_hash):
        if not self._valid_source_hash(source_hash):
            return None
        profile_path = self._read().get(source_hash)
        if profile_path is None:
            return None
        try:
            return Path(profile_path)
        except (TypeError, ValueError):
            return None

    def set(self, source_hash, profile_path):
        if not self._valid_source_hash(source_hash):
            raise ValueError("Source archive hash must be a lowercase SHA-256")
        profiles = self._read()
        if profile_path is None:
            profiles.pop(source_hash, None)
        else:
            try:
                canonical = str(Path(profile_path).expanduser().resolve())
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                raise ValueError("Graph profile path cannot be resolved") from error
            if not canonical or len(canonical) > 4096:
                raise ValueError("Graph profile path is invalid or too long")
            profiles.pop(source_hash, None)
            profiles[source_hash] = canonical
        profiles = dict(list(profiles.items())[-MAX_SOURCE_PROFILES:])
        value = {"format": PREFERENCES_FORMAT, "version": 1, "profiles": profiles}
        data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if len(data) > MAX_PREFERENCES_BYTES:
            raise ValueError("Graph profile preferences exceed the size limit")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".worldstudio-graph-profiles-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

