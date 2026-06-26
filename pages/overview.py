"""Overview Page - Overview dashboard with key visualizations

This page provides a comprehensive overview with:
- Chromosome microhaplotype counts visualization
- Allele density across chromosome positions
- Microhaplotype accumulation curve

Goals 2 & 3 (marker and haplotype search) are available in dedicated explorer tabs.
"""

from dash import dcc, html, Input, Output, State, ctx, no_update, MATCH
import dash_bootstrap_components as dbc
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import app for callback registration
from dash_app import app

from database.db_manager import DatabaseManager
from database.queries import (
    get_chromosome_counts,
    get_database_statistics,
    get_allele_density_by_position,
    get_microhaplotype_accumulation_data,
    get_microhaplotype_project_sharing_data,
    get_species_snapshot,
)

OVERVIEW_BRAND_DARK_GREEN = "#245842"
OVERVIEW_DENSITY_COLOR = OVERVIEW_BRAND_DARK_GREEN
OVERVIEW_SINGLE_COLOR = OVERVIEW_BRAND_DARK_GREEN
PLOT_STATIC_CONFIG = {"displayModeBar": False}
ACCUMULATION_PROJECTION_SAMPLES = 4000
ACCUMULATION_MAX_PLOT_POINTS = 1200


def _overview_loading(children, class_name="overview-loading-region"):
    return dcc.Loading(
        html.Div(children, className=class_name),
        type="circle",
        color="#319B42",
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
                color="danger",
                size="sm",
                align_end=True,
                className="d-inline-block",
            ),
            html.Div(id=f"overview-{chart_key}-export-status", style={"display": "none"}),
        ],
        className="d-flex justify-content-end mb-2",
    )

# Layout
layout = dbc.Container([
    #Chromosome Counts + Species Snapshot
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-bar me-2"),
                    "Microhaplotype Counts per Chromosome"
                ]),
                dbc.CardBody([
                    _overview_loading(
                        dcc.Graph(id='overview-chromosome-chart', config={'displayModeBar': False}),
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

    # Microhapotype Density Visualization
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-area me-2"),
                    "Microhapotypes Density Across Chromosome Positions",
                    html.Small(" (microhapotypes counts at each genomic position)", className="text-muted ms-2")
                ]),
                dbc.CardBody([
                    _overview_loading(
                        html.Div(id='overview-position-density-grid'),
                        "overview-loading-region overview-density-loading-region",
                    )
                ])
            ], className="mb-4")
        ], width=12)
    ]),

    # Microhaplotype Accumulation + Sharing Distribution
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
                        color="danger",
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
                            config=PLOT_STATIC_CONFIG
                        ),
                        "overview-loading-region overview-graph-loading-region",
                    )
                ])
            ], className="h-100 w-100")
        ], lg=6, width=12, className="mb-4 d-flex"),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-circle-nodes me-2"),
                    "Microhaplotype Sharing Distribution"
                ]),
                dbc.CardBody([
                    html.Div(
                        [
                            html.Label(
                                "Programs",
                                htmlFor="overview-sharing-program-groups",
                                className="fw-bold small mb-1",
                            ),
                            dcc.Dropdown(
                                id="overview-sharing-program-groups",
                                options=[],
                                value=[],
                                multi=True,
                                clearable=False,
                                placeholder="Choose programs",
                            ),
                        ],
                        className="mb-3",
                    ),
                    _plot_export_controls(
                        "sharing",
                        graph_id="overview-sharing-chart",
                        filename="microhaplotype_sharing_distribution",
                        default_width=11,
                        default_height=7.5,
                    ),
                    _overview_loading(
                        dcc.Graph(
                            id='overview-sharing-chart',
                            config=PLOT_STATIC_CONFIG
                        ),
                        "overview-loading-region overview-graph-loading-region",
                    )
                ])
            ], className="h-100 w-100")
        ], lg=6, width=12, className="mb-4 d-flex")
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


def _build_density_color_map(items):
    """Map chromosome names to the shared density chart color."""
    return {item: OVERVIEW_DENSITY_COLOR for item in items}

