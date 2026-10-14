"""Overview Page - Overview dashboard with key visualizations

This page provides a comprehensive overview with:
- Chromosome microhaplotype counts visualization
- Allele density across chromosome positions
- Microhaplotype accumulation curve

Goals 2 & 3 (marker and haplotype search) are available in dedicated explorer tabs.
"""

from dash import dcc, html, Input, Output, State, ctx, no_update
import dash_bootstrap_components as dbc
import math
import re
import statistics
from collections import Counter

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import app for callback registration
from dash_app import app

from database import allele_filter
from database.db_manager import DatabaseManager
from database.queries import (
    get_database_statistics,
    get_allele_density_by_position,
    get_microhaplotype_accumulation_data,
    get_species_snapshot,
)
from design.colors import (
    APP_BORDER,
    APP_INK,
    APP_INK_MUTED,
    APP_TEAL,
    CHART_GENOME_ALTERNATE,
    CHART_HIGHLIGHT,
    CHART_PROJECTION,
    CHART_SERIES,
    CHART_HEATMAP_SCALE,
)

# Outline of the selected cell or bar on the sharing chart: orange stands out
# against the teal scale at every shade.
SELECTION_COLOR = "#E8692C"

# Loci at or above this percentile of alleles per locus are highlighted.
HIGHLIGHT_PERCENTILE = 99
PLOT_STATIC_CONFIG = {"displayModeBar": False}
ACCUMULATION_PROJECTION_SAMPLES = 4000
ACCUMULATION_MAX_PLOT_POINTS = 1200


def _overview_loading(children, class_name="overview-loading-region"):
    return dcc.Loading(
        html.Div(children, className=class_name),
        type="circle",
        color=APP_TEAL,
        # Quick updates (e.g. changing the allele filter) shouldn't flash a
        # spinner over the chart; slow ones still show it.
        delay_show=500,
    )


def _plot_export_controls(
    chart_key,
    graph_id,
    filename,
    default_width=10,
    default_height=6,
):
    """Build BIGapp-style image export controls for a Plotly chart."""
    return html.Div(
        [
            dbc.DropdownMenu(
                [
                    html.Div(
                        [
                            html.H6("Save Image", className="mb-3"),
                            html.Label("File", className="fw-bold small mb-1"),
                            dbc.Select(
                                id=f"overview-{chart_key}-image-type",
                                options=[
                                    {"label": "jpeg", "value": "jpeg"},
                                    {"label": "png", "value": "png"},
                                    {"label": "svg", "value": "svg"},
                                ],
                                value="png",
                                size="sm",
                                className="mb-3",
                            ),
                            html.Label("Resolution", className="fw-bold small mb-1"),
                            dbc.Input(
                                id=f"overview-{chart_key}-image-res",
                                type="number",
                                value=300,
                                min=50,
                                max=1000,
                                step=50,
                                size="sm",
                                className="mb-3",
                            ),
                            html.Label("Width", className="fw-bold small mb-1"),
                            dbc.Input(
                                id=f"overview-{chart_key}-image-width",
                                type="number",
                                value=default_width,
                                min=1,
                                max=20,
                                step=0.5,
                                size="sm",
                                className="mb-3",
                            ),
                            html.Label("Height", className="fw-bold small mb-1"),
                            dbc.Input(
                                id=f"overview-{chart_key}-image-height",
                                type="number",
                                value=default_height,
                                min=1,
                                max=20,
                                step=0.5,
                                size="sm",
                                className="mb-3",
                            ),
                            html.Button(
                                [html.I(className="fas fa-download me-2"), "Save Image"],
                                id=f"overview-{chart_key}-save-image-btn",
                                type="button",
                                className="btn btn-primary btn-sm w-100",
                                **{
                                    "data-overview-export-chart": chart_key,
                                    "data-overview-export-graph": graph_id,
                                    "data-overview-export-filename": filename,
                                },
                            ),
                        ],
                        className="px-3 py-2",
                        style={"width": "300px"},
                    ),
                ],
                label=[html.I(className="fas fa-floppy-disk me-2"), "Save"],
                color="secondary",
                toggle_class_name="haplo-action-btn",
                size="sm",
                align_end=True,
                className="d-inline-block",
            ),
            html.Div(id=f"overview-{chart_key}-export-status", style={"display": "none"}),
        ],
        className="d-flex justify-content-end mb-2",
    )

# Layout
# Overview: how alleles are shared between the selected programs. Clicking the
# chart sets the global allele filter that the other tabs follow.
layout = dbc.Container([
    # Microhaplotype sharing between programs
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-circle-nodes me-2"),
                    "Alleles Shared Between Programs"
                ]),
                dbc.CardBody([
                    html.Div([
                        html.Div(id='overview-sharing-summary'),
                        _plot_export_controls(
                            "sharing",
                            graph_id="overview-sharing-chart",
                            filename="microhaplotype_sharing_distribution",
                            default_width=11,
                            default_height=7.5,
                        ),
                    ], className="d-flex justify-content-between align-items-start gap-3 mb-2"),
                    html.Div(id='overview-filter-status', className="overview-filter-status mb-2"),
                    _overview_loading(
                        dcc.Graph(
                            id='overview-sharing-chart',
                            config=PLOT_STATIC_CONFIG
                        ),
                        "overview-loading-region overview-sharing-loading-region",
                    ),
                    dcc.Store(id='overview-sharing-chart-state'),
                ])
            ], className="h-100 w-100")
        ], width=12, className="mb-4 d-flex")
    ], className="g-3"),

], fluid=True)

