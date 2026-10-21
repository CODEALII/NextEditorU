import unittest

from worldstudio.graph_validation import validate_native_world


def point(index, name, normal="", paths="", secret="", secret_paths=""):
    return [str(index), name, "", normal, paths, "", secret, secret_paths, ""]


class NativeGraphValidationTests(unittest.TestCase):
    def test_valid_three_location_chain_and_optional_branch(self):
        points = [
            point(0, "W101", "W102", "RW101W102"),
            point(1, "W102", "W103,W1K1", "RW102W103,RW102W1K1"),
            point(2, "W103"),
            point(3, "W1K1"),
        ]
        issues = validate_native_world(
            points,
            [["RW101W102", "road", ""], ["RW102W103", "road", ""]],
            known_references={"W101", "W102", "W103", "W1K1",
                              "RW101W102", "RW102W103", "RW102W1K1"},
            world_prefix="W1",
            entry_points=("W101",),
            required_locations=("W101", "W102", "W103"),
        )
        self.assertEqual(issues, [])

    def test_reports_duplicate_ids_invalid_rows_and_bad_local_destination(self):
        points = [point(0, "W101", "W199"), point(1, "W101")]
        routes = [["bad", "road", ""], ["RW101W102", "road", ""],
                  ["RW101W102", "road", ""]]
        issues = validate_native_world(points, routes, world_prefix="W1")
        self.assertIn("Duplicate point W101", issues)
        self.assertIn("W101: unresolved local destination W199", issues)
        self.assertIn("Route row 0: invalid route name 'bad'", issues)
        self.assertIn("Duplicate route segment RW101W102", issues)

    def test_reports_missing_route_endpoints_and_unreachable_location(self):
        points = [point(0, "W101", "W102"), point(1, "W102"), point(2, "W103")]
        routes = [["RW101W404", "road", ""]]
        issues = validate_native_world(
            points,
            routes,
            known_references={"W101", "W102"},
            world_prefix="W1",
            entry_points=("W101",),
            required_locations=("W102", "W103"),
        )
        self.assertIn("RW101W404: missing endpoint model reference W404", issues)
        self.assertIn("Unreachable location W103", issues)

    def test_unchanged_partial_inventory_is_not_misreported(self):
        points = [point(0, "W101", "W102", "RW101W102")]
        routes = [["RW101W102", "road", ""]]
        issues = validate_native_world(
            points,
            routes,
            known_references={"W101", "W102"},
            initial_points=points,
            initial_routes=routes,
        )
        self.assertEqual(issues, [])

    def test_editing_another_column_does_not_revalidate_old_path_inventory(self):
        initial = [point(0, "W101", "W102", "RW101W102")]
        edited = [point(0, "W101", "W103", "RW101W102")]
        issues = validate_native_world(
            edited,
            [],
            known_references={"W101", "W102", "W103"},
            initial_points=initial,
            initial_routes=[],
            world_prefix="W1",
        )
        self.assertIn("W101: unresolved local destination W103", issues)
        self.assertFalse(any("missing BFRES macro-path bone" in issue for issue in issues))

    def test_changed_path_reports_unknown_macro_bone(self):
        initial = [point(0, "W101", "W102", "RW101W102")]
        edited = [point(0, "W101", "W102", "RW101W404")]
        issues = validate_native_world(
            edited,
            [],
            known_references={"W101", "W102", "RW101W102"},
            initial_points=initial,
            initial_routes=[],
        )
        self.assertIn("W101: missing BFRES macro-path bone RW101W404", issues)


if __name__ == "__main__":
    unittest.main()
