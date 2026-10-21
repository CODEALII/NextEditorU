import sys
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform == "win32", "Cemu window selection uses Win32")
class CemuWindowSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.cemu_input_test import VK, main_game_windows
        import tools.cemu_input_test as cemu_input_test
        cls.VK = VK
        cls.main_game_windows = staticmethod(main_game_windows)
        cls.cemu_input_test = cemu_input_test

    def test_sustained_menu_navigation_uses_windows_arrow_virtual_keys(self):
        self.assertEqual(self.VK["left"], 0x25)
        self.assertEqual(self.VK["up"], 0x26)
        self.assertEqual(self.VK["right"], 0x27)
        self.assertEqual(self.VK["down"], 0x28)
        self.assertEqual(self.VK["x"], 0x58)

    def test_start_node_confirmation_names_the_expected_node(self):
        self.assertIn("Crushing-Cogs Tower", self.cemu_input_test.map_confirmation_prompt(
            "Crushing-Cogs Tower"))
        self.assertIn("intended start node", self.cemu_input_test.map_confirmation_prompt())

    def test_step_review_prompt_names_screenshot_and_next_direction(self):
        prompt = self.cemu_input_test.step_review_prompt("chain-route", 2, "d", "a")
        self.assertIn("chain-route-step-2-d-after.bmp", prompt)
        self.assertIn("Next direction is A", prompt)

    def test_ignores_titled_auxiliary_gamepad_view_when_main_title_is_present(self):
        game = {"title": "Cemu 1.26.2f [TitleId: 00050000-10101d00] New SUPER MARIO BROS. U"}
        auxiliary = {"title": "GamePad View - FPS: 60.00"}
        self.assertEqual(self.main_game_windows([auxiliary, game]), [game])

    def test_keeps_a_single_nonstandard_title_as_a_fallback(self):
        window = {"title": "Cemu"}
        self.assertEqual(self.main_game_windows([window]), [window])

    def test_preserves_ambiguity_when_multiple_game_title_windows_exist(self):
        first = {"title": "Cemu [TitleId: 00050000-10101d00] New SUPER MARIO BROS. U"}
        second = {"title": "Cemu [TitleId: 00050000-10101d00] New SUPER MARIO BROS. U"}
        self.assertEqual(self.main_game_windows([first, second]), [first, second])

    def test_process_window_picker_uses_main_game_not_auxiliary_gamepad_view(self):
        game = {"hwnd": 123, "title":
                "Cemu 1.26.2f [TitleId: 00050000-10101d00] New SUPER MARIO BROS. U"}
        auxiliary = {"hwnd": 456, "title": "GamePad View - FPS: 60.00"}
        with patch.object(self.cemu_input_test, "windows_for_pid",
                          return_value=[auxiliary, game]):
            self.assertIs(self.cemu_input_test.choose_window(42), game)

    def test_process_window_picker_rejects_multiple_main_game_windows(self):
        bounds = SimpleNamespace(left=0, top=0, right=800, bottom=600)
        first = {"hwnd": 123, "rect": bounds, "title":
                 "Cemu [TitleId: 00050000-10101d00] New SUPER MARIO BROS. U"}
        second = {"hwnd": 456, "rect": bounds, "title":
                  "Cemu [TitleId: 00050000-10101d00] New SUPER MARIO BROS. U"}
        with patch.object(self.cemu_input_test, "windows_for_pid",
                          return_value=[first, second]):
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                self.cemu_input_test.choose_window(42)

    def test_final_artifact_inventory_is_recorded_for_early_focus_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp)
            log = profile / "log.txt"
            log.write_bytes(b"boot log")
            save = profile / "mlc01/usr/save/00050000/10101D00/user/common/rp_savedata.dat"
            save.parent.mkdir(parents=True)
            save.write_bytes(b"save")
            report = {}

            self.cemu_input_test.record_final_artifacts(report, profile)

            self.assertEqual(report["game_log"], str(log.resolve()))
            self.assertEqual(report["game_log_sha256"], hashlib.sha256(b"boot log").hexdigest())
            self.assertEqual(report["final_save_hashes"][
                "common/rp_savedata.dat"]["sha256"], hashlib.sha256(b"save").hexdigest())

    def test_confirmation_returns_after_enter_while_launched_cemu_is_alive(self):
        stdin = SimpleNamespace(isatty=lambda: True)
        stdout = SimpleNamespace(write=Mock(), flush=Mock())
        process = Mock()
        process.poll.return_value = None
        keyboard = SimpleNamespace(kbhit=lambda: True, getwch=lambda: "\r")
        with patch.object(self.cemu_input_test, "sys", SimpleNamespace(stdin=stdin, stdout=stdout)), \
                patch.object(self.cemu_input_test, "msvcrt", keyboard), \
                patch.object(self.cemu_input_test, "time") as clock:
            self.cemu_input_test.wait_for_confirmation("confirm: ", pid=42, process=process)
        process.poll.assert_called_once_with()
        stdout.write.assert_any_call("confirm: ")
        clock.sleep.assert_not_called()

    def test_confirmation_fails_immediately_when_launched_cemu_exits(self):
        stdin = SimpleNamespace(isatty=lambda: True)
        stdout = SimpleNamespace(write=Mock(), flush=Mock())
        process = Mock()
        process.poll.return_value = 0
        keyboard = SimpleNamespace(kbhit=Mock(side_effect=AssertionError("keyboard polled")))
        with patch.object(self.cemu_input_test, "sys", SimpleNamespace(stdin=stdin, stdout=stdout)), \
                patch.object(self.cemu_input_test, "msvcrt", keyboard):
            with self.assertRaisesRegex(RuntimeError, "PID 42 exited with code 0"):
                self.cemu_input_test.wait_for_confirmation("confirm: ", pid=42, process=process)
        keyboard.kbhit.assert_not_called()

    def test_attached_confirmation_fails_if_cemu_pid_disappears(self):
        stdin = SimpleNamespace(isatty=lambda: True)
        stdout = SimpleNamespace(write=Mock(), flush=Mock())
        keyboard = SimpleNamespace(kbhit=Mock(side_effect=AssertionError("keyboard polled")))
        with patch.object(self.cemu_input_test, "sys", SimpleNamespace(stdin=stdin, stdout=stdout)), \
                patch.object(self.cemu_input_test, "msvcrt", keyboard), \
                patch.object(self.cemu_input_test, "active_cemu_pids", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "Attached Cemu PID 42 exited"):
                self.cemu_input_test.wait_for_confirmation("confirm: ", pid=42)
        keyboard.kbhit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
