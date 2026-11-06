"""
HapSearch colors

App UI colors follow the landing page (landing/index.html) and the other
Breeding Insight apps; assets/app_theme.css holds the same values as CSS
variables. See color_palettes.md for how the chart palette was chosen.
"""

# App UI colors (keep in step with assets/app_theme.css)
APP_TEAL = "#066A73"
APP_TEAL_STRONG = "#054F56"
APP_INK = "#1B2733"
APP_INK_MUTED = "#4A5663"
APP_BORDER = "#D3E0E1"
APP_CARD_HEADER_BG = "#F4F8F8"

# Primary button backgrounds with their WCAG AA foregrounds
APP_PRIMARY_SCALE = [
    {"background": APP_TEAL, "foreground": "#ffffff"},
    {"background": APP_TEAL_STRONG, "foreground": "#ffffff"},
]

# Categorical chart colors, in fixed order. Slot 1 is a chart-weight brand teal
# (APP_TEAL is too muted to work as a series color) and slot 2 the brand green.
# This order passes the adjacent-pair color-vision checks for all eight slots
# and the all-pairs checks for the first three; assign slots in this order and
# never cycle past the end.
CHART_CATEGORICAL = [
    "#0094A3",  # teal
    "#2AA84A",  # green
    "#6A4FB3",  # violet
    "#E8692C",  # orange
    "#D64F8F",  # magenta
    "#C98500",  # gold
    "#2F6FD0",  # blue
    "#D93F3F",  # red
]

# Single-series charts (chromosome counts, density, accumulation) use one color:
# the axis labels and panel titles already identify each chromosome. It is a
# slate rather than the brand teal, so the many data marks don't make the whole
# app read as one color; teal stays an accent for actions and navigation.
CHART_SERIES = "#3D5A73"

# Genome-wide locus plot: chromosomes alternate between two slates (no hue per
# chromosome, so any number of chromosomes works) and the loci worth a look are
# highlighted in teal.
CHART_GENOME_ALTERNATE = ["#3D5A73", "#9AA8B4"]
CHART_HIGHLIGHT = CHART_CATEGORICAL[0]

# Sequential scale (light to dark teal) for the program-sharing heatmap: more
# shared alleles, darker cell.
CHART_HEATMAP_SCALE = ["#EEF6F6", "#0B4F57"]

# Projected part of the accumulation curve (dashed)
CHART_PROJECTION = "#7A818C"

# MSA viewer nucleotide colors. These carry biological meaning, so they stay
# independent of the app theme.
NUCLEOTIDE_COLORS = {
    'A': '#319B42',  # Adenine - green
    'G': '#EFB526',  # Guanine - yellow
    'C': '#48A9C5',  # Cytosine - azure
    'T': '#E43F4F',  # Thymine - red
    '-': '#FFFFFF',  # Gap - white
    'N': '#C8CACA'   # Unknown - grey
}