# Database Overview: the panel and database as a whole.
database_layout = dbc.Container([
    # Alleles per locus + Species Snapshot
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-column me-2"),
                    "Alleles per Locus"
                ]),
                dbc.CardBody([
                    _overview_loading(
                        dcc.Graph(id='overview-allele-distribution-chart', config={'displayModeBar': False}),
                        "overview-loading-region overview-top-loading-region",
                    )
                ])
            ], className="h-100 w-100")
        ], lg=7, width=12, className="d-flex"),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-seedling me-2"),
                    "Species Snapshot"
                ]),
                dbc.CardBody([
                    _overview_loading(
                        html.Div(id='overview-species-snapshot'),
                        "overview-loading-region overview-top-loading-region",
                    )
                ], className="d-flex")
            ], className="h-100 w-100")
        ], lg=5, width=12, className="d-flex")
    ], className="mb-4 g-3 align-items-stretch"),

    # Genome-wide alleles per locus
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-area me-2"),
                    "Alleles per Locus Across the Genome",
                ]),
                dbc.CardBody([
                    html.Div(id='overview-genome-plot-caption', className="small mb-2"),
                    _overview_loading(
                        dcc.Graph(id='overview-genome-plot', config={'displayModeBar': False}),
                        "overview-loading-region overview-genome-loading-region",
                    )
                ])
            ], className="mb-4")
        ], width=12)
    ]),

    # Microhaplotype accumulation
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-line me-2"),
                    "Microhaplotype Accumulation Curve",
                ]),
                dbc.CardBody([
                    dbc.Button(
                        [html.I(className="fas fa-play me-2"), "Load Curve"],
                        id="overview-load-accumulation-btn",
                        color="primary",
                        size="sm",
                        className="mb-2",
                    ),
                    _plot_export_controls(
                        "accumulation",
                        graph_id="overview-accumulation-chart",
                        filename="microhaplotype_accumulation_curve",
                        default_width=10,
                        default_height=6,
                    ),
                    _overview_loading(
                        dcc.Graph(
                            id='overview-accumulation-chart',
                            config=PLOT_STATIC_CONFIG,
                            responsive=True,  # fill the full-width card
                        ),
                        "overview-loading-region overview-graph-loading-region",
                    )
                ])
            ], className="h-100 w-100")
        ], width=12, className="mb-4 d-flex")
    ], className="g-3 align-items-stretch")

], fluid=True)


# Callbacks

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a #RRGGBB color string to rgba(r,g,b,a)."""
    rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"


def _fit_accumulation_curve(x_vals, y_vals, projection_samples=0):
    """Fit y = y0 + (A - y0) * (1 - exp(-k * (x - x0)))."""
    if len(x_vals) < 4 or len(y_vals) < 4:
        return None

    x = np.asarray(x_vals, dtype=float)
    y = np.asarray(y_vals, dtype=float)
    finite_mask = np.isfinite(x) & np.isfinite(y)
    x = x[finite_mask]
    y = y[finite_mask]
    if len(x) < 4:
        return None

    x0 = float(x[0])
    y0 = float(y[0])
    t = x - x0
    y_current_max = float(np.max(y))
    observed_gain = y_current_max - y0
    if observed_gain <= 0 or float(np.max(t)) <= 0:
        return None

    asymptote_candidates = y_current_max + observed_gain * np.geomspace(0.02, 4.0, 220)
    best_fit = None
    t_squared_sum = float(np.sum(t * t))
    if t_squared_sum <= 0:
        return None

    for asymptote in asymptote_candidates:
        denominator = asymptote - y0
        if denominator <= 0 or np.any(asymptote <= y):
            continue

        ratios = (asymptote - y) / denominator
        if np.any(ratios <= 0):
            continue

        log_ratios = np.log(ratios)
        k = -float(np.sum(t * log_ratios) / t_squared_sum)
        if not np.isfinite(k) or k <= 0:
            continue

        fitted_y = y0 + (asymptote - y0) * (1 - np.exp(-k * t))
        sse = float(np.sum((y - fitted_y) ** 2))
        if best_fit is None or sse < best_fit["sse"]:
            best_fit = {
                "asymptote": float(asymptote),
                "k": k,
                "sse": sse,
                "fitted_y": fitted_y,
            }

    if not best_fit:
        return None

    sst = float(np.sum((y - float(np.mean(y))) ** 2))
    r_squared = 1 - (best_fit["sse"] / sst) if sst > 0 else None
    x_fit_max = float(np.max(x)) + max(float(projection_samples), 0)
    x_fit = np.linspace(float(np.min(x)), x_fit_max, 300)
    t_fit = x_fit - x0
    y_fit = y0 + (best_fit["asymptote"] - y0) * (1 - np.exp(-best_fit["k"] * t_fit))

    return {
        "x": x_fit.tolist(),
        "y": y_fit.tolist(),
        "x0": x0,
        "y0": y0,
        "asymptote": best_fit["asymptote"],
        "k": best_fit["k"],
        "r_squared": r_squared,
        "observed_x_max": float(np.max(x)),
        "projected_x_max": x_fit_max,
    }


