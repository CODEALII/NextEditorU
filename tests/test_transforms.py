import math
from pathlib import Path
import unittest
from worldstudio.bfres import Bone, Skeletons
from worldstudio.project import WorldProject


def bone(name, index, parent, xyz, rotation=(0., 0., 0., 1.), flags=1 << 12, scale=(1., 1., 1.)):
    return Bone('test', name, 0, index, parent, flags, scale, rotation, xyz)


class TransformTests(unittest.TestCase):
    def skeleton(self, bones):
        s = Skeletons.__new__(Skeletons)
        s.models = {'test': bones}
        return s

    def test_euler_hierarchy_and_parent_override(self):
        s = self.skeleton([bone('root', 0, -1, (10., 20., 30.), (0., math.pi / 2, 0., 1.)),
                           bone('child', 1, 0, (3., 0., 2.)),
                           bone('grandchild', 2, 1, (1., 0., 0.))])
        result = s.world_positions('test')
        for actual, expected in zip(result['child'], (12., 20., 27.)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(result['grandchild'], (12., 20., 26.)):
            self.assertAlmostEqual(actual, expected)
        changed = s.world_positions('test', {'root': [50., 20., 30.]})
        self.assertAlmostEqual(changed['child'][0], 52.)

    def test_quaternion_rotation(self):
        q = (0., math.sin(math.pi / 4), 0., math.cos(math.pi / 4))
        s = self.skeleton([bone('root', 0, -1, (0., 0., 0.), q, flags=0),
                           bone('child', 1, 0, (3., 0., 2.))])
        for actual, expected in zip(s.world_positions('test')['child'], (2., 0., -3.)):
            self.assertAlmostEqual(actual, expected)

    def test_world_target_converts_back_to_local_under_rotated_parent(self):
        s = self.skeleton([bone('root', 0, -1, (10., 20., 30.),
                                (0., math.pi / 2, 0., 1.)),
                           bone('child', 1, 0, (3., 4., 2.))])
        target = (70., 55., -14.)
        local = s.local_position_for_world('test', 'child', target)

        actual = s.world_positions('test', {'child': local})['child']
        for value, expected in zip(actual, target):
            self.assertAlmostEqual(value, expected)

    def test_world_target_rejects_non_finite_coordinates_and_unsupported_parent(self):
        scaled = self.skeleton([bone('root', 0, -1, (0., 0., 0.), scale=(2., 1., 1.)),
                                bone('child', 1, 0, (1., 2., 3.))])
        with self.assertRaisesRegex(ValueError, 'invalid world position'):
            scaled.local_position_for_world('test', 'child', (0., float('nan'), 0.))
        with self.assertRaisesRegex(ValueError, 'parent rest transform is unsupported'):
            scaled.local_position_for_world('test', 'child', (1., 2., 3.))

    def test_scaled_branch_omitted_not_reported_as_world_position(self):
        s = self.skeleton([bone('root', 0, -1, (0., 0., 0.)),
                           bone('scaled', 1, 0, (1., 2., 3.), scale=(2., 1., 1.)),
                           bone('child', 2, 1, (3., 0., 2.)),
                           bone('sibling', 3, 0, (4., 5., 6.))])
        self.assertEqual(s.world_positions('test'), {'root': [0., 0., 0.], 'sibling': [4., 5., 6.]})

    def test_affine_transforms_compose_positive_scale_and_rotation(self):
        q = (0., math.sin(math.pi / 4), 0., math.cos(math.pi / 4))
        s = self.skeleton([bone('root', 0, -1, (10., 20., 30.), scale=(2., 3., 4.)),
                           bone('child', 1, 0, (1., 2., 3.), q, flags=0)])

        linear, position = s.world_affine_transforms('test')['child']
        transformed = [sum(linear[i][j] * (0., 0., 2.)[j] for j in range(3)) + position[i]
                       for i in range(3)]

        for actual, expected in zip(position, (12., 26., 42.)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(transformed, (16., 26., 42.)):
            self.assertAlmostEqual(actual, expected)

    def test_affine_transforms_reject_segment_scale_compensation_branch(self):
        s = self.skeleton([bone('root', 0, -1, (0., 0., 0.)),
                           bone('compensated', 1, 0, (1., 2., 3.), flags=1 << 23),
                           bone('child', 2, 1, (3., 0., 2.)),
                           bone('sibling', 3, 0, (4., 5., 6.))])

        self.assertEqual(set(s.world_affine_transforms('test')), {'root', 'sibling'})

    def test_affine_transforms_reject_camera_facing_billboard_branch(self):
        s = self.skeleton([bone('root', 0, -1, (0., 0., 0.)),
                           bone('billboard', 1, 0, (1., 2., 3.), flags=2 << 16),
                           bone('child', 2, 1, (3., 0., 2.)),
                           bone('sibling', 3, 0, (4., 5., 6.))])

        self.assertEqual(set(s.world_affine_transforms('test')), {'root', 'sibling'})

    def test_cycle_and_missing_parent_rejected(self):
        for bones in ([bone('a', 0, 1, (0., 0., 0.)), bone('b', 1, 0, (0., 0., 0.))],
                      [bone('a', 0, 10, (0., 0., 0.))]):
            with self.subTest(bones=bones), self.assertRaises(ValueError):
                self.skeleton(bones).world_positions('test')


class LocalWorldTransformTests(unittest.TestCase):
    def test_w1_point_positions_roundtrip_through_drag_conversion(self):
        source = Path(__file__).resolve().parents[1] / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        native = WorldProject.open(source)
        world = native.world_positions
        checked = 0
        for row in native.points.rows:
            if len(row) < 2:
                continue
            name = row[1]
            if name not in native.positions or name not in world:
                continue
            local = native.skeletons.local_position_for_world(
                native.path_model, name, world[name], overrides=native.positions)
            for actual, expected in zip(local, native.positions[name]):
                self.assertAlmostEqual(actual, expected, delta=0.01, msg=name)
            checked += 1
        self.assertGreater(checked, 10)


if __name__ == '__main__':
    unittest.main()