@app.callback(
    Output('overview-chromosome-chart', 'figure'),
    Input('selected-species-store', 'data')
)
def update_chromosome_chart(species_id):
    """Update chromosome counts visualization (Goal 1)"""
    if not species_id:
        return go.Figure().update_layout(
            title="Please select a species",
            template="plotly_white"
        )

    try:
        db = DatabaseManager()
        with db.shared_connection():
            counts = get_chromosome_counts(db, species_id)

        if not counts:
            return go.Figure().update_layout(
                title="No data available",
                template="plotly_white"
            )

        # Get chromosome names and counts
        chromosomes = [c['chromosome_name'] for c in counts]
        microhap_counts = [c['microhaplotype_count'] for c in counts]

        # Single-color bars for readability across chromosome labels
        bar_color = OVERVIEW_SINGLE_COLOR
        colors = [bar_color for _ in chromosomes]

        # Create bar chart
        fig = go.Figure(data=[
            go.Bar(
                x=chromosomes,
                y=microhap_counts,
                marker_color=colors,
                text=microhap_counts,
                textposition='outside',
                cliponaxis=False,
            )
        ])

        # Calculate y-axis range with padding for text labels
        max_count = max(microhap_counts) if microhap_counts else 0
        # Add extra headroom so outside text isn't clipped
        y_max = max_count * 1.30  # 30% padding at top for labels

        fig.update_layout(
            xaxis_title="Chromosome",
            yaxis_title="Microhaplotype Count",
            xaxis=dict(fixedrange=True),
            yaxis=dict(range=[0, y_max], fixedrange=True, automargin=True),
            template="plotly_white",
            height=300,
            showlegend=False,
            dragmode=False
        )

        return fig

    except Exception as e:
        return go.Figure().update_layout(
            title=f"Error: {str(e)}",
            template="plotly_white"
        )


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
                    'color': '#245842',
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
                        'color': '#245842',
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
                                'color': '#212529',
                            }
                        ),
                        html.Div(
                            label_children,
                            style={
                                'fontSize': '0.72rem',
                                'color': '#1f2933',
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
                'border': '1px solid #245842',
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
                        'borderBottom': '2px solid #245842',
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


def _chrom_density_figure(chrom: str, positions, counts, chrom_color: str) -> go.Figure:
    """Create a single-chromosome microhapotypes density figure."""
    x_min = min(positions) if positions else 0
    x_max = max(positions) if positions else 1
    y_min = 0
    y_max = (max(counts) * 1.1) if counts else 1

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=positions,
            y=counts,
            mode='lines',
            fill='tozeroy',
            name=chrom,
            line=dict(color=chrom_color, width=1.5),
            fillcolor=_hex_to_rgba(chrom_color, 0.30),
            hovertemplate='<b>Position:</b> %{x:,}<br><b>Microhapotypes:</b> %{y}<extra></extra>',
            showlegend=False
        )
    )

    fig.update_layout(
        template='plotly_white',
        height=260,
        margin=dict(l=45, r=15, t=15, b=35),
        hovermode='x',
        # Box-drag zoom should only affect x; y stays full via fixedrange=True on y-axis
        dragmode='zoom',
        meta={'original_x_range': [x_min, x_max]}
    )

    fig.update_xaxes(
        title_text="Position",
        showgrid=True,
        gridcolor='lightgray',
        range=[x_min, x_max],
        fixedrange=False
    )
    fig.update_yaxes(
        title_text="Microhapotypes Count",
        showgrid=True,
        gridcolor='lightgray',
        range=[y_min, y_max],
        fixedrange=True
    )

    return fig