def _downsample_accumulation_rows(accumulation_rows, max_points=ACCUMULATION_MAX_PLOT_POINTS):
    """Keep a deterministic, first-to-last sample of large accumulation curves."""
    row_count = len(accumulation_rows)
    if max_points <= 0 or row_count <= max_points:
        return accumulation_rows

    sampled_indices = np.linspace(0, row_count - 1, max_points, dtype=int)
    return [accumulation_rows[index] for index in np.unique(sampled_indices)]



def _natural_key(value):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value))]


def _message_figure(message, height=300):
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        height=height,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[dict(text=message, showarrow=False, font=dict(color=APP_INK))],
    )
    return fig


def _highlight_threshold(allele_counts):
    """Smallest allele count in the top HIGHLIGHT_PERCENTILE of loci."""
    return max(2, int(math.ceil(np.percentile(allele_counts, HIGHLIGHT_PERCENTILE))))


def _allele_distribution_figure(allele_counts, highlight_min):
    """Histogram of alleles per locus; the highlighted tail is one bar."""
    histogram = Counter(allele_counts)
    first = min(allele_counts)
    values = list(range(first, highlight_min))
    labels = [str(value) for value in values] + [f"≥{highlight_min}"]
    loci = [histogram.get(value, 0) for value in values]
    loci.append(sum(n for value, n in histogram.items() if value >= highlight_min))
    colors = [CHART_SERIES] * len(values) + [CHART_HIGHLIGHT]

    fig = go.Figure(go.Bar(
        x=labels,
        y=loci,
        marker_color=colors,
        hovertemplate="%{x} alleles: %{y:,} loci<extra></extra>",
    ))

    median = statistics.median(allele_counts)
    if first <= median < highlight_min:
        median_x = median - first  # category index on the x-axis
        fig.add_shape(
            type="line", xref="x", yref="paper",
            x0=median_x, x1=median_x, y0=0, y1=1,
            line=dict(color=APP_INK, width=1, dash="dot"),
        )
        fig.add_annotation(
            x=median_x, y=1, xref="x", yref="paper",
            text=f"median {median:g}", showarrow=False,
            xanchor="left", yanchor="top", xshift=4,
            font=dict(color=APP_INK, size=11),
        )
    fig.add_annotation(
        x=len(labels) - 1, y=loci[-1], xref="x", yref="y",
        text=f"top {100 - HIGHLIGHT_PERCENTILE}%", showarrow=False,
        yanchor="bottom", yshift=4, font=dict(color=APP_INK, size=11),
    )
    fig.update_layout(
        template="plotly_white",
        height=300,
        bargap=0.12,
        showlegend=False,
        dragmode=False,
        margin=dict(t=20, l=55, r=15, b=45),
        xaxis=dict(title="Alleles per locus", type="category", fixedrange=True,
                   tickangle=0, nticks=20),
        yaxis=dict(title="Loci", fixedrange=True, automargin=True),
    )
    return fig


def _genome_locus_figure(rows, highlight_min):
    """Alleles per locus along the genome, chromosomes laid end to end."""
    by_chrom = {}
    for row in rows:
        by_chrom.setdefault(row['chromosome_name'], []).append(row)
    chromosomes = sorted(by_chrom, key=_natural_key)
    longest = max(max(r['position'] or 0 for r in by_chrom[c]) for c in chromosomes)
    gap = longest * 0.03

    series = {0: ([], [], []), 1: ([], [], []), 'highlight': ([], [], [])}
    tick_values, tick_text = [], []
    offset = 0
    for index, chrom in enumerate(chromosomes):
        loci = by_chrom[chrom]
        chrom_end = max(r['position'] or 0 for r in loci)
        for row in loci:
            key = 'highlight' if row['allele_count'] >= highlight_min else index % 2
            xs, ys, data = series[key]
            xs.append(offset + (row['position'] or 0))
            ys.append(row['allele_count'])
            data.append([row['marker_id'], chrom, row['position'] or 0])
        total = sum(r['allele_count'] for r in loci)
        tick_values.append(offset + chrom_end / 2)
        tick_text.append(f"{chrom}<br><span style='font-size:10px'>{total:,}</span>")
        offset += chrom_end + gap

    hover = (
        "<b>%{customdata[0]}</b><br>"
        "%{customdata[1]}: %{customdata[2]:,} bp<br>"
        "%{y} alleles<extra></extra>"
    )
    fig = go.Figure()
    for key in (0, 1):
        xs, ys, data = series[key]
        fig.add_trace(go.Scattergl(
            x=xs, y=ys, customdata=data, mode="markers",
            marker=dict(size=4, color=CHART_GENOME_ALTERNATE[key]),
            hovertemplate=hover, showlegend=False,
        ))
    xs, ys, data = series['highlight']
    fig.add_trace(go.Scattergl(
        x=xs, y=ys, customdata=data, mode="markers",
        marker=dict(size=7, color=CHART_HIGHLIGHT, line=dict(width=1, color="#ffffff")),
        hovertemplate=hover, showlegend=False,
    ))
    fig.add_hline(
        y=highlight_min, line=dict(color=CHART_HIGHLIGHT, width=1, dash="dot"),
        annotation_text=f"top {100 - HIGHLIGHT_PERCENTILE}% (≥{highlight_min} alleles)",
        annotation_position="top left",
        annotation_font=dict(color=APP_INK, size=11),
    )
    fig.update_layout(
        template="plotly_white",
        height=380,
        dragmode="zoom",
        hovermode="closest",
        margin=dict(t=20, l=55, r=15, b=70),
        xaxis=dict(title="Chromosome (microhaplotype count)", tickmode="array",
                   tickvals=tick_values, ticktext=tick_text,
                   showgrid=False, zeroline=False, range=[-gap, offset]),
        yaxis=dict(title="Alleles per locus", fixedrange=True, rangemode="tozero"),
    )
    return fig


