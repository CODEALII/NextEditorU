import json
from pathlib import Path
import tempfile
import unittest

from worldstudio.recent_projects import RECENT_FILE_FORMAT, RecentProjects


class RecentProjectsTests(unittest.TestCase):
    def test_records_newest_first_deduplicates_and_filters_editor_kind(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            store = RecentProjects(base / "settings" / "recent.json", limit=3)
            first = base / "world-one.json"
            second = base / "world-two.szs"
            preview = base / "preview.json"

            store.record(first, "native")
            store.record(second, "native")
            store.record(preview, "preview")
            store.record(first, "native")

            self.assertEqual([entry["path"] for entry in store.list()], [
                str(first.resolve()), str(preview.resolve()), str(second.resolve())])
            self.assertEqual(store.list("native"), [
                {"kind": "native", "path": str(first.resolve())},
                {"kind": "native", "path": str(second.resolve())}])
            self.assertEqual(store.list("preview"), [
                {"kind": "preview", "path": str(preview.resolve())}])

    def test_limit_keeps_the_most_recent_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = RecentProjects(root / "recent.json", limit=2)
            for index in range(4):
                store.record(root / f"project-{index}.json", "preview")
            self.assertEqual([Path(item["path"]).name for item in store.list()],
                             ["project-3.json", "project-2.json"])

    def test_native_and_preview_histories_have_independent_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = RecentProjects(root / "recent.json", limit=2)
            for index in range(3):
                store.record(root / f"native-{index}.szs", "native")
                store.record(root / f"preview-{index}.json", "preview")
            entries = store.list()
            self.assertEqual(len(entries), 4)
            self.assertEqual([Path(item["path"]).name for item in store.list("native")],
                             ["native-2.szs", "native-1.szs"])
            self.assertEqual([Path(item["path"]).name for item in store.list("preview")],
                             ["preview-2.json", "preview-1.json"])

    def test_malformed_store_is_ignored_and_replaced_on_next_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recent.json"
            path.write_text("{broken", encoding="utf-8")
            store = RecentProjects(path)
            self.assertEqual(store.list(), [])
            store.record(Path(folder) / "recovered.json", "native")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["format"], RECENT_FILE_FORMAT)
            self.assertEqual(saved["version"], 1)
            self.assertEqual(len(saved["projects"]), 1)

    def test_ignores_invalid_entries_without_losing_valid_neighbors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recent.json"
            valid = str((Path(folder) / "world.szs").resolve())
            path.write_text(json.dumps({
                "format": RECENT_FILE_FORMAT,
                "version": 1,
                "projects": [None, {"kind": "invalid", "path": valid},
                             {"kind": "native", "path": valid},
                             {"kind": "preview", "path": 7}],
            }), encoding="utf-8")
            self.assertEqual(RecentProjects(path).list(), [
                {"kind": "native", "path": valid}])

    def test_rejects_invalid_kind_and_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                RecentProjects(Path(folder) / "recent.json", limit=0)
            store = RecentProjects(Path(folder) / "recent.json")
            with self.assertRaises(ValueError):
                store.record(Path(folder) / "world.json", "unknown")
            with self.assertRaises(ValueError):
                store.list("unknown")


if __name__ == "__main__":
    unittest.main()
