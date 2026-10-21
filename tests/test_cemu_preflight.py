import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from worldstudio.graph_validation import graph_profile_record, load_native_graph_profile
from tools.cemu_preflight import inspect_profile


class CemuPreflightTests(unittest.TestCase):
    def make_profile(self, root, *, api='Keyboard', mapping='key_68', active=True):
        profile = Path(root)
        (profile / 'controllerProfiles').mkdir(parents=True)
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
            '18 = key_87\n19 = key_83\n20 = key_65\n21 = ' + mapping + '\n',
            encoding='utf-8')
        active_line = ('Activate graphic pack: New Super Mario Bros. U/Mods/World Studio Chain\n'
                       if active else '')
        (profile / 'log.txt').write_text(
            '------- Loaded title -------\n'
            "Loaded module 'red-pro2' with checksum 0x6caea914\n"
            '------- Activate graphic packs -------\n' + active_line +
            '------- Run title -------\n', encoding='utf-8')
        return profile

    def write_save_snapshot(self, profile, *, personal=b'personal', common=b'common'):
        save_root = Path(profile) / 'mlc01/usr/save/00050000/10101D00/user'
        (save_root / '80000001').mkdir(parents=True)
        (save_root / 'common').mkdir()
        (save_root / '80000001/rp_personal_savedata.dat').write_bytes(personal)
        (save_root / 'common/rp_savedata.dat').write_bytes(common)

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

    def test_xml_only_keyboard_profile_is_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self.make_profile(temporary)
            (profile / 'controllerProfiles/controller0.txt').unlink()
            entries = ''.join(
                f'<entry><mapping>{mapping}</mapping><button>{key}</button></entry>'
                for mapping, key in ((1, 90), (18, 87), (19, 83), (20, 65), (21, 68)))
            (profile / 'controllerProfiles/controller0.xml').write_text(
                '<emulated_controller><type>Wii U GamePad</type><controller>'
                '<api>Keyboard</api><mappings>' + entries +
                '</mappings></controller></emulated_controller>', encoding='utf-8')

            report = inspect_profile(profile, expected_pack='WorldStudioChain',
                                     require_keyboard=True, require_gamepad_a=True)

        self.assertTrue(report['ready'], report['issues'])
        self.assertTrue(report['keyboard_left_stick_configured'])
        self.assertTrue(report['gamepad_a_configured'])
        self.assertEqual(report['controller_sources'], ['controller0.xml'])

    def test_level_start_gate_rejects_profile_without_gamepad_a(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self.make_profile(temporary)
            report = inspect_profile(profile, require_keyboard=True,
                                     require_gamepad_a=True)

        self.assertFalse(report['ready'])
        self.assertFalse(report['gamepad_a_configured'])
        self.assertIn('Z is not configured as the Wii U GamePad A button',
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

    def test_graph_profile_gate_checks_packaged_manifest_and_archive_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.make_profile(root / 'cemu')
            graph_path = root / 'graph-profile.json'
            graph_data = {
                'format': 'nsmbu-world-graph-profile-v1',
                'world_prefix': 'W1',
                'entry_points': ['W101'],
                'required_locations': ['W102', 'W103'],
            }
            graph_path.write_text(json.dumps(graph_data), encoding='utf-8')
            packaged = (profile / 'graphicPacks/WorldStudioChain/content/Common/course_select/CS_W1.szs')
            record = graph_profile_record(load_native_graph_profile(graph_path))
            record.update(passed=True, scope='native point/route table reachability')
            manifest = {
                'output_sha256': hashlib.sha256(packaged.read_bytes()).hexdigest(),
                'graph_validation': record,
            }
            packaged.with_suffix('.szs.manifest.json').write_text(
                json.dumps(manifest), encoding='utf-8')

            report = inspect_profile(profile, expected_pack='WorldStudioChain',
                                      graph_profile=graph_path)

        self.assertTrue(report['ready'], report['issues'])
        self.assertTrue(report['graph_validation']['matches'])
        self.assertEqual(report['graph_validation']['required_locations'], ['W102', 'W103'])

    def test_graph_profile_gate_rejects_missing_or_mismatched_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.make_profile(root / 'cemu')
            graph_path = root / 'graph-profile.json'
            graph_path.write_text(json.dumps({
                'format': 'nsmbu-world-graph-profile-v1',
                'world_prefix': 'W1', 'entry_points': ['W101'],
                'required_locations': ['W102', 'W103'],
            }), encoding='utf-8')

            missing = inspect_profile(profile, expected_pack='WorldStudioChain',
                                       graph_profile=graph_path)
            self.assertFalse(missing['ready'])
            self.assertIn('Cannot verify graph-profile export manifest', missing['issues'][0])

            packaged = (profile / 'graphicPacks/WorldStudioChain/content/Common/course_select/CS_W1.szs')
            record = graph_profile_record(load_native_graph_profile(graph_path))
            record.update(passed=True)
            packaged.with_suffix('.szs.manifest.json').write_text(json.dumps({
                'output_sha256': '0' * 64,
                'graph_validation': record,
            }), encoding='utf-8')
            mismatched = inspect_profile(profile, expected_pack='WorldStudioChain',
                                         graph_profile=graph_path)

        self.assertFalse(mismatched['ready'])
        self.assertIn('Export manifest hash does not match the packaged CS_W1.szs',
                      mismatched['issues'])

    def test_graph_profile_gate_rejects_profile_for_another_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.make_profile(root / 'cemu')
            graph_path = root / 'world-2-profile.json'
            graph_path.write_text(json.dumps({
                'format': 'nsmbu-world-graph-profile-v1',
                'world_prefix': 'W2', 'entry_points': ['W201'],
                'required_locations': ['W202'],
            }), encoding='utf-8')
            report = inspect_profile(profile, expected_pack='WorldStudioChain',
                                     graph_profile=graph_path)

        self.assertFalse(report['ready'])
        self.assertTrue(any('profile is for W2, but the source archive is W1' in issue
                            for issue in report['issues']))

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

    def test_clean_baseline_rejects_enabled_custom_pack(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = self.make_profile(temporary)
            report = inspect_profile(profile, forbidden_pack='World Studio Chain')
        self.assertFalse(report['ready'])
        self.assertTrue(report['forbidden_pack_present_or_enabled'])
        self.assertIn("Forbidden graphic pack 'World Studio Chain' is present or enabled",
                      report['issues'])

    def test_save_comparison_requires_identical_personal_and_common_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.make_profile(root / 'profile')
            reference = self.make_profile(root / 'reference')
            self.write_save_snapshot(profile)
            self.write_save_snapshot(reference)

            report = inspect_profile(profile, compare_save_to=reference)

        self.assertTrue(report['ready'], report['issues'])
        self.assertTrue(report['save_comparison']['matches'])
        self.assertEqual(set(report['save_comparison']['profile_files']), {
            '80000001/rp_personal_savedata.dat', 'common/rp_savedata.dat'})

    def test_save_comparison_rejects_a_changed_save_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.make_profile(root / 'profile')
            reference = self.make_profile(root / 'reference')
            self.write_save_snapshot(profile)
            self.write_save_snapshot(reference, common=b'other save')

            report = inspect_profile(profile, compare_save_to=reference)

        self.assertFalse(report['ready'])
        self.assertFalse(report['save_comparison']['matches'])
        self.assertIn('NSMBU user-save files differ from the reference profile',
                      report['issues'])

    def test_save_comparison_rejects_missing_save_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.make_profile(root / 'profile')
            reference = self.make_profile(root / 'reference')
            self.write_save_snapshot(profile)

            report = inspect_profile(profile, compare_save_to=reference)

        self.assertFalse(report['ready'])
        self.assertFalse(report['save_comparison']['matches'])
        self.assertIn('Reference Cemu profile has no NSMBU user-save files to compare',
                      report['issues'])


if __name__ == '__main__':
    unittest.main()