@app.callback(
    Output('overview-allele-distribution-chart', 'figure'),
    Output('overview-genome-plot', 'figure'),
    Output('overview-genome-plot-caption', 'children'),
    Input('selected-species-store', 'data')
)
def update_locus_charts(species_id):
    """Alleles per locus: overall distribution and along the genome."""
    if not species_id:
        message = "Please select a species"
        return _message_figure(message), _message_figure(message, 380), ""

    try:
        db = DatabaseManager()
        with db.shared_connection():
            rows = get_allele_density_by_position(db, species_id)
        if not rows:
            message = "No locus data available"
            return _message_figure(message), _message_figure(message, 380), ""

        allele_counts = [row['allele_count'] for row in rows]
        highlight_min = _highlight_threshold(allele_counts)
        caption = [
            html.Div([
                "Each dot is a locus, placed by its position along the genome and its number of alleles. ",
                html.Span("Teal dots", style={'color': CHART_HIGHLIGHT, 'fontWeight': '700'}),
                f" are the top {100 - HIGHLIGHT_PERCENTILE}% (≥{highlight_min} alleles).",
            ]),
            html.Div([
                html.Span([html.I(className="fas fa-hand-pointer me-1"), "Click a dot to open its alignment"],
                          className="me-3"),
                html.Span([html.I(className="fas fa-magnifying-glass-plus me-1"), "Drag to zoom"],
                          className="me-3"),
                html.Span([html.I(className="fas fa-rotate-left me-1"), "Double-click to reset"]),
            ], className="mt-1", style={'color': APP_INK_MUTED}),
        ]
        return (
            _allele_distribution_figure(allele_counts, highlight_min),
            _genome_locus_figure(rows, highlight_min),
            caption,
        )

    except Exception as e:
        message = f"Error: {str(e)}"
        return _message_figure(message), _message_figure(message, 380), ""


@app.callback(
    Output('navigate-to-marker-store', 'data', allow_duplicate=True),
    Output('main-tabs', 'active_tab', allow_duplicate=True),
    Input('overview-genome-plot', 'clickData'),
    prevent_initial_call=True
)
def open_clicked_locus(click_data):
    """Open a clicked locus in the Multiple Sequence Alignment tab.

    Switches the tab here rather than through navigate_between_tabs, whose
    guard ignores navigation until the user has left the first tab once; a
    click on the plot is always a deliberate action.
    """
    points = (click_data or {}).get('points') or []
    if not points or not points[0].get('customdata'):
        return no_update, no_update
    return {'marker_id': points[0]['customdata'][0]}, 'marker-tab'


SNAPSHOT_TILES = [
    {'key': 'marker_count',           'label': 'Loci',                  'icon': 'fas fa-map-marker-alt'},
    {'key': 'microhaplotype_count',   'label': 'Microhaplotypes',       'icon': 'fas fa-dna'},
    {'key': 'avg_alleles_per_marker', 'label': 'Avg. microhapotypes / Loci', 'icon': 'fas fa-layer-group'},
    {'key': 'sample_count',           'label': 'Samples',               'icon': 'fas fa-vial'},
    {'key': 'project_count',          'label': 'Contributing Projects', 'icon': 'fas fa-folder-open'},
    {'key': 'rare_microhaplotypes',   'label': 'Rare microhapotypes',   'icon': 'fas fa-gem',
     'tooltip': 'Microhapotypes observed in only one sample across all projects'},
]


_snapshot_tile_counter = {'n': 0}


def _snapshot_tile(icon_cls: str, value, label: str, tooltip: str = None):
    """Build a single stat tile for the species snapshot."""
    label_children = [label]
    extra_children = []

    if tooltip:
        tip_id = f"snapshot-tip-{_snapshot_tile_counter['n']}"
        _snapshot_tile_counter['n'] += 1
        label_children.append(
            html.I(
                className="fas fa-info-circle ms-1",
                id=tip_id,
                style={
                    'fontSize': '0.72rem',
                    'color': APP_INK_MUTED,
                    'cursor': 'pointer',
                },
            )
        )
        extra_children.append(
            dbc.Tooltip(tooltip, target=tip_id, placement="top")
        )

    return dbc.Col(
        html.Div(
            [
                html.I(
                    className=icon_cls,
                    style={
                        'fontSize': '1.15rem',
                        'color': APP_INK_MUTED,
                        'flexShrink': '0',
                    },
                ),
                html.Div(
                    [
                        html.Div(
                            str(value),
                            style={
                                'fontSize': '1.28rem',
                                'fontWeight': '700',
                                'lineHeight': '1.15',
                                'color': APP_INK,
                            }
                        ),
                        html.Div(
                            label_children,
                            style={
                                'fontSize': '0.72rem',
                                'color': APP_INK,
                                'lineHeight': '1.2',
                            }
                        ),
                    ],
                ),
                *extra_children,
            ],
            style={
                'display': 'flex',
                'alignItems': 'center',
                'gap': '0.55rem',
                'flex': '1 1 auto',
                'minHeight': '62px',
                'padding': '0.55rem 0.75rem',
                'backgroundColor': '#ffffff',
                'borderRadius': '8px',
                'border': f'1px solid {APP_BORDER}',
            }
        ),
        width=6,
        className="d-flex",
    )


