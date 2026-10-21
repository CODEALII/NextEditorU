import unittest

from worldstudio.graph_validation import validate_native_world


def point(index, name, normal="", paths="", secret="", secret_paths=""):
    return [str(index), name, "", normal, paths, "", secret, secret_paths, ""]


class NativeGraphValidationTests(unittest.TestCase):
    def test_changed_same_world_destination_accepts_direct_route_segment(self):
        initial_points = [point(0, "W101"), point(1, "W102")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W102"
        points[0][4] = "RW101W102"
        routes = [["RW101W102", "road", ""]]
        issues = validate_native_world(
            points,
            routes,
            known_references={"W101", "W102", "RW101W102"},
            initial_points=initial_points,
            initial_routes=[],
            world_prefix="W1",
            entry_points=("W101",),
            required_locations=("W102",),
        )
        self.assertEqual(issues, [])

    def test_changed_same_world_destination_accepts_multihop_route_chain(self):
        initial_points = [point(0, "W101"), point(1, "W102")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W102"
        points[0][4] = "RW101K001,RK001W102"
        routes = [["RW101K001", "road", ""], ["RK001W102", "road", ""]]
        issues = validate_native_world(
            points,
            routes,
            known_references={"W101", "W102", "K001", "RW101K001", "RK001W102"},
            initial_points=initial_points,
            initial_routes=[],
            world_prefix="W1",
            entry_points=("W101",),
            required_locations=("W102",),
        )
        self.assertEqual(issues, [])

    def test_changed_destination_rejects_stale_macro_path_chain(self):
        initial_points = [point(0, "W101", "W102", "RW101W102"),
                         point(1, "W102"), point(2, "W103")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W103"
        initial_routes = [["RW101W102", "road", ""]]
        routes = [["RW101W103", "road", ""]]
        references = {"W101", "W102", "W103", "RW101W102", "RW101W103"}

        issues = validate_native_world(
            points,
            routes,
            known_references=references,
            initial_points=initial_points,
            initial_routes=initial_routes,
            world_prefix="W1",
        )

        self.assertIn("W101: BFRES macro-path chain does not reach W103", issues)

    def test_changed_destination_accepts_matching_macro_path_chain(self):
        initial_points = [point(0, "W101", "W102", "RW101W102"),
                         point(1, "W102"), point(2, "W103")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W103"
        points[0][4] = "RW101W103"
        initial_routes = [["RW101W102", "road", ""]]
        routes = [["RW101W103", "road", ""]]
        references = {"W101", "W102", "W103", "RW101W102", "RW101W103"}

        issues = validate_native_world(
            points,
            routes,
            known_references=references,
            initial_points=initial_points,
            initial_routes=initial_routes,
            world_prefix="W1",
        )

        self.assertEqual(issues, [])

    def test_changed_destination_rejects_out_of_order_macro_path_chain(self):
        initial_points = [point(0, "W101", "W102"),
                          point(1, "W102"), point(2, "W103")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W103"
        points[0][4] = "RK001W103,RW101K001"
        routes = [["RW101K001", "road", ""], ["RK001W103", "road", ""]]
        references = {"W101", "W102", "W103", "K001",
                      "RW101K001", "RK001W103"}

        issues = validate_native_world(
            points,
            routes,
            known_references=references,
            initial_points=initial_points,
            initial_routes=[],
            world_prefix="W1",
        )

        self.assertIn("W101: BFRES macro-path chain does not reach W103", issues)

    def test_changed_destination_skips_ambiguous_stock_branch_path_list(self):
        initial_points = [point(0, "W104", "W1K3",
                                "RW104W1K3,RW104F008,RF008W1C0"),
                          point(1, "W1K3"), point(2, "W1C0")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W1C0"
        routes = [["RW104W1K3", "road", ""],
                  ["RW104F008", "road", ""],
                  ["RF008W1C0", "road", ""]]
        references = {"W104", "W1K3", "W1C0", "F008",
                      "RW104W1K3", "RW104F008", "RF008W1C0"}

        issues = validate_native_world(
            points,
            routes,
            known_references=references,
            initial_points=initial_points,
            initial_routes=routes,
            world_prefix="W1",
        )

        self.assertFalse(any("BFRES macro-path chain" in issue for issue in issues))

    def test_changed_same_world_destination_rejects_missing_or_disconnected_route(self):
        initial_points = [point(0, "W101"), point(1, "W102")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W102"
        cases = (
            ([], {"W101", "W102"}),
            ([['RW101K001', "road", ""], ['RK002W102', "road", ""]],
             {"W101", "W102", "K001", "K002"}),
        )
        for routes, references in cases:
            with self.subTest(routes=routes):
                issues = validate_native_world(
                    points,
                    routes,
                    known_references=references,
                    initial_points=initial_points,
                    initial_routes=[],
                    world_prefix="W1",
                    entry_points=("W101",),
                    required_locations=("W102",),
                )
                self.assertIn("W101: no directed route-segment path to W102", issues)

    def test_route_edge_removal_rechecks_unchanged_destinations(self):
        points = [point(0, "W101", "W102"), point(1, "W102", "W103"),
                  point(2, "W103")]
        routes = [["RW101W102", "road", ""], ["RW102W103", "road", ""]]
        edited_routes = routes[:1]
        issues = validate_native_world(
            points,
            edited_routes,
            known_references={"W101", "W102", "W103"},
            initial_points=points,
            initial_routes=routes,
            world_prefix="W1",
        )
        self.assertIn("W102: no directed route-segment path to W103", issues)

    def test_route_display_column_change_does_not_change_connectivity(self):
        points = [point(0, "W101", "W102"), point(1, "W102")]
        initial_routes = [["RW101W102", "road", ""]]
        edited_routes = [["RW101W102", "stone", "reserved"]]
        issues = validate_native_world(
            points,
            edited_routes,
            known_references={"W101", "W102"},
            initial_points=points,
            initial_routes=initial_routes,
            world_prefix="W1",
        )
        self.assertEqual(issues, [])

    def test_cross_world_route_segments_cannot_bridge_a_local_chain(self):
        initial_points = [point(0, "W101"), point(1, "W102")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W102"
        routes = [["RW101W201", "road", ""], ["RW201W102", "road", ""]]
        issues = validate_native_world(
            points,
            routes,
            known_references={"W101", "W102"},
            initial_points=initial_points,
            initial_routes=routes,
            world_prefix="W1",
        )
        self.assertIn("W101: no directed route-segment path to W102", issues)

    def test_external_route_endpoint_is_not_required_in_local_bfres(self):
        points = [point(0, "W101"), point(1, "W102")]
        issues = validate_native_world(
            points,
            [["RW101W201", "road", ""]],
            known_references={"W101", "W102", "RW101W201"},
            initial_points=points,
            initial_routes=[],
            world_prefix="W1",
            entry_points=("W101",),
            required_locations=("W102",),
        )
        self.assertNotIn("RW101W201: missing endpoint model reference W201", issues)
        self.assertIn("Unreachable location W102", issues)

    def test_preserves_old_route_gaps_and_skips_cross_world_destinations(self):
        partial_baseline = [point(0, "W101", "W102"), point(1, "W102"),
                            point(2, "W103")]
        edited_partial = [row[:] for row in partial_baseline]
        edited_partial[0][3] = "W102,W103"
        partial_issues = validate_native_world(
            edited_partial,
            [["RW101W103", "road", ""]],
            known_references={"W101", "W102", "W103"},
            initial_points=partial_baseline,
            initial_routes=[],
            world_prefix="W1",
        )
        self.assertFalse(any("route-segment path" in issue for issue in partial_issues))

        initial_points = [point(0, "W101"), point(1, "W102")]
        points = [row[:] for row in initial_points]
        points[0][3] = "W201"
        cross_world_issues = validate_native_world(
            points,
            [],
            known_references={"W101", "W102"},
            initial_points=initial_points,
            initial_routes=[],
            world_prefix="W1",
        )
        self.assertFalse(any("route-segment path" in issue for issue in cross_world_issues))

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
        routes = [["RW101W199", "road", ""]]
        issues = validate_native_world(
            points,
            routes,
            known_references={"W101", "W102"},
            world_prefix="W1",
            entry_points=("W101",),
            required_locations=("W102", "W103"),
        )
        self.assertIn("RW101W199: missing endpoint model reference W199", issues)
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
