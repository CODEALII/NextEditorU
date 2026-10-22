import sys
import hashlib
import json
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

    def test_title_click_targets_exact_game_window_center_and_releases_mouse(self):
        bounds = SimpleNamespace(left=100, top=50, right=900, bottom=650)
        window = {"rect": bounds, "width": 800, "height": 600}
        with patch.object(self.cemu_input_test.user32, "SetCursorPos", return_value=1) as move, \
                patch.object(self.cemu_input_test, "send_inputs") as send:
            self.cemu_input_test.click_window_center(window)

        move.assert_called_once_with(500, 350)
        inputs = send.call_args.args[0]
        self.assertEqual([item.type for item in inputs], [self.cemu_input_test.INPUT_MOUSE] * 2)
        self.assertEqual([item.mi.dwFlags for item in inputs], [
            self.cemu_input_test.MOUSEEVENTF_LEFTDOWN,
            self.cemu_input_test.MOUSEEVENTF_LEFTUP,
        ])

    def test_title_click_path_does_not_send_a_keyboard_key(self):
        window = {"rect": SimpleNamespace(left=0, top=0, right=800, bottom=600),
                  "width": 800, "height": 600}
        with patch.object(self.cemu_input_test, "click_window_center") as click, \
                patch.object(self.cemu_input_test, "key_event") as key:
            action = self.cemu_input_test.advance_title(window, click=True)

        self.assertEqual(action, "mouse_click")
        click.assert_called_once_with(window)
        key.assert_not_called()

    def test_controller_profile_comparison_checks_exact_file_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "current/controllerProfiles/controller0.txt"
            reference = root / "reference/controllerProfiles/controller0.txt"
            current.parent.mkdir(parents=True)
            reference.parent.mkdir(parents=True)
            current.write_text("emulate = Wii U Pro Controller\nWASD = left stick\n",
                               encoding="utf-8")
            reference.write_text("emulate = Wii U GamePad\nWASD = left stick\n",
                                 encoding="utf-8")

            comparison = self.cemu_input_test.compare_controller_profiles(
                current, reference.parent.parent)

            self.assertFalse(comparison["matches"])
            self.assertNotEqual(comparison["controller_sha256"],
                                comparison["reference_controller_sha256"])

            reference.write_bytes(current.read_bytes())
            comparison = self.cemu_input_test.compare_controller_profiles(
                current, reference.parent.parent)
            self.assertTrue(comparison["matches"])

    def test_controller_mismatch_blocks_cemu_before_launch_and_records_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile"
            reference = root / "reference"
            controller = profile / "controllerProfiles/controller0.txt"
            reference_controller = reference / "controllerProfiles/controller0.txt"
            controller.parent.mkdir(parents=True)
            reference_controller.parent.mkdir(parents=True)
            (profile / "Cemu.exe").write_bytes(b"test-executable")
            controller.write_text("emulate = Wii U Pro Controller\n", encoding="utf-8")
            reference_controller.write_text("emulate = Wii U GamePad\n", encoding="utf-8")
            rpx = root / "red-pro2.rpx"
            rpx.write_bytes(b"test-rpx")
            screenshot_dir = root / "evidence"
            args = SimpleNamespace(
                profile=profile, rpx=rpx, key="d", keys=None,
                screenshot_dir=screenshot_dir, pack_file=None,
                pack_name="WorldStudioChain", compare_controller_to=reference,
                compare_save_to=None, graph_profile=None, enter_level=False,
                attach=False, case="controller-mismatch", sequence=["d"],
                start_label="Tower", pause_after_each_step=False, hold_ms=2000,
                navigation_key=None, navigation_hold_ms=700,
            )

            with patch.object(self.cemu_input_test, "active_cemu_pids", return_value=[]), \
                    patch.object(self.cemu_input_test.subprocess, "Popen") as launch:
                with self.assertRaisesRegex(ValueError, "does not byte-match"):
                    self.cemu_input_test.run(args)

            launch.assert_not_called()
            result = json.loads((screenshot_dir / "controller-mismatch-result.json").read_text(
                encoding="utf-8"))
            self.assertEqual(result["rpx_sha256"], hashlib.sha256(b"test-rpx").hexdigest())
            self.assertEqual(result["cemu_executable_sha256"],
                             hashlib.sha256(b"test-executable").hexdigest())
            self.assertFalse(result["controller_comparison"]["matches"])
            self.assertEqual(result["controller_comparison"]["reference_controller_sha256"],
                             hashlib.sha256(reference_controller.read_bytes()).hexdigest())

    def test_step_review_prompt_names_screenshot_and_next_direction(self):
        prompt = self.cemu_input_test.step_review_prompt("chain-route", 2, "d", "a")
        self.assertIn("chain-route-step-2-d-after.bmp", prompt)
        self.assertIn("Next direction is A", prompt)
        self.assertIn("operator observation only", prompt)
        self.assertIn("visible course/node label is required", self.cemu_input_test.step_review_prompt(
            "chain-route", 1, "a", "d", require_label=True))

    def test_step_observation_records_label_or_unknown_and_can_require_label(self):
        with patch.object(self.cemu_input_test, "input", side_effect=["", "Blooper's Secret Lair"]):
            confirmed, label = self.cemu_input_test.wait_for_step_observation(
                "label: ", pid=42, process=Mock(poll=Mock(return_value=None)),
                require_label=True)
        self.assertTrue(confirmed)
        self.assertEqual(label, "Blooper's Secret Lair")

        with patch.object(self.cemu_input_test, "input", return_value=""):
            confirmed, label = self.cemu_input_test.wait_for_step_observation(
                "label: ", pid=42, process=Mock(poll=Mock(return_value=None)))
        self.assertTrue(confirmed)
        self.assertIsNone(label)

    def test_step_observation_can_abort_without_label(self):
        with patch.object(self.cemu_input_test, "input", return_value="n"):
            confirmed, label = self.cemu_input_test.wait_for_step_observation(
                "label: ", pid=42, process=Mock(poll=Mock(return_value=None)))
        self.assertFalse(confirmed)
        self.assertIsNone(label)

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

    def test_failed_graph_profile_preflight_records_result_without_launching_cemu(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile"
            profile.mkdir()
            (profile / "Cemu.exe").write_bytes(b"test-executable")
            packaged = (profile / "graphicPacks/WorldStudioChain/content/Common/course_select/CS_W1.szs")
            packaged.parent.mkdir(parents=True)
            packaged.write_bytes(b"profiled-world")
            pack = root / "expected-CS_W1.szs"
            pack.write_bytes(b"profiled-world")
            rpx = root / "red-pro2.rpx"
            rpx.write_bytes(b"test-rpx")
            graph_profile = root / "profile.json"
            graph_profile.write_text("{}", encoding="utf-8")
            screenshot_dir = root / "evidence"
            args = SimpleNamespace(
                profile=profile, rpx=rpx, key="d", keys=None,
                screenshot_dir=screenshot_dir, pack_file=pack,
                pack_name="WorldStudioChain", graph_profile=graph_profile,
                compare_save_to=None, compare_controller_to=None,
                enter_level=False, attach=False,
                case="blocked-profile", sequence=["d"], start_label="Tower",
                pause_after_each_step=False, hold_ms=2000,
                navigation_key=None, navigation_hold_ms=700,
            )
            with patch.object(self.cemu_input_test, "active_cemu_pids", return_value=[]), \
                    patch("tools.cemu_preflight.inspect_profile", return_value={
                        "ready": False, "issues": ["manifest does not match profile"]
                    }), \
                    patch.object(self.cemu_input_test.subprocess, "Popen") as launch:
                with self.assertRaisesRegex(RuntimeError, "Cemu preflight blocked launch"):
                    self.cemu_input_test.run(args)

            launch.assert_not_called()
            result = json.loads((screenshot_dir / "blocked-profile-result.json").read_text(
                encoding="utf-8"))
            self.assertIn("manifest does not match profile", result["prelaunch_error"])
            self.assertFalse(result["profile_preflight"]["ready"])

    def test_confirmation_returns_after_enter_while_launched_cemu_is_alive(self):
        stdin = SimpleNamespace(isatty=lambda: True)
        stdout = SimpleNamespace(write=Mock(), flush=Mock())
        process = Mock()
        process.poll.return_value = None
        keyboard = SimpleNamespace(kbhit=lambda: True, getwch=lambda: "\r")
        with patch.object(self.cemu_input_test, "sys", SimpleNamespace(stdin=stdin, stdout=stdout)), \
                patch.object(self.cemu_input_test, "msvcrt", keyboard), \
                patch.object(self.cemu_input_test, "time") as clock:
            confirmed = self.cemu_input_test.wait_for_confirmation(
                "confirm: ", pid=42, process=process)
        self.assertTrue(confirmed)
        process.poll.assert_called_once_with()
        stdout.write.assert_any_call("confirm: ")
        clock.sleep.assert_not_called()

    def test_confirmation_returns_false_on_n_without_more_input(self):
        stdin = SimpleNamespace(isatty=lambda: True)
        stdout = SimpleNamespace(write=Mock(), flush=Mock())
        process = Mock()
        process.poll.return_value = None
        keyboard = SimpleNamespace(kbhit=lambda: True, getwch=lambda: "n")
        with patch.object(self.cemu_input_test, "sys", SimpleNamespace(stdin=stdin, stdout=stdout)), \
                patch.object(self.cemu_input_test, "msvcrt", keyboard), \
                patch.object(self.cemu_input_test, "time") as clock:
            confirmed = self.cemu_input_test.wait_for_confirmation(
                "confirm: ", pid=42, process=process)
        self.assertFalse(confirmed)
        stdout.write.assert_any_call("\nAborted at confirmation gate.\n")
        clock.sleep.assert_not_called()

    def test_non_tty_confirmation_can_abort_with_n(self):
        stdin = SimpleNamespace(isatty=lambda: False)
        stdout = SimpleNamespace(write=Mock(), flush=Mock())
        with patch.object(self.cemu_input_test, "sys", SimpleNamespace(stdin=stdin, stdout=stdout)), \
                patch.object(self.cemu_input_test, "input", return_value="n"):
            confirmed = self.cemu_input_test.wait_for_confirmation("confirm: ", pid=42)
        self.assertFalse(confirmed)

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
