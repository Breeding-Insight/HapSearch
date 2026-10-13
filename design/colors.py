"""
HaploSearch Color Palettes

Visually equidistant color palettes for data visualization.
See color_palettes.md for full documentation.
"""

# App UI colors
APP_NAVY = "#304C89"
APP_BLUE = "#648DE5"
APP_CARD_HEADER_BG = "#D8EAD8"

# App UI palette (light -> dark) with explicit WCAG-compliant foregrounds
APP_PRIMARY_SCALE = [
    {"background": "#245842", "foreground": "#ffffff"},
    {"background": "#245842", "foreground": "#ffffff"},
    {"background": "#245842", "foreground": "#ffffff"},
    {"background": "#245842", "foreground": "#ffffff"},
    {"background": "#245842", "foreground": "#ffffff"},
]

# Base list form used for chart color cycling and palette access
APP_PRIMARY_COLORS = [step["background"] for step in APP_PRIMARY_SCALE]

# Shiny/color-blind graph palette for categorical chart colors.
# Use only when a chart needs multiple distinct colors.
SHINY_GRAPH_COLORS = [
    "#48A9C5",  # Azure Core
    "#319B42",  # Green Core
    "#EFB526",  # Yellow Core
    "#512C85",  # Purple Core
    "#E43F4F",  # Red Core
    "#707372",  # Grey Core
    "#2A6576",  # Azure Deep
    "#8F6D17",  # Yellow Deep
]

# Color palettes by number of items
COLOR_PALETTES = {
    8: SHINY_GRAPH_COLORS,
    7: SHINY_GRAPH_COLORS[:7],
    6: SHINY_GRAPH_COLORS[:6],
    5: SHINY_GRAPH_COLORS[:5],
    4: SHINY_GRAPH_COLORS[:4],
    3: SHINY_GRAPH_COLORS[:3],
}

# MSA Viewer nucleotide colors (Shiny app core palette)
NUCLEOTIDE_COLORS = {
    'A': '#319B42',  # Adenine - Green Core
    'G': '#EFB526',  # Guanine - Yellow Core
    'C': '#48A9C5',  # Cytosine - Azure Core
    'T': '#E43F4F',  # Thymine - Red Core
    '-': '#FFFFFF',  # Gap - White
    'N': '#C8CACA'   # Unknown - Grey Lite
}


def get_app_primary_scale():
    """Return the ordered app primary scale with foreground contrast mapping."""
    return APP_PRIMARY_SCALE


def get_app_ui_colors():
    """Return named app UI colors."""
    return {
        "navy": APP_NAVY,
        "blue": APP_BLUE,
        "card_header_bg": APP_CARD_HEADER_BG,
    }


def get_app_primary_colors():
    """Return app primary colors (light -> dark)."""
    return APP_PRIMARY_COLORS


def get_app_color_for_index(index):
    """Return an app primary color cycling through the 5-color set."""
    return APP_PRIMARY_COLORS[index % len(APP_PRIMARY_COLORS)]


def get_shiny_graph_colors():
    """Return the Shiny app graph palette."""
    return SHINY_GRAPH_COLORS


def get_shiny_graph_color_for_index(index):
    """Return a Shiny graph color cycling through the palette."""
    return SHINY_GRAPH_COLORS[index % len(SHINY_GRAPH_COLORS)]


def get_palette(n_items):
    """
    Get the appropriate color palette for n items

    Args:
        n_items: Number of items to be colored

    Returns:
        List of hex color codes
    """
    if n_items <= 3:
        return COLOR_PALETTES[3]
    elif n_items <= 4:
        return COLOR_PALETTES[4]
    elif n_items <= 5:
        return COLOR_PALETTES[5]
    elif n_items <= 6:
        return COLOR_PALETTES[6]
    elif n_items <= 7:
        return COLOR_PALETTES[7]
    else:
        return COLOR_PALETTES[8]


def get_color_for_index(index, total_items):
    """
    Get color for a specific index given total items

    Args:
        index: Zero-based index of the item
        total_items: Total number of items

    Returns:
        Hex color code
    """
    palette = get_palette(total_items)
    # Cycle through palette if more items than colors
    return palette[index % len(palette)]


def get_color_mapping(items):
    """
    Create a color mapping for a list of items

    Args:
        items: List of items to map colors to (e.g., chromosome names)

    Returns:
        Dictionary mapping item -> color
    """
    palette = get_palette(len(items))
    color_map = {}
    for i, item in enumerate(items):
        color_map[item] = palette[i % len(palette)]
    return color_map
