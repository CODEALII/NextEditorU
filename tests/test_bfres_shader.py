import unittest
from pathlib import Path

from worldstudio.archive import Archive
from worldstudio.bfres import Skeletons
from worldstudio.bfres_shader import (attach_shader_metadata,
                                      extract_material_shader_assignments,
                                      resolve_material_option_variation)
from worldstudio.mesh import extract_rigid_model


class BfresShaderMetadataTests(unittest.TestCase):
    def _assets(self):
        root = Path(__file__).resolve().parents[1]
        world_source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        shader_source = root / 'NSMBU Modding Project/content/Common/shader/shaderfb.szs'
        if not world_source.is_file() or not shader_source.is_file():
            self.skipTest('User-provided local game resources unavailable')
        model = Archive(world_source.read_bytes()).read('CS_W1.bfres')
        container = Archive(shader_source.read_bytes())
        shader_archives = {
            entry.rsplit('/', 1)[-1][:-len('.sharcfb')]: container.read(entry)
            for entry in container.entries if entry.lower().endswith('.sharcfb')
        }
        return model, shader_archives

    def test_local_material_assignments_resolve_program_and_sampler_symbols(self):
        model, archives = self._assets()
        assignments = extract_material_shader_assignments(model)
        self.assertEqual(assignments['mtGrass']['archive_name'], 'nw4f_cs_shader')
        self.assertEqual(assignments['mtGrass']['program_name'], 'nw4f_cs_shader')
        self.assertEqual(assignments['mtRW101W102a']['program_name'], 'nw4f_cs_route_shader')
        self.assertEqual(assignments['mtRW101W102a']['samplers']['_o0'], '_o0')

        shapes = extract_rigid_model(model)
        failures = attach_shader_metadata(model, shapes, archives)
        self.assertEqual(failures, set())
        self.assertEqual(len(shapes), 42)
        self.assertTrue(all(shape.get('shaderMetadata') for shape in shapes))
        route = next(shape for shape in shapes
                     if shape['shaderMetadata']['programName'] == 'nw4f_cs_route_shader' and
                     shape['shaderMetadata']['samplerSymbols'].get('_o1') == 'cTexMapEdgeMask')
        metadata = route['shaderMetadata']
        self.assertEqual(metadata['samplerSymbols']['_o0'], 'cTexMapRouteMask')
        self.assertEqual(metadata['samplerSymbols']['_x0'], 'cLightMap0')
        self.assertEqual(metadata['samplerSymbols']['_x1'], 'cLightMap1')
        self.assertEqual(metadata['samplerSymbols']['_b0'], 'cBakeMap0')
        self.assertEqual(metadata['samplerSymbols']['_b1'], 'cBakeMap1')
        self.assertEqual(metadata['samplerSymbols']['_s0'], 'cSpecMaskMap0')
        self.assertEqual(metadata['samplerSymbols']['_n0'], 'cNormalMap0')
        self.assertEqual(metadata['attributeBindings']['_u4'], {
            'shader_name': 'aTexCoordRouteMask',
            'source_attribute': '_u2',
            'present': True,
            'format': 0x80d,
            'offset': 24,
        })
        self.assertEqual(metadata['attributeBindings']['_u3']['format'], 7)
        self.assertTrue({'texmtx0', 'texmtx1'}.issubset(metadata['uniformNames']))
        selection = metadata['variationSelection']
        self.assertIsInstance(selection['candidate_index'], int)
        self.assertEqual(selection['candidate_count'], 576)
        self.assertEqual(selection['selection_model'],
                         'AGL material-option lookup; shape variation unresolved')
        self.assertEqual(selection['unresolved_macros'], ['NUM_SKINNING_VTX'])
        selected = {row['name']: row['value'] for row in selection['macro_values']}
        self.assertEqual(selected['ENABLE_EDGE_MASK'], '1')
        self.assertIn('var_color_anim', selection['ignored_options'])

    def test_material_option_index_uses_declared_mixed_radix_order(self):
        program = {
            'variation_count': 6,
            'variation_macros': [
                {'name': 'FIRST', 'symbol': 'first', 'values': ['a', 'b']},
                {'name': 'SECOND', 'symbol': 'second', 'values': ['0', '1', '2']},
            ],
        }
        selected = resolve_material_option_variation(program, {'second': '2', 'extra': 'x'})
        self.assertEqual(selected['candidate_index'], 2)
        self.assertEqual(selected['candidate_count'], 6)
        self.assertEqual(selected['macro_values'], [
            {'name': 'FIRST', 'value': 'a', 'source': 'first-declared'},
            {'name': 'SECOND', 'value': '2', 'source': 'material-option'},
        ])
        self.assertEqual(selected['ignored_options'], ['extra'])

    def test_invalid_material_option_does_not_claim_a_candidate(self):
        program = {'variation_count': 2, 'variation_macros': [
            {'name': 'MODE', 'symbol': 'mode', 'values': ['0', '1']},
        ]}
        selected = resolve_material_option_variation(program, {'mode': '2'})
        self.assertIsNone(selected['candidate_index'])
        self.assertEqual(selected['invalid_options'], [{'symbol': 'mode', 'value': '2'}])

    def test_missing_shader_archive_fails_closed_for_every_shape(self):
        model, _ = self._assets()
        shapes = extract_rigid_model(model)
        failures = attach_shader_metadata(model, shapes, {})
        self.assertEqual(len(failures), len({shape['material'] for shape in shapes}))
        self.assertTrue(all('shaderMetadata' not in shape for shape in shapes))


if __name__ == '__main__':
    unittest.main()
