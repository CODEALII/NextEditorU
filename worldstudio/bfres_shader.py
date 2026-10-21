"""Resolve Wii U BFRES material shader assignments to SHARCFB interfaces.

Only exact archive/program/symbol names are joined. Material option values can
be mapped to an AGL-style candidate index; shape-specific variants and GX2
instructions remain unevaluated.
"""
from functools import lru_cache
from pathlib import Path

from .archive import Archive
from .bfres import Skeletons
from .shader_archive import parse_sharcfb


@lru_cache(maxsize=1)
def _parse_shader_container(data):
    """Cache the parsed local shader container by its immutable bytes."""
    container = Archive(data)
    return tuple(
        (entry.rsplit('/', 1)[-1][:-len('.sharcfb')], container.read(entry))
        for entry in container.entries if entry.lower().endswith('.sharcfb')
    )


def load_shader_archives(path):
    """Load local SHARCFB files, reusing an unchanged container parse."""
    return dict(_parse_shader_container(Path(path).read_bytes()))


def resolve_material_option_variation(program, options):
    """Return an AGL-style candidate index for material option values.

    The SHARCFB variation order follows the mixed-radix lookup implemented by
    the checked-in AGL reference. Shape-specific macros (for example skinning
    influence count) and options absent from the program remain unresolved.
    This does not establish the game's final per-shape active shader.
    """
    macros = program["variation_macros"]
    option_symbols = {macro["symbol"] for macro in macros if macro["symbol"]}
    ignored_options = sorted(set(options) - option_symbols)
    choices = []
    unresolved_macros = []
    invalid_options = []
    indexes = []

    for macro in macros:
        values = macro["values"]
        symbol = macro["symbol"]
        option_value = options.get(symbol) if symbol else None
        if not symbol:
            unresolved_macros.append(macro["name"])
        if option_value is None:
            value_index = 0
            source = "first-declared"
        elif option_value in values:
            value_index = values.index(option_value)
            source = "material-option"
        else:
            value_index = 0
            source = "invalid-option"
            invalid_options.append({"symbol": symbol, "value": option_value})
        indexes.append(value_index)
        choices.append({"name": macro["name"], "value": values[value_index], "source": source})

    variation_index = 0
    multiplier = 1
    for index in range(len(macros) - 1, -1, -1):
        variation_index += indexes[index] * multiplier
        multiplier *= len(macros[index]["values"])

    return {
        "candidate_index": None if invalid_options else variation_index,
        "candidate_count": program["variation_count"],
        "macro_values": choices,
        "unresolved_macros": unresolved_macros,
        "ignored_options": ignored_options,
        "invalid_options": invalid_options,
        "selection_model": "AGL material-option lookup; shape variation unresolved",
    }


def extract_material_shader_assignments(data, model_name="CS_W1_World"):
    """Return bounded ShaderAssign metadata for every material in one model."""
    reader = Skeletons(data)
    models = dict(reader.dictionary(reader.ptr(0x20)))
    if model_name not in models:
        raise ValueError(f"Missing BFRES model: {model_name}")
    materials = reader.dictionary(reader.ptr(models[model_name] + 24))
    if len({name for name, _ in materials}) != len(materials):
        raise ValueError(f"{model_name}: duplicate BFRES material names")

    result = {}
    for material_name, material in materials:
        reader.bounds(material, 0x48)
        if data[material:material + 4] != b"FMAT":
            raise ValueError(f"{material_name}: invalid BFRES material")
        shader_offset = reader.ptr(material + 36)
        if not shader_offset:
            result[material_name] = None
            continue
        reader.bounds(shader_offset, 28)
        archive_pointer = reader.ptr(shader_offset)
        program_pointer = reader.ptr(shader_offset + 4)
        if not archive_pointer or not program_pointer:
            result[material_name] = None
            continue
        archive_name = reader.string(archive_pointer)
        program_name = reader.string(program_pointer)
        revision = reader.u32(shader_offset + 8)
        attrib_count, sampler_count = data[shader_offset + 12:shader_offset + 14]
        option_count = reader.u16(shader_offset + 14)
        dictionaries = []
        for index, expected_count in enumerate((attrib_count, sampler_count, option_count)):
            dictionary_offset = reader.ptr(shader_offset + 16 + index * 4)
            rows = reader.dictionary(dictionary_offset)
            if len(rows) != expected_count:
                raise ValueError(f"{material_name}: ShaderAssign dictionary count mismatch")
            values = {}
            for key, value_offset in rows:
                if not value_offset:
                    raise ValueError(f"{material_name}: empty ShaderAssign value for {key}")
                if key in values:
                    raise ValueError(f"{material_name}: duplicate ShaderAssign key {key}")
                values[key] = reader.string(value_offset)
            dictionaries.append(values)
        result[material_name] = {
            "archive_name": archive_name,
            "program_name": program_name,
            "revision": revision,
            "attributes": dictionaries[0],
            "samplers": dictionaries[1],
            "options": dictionaries[2],
        }
    return result


