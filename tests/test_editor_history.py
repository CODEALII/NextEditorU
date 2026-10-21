"""Regression checks for the bounded editor undo/redo cursor."""
import unittest

from worldstudio.editor import EditHistory


class EditHistoryTests(unittest.TestCase):
    def test_undo_redo_and_new_edit_after_undo_discards_redo_branch(self):
        history = EditHistory({"value": 0}, limit=4)
        history.push({"value": 1})
        history.push({"value": 2})

        self.assertEqual(history.undo(), {"value": 1})
        history.push({"value": 3})

        self.assertFalse(history.can_redo)
        self.assertEqual(history.undo(), {"value": 1})
        self.assertEqual(history.undo(), {"value": 0})
        self.assertIsNone(history.undo())
        self.assertEqual(history.redo(), {"value": 1})
        self.assertEqual(history.redo(), {"value": 3})
        self.assertIsNone(history.redo())

    def test_history_is_bounded_and_reset_starts_a_clean_project(self):
        history = EditHistory(0, limit=3)
        for value in range(1, 6):
            history.push(value)

        self.assertEqual(history.states, [3, 4, 5])
        self.assertEqual(history.undo(), 4)
        self.assertEqual(history.undo(), 3)
        self.assertIsNone(history.undo())

        history.reset("new project")
        self.assertFalse(history.can_undo)
        self.assertFalse(history.can_redo)
        self.assertEqual(history.redo(), None)


if __name__ == "__main__":
    unittest.main()