@app.callback(
    Output('overview-species-snapshot', 'children'),
    Input('selected-species-store', 'data')
)
def update_species_snapshot(species_id):
    """Render the compact species snapshot stat tiles."""
    if not species_id:
        return dbc.Alert("Please select a species.", color="secondary")

    try:
        db = DatabaseManager()
        with db.shared_connection():
            snap = get_species_snapshot(db, species_id)

        if not snap:
            return dbc.Alert("No data available.", color="secondary")

        species_label = snap.get('species_label') or "Selected Species"
        _snapshot_tile_counter['n'] = 0
        tiles = []
        for t in SNAPSHOT_TILES:
            raw = snap.get(t['key'], 0)
            display = f"{raw:,}" if isinstance(raw, int) else str(raw)
            tiles.append(_snapshot_tile(t['icon'], display, t['label'], t.get('tooltip')))

        return html.Div(
            [
                html.Div(
                    [
                        html.I(
                            className="fas fa-seedling me-2",
                            style={'color': '#000000'},
                        ),
                        species_label,
                    ],
                    style={
                        'fontSize': '1.15rem',
                        'fontWeight': '700',
                        'color': '#000000',
                        'borderBottom': f'2px solid {APP_BORDER}',
                        'paddingBottom': '0.5rem',
                        'marginBottom': '0.25rem',
                        'textAlign': 'center',
                    }
                ),
                dbc.Row(
                    tiles,
                    className="g-2",
                    style={
                        'flex': '1 1 auto',
                        'alignContent': 'space-evenly',
                        'flexWrap': 'wrap',
                    }
                ),
            ],
            style={
                'display': 'flex',
                'flexDirection': 'column',
                'justifyContent': 'center',
                'height': '100%',
                'width': '100%',
            }
        )

    except Exception as e:
        return dbc.Alert(f"Error: {str(e)}", color="danger")


def _build_accumulation_figure(accumulation_rows):
    """Build the cumulative microhaplotype discovery curve."""
    plot_rows = _downsample_accumulation_rows(accumulation_rows)
    x_vals = [row['sample_index'] for row in plot_rows]
    y_vals = [row['cumulative_unique_microhaplotypes'] for row in plot_rows]
    hover_metadata = [
        (
            row.get("institution_label") or "Unknown institution",
            row.get("institution_location") or "Unknown location",
            row.get("project_name") or "Unknown project",
        )
        for row in plot_rows
    ]
    fit = _fit_accumulation_curve(
        x_vals,
        y_vals,
        projection_samples=ACCUMULATION_PROJECTION_SAMPLES,
    )
    observed_color = CHART_SERIES
    projection_color = CHART_PROJECTION

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=y_vals,
        customdata=hover_metadata,
        mode='lines',
        line=dict(color=observed_color, width=2),
        fill='tozeroy',
        fillcolor=_hex_to_rgba(observed_color, 0.12),
        name="Observed",
        hovertemplate=(
            '<b>Sample #%{x}</b><br>'
            'Institution: %{customdata[0]}<br>'
            'Location: %{customdata[1]}<br>'
            'Project: %{customdata[2]}<br>'
            'Cumulative unique microhaplotypes: %{y:,}<extra></extra>'
        ),
    ))

    y_max_candidates = list(y_vals)
    if fit:
        fig.add_trace(go.Scatter(
            x=fit["x"],
            y=fit["y"],
            mode='lines',
            line=dict(color=projection_color, width=2, dash="dash"),
            name="Projection",
            hovertemplate=(
                '<b>Projection</b><br>'
                'Sample: %{x:,.0f}<br>'
                'Estimated cumulative microhaplotypes: %{y:,.0f}<extra></extra>'
            ),
        ))
        y_max_candidates.extend(fit["y"])

    # Label the lines directly instead of using a legend.
    if x_vals:
        fig.add_annotation(
            x=x_vals[-1], y=y_vals[-1],
            text=(f"<b>Observed</b><br>{y_vals[-1]:,} microhaplotypes<br>"
                  f"from {x_vals[-1]:,} samples"),
            # Below the line, where the curve's last step won't run through it.
            showarrow=False, xanchor="right", yanchor="top", xshift=-6, yshift=-40,
            align="right", font=dict(color=APP_INK, size=11),
            bgcolor="rgba(255, 255, 255, 0.85)",
        )
    y_max = max(y_max_candidates) * 1.15 if y_max_candidates else 1
    fig.update_layout(
        xaxis_title="Samples added",
        yaxis_title="Cumulative unique microhaplotypes",
        xaxis=dict(
            range=[
                min(x_vals) if x_vals else 0,
                fit["projected_x_max"] if fit else (max(x_vals) if x_vals else 1),
            ],
            fixedrange=True,
            tickformat=",d",  # 15,000 rather than 15k
        ),
        yaxis=dict(
            range=[0, y_max],
            fixedrange=True,
            tickformat=",d",  # 35,000 rather than 35k
        ),
        template="plotly_white",
        height=500,
        showlegend=False,
        dragmode=False,
        margin=dict(t=25, l=65, r=20, b=55),
    )
    return fig


