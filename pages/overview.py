"""Overview Page - Overview dashboard with key visualizations

This page provides a comprehensive overview with:
- Chromosome microhaplotype counts visualization
- Allele density across chromosome positions
- Microhaplotype accumulation curve

Goals 2 & 3 (marker and haplotype search) are available in dedicated explorer tabs.
"""

from dash import dcc, html, Input, Output, State, ctx, no_update, MATCH
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
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
    get_species_snapshot,
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
                    dcc.Loading(
                        dcc.Graph(id='overview-chromosome-chart', config={'displayModeBar': False}),
                        type="default"
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
                    dcc.Loading(
                        html.Div(id='overview-species-snapshot'),
                        type="default"
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
                    dcc.Loading(
                        html.Div(id='overview-position-density-grid'),
                        type="default"
                    )
                ])
            ], className="mb-4")
        ], width=12)
    ]),

    # Microhaplotype Accumulation Curve
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-line me-2"),
                    "Microhaplotype Accumulation Curve",
                    html.Small(
                        " (Cumulative unique microhaplotypes discovered per sample)",
                        className="text-muted ms-2"
                    )
                ]),
                dbc.CardBody([
                    dcc.Loading(
                        dcc.Graph(
                            id='overview-accumulation-chart',
                            config={'displayModeBar': False}
                        ),
                        type="default"
                    )
                ])
            ])
        ], width=12)
    ])

], fluid=True)


# Callbacks

OVERVIEW_BRAND_DARK_GREEN = "#245842"
OVERVIEW_DENSITY_COLOR = OVERVIEW_BRAND_DARK_GREEN
OVERVIEW_SINGLE_COLOR = OVERVIEW_BRAND_DARK_GREEN

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a #RRGGBB color string to rgba(r,g,b,a)."""
    rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"


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
    {'key': 'rare_alleles',           'label': 'Rare microhapotypes',   'icon': 'fas fa-gem',
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
                                'fontSize': '1.45rem',
                                'fontWeight': '700',
                                'lineHeight': '1.15',
                                'color': '#212529',
                            }
                        ),
                        html.Div(
                            label_children,
                            style={
                                'fontSize': '0.76rem',
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
                'minHeight': '78px',
                'padding': '0.75rem 0.9rem',
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


@app.callback(
    Output('overview-accumulation-chart', 'figure'),
    Input('selected-species-store', 'data')
)
def update_accumulation_curve(species_id):
    """Cumulative unique microhaplotype discovery curve across samples."""
    empty = go.Figure().update_layout(template="plotly_white")

    if not species_id:
        empty.update_layout(title="Please select a species")
        return empty

    try:
        db = DatabaseManager()
        with db.shared_connection():
            rows = get_microhaplotype_accumulation_data(db, species_id)

        if not rows:
            empty.update_layout(title="No sample-microhaplotype data available")
            return empty

        x_vals = [row['sample_index'] for row in rows]
        y_vals = [row['cumulative_unique_microhaplotypes'] for row in rows]

        # Track project transitions to optionally render separators.
        project_boundaries = []
        current_project = None
        for row in rows:
            pid = row['project_id']
            if pid != current_project:
                project_boundaries.append({
                    'x': row['sample_index'],
                    'name': row['project_name'],
                })
                current_project = pid

        # Label boundaries compactly for readability on large datasets:
        # keep "Validation" as-is, number all other projects as #1, #2, ...
        project_number = 1
        for boundary in project_boundaries:
            project_name = (boundary.get('name') or '').strip()
            if project_name.lower() == 'validation':
                boundary['label'] = 'Validation'
            else:
                boundary['label'] = f"#{project_number}"
                project_number += 1

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode='lines',
            line=dict(color=OVERVIEW_SINGLE_COLOR, width=2),
            fill='tozeroy',
            fillcolor=_hex_to_rgba(OVERVIEW_SINGLE_COLOR, 0.12),
            hovertemplate=(
                '<b>Sample #%{x}</b><br>'
                'Unique microhaplotypes: %{y:,}<extra></extra>'
            ),
        ))

        # Keep figure payload bounded for large datasets.
        max_boundary_lines = 80
        max_boundary_annotations = 20
        boundary_count = len(project_boundaries)
        if boundary_count <= max_boundary_lines:
            for i, boundary in enumerate(project_boundaries):
                annotate = boundary_count <= max_boundary_annotations
                line_kwargs = {
                    'x': boundary['x'],
                    'line_dash': 'dash',
                    'line_color': '#000000',
                    'line_width': 1.5,
                }
                if annotate:
                    line_kwargs.update({
                        'annotation_text': boundary['label'],
                        'annotation_position': 'top',
                        'annotation_textangle': -35,
                        'annotation_font_size': 10,
                        'annotation_font_color': '#000000',
                    })
                fig.add_vline(**line_kwargs)

        y_max = max(y_vals) * 1.15 if y_vals else 1

        fig.update_layout(
            xaxis_title="Cumulative Samples",
            yaxis_title="Unique Microhaplotypes",
            xaxis=dict(fixedrange=True),
            yaxis=dict(range=[0, y_max], fixedrange=True),
            template="plotly_white",
            height=400,
            showlegend=False,
            dragmode=False,
            margin=dict(t=60),
        )

        return fig

    except Exception as e:
        empty.update_layout(title=f"Error: {str(e)}")
        return empty
