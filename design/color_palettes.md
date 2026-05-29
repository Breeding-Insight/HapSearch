# HaploSearch Color Palette Design

## Overview
HaploSearch uses app UI colors for interface elements and single-color chart treatments. The Shiny/color-blind graph colors are reserved for charts that need multiple distinct categorical colors.

## App UI Primary Palette (WCAG AA)

Use this palette for Dash app interface controls (buttons, button states, and chart accents on the Overview page). Do not use this section for landing page styling.

### App UI Colors

```python
APP_NAVY = "#304C89"
APP_BLUE = "#648DE5"
APP_CARD_HEADER_BG = "#D8EAD8"
```

```python
APP_PRIMARY_SCALE = [
    {"background": "#245842", "foreground": "#ffffff"},
    {"background": "#245842", "foreground": "#ffffff"},
    {"background": "#245842", "foreground": "#ffffff"},
    {"background": "#245842", "foreground": "#ffffff"},
    {"background": "#245842", "foreground": "#ffffff"},
]
```

### Accessibility Notes
- This foreground mapping is locked to WCAG AA for normal text (minimum 4.5:1).
- All primary scale steps use white text for contrast.

### Dash App Usage
- Button theming is defined in `assets/app_theme.css`.
- Shared token definitions are defined in `design/colors.py`.
- Overview charts should use single app colors unless the chart requires multiple distinct categories.
- Use `get_shiny_graph_colors()`, `get_shiny_graph_color_for_index()`, or `get_color_mapping()` only for multicolor categorical charts.

### Overview Chart Color Policy
- **Microhaplotype Counts per Chromosome**: use a single bar color to emphasize value and label readability over category color encoding.
- **Allele Density Across Chromosome Positions**: use a single line/fill color unless explicit categorical comparison requires multicolor encoding.
- **Microhaplotype Accumulation Curve**: keep a single line/fill color.

### Allowed Supporting Colors
To support interactive states while keeping base colors unchanged, derived/support colors are allowed for:
- focus rings
- transparent fills in charts
- disabled-state opacity adjustments

## Color Palettes

Use these Shiny/color-blind palettes only when a chart needs multiple categorical colors.

### 8 Colors
Use when displaying 8 or more categories (e.g., 8+ chromosomes)

```python
PALETTE_8 = [
    '#48A9C5',  # Azure Core
    '#319B42',  # Green Core
    '#EFB526',  # Yellow Core
    '#512C85',  # Purple Core
    '#E43F4F',  # Red Core
    '#707372',  # Grey Core
    '#2A6576',  # Azure Deep
    '#8F6D17'   # Yellow Deep
]
```

### 7 Colors
Use when displaying exactly 7 categories

```python
PALETTE_7 = [
    '#48A9C5',  # Azure Core
    '#319B42',  # Green Core
    '#EFB526',  # Yellow Core
    '#512C85',  # Purple Core
    '#E43F4F',  # Red Core
    '#707372',  # Grey Core
    '#2A6576'   # Azure Deep
]
```

### 6 Colors
Use when displaying exactly 6 categories

```python
PALETTE_6 = [
    '#48A9C5',  # Azure Core
    '#319B42',  # Green Core
    '#EFB526',  # Yellow Core
    '#512C85',  # Purple Core
    '#E43F4F',  # Red Core
    '#707372'   # Grey Core
]
```

### 5 Colors
Use when displaying exactly 5 categories

```python
PALETTE_5 = [
    '#48A9C5',  # Azure Core
    '#319B42',  # Green Core
    '#EFB526',  # Yellow Core
    '#512C85',  # Purple Core
    '#E43F4F'   # Red Core
]
```

### 4 Colors
Use when displaying exactly 4 categories

```python
PALETTE_4 = [
    '#48A9C5',  # Azure Core
    '#319B42',  # Green Core
    '#EFB526',  # Yellow Core
    '#512C85'   # Purple Core
]
```

### 3 Colors
Use when displaying exactly 3 categories

```python
PALETTE_3 = [
    '#48A9C5',  # Azure Core
    '#319B42',  # Green Core
    '#EFB526'   # Yellow Core
]
```

## Usage Guidelines

### Chromosome Charts
Use one app chart color by default. Apply multicolor categorical palettes only when chromosome identity needs color encoding:
- Sort chromosomes alphabetically first
- Assign colors in palette order
- For >8 chromosomes, cycle through the 8-color palette

### Position Density Charts
Use one app chart color by default. Use `SHINY_GRAPH_COLORS` only when multiple chromosome traces are shown in the same chart and need categorical distinction.

### MSA Viewer

**Nucleotide Colors** (fixed for biological meaning, using Shiny app core colors):
- **A (Adenine)**: `#319B42` (green core)
- **G (Guanine)**: `#EFB526` (yellow core)
- **C (Cytosine)**: `#48A9C5` (azure core)
- **T (Thymine)**: `#E43F4F` (red core)
- **Gap (-)**: `#FFFFFF` (white)
- **Unknown (N)**: `#C8CACA` (grey lite)

**Variant Type Colors** (use 3-color palette):
- SNP: `#319B42` (green core)
- Indel: `#EFB526` (yellow core)
- Target_SNP: `#48A9C5` (azure core)

## Implementation

All color palettes are defined in `design/colors.py` for consistent access:

```python
from design.colors import APP_CARD_HEADER_BG, COLOR_PALETTES, NUCLEOTIDE_COLORS, get_color_mapping

# For app section/card headers
header_fill = APP_CARD_HEADER_BG  # Returns '#D8EAD8'

# For multicolor categorical chromosome charts
chromosomes = ['chr1', 'chr2', 'chr3', 'chr4', 'chr5']
color_map = get_color_mapping(chromosomes)
# Returns: {'chr1': '#48A9C5', 'chr2': '#319B42', 'chr3': '#EFB526', ...}

# For MSA viewer nucleotides
base_color = NUCLEOTIDE_COLORS['A']  # Returns '#319B42'

# For variant type colors
variant_colors = COLOR_PALETTES[3]
snp_color = variant_colors[1]      # '#319B42'
indel_color = variant_colors[2]    # '#EFB526'
target_color = variant_colors[0]   # '#48A9C5'
```

### Example Usage in Plotly

```python
from design.colors import get_color_mapping, NUCLEOTIDE_COLORS

# Multicolor categorical bar chart
sorted_chroms = sorted(['chr1', 'chr2', 'chr3'])
color_map = get_color_mapping(sorted_chroms)

fig = go.Figure(data=[
    go.Bar(
        x=sorted_chroms,
        y=counts,
        marker_color=[color_map[c] for c in sorted_chroms]
    )
])

# MSA heatmap
fig = go.Figure(data=go.Heatmap(
    colorscale=[
        [0, NUCLEOTIDE_COLORS['A']],
        [0.2, NUCLEOTIDE_COLORS['T']],
        [0.4, NUCLEOTIDE_COLORS['G']],
        [0.6, NUCLEOTIDE_COLORS['C']],
        [0.8, NUCLEOTIDE_COLORS['-']],
        [1.0, NUCLEOTIDE_COLORS['N']]
    ]
))
```

## Benefits
- **Brand-consistent**: Keeps app UI colors as the default visual language
- **Readable with labels**: Works well where charts include labels, letters, or hover text
- **Print-friendly**: Good contrast in both color and grayscale
- **Professional**: Modern, clean appearance
- **Consistent**: Same color scheme across entire application