def _sharing_summary(sharing_data):
    """Alleles per program, private to each, and shared by each pair."""
    groups = sharing_data.get("owner_groups") or sharing_data.get("projects") or []
    ids = [group.get("group_id", group.get("project_id")) for group in groups]
    labels = [group["label"] for group in groups]
    index = {group_id: position for position, group_id in enumerate(ids)}
    n = len(ids)
    pair = [[0] * n for _ in range(n)]
    total = [0] * n
    private = [0] * n
    shared_by_all = 0
    for row in sharing_data.get("intersections") or []:
        count = int(row["microhaplotype_count"] or 0)
        members = [index[g] for g in (row.get("group_ids") or row.get("project_ids") or []) if g in index]
        if not members or not count:
            continue
        for i in members:
            total[i] += count
            for j in members:
                if i != j:
                    pair[i][j] += count
        if len(members) == 1:
            private[members[0]] += count
    # Programs with no alleles for this species would make "shared by all" zero
    # and add an empty row and column, so they are listed separately instead.
    keep = [i for i in range(n) if total[i]]
    empty = [labels[i] for i in range(n) if not total[i]]
    keep_set = set(keep)
    for row in sharing_data.get("intersections") or []:
        members = {index[g] for g in (row.get("group_ids") or row.get("project_ids") or []) if g in index}
        if len(keep) > 1 and members & keep_set == keep_set:
            shared_by_all += int(row["microhaplotype_count"] or 0)
    return {"ids": [ids[i] for i in keep],
            "labels": [labels[i] for i in keep],
            "pair": [[pair[i][j] for j in keep] for i in keep],
            "total": [total[i] for i in keep],
            "private": [private[i] for i in keep],
            "shared_by_all": shared_by_all,
            "empty": empty}


def _short_count(value):
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)


def _selection_shapes(ids, private, allele_filter_value):
    """Outline for the active filter: a pair's cell, or a program's private bar.

    Orange over a white halo, so it shows on dark and light cells alike.
    """
    position = {group_id: index for index, group_id in enumerate(ids)}
    value = allele_filter_value or ""
    rect = None
    if value.startswith("pair:"):
        first, _, second = value[len("pair:"):].partition("|")
        if first in position and second in position:
            row, column = max(position[first], position[second]), min(position[first], position[second])
            rect = dict(xref="x", yref="y", x0=column - 0.5, x1=column + 0.5, y0=row - 0.5, y1=row + 0.5)
    elif value.startswith("only:") and value[len("only:"):] in position:
        row = position[value[len("only:"):]]
        rect = dict(xref="x2", yref="y2", x0=0, x1=private[row], y0=row - 0.38, y1=row + 0.38)
    if rect is None:
        return []
    return [dict(type="rect", line=line, **rect)
            for line in (dict(color="#ffffff", width=6), dict(color=SELECTION_COLOR, width=3))]


