"""
HaploSearch Color Palettes

Visually equidistant color palettes for data visualization.
See color_palettes.md for full documentation.
"""

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

# Okabe-Ito colorblind-safe palette (excluding black, used separately in charts)
OKABE_ITO_COLORS = [
    "#E69F00",  # Orange
    "#56B4E9",  # Sky Blue
    "#245842",  # Replaced bluish green per app theme request
    "#F0E442",  # Yellow
    "#0072B2",  # Blue
    "#D55E00",  # Vermillion
    "#CC79A7",  # Reddish Purple
]

# Color palettes by number of items
COLOR_PALETTES = {
    8: ['#003f5c', '#2f4b7c', '#665191', '#a05195', '#d45087', '#f95d6a', '#ff7c43', '#ffa600'],
    7: ['#003f5c', '#374c80', '#7a5195', '#bc5090', '#ef5675', '#ff764a', '#ffa600'],
    6: ['#003f5c', '#444e86', '#955196', '#dd5182', '#ff6e54', '#ffa600'],
    5: ['#003f5c', '#58508d', '#bc5090', '#ff6361', '#ffa600'],
    4: ['#003f5c', '#7a5195', '#ef5675', '#ffa600'],
    3: ['#003f5c', '#bc5090', '#ffa600']
}

# MSA Viewer nucleotide colors (Purine/Pyrimidine scheme)
NUCLEOTIDE_COLORS = {
    'A': '#4CAF50',  # Adenine (Purine) - Green
    'G': '#FFB300',  # Guanine (Purine) - Yellow/Orange
    'C': '#2196F3',  # Cytosine (Pyrimidine) - Blue
    'T': '#E53935',  # Thymine (Pyrimidine) - Red
    '-': '#FFFFFF',  # Gap - White
    'N': '#E0E0E0'   # Unknown - Light Gray
}


def get_app_primary_scale():
    """Return the ordered app primary scale with foreground contrast mapping."""
    return APP_PRIMARY_SCALE


def get_app_primary_colors():
    """Return app primary colors (light -> dark)."""
    return APP_PRIMARY_COLORS


def get_app_color_for_index(index):
    """Return an app primary color cycling through the 5-color set."""
    return APP_PRIMARY_COLORS[index % len(APP_PRIMARY_COLORS)]


def get_okabe_ito_colors():
    """Return the Okabe-Ito colorblind-safe palette."""
    return OKABE_ITO_COLORS


def get_okabe_ito_color_for_index(index):
    """Return an Okabe-Ito color cycling through the palette."""
    return OKABE_ITO_COLORS[index % len(OKABE_ITO_COLORS)]


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
