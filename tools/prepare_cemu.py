"""Prepare an isolated portable Cemu test folder without launching it.

Inputs are only read/copied. Existing destinations are refused. No saves,
controller profiles, settings or enabled packs from the source are imported.
Schema evidence: inspected local Cemu 1.26.2f controller0.xml/settings.xml;
https://github.com/cemu-project/Cemu/blob/main/src/input/InputManager.cpp
https://github.com/cemu-project/Cemu/blob/main/src/input/api/Keyboard/KeyboardController.cpp
https://github.com/cemu-project/Cemu/blob/main/src/input/emulated/VPADController.h
https://github.com/cemu-project/Cemu/blob/main/src/gui/wxgui/wxWindowSystem.cpp
https://github.com/cemu-project/Cemu/blob/main/src/config/LaunchSettings.cpp
Current upstream confirms schema, but the installed legacy binary still needs
runtime confirmation. The generated profile uses Windows virtual key codes.
"""
from pathlib import Path
import argparse
import json
import shutil
import xml.etree.ElementTree as ET


KEYBOARD_BINDINGS = {1: 90, 2: 88, 3: 67, 4: 86, 5: 81, 6: 69,
                     7: 49, 8: 51, 9: 13, 10: 8, 11: 38, 12: 40,
                     13: 37, 14: 39, 17: 87, 18: 83, 19: 65, 20: 68}


def legacy_keyboard_profile():
    """Cemu 1.26 INI; decimal key_ values verified by v2.0 migration code."""
    header = ("[General]\nemulate = Wii U GamePad\napi = Keyboard\n"
              "\n[Controller]\nrumble = 0\nleftRange = 1\nrightRange = 1\n"
              "leftDeadzone = 0.15\nrightDeadzone = 0.15\nbuttonThreshold = 0.5\n")
    return header + "".join(f"{mapping} = key_{button}\n"
                            for mapping, button in KEYBOARD_BINDINGS.items())


