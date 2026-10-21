"""Atomic, bounded recovery snapshots for edits to saved projects."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile

from .recent_projects import RecentProjects, default_recent_projects_path


RECOVERY_FILE_FORMAT = "nsmbu-world-studio-recovery"
MAX_RECOVERY_BYTES = 64 * 1024 * 1024


class StaleRecoveryError(ValueError):
    """A recovery belongs to a different saved version of the project."""


class SessionRecovery:
    """Store one recent edit snapshot per saved project and editor kind."""

    def __init__(self, root=None, max_bytes=MAX_RECOVERY_BYTES):
        self.root = (Path(root) if root is not None else
                     default_recent_projects_path().parent / "recovery")
        if (not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or
                max_bytes < 1):
            raise ValueError("Recovery size limit must be a positive integer")
        self.max_bytes = max_bytes

    @staticmethod
    def _canonical(path):
        return RecentProjects._canonical(path)

    def path_for(self, project_path, kind):
        if kind not in ("native", "preview"):
            raise ValueError("Recovery kind must be 'native' or 'preview'")
        canonical = self._canonical(project_path)
        identity = f"{kind}\0{os.path.normcase(canonical)}".encode("utf-8")
        name = hashlib.sha256(identity).hexdigest() + ".json"
        return self.root / name

    @staticmethod
    def _payload_bytes(payload):
        try:
            return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Recovery snapshot is not valid JSON: {error}") from error

    def save(self, project_path, kind, baseline_sha256, payload):
        canonical = self._canonical(project_path)
        if not isinstance(baseline_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", baseline_sha256):
            raise ValueError("Recovery needs the saved project's SHA-256")
        if not isinstance(payload, dict) or payload.get("kind") != kind:
            raise ValueError("Recovery snapshot kind does not match the editor")
        payload_bytes = self._payload_bytes(payload)
        envelope = {
            "format": RECOVERY_FILE_FORMAT,
            "version": 1,
            "kind": kind,
            "project_path": canonical,
            "baseline_sha256": baseline_sha256,
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        try:
            data = (json.dumps(envelope, indent=2, ensure_ascii=False,
                               allow_nan=False) + "\n").encode("utf-8")
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Recovery envelope is not valid JSON: {error}") from error
        if len(data) > self.max_bytes:
            if self.max_bytes % (1024 * 1024) == 0:
                limit = f"{self.max_bytes // (1024 * 1024)} MiB"
            else:
                limit = f"{self.max_bytes} byte"
            raise ValueError(f"Recovery snapshot exceeds the configured {limit} size limit")

        destination = self.path_for(canonical, kind)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".worldstudio-recovery-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return destination

    def load(self, project_path, kind, baseline_sha256):
        canonical = self._canonical(project_path)
        if not isinstance(baseline_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", baseline_sha256):
            raise ValueError("Recovery needs the saved project's SHA-256")
        source = self.path_for(canonical, kind)
        try:
            data = source.read_bytes()
        except FileNotFoundError:
            return None
        if len(data) > self.max_bytes:
            raise ValueError("Recovery snapshot exceeds the configured size limit")
        try:
            envelope = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Recovery snapshot is unreadable: {error}") from error
        if (not isinstance(envelope, dict) or envelope.get("format") != RECOVERY_FILE_FORMAT or
                envelope.get("version") != 1 or envelope.get("kind") != kind or
                envelope.get("project_path") != canonical):
            raise ValueError("Recovery snapshot identity is invalid")
        if not hmac.compare_digest(str(envelope.get("baseline_sha256", "")), baseline_sha256):
            raise StaleRecoveryError("The saved project changed after this recovery snapshot was made")
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or payload.get("kind") != kind:
            raise ValueError("Recovery snapshot payload is invalid")
        actual = hashlib.sha256(self._payload_bytes(payload)).hexdigest()
        expected = envelope.get("payload_sha256")
        if not isinstance(expected, str) or not hmac.compare_digest(actual, expected):
            raise ValueError("Recovery snapshot checksum does not match")
        return payload

    def delete(self, project_path, kind):
        path = self.path_for(project_path, kind)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