@app.callback(
    Output('overview-position-density-grid', 'children'),
    Input('selected-species-store', 'data')
)
def update_position_density_grid(species_id):
    """Render per-chromosome density charts (one Graph per chromosome)."""
    if not species_id:
        return dbc.Alert("Please select a species to view microhapotypes density.", color="secondary")

    try:
        db = DatabaseManager()
        with db.shared_connection():
            density_data = get_allele_density_by_position(db, species_id)
        if not density_data:
            return dbc.Alert("No position data available.", color="secondary")

        # Group by chromosome
        chromosomes = {}
        for row in density_data:
            chrom = row['chromosome_name']
            chromosomes.setdefault(chrom, {'positions': [], 'counts': []})
            chromosomes[chrom]['positions'].append(row['position'])
            chromosomes[chrom]['counts'].append(row['allele_count'])

        sorted_chrom_names = sorted(chromosomes.keys())
        color_map = _build_density_color_map(sorted_chrom_names)

        cards = []
        for chrom in sorted_chrom_names:
            data = chromosomes[chrom]
            fig = _chrom_density_figure(chrom, data['positions'], data['counts'], color_map[chrom])

            cards.append(
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader(
                            html.Div([
                                html.Span(chrom, className="fw-bold"),
                                dbc.Button(
                                    [html.I(className="fas fa-undo me-1"), "Reset"],
                                    id={'type': 'density-reset-btn', 'chrom': chrom},
                                    color="secondary",
                                    size="sm",
                                    outline=True,
                                    className="haplo-action-btn"
                                )
                            ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center'})
                        ),
                        dbc.CardBody(
                            dcc.Graph(
                                id={'type': 'density-chrom-graph', 'chrom': chrom},
                                figure=fig,
                                config={'displayModeBar': False}
                            )
                        )
                    ], className="h-100"),
                    width=12,
                    md=6,
                    lg=4,
                    className="mb-3"
                )
            )

        return dbc.Row(cards)

    except Exception as e:
        return dbc.Alert(f"Error loading density charts: {str(e)}", color="danger")


@app.callback(
    Output({'type': 'density-chrom-graph', 'chrom': MATCH}, 'figure'),
    Input({'type': 'density-reset-btn', 'chrom': MATCH}, 'n_clicks'),
    State({'type': 'density-chrom-graph', 'chrom': MATCH}, 'figure'),
    prevent_initial_call=True
)
def reset_density_chrom(_n_clicks, fig_dict):
    """Reset x-zoom for a single chromosome chart."""
    if not fig_dict:
        return no_update
    meta = (fig_dict.get('layout') or {}).get('meta') or {}
    orig = meta.get('original_x_range')
    if not (isinstance(orig, list) and len(orig) == 2):
        return no_update

    import copy
    out = copy.deepcopy(fig_dict)
    out.setdefault('layout', {}).setdefault('xaxis', {})['range'] = orig
    return out


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

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=y_vals,
        customdata=hover_metadata,
        mode='lines',
        line=dict(color=OVERVIEW_SINGLE_COLOR, width=2),
        fill='tozeroy',
        fillcolor=_hex_to_rgba(OVERVIEW_SINGLE_COLOR, 0.12),
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
            line=dict(color="#6b7280", width=2, dash="dash"),
            name="Projection",
            hovertemplate=(
                '<b>Projection</b><br>'
                'Sample: %{x:,.0f}<br>'
                'Estimated cumulative microhaplotypes: %{y:,.0f}<extra></extra>'
            ),
        ))
        y_max_candidates.extend(fit["y"])

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
        ),
        yaxis=dict(
            range=[0, y_max],
            fixedrange=True,
        ),
        template="plotly_white",
        height=500,
        showlegend=False,
        dragmode=False,
        margin=dict(t=25, l=65, r=20, b=55),
    )
    return fig


