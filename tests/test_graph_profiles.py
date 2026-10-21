import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from worldstudio.graph_validation import load_native_graph_profile


PROFILE = {
    "format": "nsmbu-world-graph-profile-v1",
    "world_prefix": "W1",
    "entry_points": ["W101"],
    "required_locations": ["W102", "W103"],
}


class NativeGraphProfileTests(unittest.TestCase):
    def test_loads_explicit_profile_and_checks_its_world(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            path.write_text(json.dumps(PROFILE), encoding="utf-8")

            loaded = load_native_graph_profile(path, "W1")
            with self.assertRaisesRegex(ValueError, "source archive is W2"):
                load_native_graph_profile(path, "W2")

        self.assertEqual(loaded, {
            "world_prefix": "W1",
            "entry_points": ("W101",),
            "required_locations": ("W102", "W103"),
        })
    def test_rejects_malformed_profile_fields_and_point_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            for field, value, message in (
                    ("extra", True, "fields must be"),
                    ("world_prefix", "W10", "world_prefix must be"),
                    ("entry_points", ["W101", "W101"], "duplicate point IDs"),
                    ("required_locations", ["W201"], "invalid W1 point ID")):
                with self.subTest(field=field, value=value):
                    payload = dict(PROFILE)
                    payload[field] = value
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        load_native_graph_profile(path, "W1")

            path.write_bytes(b"not-json")
            with self.assertRaisesRegex(ValueError, "valid UTF-8 JSON"):
                load_native_graph_profile(path)

            path.write_bytes(b'{"format":"wrong","format":"wrong"}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_native_graph_profile(path)

            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(ValueError, "valid UTF-8 JSON"):
                load_native_graph_profile(path)

            path.write_bytes(b" " * (64 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "exceeds 65536 bytes"):
                load_native_graph_profile(path)

    def test_checked_in_w1_profile_runs_through_cli(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "NSMBU Modding Project/content/Common/course_select/CS_W1.szs"
        if not source.is_file():
            self.skipTest("User-provided local W1 dump unavailable")
        profile = root / "profiles/w1-core-progression.json"
        result = subprocess.run(
            [sys.executable, "-m", "worldstudio", "validate-graph", str(source),
             "--profile", str(profile)],
            cwd=root, capture_output=True, text=True, encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["entry_points"], ["W101"])
        self.assertEqual(report["required_locations"], ["W102", "W103"])
        self.assertEqual(report["validation_errors"], [])
        self.assertTrue(report["reachable_locations_checked"])


if __name__ == "__main__":
    unittest.main()