def _build_sharing_figure(summary, allele_filter_value=None):
    """Pairwise shared alleles between programs, plus each program's private alleles.

    The active allele filter, if it is a pair or a single program, is outlined.
    """
    labels, pair, total, private = (
        summary[key] for key in ("labels", "pair", "total", "private"))
    n = len(labels)
    if n == 0:
        return _message_figure("No program sharing data available", 300)

    # The matrix is symmetric, so only the lower triangle is drawn: one cell
    # per pair. The last column would be empty, so it is dropped; the first
    # row stays (empty) so every row lines up with its bar on the right. Each
    # program's private alleles are in those bars.
    columns = range(n - 1)

    def share(i, j):
        return f"{pair[i][j] / total[i]:.0%} of {labels[i]}'s alleles" if total[i] else ""

    z = [[pair[i][j] if j < i else None for j in columns] for i in range(n)]
    upper = max([value for row in z for value in row if value is not None] or [1])
    text = [[_short_count(pair[i][j]) if j < i else "" for j in columns] for i in range(n)]
    cell_data = [[f"{share(i, j)}<br>{share(j, i)}" if j < i else "" for j in columns]
                 for i in range(n)]

    fig = make_subplots(rows=1, cols=2, column_widths=[0.55, 0.45], horizontal_spacing=0.06,
                        shared_yaxes=True)
    fig.add_trace(go.Heatmap(
        z=z, x=labels[:-1], y=labels, text=text, texttemplate="%{text}",
        # Rows carry numbered full names; columns show just the numbers.
        textfont=dict(size=11), customdata=cell_data,
        colorscale=[[0, CHART_HEATMAP_SCALE[0]], [1, CHART_HEATMAP_SCALE[1]]], zmin=0, zmax=upper,
        xgap=2, ygap=2, showscale=False, hoverongaps=False,
        hovertemplate="<b>%{y}</b> and <b>%{x}</b><br>%{z:,} shared alleles<br>"
                      "%{customdata}<br><i>Click to list these alleles</i><extra></extra>",
    ), row=1, col=1)

    shared = [total[i] - private[i] for i in range(n)]
    fig.add_trace(go.Bar(
        y=labels, x=private, orientation="h", name="Private to the program",
        marker=dict(color=CHART_HIGHLIGHT, line=dict(color="#ffffff", width=1)),
        hovertemplate="%{y}<br>%{x:,} private alleles<br>"
                      "<i>Click to list these alleles</i><extra></extra>",
    ), row=1, col=2)
    fig.add_trace(go.Bar(
        y=labels, x=shared, orientation="h", name="Shared with another program",
        marker=dict(color=CHART_GENOME_ALTERNATE[1], line=dict(color="#ffffff", width=1)),
        customdata=total,
        hovertemplate="%{y}<br>%{x:,} shared with another program<br>"
                      "%{customdata:,} alleles in total<extra></extra>",
    ), row=1, col=2)

    fig.update_layout(shapes=_selection_shapes(summary["ids"], private, allele_filter_value))

    # Label each program's bar at its end: private of total.
    for label, private_count, total_count in zip(labels, private, total):
        fig.add_annotation(
            x=total_count, y=label, xref="x2", yref="y2",
            text=f"{_short_count(private_count)} private of {_short_count(total_count)}",
            showarrow=False, xanchor="left", xshift=6,
            font=dict(color=APP_INK, size=11),
        )

    fig.update_layout(
        template="plotly_white",
        barmode="stack",
        height=140 + (60 if n <= 4 else 36) * n,
        dragmode=False,
        bargap=0.3,
        margin=dict(t=70, l=20, r=15, b=20),
        legend=dict(orientation="h", x=1, xanchor="right", y=1.0, yanchor="bottom",
                    traceorder="normal", font=dict(color=APP_INK, size=11)),
        font=dict(color=APP_INK),
    )
    numbers = [str(position + 1) for position in range(n - 1)]
    numbered = [f"{position + 1}  {label}" for position, label in enumerate(labels)]
    fig.update_xaxes(side="top", title_text="Alleles shared by each pair of programs",
                     title_font=dict(size=12, color=APP_INK),
                     fixedrange=True, automargin=True, constrain="domain",
                     tickmode="array", tickvals=labels[:-1], ticktext=numbers, row=1, col=1)
    # Square cells, however wide the card is.
    fig.update_yaxes(autorange="reversed", fixedrange=True, automargin=True,
                     scaleanchor="x", scaleratio=1, tickmode="array",
                     tickvals=labels, ticktext=numbered, row=1, col=1)
    fig.update_xaxes(fixedrange=True, showgrid=False, showticklabels=False,
                     range=[0, max(total) * 1.45 if any(total) else 1], row=1, col=2)
    return fig


def _sharing_headline(summary, allele_filter_value=None):
    """The "shared by all" filter button and how to use the chart."""
    n = len(summary["labels"])
    empty_note = None
    if summary["empty"]:
        empty_note = html.Div("No alleles for this species: " + ", ".join(summary["empty"]) + ".",
                              className="small mt-2")
    if n < 2:
        return empty_note
    active = allele_filter_value == allele_filter.ALL
    return html.Div([
        html.Button(
            [
                html.I(className="fas fa-filter me-2"),
                f"Shared by all {n} programs",
                html.Span(f"{summary['shared_by_all']:,}", className="sharing-all-count"),
            ],
            id='overview-filter-shared-all',
            type="button",
            className="btn btn-sm sharing-all-btn" + (" active" if active else ""),
            title="Filter to the alleles every selected program shares",
        ),
        html.Span(
            "or click a cell or a teal bar to filter the Microhaplotypes and "
            "Multiple Sequence Alignment tabs.",
            className="sharing-hint",
        ),
        empty_note,
    ], className="sharing-toolbar")


@app.callback(
    Output('global-allele-filter', 'value', allow_duplicate=True),
    Input('overview-filter-shared-all', 'n_clicks'),
    State('global-allele-filter', 'value'),
    prevent_initial_call=True
)
def filter_shared_by_all(n_clicks, current_value):
    """Toggle the "shared by every selected program" filter."""
    if not n_clicks:
        return no_update
    return allele_filter.ANY if current_value == allele_filter.ALL else allele_filter.ALL


def _empty_accumulation_figure(title="Load the accumulation curve when needed"):
    fig = go.Figure()
    fig.update_layout(
        title=title,
        template="plotly_white",
        height=500,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
        margin=dict(t=55, l=20, r=15, b=55),
    )
    return fig


@app.callback(
    Output('overview-accumulation-chart', 'figure'),
    Input('selected-species-store', 'data'),
    Input('overview-load-accumulation-btn', 'n_clicks'),
)
def update_accumulation_curve(species_id, n_clicks):
    """Cumulative unique microhaplotype discovery curve."""
    triggered_id = ctx.triggered_id

    if not species_id:
        return _empty_accumulation_figure("Please select a species")

    if triggered_id != "overview-load-accumulation-btn":
        return _empty_accumulation_figure("Click Load Curve to generate this plot")

    try:
        db = DatabaseManager()
        with db.shared_connection():
            rows = get_microhaplotype_accumulation_data(
                db,
                species_id,
                max_result_points=ACCUMULATION_MAX_PLOT_POINTS,
            )

        if not rows:
            return _empty_accumulation_figure("No sample-microhaplotype data available")

        return _build_accumulation_figure(rows)

    except Exception as e:
        return _empty_accumulation_figure(f"Error: {str(e)}")


