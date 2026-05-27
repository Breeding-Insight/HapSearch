import unittest
import importlib.util
from pathlib import Path

COORDINATES_PATH = Path(__file__).resolve().parents[1] / "alignment" / "coordinates.py"
spec = importlib.util.spec_from_file_location("alignment_coordinates", COORDINATES_PATH)
coordinates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coordinates)

relative_position = coordinates.relative_position
relative_positions = coordinates.relative_positions


class RelativePositionTests(unittest.TestCase):
    def test_top_strand_target_upstream_downstream(self):
        self.assertEqual(relative_position(100, 100, False), 0)
        self.assertEqual(relative_position(99, 100, False), -1)
        self.assertEqual(relative_position(101, 100, False), 1)

    def test_bottom_strand_target_upstream_downstream(self):
        self.assertEqual(relative_position(100, 100, True), 0)
        self.assertEqual(relative_position(99, 100, True), 1)
        self.assertEqual(relative_position(101, 100, True), -1)

    def test_missing_target_keeps_absolute_positions(self):
        self.assertEqual(relative_position(12345, None, False), 12345)
        self.assertEqual(relative_positions([10, 11, 12], None, True), [10, 11, 12])

    def test_fractional_gap_positions_stay_between_bases(self):
        self.assertAlmostEqual(relative_position(99.1, 100, False), -0.9)
        self.assertAlmostEqual(relative_position(99.1, 100, True), 0.9)


if __name__ == "__main__":
    unittest.main()
