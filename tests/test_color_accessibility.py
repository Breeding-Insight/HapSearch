import unittest

from design.colors import APP_PRIMARY_SCALE


def _hex_to_srgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _relative_luminance(hex_color):
    def _to_linear(channel):
        if channel <= 0.03928:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (_to_linear(c) for c in _hex_to_srgb(hex_color))
    return (0.2126 * r) + (0.7152 * g) + (0.0722 * b)


def _contrast_ratio(color_a, color_b):
    l1 = _relative_luminance(color_a)
    l2 = _relative_luminance(color_b)
    lighter, darker = (l1, l2) if l1 > l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


class ColorAccessibilityTests(unittest.TestCase):
    def test_app_primary_scale_uses_expected_foregrounds(self):
        expected = ["#ffffff", "#ffffff", "#ffffff", "#ffffff", "#ffffff"]
        actual = [entry["foreground"].lower() for entry in APP_PRIMARY_SCALE]
        self.assertEqual(actual, expected)

    def test_app_primary_scale_meets_wcag_aa_for_normal_text(self):
        minimum_ratio = 4.5
        for entry in APP_PRIMARY_SCALE:
            ratio = _contrast_ratio(entry["background"], entry["foreground"])
            self.assertGreaterEqual(
                ratio,
                minimum_ratio,
                msg=(
                    f"Contrast ratio failed for background={entry['background']} "
                    f"foreground={entry['foreground']} ratio={ratio:.2f}"
                ),
            )


if __name__ == "__main__":
    unittest.main()