def attach_shader_metadata(model_data, shapes, shader_archives):
    """Attach exact assigned-program interface labels to supported mesh shapes.

    ``shader_archives`` maps each archive name to its raw SHARCFB bytes. A
    missing archive, program, or sampler-slot assignment is left unattached and
    reported in the returned material-name set; no guessed mapping is used.
    """
    assignments = extract_material_shader_assignments(model_data)
    parsed_archives = {}
    program_indexes = {}
    material_metadata = {}
    failed_materials = set()
    for shape in shapes:
        shape.pop("shaderMetadata", None)
        material_name = shape.get("material")
        if not isinstance(material_name, str):
            continue
        if material_name not in material_metadata:
            assignment = assignments.get(material_name)
            metadata = None
            if assignment:
                archive_name = assignment["archive_name"]
                if archive_name not in parsed_archives:
                    raw_archive = shader_archives.get(archive_name)
                    if raw_archive is None:
                        parsed_archives[archive_name] = None
                    else:
                        try:
                            parsed = parse_sharcfb(raw_archive)
                            parsed_archives[archive_name] = (
                                parsed if parsed["archive_name"] == archive_name else None)
                        except (ValueError, TypeError, OverflowError):
                            parsed_archives[archive_name] = None
                archive = parsed_archives.get(archive_name)
                if archive is not None:
                    index = program_indexes.setdefault(
                        archive_name, {program["name"]: program for program in archive["programs"]})
                    program = index.get(assignment["program_name"])
                    if program is not None:
                        sampler_symbols = {}
                        for sampler in program["samplers"]:
                            slot = sampler["symbol"]
                            if assignment["samplers"].get(slot) == slot:
                                sampler_symbols[slot] = sampler["name"]
                        attribute_symbols = {}
                        for attribute in program["attributes"]:
                            slot = attribute["symbol"]
                            source_attribute = assignment["attributes"].get(slot)
                            if source_attribute is not None:
                                attribute_symbols[slot] = {
                                    "shader_name": attribute["name"],
                                    "source_attribute": source_attribute,
                                }
                        metadata = {
                            "archiveName": archive_name,
                            "programName": program["name"],
                            "samplerSymbols": sampler_symbols,
                            "attributeSymbols": attribute_symbols,
                            "uniformNames": [item["name"] for item in program["uniforms"]],
                            "shaderOptions": dict(assignment["options"]),
                            "variationCount": program["variation_count"],
                            "variationSelection": resolve_material_option_variation(
                                program, assignment["options"]),
                        }
            material_metadata[material_name] = metadata
            if metadata is None:
                failed_materials.add(material_name)
        if material_metadata[material_name] is not None:
            metadata = dict(material_metadata[material_name])
            vertex_attributes = shape.get("vertexAttributes", {})
            bindings = {}
            for slot, binding in metadata.pop("attributeSymbols").items():
                source = binding["source_attribute"]
                source_info = vertex_attributes.get(source)
                bindings[slot] = {
                    "shader_name": binding["shader_name"],
                    "source_attribute": source,
                    "present": source_info is not None,
                    "format": source_info.get("format") if source_info else None,
                    "offset": source_info.get("offset") if source_info else None,
                }
            metadata["attributeBindings"] = bindings
            shape["shaderMetadata"] = metadata
    return failed_materials
