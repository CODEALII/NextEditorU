import tempfile
import unittest
from pathlib import Path

from tools.cemu_preflight import inspect_profile


class CemuPreflightTests(unittest.TestCase):
    def make_profile(self, root, *, api='Keyboard', mapping='key_68', active=True):
        profile = Path(root)
        (profile / 'controllerProfiles').mkdir()
        (profile / 'graphicPacks/WorldStudioChain/content/Common/course_select').mkdir(parents=True)
        (profile / 'graphicPacks/WorldStudioChain/rules.txt').write_text(
            '[Definition]\nname = World Studio Three Level Chain\n', encoding='utf-8')
        (profile / 'graphicPacks/WorldStudioChain/content/Common/course_select/CS_W1.szs').write_bytes(
            b'fake-szs-test-payload')
        pack_entry = ('graphicPacks\\WorldStudioChain\\rules.txt' if active else
                      'graphicPacks\\Other\\rules.txt')
        (profile / 'settings.xml').write_text(
            '<?xml version="1.0"?><content><GraphicPack><Entry filename="' +
            pack_entry + '"/></GraphicPack></content>', encoding='utf-8')
        (profile / 'controllerProfiles/controller0.txt').write_text(
            f'[General]\nemulate = Wii U GamePad\napi = {api}\n[Controller]\n'
            '17 = key_87\n18 = key_83\n19 = key_65\n20 = ' + mapping + '\n',
            encoding='utf-8')
        active_line = ('Activate graphic pack: New Super Mario Bros. U/Mods/World Studio Chain\n'
                       if active else '')
        (profile / 'log.txt').write_text(
            '------- Loaded title -------\n'
            "Loaded module 'red-pro2' with checksum 0x6caea914\n"
            '------- Activate graphic packs -------\n' + active_line +
            '------- Run title -------\n', encoding='utf-8')
        return profile

    def test_ready_profile_checks_keyboard_pack_log_and_archive_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self.make_profile(temporary)
            archive = profile / 'expected.szs'
            archive.write_bytes(b'fake-szs-test-payload')
            report = inspect_profile(profile, expected_pack='WorldStudioChain',
                                     archive=archive, require_keyboard=True,
                                     require_run=True)
        self.assertTrue(report['ready'], report['issues'])
        self.assertTrue(report['keyboard_left_stick_configured'])
        self.assertTrue(report['expected_pack_active_in_log'])
        self.assertTrue(report['archive']['matches_profile_copy'])
        self.assertFalse(report['gameplay_verified'])

    def test_directinput_profile_is_rejected_for_wasd_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self.make_profile(temporary, api='DirectInput')
            report = inspect_profile(profile, expected_pack='WorldStudioChain',
                                     require_keyboard=True)
        self.assertFalse(report['ready'])
        self.assertFalse(report['keyboard_left_stick_configured'])
        self.assertIn('WASD is not configured as the Wii U GamePad left stick',
                      report['issues'])

    def test_reports_enabled_pack_that_never_appeared_in_run_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self.make_profile(temporary, active=False)
            report = inspect_profile(profile, expected_pack='WorldStudioChain',
                                     require_run=True)
        self.assertFalse(report['ready'])
        self.assertIn("Expected graphic pack 'WorldStudioChain' is not active in log.txt",
                      report['issues'])

    def test_archive_must_match_profile_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self.make_profile(temporary)
            archive = profile / 'expected.szs'
            archive.write_bytes(b'another-payload')
            report = inspect_profile(profile, expected_pack='WorldStudioChain',
                                     archive=archive)
        self.assertFalse(report['ready'])
        self.assertIn('Expected archive hash does not match the profile pack copy',
                      report['issues'])

    def test_run_evidence_is_taken_from_latest_title_not_old_log_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self.make_profile(temporary)
            log = profile / 'log.txt'
            previous = log.read_text(encoding='utf-8')
            log.write_text(
                previous + '\n------- Loaded title -------\n'
                "Loaded module 'red-pro2' with checksum 0x6caea914\n"
                '------- Activate graphic packs -------\n'
                'Activate graphic pack: New Super Mario Bros. U/Workarounds/Title Screen Crash Fix\n'
                '------- Run title -------\n', encoding='utf-8')
            report = inspect_profile(profile, expected_pack='WorldStudioChain',
                                     require_run=True)
        self.assertFalse(report['ready'])
        self.assertEqual(report['active_packs_in_log'],
                         ['New Super Mario Bros. U/Workarounds/Title Screen Crash Fix'])


if __name__ == '__main__':
    unittest.main()
