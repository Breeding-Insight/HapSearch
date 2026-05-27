# HaploSearch Color Palette Design

## Overview
These color palettes are visually equidistant and designed for optimal data visualization across different numbers of categories. Use the appropriate palette based on the number of items being displayed.

## App UI Primary Palette (WCAG AA)

Use this palette for Dash app interface controls (buttons, button states, and chart accents on the Overview page). Do not use this section for landing page styling.

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
- Overview charts should use `get_app_primary_colors()` or `get_app_color_for_index()` for consistent color cycling.

### Overview Chart Color Policy
- **Microhaplotype Counts per Chromosome**: use a single bar color to emphasize value and label readability over category color encoding.
- **Allele Density Across Chromosome Positions**: use `OKABE_ITO_COLORS` for per-chromosome chart colors (colorblind-friendly categorical distinction).
- **Microhaplotype Accumulation Curve**: keep a single line/fill color.

### Allowed Supporting Colors
To support interactive states while keeping base colors unchanged, derived/support colors are allowed for:
- focus rings
- transparent fills in charts
- disabled-state opacity adjustments

## Color Palettes

### 8 Colors
Use when displaying 8 or more categories (e.g., 8+ chromosomes)

```python
PALETTE_8 = [
    '#003f5c',  # Dark blue
    '#2f4b7c',  # Blue
    '#665191',  # Purple-blue
    '#a05195',  # Purple
    '#d45087',  # Pink-purple
    '#f95d6a',  # Pink-red
    '#ff7c43',  # Orange-red
    '#ffa600'   # Orange
]
```

### 7 Colors
Use when displaying exactly 7 categories

```python
PALETTE_7 = [
    '#003f5c',  # Dark blue
    '#374c80',  # Blue
    '#7a5195',  # Purple
    '#bc5090',  # Pink-purple
    '#ef5675',  # Pink
    '#ff764a',  # Orange-red
    '#ffa600'   # Orange
]
```

### 6 Colors
Use when displaying exactly 6 categories

```python
PALETTE_6 = [
    '#003f5c',  # Dark blue
    '#444e86',  # Blue
    '#955196',  # Purple
    '#dd5182',  # Pink
    '#ff6e54',  # Orange-red
    '#ffa600'   # Orange
]
```

### 5 Colors
Use when displaying exactly 5 categories

```python
PALETTE_5 = [
    '#003f5c',  # Dark blue
    '#58508d',  # Blue-purple
    '#bc5090',  # Pink-purple
    '#ff6361',  # Red-orange
    '#ffa600'   # Orange
]
```

### 4 Colors
Use when displaying exactly 4 categories

```python
PALETTE_4 = [
    '#003f5c',  # Dark blue
    '#7a5195',  # Purple
    '#ef5675',  # Pink
    '#ffa600'   # Orange
]
```

### 3 Colors
Use when displaying exactly 3 categories

```python
PALETTE_3 = [
    '#003f5c',  # Dark blue
    '#bc5090',  # Pink-purple
    '#ffa600'   # Orange
]
```

## Usage Guidelines

### Chromosome Charts
Apply colors based on the number of chromosomes in the dataset:
- Sort chromosomes alphabetically first
- Assign colors in palette order
- For >8 chromosomes, cycle through the 8-color palette

### Position Density Charts
Use `OKABE_ITO_COLORS` for per-chromosome categorical distinction. This keeps dense multi-chromosome area charts readable and colorblind-friendly.

### MSA Viewer

**Nucleotide Colors** (fixed for biological meaning):
- **A (Adenine)**: `#4CAF50` (green)
- **G (Guanine)**: `#FFB300` (yellow/orange)
- **C (Cytosine)**: `#2196F3` (blue)
- **T (Thymine)**: `#E53935` (red)
- **Gap (-)**: `#FFFFFF` (white)
- **Unknown (N)**: `#E0E0E0` (light gray)

**Variant Type Colors** (use 3-color palette):
- SNP: `#bc5090` (pink-purple)
- Indel: `#ffa600` (orange)
- Target_SNP: `#003f5c` (dark blue)

## Implementation

All color palettes are defined in `design/colors.py` for consistent access:

```python
from design.colors import COLOR_PALETTES, NUCLEOTIDE_COLORS, get_color_mapping

# For chromosome charts
chromosomes = ['chr1', 'chr2', 'chr3', 'chr4', 'chr5']
color_map = get_color_mapping(chromosomes)
# Returns: {'chr1': '#003f5c', 'chr2': '#58508d', 'chr3': '#bc5090', ...}

# For MSA viewer nucleotides
base_color = NUCLEOTIDE_COLORS['A']  # Returns '#CA3C25'

# For variant type colors
variant_colors = COLOR_PALETTES[3]
snp_color = variant_colors[1]      # '#bc5090'
indel_color = variant_colors[2]    # '#ffa600'
target_color = variant_colors[0]   # '#003f5c'
```

### Example Usage in Plotly

```python
from design.colors import get_color_mapping, NUCLEOTIDE_COLORS

# Bar chart with chromosome colors
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
- **Perceptually uniform**: Colors are equally distinguishable
- **Color-blind friendly**: Works well for most types of color blindness
- **Print-friendly**: Good contrast in both color and grayscale
- **Professional**: Modern, clean appearance
- **Consistent**: Same color scheme across entire application
