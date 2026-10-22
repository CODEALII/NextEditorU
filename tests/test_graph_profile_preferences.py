import json
from pathlib import Path
import tempfile
import unittest

from worldstudio.graph_profile_preferences import (
    MAX_PREFERENCES_BYTES,
    PREFERENCES_FORMAT,
    GraphProfilePreferences,
)


class GraphProfilePreferencesTests(unittest.TestCase):
    def test_preferences_are_source_hash_bound_and_clearable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = GraphProfilePreferences(root / "settings" / "graph-profiles.json")
            source_a, source_b = "a" * 64, "b" * 64
            profile = root / "w1-profile.json"
            store.set(source_a, profile)

            self.assertEqual(store.get(source_a), profile.resolve())
            self.assertIsNone(store.get(source_b))
            saved = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["format"], PREFERENCES_FORMAT)
            self.assertEqual(saved["version"], 1)

            store.set(source_a, None)
            self.assertIsNone(store.get(source_a))

    def test_malformed_or_oversized_preferences_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "graph-profiles.json"
            path.write_text("{bad", encoding="utf-8")
            store = GraphProfilePreferences(path)
            self.assertIsNone(store.get("a" * 64))

            path.write_bytes(b" " * (MAX_PREFERENCES_BYTES + 1))
            self.assertIsNone(store.get("a" * 64))

    def test_invalid_source_hash_is_rejected_before_persisting(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GraphProfilePreferences(Path(folder) / "graph-profiles.json")
            with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
                store.set("not-a-hash", Path(folder) / "profile.json")
            self.assertFalse(store.path.exists())


if __name__ == "__main__":
    unittest.main()