def _build_sharing_figure(sharing_data):
    """Build the owner-group sharing distribution chart."""
    projects = sharing_data.get("owner_groups") or sharing_data.get("projects") or []
    intersections = sharing_data.get("intersections") or []

    if not intersections or not projects:
        return go.Figure().update_layout(
            title="No project sharing data available",
            template="plotly_white",
            height=500,
        )

    fig = make_subplots(
        rows=2,
        cols=2,
        specs=[
            [{}, {}],
            [{}, {}],
        ],
        column_widths=[0.24, 0.76],
        row_heights=[0.62, 0.38],
        horizontal_spacing=0.02,
        vertical_spacing=0.04,
    )

    pattern_step = 1
    pattern_x = list(range(1, len(intersections) + 1))
    bar_counts = [row["microhaplotype_count"] for row in intersections]
    project_ids = [
        project.get("group_id", project.get("project_id"))
        for project in projects
    ]
    project_labels = [project["label"] for project in projects]
    project_names = {
        project.get("group_id", project.get("project_id")): (
            project.get("owner_name") or project.get("project_name")
        )
        for project in projects
    }
    project_labels_by_id = dict(zip(project_ids, project_labels))
    intersection_hover_data = [
        [
            {
                "common": "Common",
                "rare": "Rare",
                "private": "Private",
            }.get(row.get("category"), row.get("category", "").title()),
            " + ".join(
                project_labels_by_id.get(group_id, str(group_id))
                for group_id in (row.get("group_ids") or row.get("project_ids") or [])
            ),
        ]
        for row in intersections
    ]
    category_colors = {
        "common": OVERVIEW_BRAND_DARK_GREEN,
        "rare": "#4f7f74",
        "private": "#6b7280",
    }
    empty_category_colors = {
        "common": "#d8e1dd",
        "rare": "#dce7e5",
        "private": "#e5e7eb",
    }
    bar_colors = [
        category_colors.get(row["category"], OVERVIEW_SINGLE_COLOR)
        if count
        else empty_category_colors.get(row["category"], "#e5e7eb")
        for row, count in zip(intersections, bar_counts)
    ]
    fig.add_trace(
        go.Bar(
            x=pattern_x,
            y=bar_counts,
            marker_color=bar_colors,
            width=0.55,
            text=[count if count else "" for count in bar_counts],
            textposition="outside",
            textfont=dict(
                size=11,
                family="Arial, sans-serif",
                color="#1f2933",
            ),
            cliponaxis=False,
            customdata=intersection_hover_data,
            hovertemplate=(
                "<b>%{y:,} microhaplotypes</b><br>"
                "%{customdata[0]} intersection<br>"
                "%{customdata[1]}<extra></extra>"
            ),
        ),
        row=1,
        col=2,
    )

    group_counts = {project_id: 0 for project_id in project_ids}
    for row in intersections:
        count = int(row["microhaplotype_count"] or 0)
        active_ids = row.get("group_ids") or row.get("project_ids") or []
        for project_id in active_ids:
            if project_id in group_counts:
                group_counts[project_id] += count

    row_step = 1
    y_positions = [index * row_step for index in range(len(project_ids))]
    project_y = {
        project_id: y_position
        for project_id, y_position in zip(project_ids, y_positions)
    }
    fig.add_trace(
        go.Bar(
            x=[group_counts[project_id] for project_id in project_ids],
            y=y_positions,
            orientation="h",
            marker_color=OVERVIEW_SINGLE_COLOR,
            width=0.28,
            customdata=project_labels,
            hovertemplate="%{customdata}: %{x:,} microhaplotypes<extra></extra>",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    all_bg_x = []
    all_bg_y = []
    for x in pattern_x:
        for y in y_positions:
            all_bg_x.append(x)
            all_bg_y.append(y)

    fig.add_trace(
        go.Scatter(
            x=all_bg_x,
            y=all_bg_y,
            mode="markers",
            marker=dict(size=5, color="#d8d8d8"),
            hoverinfo="skip",
            showlegend=False,
        ),
        row=2,
        col=2,
    )

    active_x = []
    active_y = []
    active_text = []
    for x, row in zip(pattern_x, intersections):
        active_ids = row.get("group_ids") or row.get("project_ids") or []
        ys = [project_y[pid] for pid in active_ids if pid in project_y]
        if len(ys) > 1:
            fig.add_trace(
                go.Scatter(
                    x=[x, x],
                    y=[min(ys), max(ys)],
                    mode="lines",
                    line=dict(color="#333333", width=1),
                    hoverinfo="skip",
                    showlegend=False,
                ),
                row=2,
                col=2,
            )
        for pid in active_ids:
            if pid not in project_y:
                continue
            active_x.append(x)
            active_y.append(project_y[pid])
            active_text.append(project_names.get(pid, f"Owner {pid}"))

    fig.add_trace(
        go.Scatter(
            x=active_x,
            y=active_y,
            mode="markers",
            marker=dict(size=6, color="#333333"),
            text=active_text,
            hovertemplate="%{text}<extra></extra>",
            showlegend=False,
        ),
        row=2,
        col=2,
    )

    start = 0
    while start < len(intersections):
        category = intersections[start]["category"]
        end = start
        while end + 1 < len(intersections) and intersections[end + 1]["category"] == category:
            end += 1
        color = category_colors.get(category, OVERVIEW_SINGLE_COLOR)
        category_label = {
            "common": "Common",
            "rare": "Rare",
            "private": "Private",
        }.get(category, category.title())
        x0 = pattern_x[start] - (pattern_step / 2)
        x1 = pattern_x[end] + (pattern_step / 2)
        for subplot_row in (1, 2):
            fig.add_vrect(
                x0=x0,
                x1=x1,
                line_width=1,
                line_color=color,
                fillcolor=_hex_to_rgba(color, 0.035),
                row=subplot_row,
                col=2,
            )
        fig.add_annotation(
            x=(x0 + x1) / 2,
            y=1.08,
            xref="x2",
            yref="paper",
            text=f"<b>{category_label}</b>",
            showarrow=False,
            font=dict(
                color=color,
                size=13,
                family="Arial, sans-serif",
            ),
        )
        start = end + 1

    bar_y_max = max(max(bar_counts) * 1.25, 1) if bar_counts else 1
    group_x_max = max(max(group_counts.values()) * 1.15, 1) if group_counts else 1
    pattern_x_range = [0.5, len(intersections) + 0.5]
    fig.update_xaxes(visible=False, fixedrange=True, row=1, col=1)
    fig.update_yaxes(visible=False, fixedrange=True, row=1, col=1)
    fig.update_xaxes(
        showticklabels=False,
        range=pattern_x_range,
        fixedrange=True,
        row=1,
        col=2,
    )
    fig.update_yaxes(title_text="# Intersection alleles", range=[0, bar_y_max], fixedrange=True, row=1, col=2)
    fig.update_xaxes(
        title_text="# Alleles (Total)",
        range=[group_x_max, 0],
        fixedrange=True,
        row=2,
        col=1,
    )
    fig.update_yaxes(
        tickmode="array",
        tickvals=y_positions,
        ticktext=project_labels,
        range=[y_positions[-1] + 0.45, -0.45],
        fixedrange=True,
        row=2,
        col=1,
    )
    fig.update_xaxes(
        title_text="",
        tickmode="array",
        tickvals=pattern_x,
        ticktext=["" for _ in pattern_x],
        range=pattern_x_range,
        fixedrange=True,
        row=2,
        col=2,
    )
    fig.update_yaxes(
        showticklabels=False,
        range=[y_positions[-1] + 0.45, -0.45],
        fixedrange=True,
        row=2,
        col=2,
    )
    fig.update_layout(
        template="plotly_white",
        height=500,
        showlegend=False,
        dragmode=False,
        margin=dict(t=55, l=20, r=15, b=55),
        bargap=0.25,
    )
    return fig


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
    Output('overview-sharing-chart', 'figure'),
    Input('selected-species-store', 'data'),
    Input('overview-sharing-program-groups', 'value'),
)
def update_sharing_chart(species_id, selected_group_ids):
    """Owner-group microhaplotype sharing distribution."""
    empty = go.Figure().update_layout(template="plotly_white")

    if not species_id:
        empty.update_layout(title="Please select a species")
        return empty

    try:
        db = DatabaseManager()
        with db.shared_connection():
            sharing_data = get_microhaplotype_project_sharing_data(
                db,
                species_id,
                selected_group_ids=selected_group_ids,
            )

        return _build_sharing_figure(sharing_data)

    except Exception as e:
        empty.update_layout(title=f"Error: {str(e)}")
        return empty


@app.callback(
    Output('overview-sharing-program-groups', 'options'),
    Output('overview-sharing-program-groups', 'value'),
    Input('selected-species-store', 'data')
)
def update_sharing_group_options(species_id):
    """Populate selectable program groups for the sharing UpSet plot."""
    if not species_id:
        return [], []

    try:
        db = DatabaseManager()
        with db.shared_connection():
            sharing_data = get_microhaplotype_project_sharing_data(db, species_id)

        groups = sharing_data.get("available_owner_groups") or sharing_data.get("owner_groups") or []
        options = [
            {"label": group["label"], "value": group["group_id"]}
            for group in groups
        ]
        return options, sharing_data.get("default_group_ids") or [opt["value"] for opt in options[:3]]

    except Exception:
        return [], []
