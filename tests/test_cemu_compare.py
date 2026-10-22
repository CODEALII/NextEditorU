import tempfile
import unittest
from pathlib import Path

from tools.compare_cemu_runs import compare_runs


class CemuRunCompareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.screenshot = Path(self.temp.name) / "step.bmp"
        self.screenshot.write_bytes(b"synthetic screenshot")

    def tearDown(self):
        self.temp.cleanup()

    def run_fixture(self, case, *, label, pack=None):
        saves = {"common/rp_savedata.dat": {"size": 2, "sha256": "same"}}
        return {
            "case": case, "status": "completed", "pause_after_each_step": True,
            "sequence": ["a", "d"], "start_label": "Tower", "hold_ms": 2000,
            "record_level_clear_requested": False,
            "settle_wait_ms": 2000, "rpx_sha256": "rpx", "cemu_executable_sha256": "cemu",
            "controller_sha256": "controller", "baseline_save_hashes": saves,
            "final_save_hashes": saves, "pack_sha256": pack,
            "profile_pack_sha256": pack,
            "profile_preflight": ({"ready": True, "expected_pack_active_in_log": True,
                                   "graph_validation": {"matches": True},
                                   "archive": {"sha256": pack, "matches_profile_copy": True}}
                                  if pack else None),
            "events": [
                {"action": "manual_gate_confirmed", "gate": "overworld_visible"},
                {"action": "manual_gate_confirmed", "gate": "starting_node"},
                {"action": "step_review_confirmed", "step": 1, "key": "a",
                 "observed_location": "Acorn Plains", "observation_source": "operator",
                 "screenshot": str(self.screenshot)},
                {"action": "step_review_confirmed", "step": 2, "key": "d",
                 "observed_location": label, "observation_source": "operator",
                 "screenshot": str(self.screenshot)},
            ],
        }

    def test_compares_matched_inputs_and_reports_manual_labels_without_gameplay_claim(self):
        clean = self.run_fixture("clean", label="Acorn Plains")
        modified = self.run_fixture("chain", label="Blooper's Secret Lair", pack="pack-hash")
        result = compare_runs(clean, modified, expected_pack_sha256="pack-hash")
        self.assertTrue(result["comparable"])
        self.assertFalse(result["gameplay_verified"])
        self.assertTrue(result["matched_inputs"]["sequence"])
        self.assertTrue(result["steps"][1]["labels_differ"])
        self.assertIn("screenshot_sha256", result["steps"][0]["clean"])

    def test_level_clear_is_reported_as_operator_observation_and_keeps_claim_false(self):
        clean = self.run_fixture("clean", label="Acorn Plains")
        modified = self.run_fixture("chain", label="Acorn Plains", pack="pack-hash")
        for run in (clean, modified):
            run["record_level_clear_requested"] = True
            run["events"].append({"action": "level_clear_return_observed",
                                  "observed_location": "Acorn Plains",
                                  "observation_source": "operator",
                                  "screenshot": str(self.screenshot)})
        result = compare_runs(clean, modified, expected_pack_sha256="pack-hash")
        self.assertTrue(result["comparable"])
        self.assertFalse(result["gameplay_verified"])
        self.assertFalse(result["progression_verified"])
        self.assertEqual(result["level_clear_observations"]["modified"][0]["observation"]["label"],
                         "Acorn Plains")

    def test_flags_mismatched_inputs_and_missing_observation(self):
        clean = self.run_fixture("clean", label="")
        modified = self.run_fixture("chain", label="Course", pack="pack-hash")
        modified["controller_sha256"] = "different"
        result = compare_runs(clean, modified)
        self.assertFalse(result["comparable"])
        self.assertFalse(result["matched_inputs"]["controller_sha256"])
        self.assertTrue(any("operator location label" in issue for issue in result["issues"]))
        self.assertIn("screenshot_sha256", result["steps"][0]["clean"])


if __name__ == "__main__":
    unittest.main()
