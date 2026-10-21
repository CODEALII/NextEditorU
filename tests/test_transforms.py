import math
import unittest
from worldstudio.bfres import Bone, Skeletons


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

    def test_scaled_branch_omitted_not_reported_as_world_position(self):
        s = self.skeleton([bone('root', 0, -1, (0., 0., 0.)),
                           bone('scaled', 1, 0, (1., 2., 3.), scale=(2., 1., 1.)),
                           bone('child', 2, 1, (3., 0., 2.)),
                           bone('sibling', 3, 0, (4., 5., 6.))])
        self.assertEqual(s.world_positions('test'), {'root': [0., 0., 0.], 'sibling': [4., 5., 6.]})

    def test_cycle_and_missing_parent_rejected(self):
        for bones in ([bone('a', 0, 1, (0., 0., 0.)), bone('b', 1, 0, (0., 0., 0.))],
                      [bone('a', 0, 10, (0., 0., 0.))]):
            with self.subTest(bones=bones), self.assertRaises(ValueError):
                self.skeleton(bones).world_positions('test')


if __name__ == '__main__':
    unittest.main()