def xml_write(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def configure(out: Path):
    """Write new configs only; safe for a folder pre-created by the caller."""
    for name in ("settings.xml", "controllerProfiles/controller0.xml", "controllerProfiles/controller0.txt"):
        if (out / name).exists():
            raise FileExistsError(out / name)
    (out / "mlc01").mkdir(exist_ok=True)
    root = ET.Element("content")
    values = {"logflag": "0", "mlc_path": str(out / "mlc01"),
              "permanent_storage": "false", "language": "0",
              "use_discord_presence": "false", "check_update": "false",
              # Legacy Cemu: gp_download means setup wizard already shown.
              # It does not enable background graphic-pack downloading.
              "gp_download": "true", "fullscreen": "false",
              "console_language": "1", "open_pad": "false"}
    for name, value in values.items():
        ET.SubElement(root, name).text = value
    graphics = ET.SubElement(root, "Graphic")
    ET.SubElement(graphics, "api").text = "1"  # Vulkan, observed local setting.
    ET.SubElement(graphics, "GX2DrawdoneSync").text = "true"
    packs = ET.SubElement(root, "GraphicPack")
    for name in ("WorldStudioChain", "CrashFix"):
        ET.SubElement(packs, "Entry", filename=f"graphicPacks\\{name}\\rules.txt")
    account = ET.SubElement(root, "Account")
    ET.SubElement(account, "PersistentId").text = "2147483649"
    ET.SubElement(account, "OnlineEnabled").text = "false"
    xml_write(out / "settings.xml", root)

    root = ET.Element("emulated_controller")
    ET.SubElement(root, "type").text = "Wii U GamePad"
    controller = ET.SubElement(root, "controller")
    for name, value in (("api", "Keyboard"), ("uuid", "keyboard"),
                        ("display_name", "Keyboard")):
        ET.SubElement(controller, name).text = value
    mappings = ET.SubElement(controller, "mappings")
    # VPAD mapping IDs from VPADController.h; Windows VKs from wxWindowSystem.
    for mapping, button in KEYBOARD_BINDINGS.items():
        entry = ET.SubElement(mappings, "entry")
        ET.SubElement(entry, "mapping").text = str(mapping)
        ET.SubElement(entry, "button").text = str(button)
    (out / "controllerProfiles").mkdir(exist_ok=True)
    xml_write(out / "controllerProfiles/controller0.xml", root)
    # Cemu 1.26 reads INI; later versions read XML or migrate INI when absent.
    # Both represent the same mappings. Never use controller button bitmasks
    # for keyboard mappings: the legacy prefix is key_, followed by decimal VK.
    (out / "controllerProfiles/controller0.txt").write_text(
        legacy_keyboard_profile(), encoding="utf-8")


def prepare(cemu: Path, patch: Path, out: Path):
    cemu, patch, out = cemu.resolve(), patch.resolve(), out.resolve()
    source = cemu.parent if cemu.is_file() else cemu
    exe = source / "Cemu.exe"
    if not exe.is_file() or not (patch / "content").is_dir():
        raise ValueError("Cemu.exe and patch/content are required")
    if out.exists():
        raise FileExistsError(f"Refusing existing output: {out}")
    # Do not allow the output inside either input tree.
    for original in (source, patch):
        if out == original or original in out.parents:
            raise ValueError("Output must be separate from input trees")
    crashfix = source / "graphicPacks/downloadedGraphicPacks/NewSuperMarioBrosU/Workarounds/CrashFix"
    if not crashfix.is_dir():
        crashfix = source / "graphicPacks/CrashFix"
    if not (crashfix / "rules.txt").is_file():
        raise FileNotFoundError("Source Cemu CrashFix graphic pack not found")
    out.mkdir(parents=True)
    shutil.copy2(exe, out / "Cemu.exe")
    for dll in source.glob("*.dll"):
        shutil.copy2(dll, out / dll.name)
    if (source / "resources").is_dir():
        shutil.copytree(source / "resources", out / "resources")
    shutil.copytree(crashfix, out / "graphicPacks/CrashFix")
    pack = out / "graphicPacks/WorldStudioChain"
    shutil.copytree(patch / "content", pack / "content")
    # Generated test pack only; no unknown source graphic-pack settings copied.
    (pack / "rules.txt").write_text(
        '[Definition]\ntitleIds = 0005000010101D00\n'
        'name = World Studio Three Level Chain\n'
        'path = "New Super Mario Bros. U/Mods/World Studio Chain"\n'
        'description = Experimental topology test.\nversion = 6\ndefault = 1\n', encoding="utf-8")
    # System font installation is optional and read-only copied. Never copy saves
    # or installed game updates, which could override the requested input dump.
    sys_title = source / "mlc01/sys/title"
    if sys_title.is_dir():
        shutil.copytree(sys_title, out / "mlc01/sys/title")
    configure(out)
    (out / "launch.ps1").write_text(
        'param([Parameter(Mandatory=$true)][string]$GameRpx)\n'
        '$ErrorActionPreference = "Stop"\n'
        'if (-not (Test-Path -LiteralPath $GameRpx -PathType Leaf)) { throw "RPX not found" }\n'
        'Push-Location -LiteralPath $PSScriptRoot\n'
        'try { & "$PSScriptRoot/Cemu.exe" -g $GameRpx -m "$PSScriptRoot/mlc01" }\n'
        'finally { Pop-Location }\n', encoding="utf-8")
    (out / "README.txt").write_text(
        "Isolated test folder. No emulator has been launched by this tool.\n"
        "Run launch.ps1 -GameRpx <absolute path to supplied code/red-pro2.rpx>\n"
        "Keyboard: Z=A, X=B, C=X, V=Y, Enter=Plus; arrows=D-pad; WASD=left stick.\n"
        "Fresh saves and cache stay here. Source game files are not modified.\n"
        "Only WorldStudioChain and CrashFix are enabled. Check log.txt after launch.\n",
        encoding="utf-8")
    return {"output": str(out), "settings": str(out / "settings.xml"),
            "launch": str(out / "launch.ps1"), "launched": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cemu", required=True, type=Path)
    parser.add_argument("--patch", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.cemu, args.patch, args.out), indent=2))
