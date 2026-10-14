import unittest

from design.colors import (
    APP_PRIMARY_SCALE,
    CHART_CATEGORICAL,
    CHART_SERIES,
)


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
    def test_app_primary_scale_uses_white_foregrounds(self):
        for entry in APP_PRIMARY_SCALE:
            self.assertEqual(entry["foreground"].lower(), "#ffffff")

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


class ChartPaletteTests(unittest.TestCase):
    def test_categorical_palette_has_eight_distinct_hex_colors(self):
        self.assertEqual(len(CHART_CATEGORICAL), 8)
        self.assertEqual(len(set(CHART_CATEGORICAL)), 8)
        for color in CHART_CATEGORICAL:
            self.assertRegex(color, r"^#[0-9A-F]{6}$")

    def test_categorical_colors_reach_3_to_1_on_the_chart_surface(self):
        for color in CHART_CATEGORICAL:
            ratio = _contrast_ratio(color, "#ffffff")
            self.assertGreaterEqual(ratio, 3.0, msg=f"{color} ratio={ratio:.2f}")

    def test_single_series_color_reaches_3_to_1_on_the_chart_surface(self):
        self.assertGreaterEqual(_contrast_ratio(CHART_SERIES, "#ffffff"), 3.0)


if __name__ == "__main__":
    unittest.main()