@app.callback(
    Output('overview-sharing-summary', 'children'),
    Output('overview-sharing-chart', 'figure'),
    Output('overview-sharing-chart-state', 'data'),
    Input('selected-species-store', 'data'),
    Input('global-programs-dropdown', 'value'),
    Input('global-allele-filter', 'value'),
)
def update_sharing_chart(species_id, program_ids, allele_filter_value):
    """Alleles shared between the selected programs, with the active filter outlined.

    This is the only callback that writes the chart. Changing programs also
    resets the allele filter, re-triggering it while the first run may still
    be computing; Dash then keeps only the newer run, which carries both the
    current programs and the current filter. A second callback patching the
    same figure made Dash discard the slower full rebuild and leave the chart
    on the previous programs.
    """
    if not species_id:
        return "", _message_figure("Please select a species", 300), {}

    try:
        summary = _sharing_summary(allele_filter.sharing_data(int(species_id), program_ids))
        # Clicks report program names; label_ids maps them back to group ids.
        chart_state = {"label_ids": dict(zip(summary["labels"], summary["ids"]))}
        return (
            _sharing_headline(summary, allele_filter_value),
            _build_sharing_figure(summary, allele_filter_value),
            chart_state,
        )

    except Exception as e:
        return "", _message_figure(f"Error: {str(e)}", 300), {}


@app.callback(
    Output('global-allele-filter', 'value', allow_duplicate=True),
    Input('overview-sharing-chart', 'clickData'),
    State('overview-sharing-chart-state', 'data'),
    State('global-allele-filter', 'value'),
    prevent_initial_call=True
)
def filter_from_sharing_chart(click_data, chart_state, current_value):
    """Clicking a cell or a teal bar sets the global allele filter; clicking
    the selected one again clears it.

    Uses the clicked point's program names: Dash drops customdata for
    heatmap cells, whose point numbers are [row, column] pairs.
    """
    points = (click_data or {}).get('points') or []
    label_ids = (chart_state or {}).get("label_ids")
    if not points or not label_ids:
        return no_update
    point = points[0]
    row_label, column_label = point.get('y'), point.get('x')
    value = None
    if point.get('curveNumber') == 0 and row_label != column_label \
            and row_label in label_ids and column_label in label_ids:
        order = list(label_ids)  # chart order, which the filter options also use
        first, second = sorted((row_label, column_label), key=order.index)
        value = f"pair:{label_ids[first]}|{label_ids[second]}"
    elif point.get('curveNumber') == 1 and row_label in label_ids:
        value = f"only:{label_ids[row_label]}"
    if value is None:
        return no_update
    return allele_filter.ANY if value == current_value else value


@app.callback(
    Output('overview-filter-status', 'children'),
    Input('selected-species-store', 'data'),
    Input('global-programs-dropdown', 'value'),
    Input('global-allele-filter', 'value'),
    State('global-allele-filter', 'options'),
)
def show_filter_status(species_id, program_ids, allele_filter_value, options):
    """Say what the allele filter keeps and offer the tabs that use it."""
    if not species_id:
        return None
    try:
        kept = allele_filter.resolve_allele_filter(species_id, program_ids, allele_filter_value)
    except Exception as e:
        return dbc.Alert(f"Error: {str(e)}", color="danger")
    if kept is None:
        # No restriction: every allele in the selected programs.
        count = len(allele_filter.sharing_data(int(species_id), program_ids)
                    .get("microhaplotype_groups") or {})
        return html.Div([
            html.Span("Selected alleles:", className="selected-alleles-label"),
            html.Span([html.Strong("All alleles in the selected programs"), f" ({count:,})"]),
        ], className="selected-alleles")
    label = next((option['label'] for option in options or []
                  if option['value'] == allele_filter_value), "Selected programs")
    return html.Div([
        html.Span("Selected alleles:", className="selected-alleles-label"),
        html.Span([html.Strong(label), f" ({len(kept):,})"]),
        html.Button("Clear", id='overview-clear-filter', className="btn btn-link btn-sm p-0"),
        html.Span([
            html.Button([html.I(className="fas fa-magnifying-glass me-2"), "View in Microhaplotypes"],
                        id='overview-open-haplotypes', className="btn btn-primary btn-sm"),
            html.Button([html.I(className="fas fa-align-left me-2"), "View loci in Multiple Sequence Alignment"],
                        id='overview-open-alignment', className="btn btn-outline-secondary btn-sm haplo-action-btn"),
        ], className="selected-alleles-actions"),
    ], className="selected-alleles")


@app.callback(
    Output('global-allele-filter', 'value', allow_duplicate=True),
    Input('overview-clear-filter', 'n_clicks'),
    prevent_initial_call=True
)
def clear_allele_filter(n_clicks):
    return allele_filter.ANY if n_clicks else no_update


@app.callback(
    Output('main-tabs', 'active_tab', allow_duplicate=True),
    Input('overview-open-haplotypes', 'n_clicks'),
    Input('overview-open-alignment', 'n_clicks'),
    prevent_initial_call=True
)
def open_filtered_tab(haplotype_clicks, alignment_clicks):
    """Jump to a tab that follows the allele filter."""
    if ctx.triggered_id == 'overview-open-haplotypes' and haplotype_clicks:
        return 'haplotype-tab'
    if ctx.triggered_id == 'overview-open-alignment' and alignment_clicks:
        return 'marker-tab'
    return no_update
