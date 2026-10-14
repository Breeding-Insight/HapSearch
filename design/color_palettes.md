# HapSearch colors

HapSearch shares its look with its landing page (`landing/index.html`) and the
other Breeding Insight apps (HapApp, AlloMate). The values live in two places,
kept in step by hand:

- `assets/app_theme.css`: CSS variables for the app's UI
- `design/colors.py`: the same values for Python (charts and inline styles)

## App UI

| Token | Hex | Use |
|---|---|---|
| `APP_TEAL` / `--app-teal` | `#066A73` | Buttons, links, active tab, icons, focus rings |
| `APP_TEAL_STRONG` / `--app-teal-strong` | `#054F56` | Hover and pressed states |
| `APP_INK` / `--app-ink` | `#1B2733` | Body text |
| `APP_INK_MUTED` / `--app-ink-muted` | `#4A5663` | Secondary text in the header |
| `APP_BORDER` / `--app-border` | `#D3E0E1` | Card and input borders, dividers |
| `APP_CARD_HEADER_BG` / `--app-surface-alt` | `#F4F8F8` | Card header bars |
| `--app-footer-bg` | `#0C3237` | Footer |

White text on both teals passes WCAG AA for normal text
(`tests/test_color_accessibility.py`).

The wordmark in the header uses the logo's two colors, as HapApp's does:
"Hap" `#115C55` and "Search" `#25A244`.

## Charts

Teal is the app's accent, so most data is drawn in neutral slates and color is
kept for marks that mean something. That keeps the app from reading as one
color.

### Single series

Alleles-per-locus histogram bars and the observed accumulation curve use
`CHART_SERIES` (`#3D5A73`, slate). The projected part of the accumulation curve
is `CHART_PROJECTION` (`#7A818C`), dashed.

### Highlight

`CHART_HIGHLIGHT` (`#0094A3`, chart teal) marks the data worth a closer look:
the top 1% of loci by allele count (in the histogram and the genome plot), the
"private" part of each program's bar on the Filter by Programs tab, and, in the
alignment, the alleles that match the allele filter.

### Genome-wide alleles per locus

Chromosomes alternate between the two `CHART_GENOME_ALTERNATE` slates
(`#3D5A73`, `#9AA8B4`), the usual Manhattan-plot convention. It needs no hue per
chromosome, so it works for any number of chromosomes (strawberry has 28).

### Program sharing heatmap

A sequential scale from `CHART_HEATMAP_SCALE[0]` (`#EEF6F6`) to
`CHART_HEATMAP_SCALE[1]` (`#0B4F57`): the more alleles two programs share, the
darker the cell. Shared-with-another-program bars are the light slate. The
selected cell or bar is outlined in orange (`#E8692C`) over a white halo, which
stands out against every shade of the scale.

### Categorical palette

Use `CHART_CATEGORICAL` when color is the only thing telling series apart.
Assign slots in order and never cycle past the end. A ninth series should be
folded into "Other" or split into separate charts.

| Slot | Hue | Hex |
|---|---|---|
| 1 | teal | `#0094A3` |
| 2 | green | `#2AA84A` |
| 3 | violet | `#6A4FB3` |
| 4 | orange | `#E8692C` |
| 5 | magenta | `#D64F8F` |
| 6 | gold | `#C98500` |
| 7 | blue | `#2F6FD0` |
| 8 | red | `#D93F3F` |

Slot 1 is a chart-weight version of the brand teal: `#066A73` is too muted to
read as a hue (OKLCH chroma 0.08, below the 0.10 floor). Slot 2 is the brand
green.

The order was chosen by checking every ordering of these hues with the
data-viz palette validator, on a white chart surface:

- all eight slots, adjacent pairs: worst color-vision ΔE 14.0 (target ≥ 8),
  worst normal-vision ΔE 15.2 (floor 15)
- first three slots, all pairs: worst color-vision ΔE 14.2, normal-vision 15.4
- every slot reaches 3:1 contrast against white

So the first three slots are safe wherever all of them appear together; past
three, rely on adjacency (bars, stacks, lines) or add direct labels.

### Nucleotides

The alignment views keep their own nucleotide colors (`NUCLEOTIDE_COLORS`),
which follow sequence-viewer convention and are independent of the theme.
