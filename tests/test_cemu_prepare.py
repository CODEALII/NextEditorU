"""Synthetic Cemu setup tests; never launch an emulator or use game assets."""
import configparser
import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.prepare_cemu import prepare


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class PrepareCemuTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.patch = self.root / "patch"
        self.output = self.root / "isolated"
        self.put(self.source, "Cemu.exe", b"fake executable: must never run")
        self.put(self.source, "runtime.dll", b"fake runtime")
        self.put(self.source, "resources/ui.txt", b"runtime resource")
        self.put(self.source, "settings.xml", b"source settings must not be copied")
        self.put(self.source, "controllerProfiles/controller0.txt", b"user input profile")
        self.put(self.source, "mlc01/usr/save/test.dat", b"private save")
        self.put(self.source, "mlc01/usr/title/0005000e/update.dat", b"installed update")
        self.put(self.source, "mlc01/sys/title/fonts/font.dat", b"system resource")
        self.put(self.source, "graphicPacks/Cloudy/rules.txt", b"unrelated enabled mod")
        self.put(self.source, "graphicPacks/CrashFix/rules.txt", b"[Definition]\nversion = 6\n")
        self.put(self.patch, "content/Common/course_select/CS_W1.szs", b"synthetic archive")

    @staticmethod
    def put(root, relative, content):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def run_prepare(self, executable=False):
        return prepare(self.source / "Cemu.exe" if executable else self.source,
                       self.patch, self.output)

    def test_preserves_inputs_and_excludes_private_state_and_installed_updates(self):
        before_source, before_patch = snapshot(self.source), snapshot(self.patch)
        result = self.run_prepare(executable=True)
        self.assertEqual(snapshot(self.source), before_source)
        self.assertEqual(snapshot(self.patch), before_patch)
        self.assertFalse(result["launched"])
        self.assertFalse((self.output / "mlc01/usr").exists())
        self.assertFalse((self.output / "graphicPacks/Cloudy").exists())
        self.assertEqual((self.output / "mlc01/sys/title/fonts/font.dat").read_bytes(), b"system resource")
        self.assertEqual((self.output / "runtime.dll").read_bytes(), b"fake runtime")
        self.assertEqual((self.output / "resources/ui.txt").read_bytes(), b"runtime resource")

    def test_isolated_settings_and_enabled_pack_references(self):
        self.run_prepare()
        settings = ET.parse(self.output / "settings.xml").getroot()
        self.assertEqual(Path(settings.findtext("mlc_path")), self.output / "mlc01")
        # Legacy gp_download is the completed-wizard marker, not auto-download.
        self.assertEqual(settings.findtext("gp_download"), "true")
        for name in ("permanent_storage", "use_discord_presence", "check_update"):
            self.assertEqual(settings.findtext(name), "false")
        self.assertEqual(settings.findtext("Account/OnlineEnabled"), "false")
        references = [entry.get("filename").replace("\\", "/")
                      for entry in settings.findall("GraphicPack/Entry")]
        self.assertCountEqual(references, ["graphicPacks/WorldStudioChain/rules.txt",
                                           "graphicPacks/CrashFix/rules.txt"])
        for reference in references:
            self.assertTrue((self.output / reference).is_file())
        rules = (self.output / references[0]).read_text()
        self.assertIn("titleIds = 0005000010101D00", rules)
        self.assertIn("default = 1", rules)
        archive = self.output / "graphicPacks/WorldStudioChain/content/Common/course_select/CS_W1.szs"
        self.assertEqual(archive.read_bytes(), b"synthetic archive")
        launcher = (self.output / "launch.ps1").read_text()
        self.assertIn("-g $GameRpx", launcher)
        self.assertIn('-m "$PSScriptRoot/mlc01"', launcher)

    def test_clean_baseline_requires_no_patch_and_disables_world_studio_chain(self):
        before_source = snapshot(self.source)
        result = prepare(self.source, None, self.output, baseline=True)
        self.assertTrue(result["baseline"])
        self.assertEqual(result["enabled_packs"], ["CrashFix"])
        self.assertEqual(snapshot(self.source), before_source)
        settings = ET.parse(self.output / "settings.xml").getroot()
        references = [entry.get("filename").replace("\\", "/")
                      for entry in settings.findall("GraphicPack/Entry")]
        self.assertEqual(references, ["graphicPacks/CrashFix/rules.txt"])
        self.assertTrue((self.output / references[0]).is_file())
        self.assertFalse((self.output / "graphicPacks/WorldStudioChain").exists())
        self.assertFalse((self.output / "mlc01/usr").exists())
        self.assertFalse((self.output / "graphicPacks/Cloudy").exists())
        readme = (self.output / "README.txt").read_text(encoding="utf-8")
        self.assertIn("Clean baseline", readme)
        self.assertIn("Verify WASD is left stick in Input Settings", readme)
        self.assertIn("Enabled graphic packs: CrashFix", readme)

    def test_baseline_rejects_patch_and_output_inside_source(self):
        with self.assertRaisesRegex(ValueError, "does not use --patch"):
            prepare(self.source, self.patch, self.output, baseline=True)
        with self.assertRaisesRegex(ValueError, "separate from input"):
            prepare(self.source, None, self.source / "nested-baseline", baseline=True)

    def test_legacy_ini_and_xml_have_same_usable_keyboard_bindings(self):
        self.run_prepare()
        profile = configparser.ConfigParser()
        profile.read(self.output / "controllerProfiles/controller0.txt")
        self.assertEqual(profile["General"]["emulate"], "Wii U GamePad")
        self.assertEqual(profile["General"]["api"], "Keyboard")
        root = ET.parse(self.output / "controllerProfiles/controller0.xml").getroot()
        self.assertEqual(root.findtext("type"), "Wii U GamePad")
        self.assertEqual(root.findtext("controller/api"), "Keyboard")
        xml = {int(e.findtext("mapping")): int(e.findtext("button"))
               for e in root.findall("controller/mappings/entry")}
        legacy = {}
        for key, value in profile["Controller"].items():
            if key.isdecimal():
                self.assertTrue(value.startswith("key_"))
                legacy[int(key)] = int(value[4:])
        self.assertEqual(legacy, xml)
        # Independently established VPAD IDs / Windows VKs prevent a shared
        # erroneous constant from passing merely because both serializers agree.
        self.assertEqual({k: xml[k] for k in (1, 2, 9, 11, 12, 13, 14)},
                         {1: 90, 2: 88, 9: 13, 11: 38, 12: 40, 13: 37, 14: 39})
        self.assertEqual({k: xml[k] for k in (17, 18, 19, 20)},
                         {17: 87, 18: 83, 19: 65, 20: 68})

    def test_refuses_existing_output_without_changing_anything(self):
        self.output.mkdir()
        self.put(self.output, "keep.bin", b"existing output")
        before = snapshot(self.root)
        with self.assertRaises(FileExistsError):
            self.run_prepare()
        self.assertEqual(snapshot(self.root), before)

    def test_refuses_output_inside_input_trees(self):
        before = snapshot(self.root)
        for parent in (self.source, self.patch):
            with self.subTest(parent=parent), self.assertRaises(ValueError):
                prepare(self.source, self.patch, parent / "nested-output")
        self.assertEqual(snapshot(self.root), before)

    def test_finds_standard_downloaded_crashfix_layout(self):
        original = self.source / "graphicPacks/CrashFix"
        standard = self.source / "graphicPacks/downloadedGraphicPacks/NewSuperMarioBrosU/Workarounds/CrashFix"
        standard.parent.mkdir(parents=True)
        original.rename(standard)
        self.run_prepare()
        self.assertEqual((self.output / "graphicPacks/CrashFix/rules.txt").read_bytes(),
                         (standard / "rules.txt").read_bytes())


if __name__ == "__main__":
    unittest.main()
