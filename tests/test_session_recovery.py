import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from worldstudio.session_recovery import (
    RECOVERY_FILE_FORMAT,
    SessionRecovery,
    StaleRecoveryError,
)


class SessionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "world.json"
        self.project.write_text('{"saved": true}', encoding="utf-8")
        self.baseline = hashlib.sha256(self.project.read_bytes()).hexdigest()
        self.store = SessionRecovery(self.root / "recovery")
        self.payload = {"kind": "preview", "project": {"nodes": [{"id": "W101"}]},
                        "mesh": [[], []]}

    def tearDown(self):
        self.temp.cleanup()

    def test_roundtrip_is_bound_to_project_kind_and_saved_baseline(self):
        destination = self.store.save(self.project, "preview", self.baseline, self.payload)
        self.assertTrue(destination.is_file())
        envelope = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(envelope["format"], RECOVERY_FILE_FORMAT)
        self.assertEqual(envelope["version"], 1)
        self.assertEqual(envelope["project_path"], str(self.project.resolve()))
        self.assertEqual(self.store.load(self.project, "preview", self.baseline), self.payload)
        self.assertIsNone(self.store.load(self.project, "native", self.baseline))

    def test_rejects_stale_baselines_and_tampered_payloads(self):
        destination = self.store.save(self.project, "preview", self.baseline, self.payload)
        with self.assertRaises(StaleRecoveryError):
            self.store.load(self.project, "preview", "0" * 64)

        envelope = json.loads(destination.read_text(encoding="utf-8"))
        envelope["payload"]["project"]["nodes"][0]["id"] = "changed"
        destination.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.store.load(self.project, "preview", self.baseline)

    def test_removes_recovery_only_for_the_selected_project_kind(self):
        self.store.save(self.project, "preview", self.baseline, self.payload)
        native_payload = {"kind": "native", "points": [], "routes": []}
        self.store.save(self.project, "native", self.baseline, native_payload)
        self.assertTrue(self.store.delete(self.project, "preview"))
        self.assertIsNone(self.store.load(self.project, "preview", self.baseline))
        self.assertEqual(self.store.load(self.project, "native", self.baseline), native_payload)
        self.assertFalse(self.store.delete(self.project, "preview"))

    def test_refuses_non_json_and_over_limit_snapshots(self):
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            self.store.save(self.project, "preview", self.baseline,
                            {"kind": "preview", "value": float("nan")})
        limited = SessionRecovery(self.root / "small", max_bytes=120)
        with self.assertRaisesRegex(ValueError, "size limit"):
            limited.save(self.project, "preview", self.baseline, self.payload)

    def test_rejects_invalid_kind_and_missing_baseline(self):
        with self.assertRaises(ValueError):
            self.store.path_for(self.project, "unknown")
        with self.assertRaises(ValueError):
            self.store.save(self.project, "preview", "bad", self.payload)


if __name__ == "__main__":
    unittest.main()
