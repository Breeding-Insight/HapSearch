"""Haplotype Explorer - Split-view with inline sample and project display

Different from original: Integrated search and details in one view,
with expandable sample/project information
"""

import dash
from dash import dcc, html, Input, Output, State, no_update, ctx
import dash_bootstrap_components as dbc
import re
try:
    import dash_ag_grid as dag
except ImportError:  # pragma: no cover
    dag = None
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import app for callback registration
from dash_app import app

from database.db_manager import DatabaseManager
from database.queries import (
    get_microhaplotypes_paginated,
    get_microhaplotype_details,
    get_samples_for_microhaplotype,
    get_projects_for_microhaplotype,
    get_projects_for_allele_presence,
    get_projects_for_sample_presence,
    get_samples_for_allele,
    get_presence_statistics,
    get_species_sample_count,
    get_all_chromosomes_for_species,
    get_contacts_for_projects,
    _deduplicate_projects,
)
from pages.collaborator_rows import build_collaborator_rows_from_contacts


def _require_ag_grid():
    """Return (ok, component) where component is a fallback message if AG Grid is unavailable."""
    if dag is None:
        return False, dbc.Alert(
            "Dash AG Grid is not installed in this environment. Install 'dash-ag-grid' or rebuild the Docker image.",
            color="warning",
            className="mb-0"
        )
    return True, None


DEFAULT_FREQUENCY_RANGE = (0.0, 1.0)


def _resolve_frequency_bounds(freq_range):
    """Map UI slider values to query bounds. Default range means no filter."""
    if not isinstance(freq_range, (list, tuple)) or len(freq_range) != 2:
        return None, None
    min_freq = float(freq_range[0])
    max_freq = float(freq_range[1])
    if min_freq <= DEFAULT_FREQUENCY_RANGE[0] and max_freq >= DEFAULT_FREQUENCY_RANGE[1]:
        return None, None
    return min_freq, max_freq


def _is_missing_sample_context(species_sample_count):
    """True when the species has no samples in the database."""
    return int(species_sample_count or 0) <= 0


def _is_missing_sample_value(sample_count):
    """Treat zero/empty sample counts as missing for UI labels."""
    return int(sample_count or 0) <= 0





# Layout
layout = dbc.Container([
    # Store for left panel minimized state
    dcc.Store(id='haplotype-left-panel-minimized', data=False),
    # Store for results page
    dcc.Store(id='haplotype-results-page', data=1),
    # Stores for samples table data
    dcc.Store(id='samples-data-store', data=None),
    # Store for sample search filter
    dcc.Store(id='samples-search-filter', data=''),
    # Store for samples table page
    dcc.Store(id='samples-table-page', data=1),

    dbc.Row([
        # Left panel: Search and browse with separate scrolling
        dbc.Col([
            html.Div([
                # Filters section (not sticky)
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.H5([
                                html.I(className="fas fa-dna me-2", id='haplotype-search-icon'),
                                html.Span("Search & Browse", id='haplotype-search-title')
                            ], className="mb-0"),
                            dbc.Button(
                                html.I(className="fas fa-chevron-left", id='haplotype-minimize-icon'),
                                id='haplotype-minimize-btn',
                                color="link",
                                size="sm",
                                className="float-end p-0",
                                style={'color': '#000000', 'textDecoration': 'none'}
                            )
                        ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center', 'width': '100%'})
                    ]),
                    dbc.CardBody([
                        # Chromosome dropdown (like Marker Explorer / MSA)
                        html.Div([
                            html.Label("Chromosome:", className="fw-bold small", id='haplotype-chromosome-label'),
                            dcc.Dropdown(
                                id='haplotype-chromosome-filter',
                                placeholder="All chromosomes",
                                clearable=True,
                                searchable=True,
                                className="mb-3"
                            )
                        ], id='haplotype-chromosome-container'),

                        # Allele ID filter
                        html.Div([
                            html.Label("Allele ID:", className="fw-bold small", id='haplotype-marker-label'),
                            dbc.Input(
                                id='haplotype-marker-filter',
                                type='text',
                                placeholder='Search allele ID...',
                                debounce=True,
                                className="mb-3"
                            )
                        ], id='haplotype-marker-container'),

                        # Sequence search
                        html.Div([
                            html.Label("Sequence:", className="fw-bold small", id='haplotype-sequence-label'),
                            dbc.Input(
                                id='haplotype-sequence-search',
                                type='text',
                                placeholder='Search sequence...',
                                debounce=True,
                                className="mb-2"
                            )
                        ], id='haplotype-sequence-container')
                        ,

                        # Sample filter
                        html.Div([
                            html.Label("Sample:", className="fw-bold small", id='haplotype-sample-label'),
                            dbc.Input(
                                id='haplotype-sample-filter',
                                type='text',
                                placeholder='Search sample...',
                                debounce=True,
                                className="mb-2"
                            )
                        ], id='haplotype-sample-container'),

                        # Frequency range filter
                        html.Div([
                            html.Div([
                                html.Label([
                                    html.Span("Frequency range:"),
                                    html.I(
                                        className="fas fa-info-circle ms-1",
                                        id="haplotype-frequency-range-tooltip-target",
                                        style={'cursor': 'help'}
                                    ),
                                    dbc.Tooltip(
                                        "The proportion of samples containing this microhaplotype relative to the total number of samples for this species. Note: This represents sample frequency, not allelic frequency.",
                                        target="haplotype-frequency-range-tooltip-target",
                                        placement="top"
                                    )
                                ], className="fw-bold small mb-0", id='haplotype-frequency-label'),
                                dbc.Button(
                                    [html.I(className="fas fa-undo me-1"), "Reset"],
                                    id="haplotype-frequency-reset",
                                    color="secondary",
                                    size="sm",
                                    outline=True,
                                    style={"whiteSpace": "nowrap"},
                                    className="haplo-action-btn"
                                )
                            ], className="d-flex justify-content-between align-items-center"),
                            html.Div(
                                dcc.RangeSlider(
                                    id='haplotype-frequency-range',
                                    min=0.0,
                                    max=1.0,
                                    step=0.01,
                                    value=[0.0, 1.0],
                                    className="haplo-frequency-range-slider",
                                    marks={
                                        0.0: "0.0",
                                        0.25: "0.25",
                                        0.5: "0.5",
                                        0.75: "0.75",
                                        1.0: "1.0"
                                    },
                                    tooltip={"placement": "bottom", "always_visible": False}
                                ),
                                className="mt-1"
                            )
                        ], id='haplotype-frequency-container')
                    ], id='haplotype-filters-body')
                ], style={'flexShrink': '0'}, className="mb-2", id='haplotype-filters-card'),

                # Results section (no internal scrolling; page scroll only)
                dbc.Card([
                    dbc.CardBody([
                        html.Label("Results:", className="fw-bold small mb-2", id='haplotype-results-label'),
                        html.Div(id='haplotype-search-results'),
                        html.Div([
                            html.Div(id='haplotype-pagination-info', className="me-3 text-muted small align-self-center"),
                            dbc.Button(
                                html.I(className="fas fa-chevron-left"),
                                id='haplotype-page-prev',
                                color="secondary",
                                outline=True,
                                size="sm",
                                className="me-2 haplo-action-btn"
                            ),
                            html.Span(id='haplotype-page-indicator', className="text-muted small align-self-center me-2"),
                            dbc.Button(
                                html.I(className="fas fa-chevron-right"),
                                id='haplotype-page-next',
                                color="secondary",
                                outline=True,
                                size="sm",
                                className="haplo-action-btn"
                            )
                        ], className="mt-2 d-flex justify-content-center align-items-center", id='haplotype-pagination-container')
                    ])
                ], id='haplotype-results-card')
            ], style={'display': 'flex', 'flexDirection': 'column'}, id='haplotype-left-panel-content')
        ], id='haplotype-left-col', width=3),

        # Right panel: Details
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5([
                    html.I(className="fas fa-info-circle me-2"),
                    "Microhaplotype Details"
                ])),
                dbc.CardBody([
                    # Keep details content as a stable in-card region and avoid loading overlay
                    # flash when selecting a new microhaplotype.
                    html.Div(
                        "Select a microhaplotype result to view details",
                        className="text-muted",
                        id='haplotype-detail-content'
                    ),

                    # Samples section lives in the base layout (stable IDs; not recreated on keystrokes)
                    html.Div([
                        html.Hr(),
                        html.Div([
                            dbc.Button([
                                html.I(className="fas fa-leaf me-2"),
                                "Samples (0)",
                                html.I(className="fas fa-chevron-down ms-2", id='samples-chevron')
                            ], id='toggle-samples', color="secondary", outline=True, size="sm", className="mb-2 haplo-action-btn")
                        ]),
                        html.Div([
                            # Search input for samples table
                            html.Div([
                                html.Label("Search samples:", className="fw-bold small mb-2"),
                                dbc.Input(
                                    id='samples-search-input',
                                    type='text',
                                    placeholder='Search samples...',
                                    debounce=True,
                                    className="mb-3"
                                )
                            ], id='samples-search-container'),
                            # Samples table
                            html.Div(id='samples-table-body'),
                            # Pagination for samples table
                            html.Div([
                                html.Div(id='samples-pagination-info', className="me-3 text-muted small align-self-center"),
                                dbc.Pagination(
                                    id='samples-pagination',
                                    max_value=1,
                                    first_last=True,
                                    previous_next=True,
                                    size="sm",
                                    fully_expanded=False,
                                    active_page=1,
                                    style={'display': 'none'}
                                )
                            ], className="mt-2 d-flex justify-content-center align-items-center", id='samples-pagination-container')
                        ], id='samples-collapse', style={'display': 'none'})
                    ], id='samples-section-wrapper', style={'display': 'none'})
                ])
            ])
        ], id='haplotype-right-col', width=9)
    ])

], fluid=True)


@app.callback(
    Output('haplotype-chromosome-filter', 'options'),
    Input('selected-species-store', 'data')
)
def load_haplotype_chromosomes(species_id):
    """Load chromosomes for selected species (Microhaplotypes tab)"""
    if not species_id:
        return []
    try:
        db = DatabaseManager()
        with db.shared_connection():
            chromosomes = get_all_chromosomes_for_species(db, species_id)
        return [{'label': c['chromosome_name'], 'value': c['id']} for c in chromosomes]
    except Exception:
        return []


@app.callback(
    Output('haplotype-frequency-range', 'value'),
    Input('haplotype-frequency-reset', 'n_clicks'),
    prevent_initial_call=True
)
def reset_haplotype_frequency_range(_n_clicks):
    return [0.0, 1.0]


# Update page number
@app.callback(
    [Output('haplotype-results-page', 'data'),
     Output('haplotype-page-indicator', 'children'),
     Output('haplotype-page-prev', 'disabled'),
     Output('haplotype-page-next', 'disabled'),
     Output('haplotype-pagination-container', 'style'),
     Output('haplotype-pagination-info', 'children')],
    Input('haplotype-sequence-search', 'value'),
    Input('selected-species-store', 'data'),
    Input('haplotype-marker-filter', 'value'),
    Input('haplotype-chromosome-filter', 'value'),
    Input('haplotype-sample-filter', 'value'),
    Input('haplotype-frequency-range', 'value'),
    Input('haplotype-page-prev', 'n_clicks'),
    Input('haplotype-page-next', 'n_clicks'),
    State('haplotype-results-page', 'data'),
    prevent_initial_call=True
)
def update_haplotype_page(
    seq_search,
    species_id,
    marker_filter,
    chromosome_id,
    sample_filter,
    freq_range,
    prev_clicks,
    next_clicks,
    current_page
):
    """Update page number based on filters or pagination component"""
    triggered = ctx.triggered_id if ctx.triggered else None
    
    # Get total pages and total count for pagination
    try:
        db = DatabaseManager()
        with db.shared_connection():
            min_freq, max_freq = _resolve_frequency_bounds(freq_range)

            result = get_microhaplotypes_paginated(
                db,
                species_id=species_id,
                chromosome_id=chromosome_id,
                search_name=None,
                search_sequence=seq_search,
                marker_id=marker_filter,
                sample_filter=sample_filter,
                min_frequency=min_freq,
                max_frequency=max_freq,
                page=1,
                per_page=7
            )
            total_pages = result.get('total_pages', 1)
            total_count = result.get('total', 0)
    except Exception:
        total_pages = 1
        total_count = 0
    
    # Create pagination info text
    if total_count > 0:
        pagination_info = f"{total_count:,} Microhaplotypes"
    else:
        pagination_info = ""
    
    # Determine new page
    page = current_page or 1

    # Reset to page 1 when filters change
    if triggered in ['haplotype-sequence-search', 'selected-species-store', 'haplotype-marker-filter', 'haplotype-chromosome-filter', 'haplotype-sample-filter', 'haplotype-frequency-range']:
        page = 1
    elif triggered == 'haplotype-page-prev':
        page = max(1, page - 1)
    elif triggered == 'haplotype-page-next':
        page = min(total_pages, page + 1)

    # Clamp page in case total_pages shrank
    page = max(1, min(page, total_pages))

    # Build UI state
    show_controls = total_pages > 1 and total_count > 0
    container_style = {'display': 'flex'} if show_controls else {'display': 'none'}
    info_style = {'display': 'block'} if total_count > 0 else {'display': 'none'}

    indicator = f"Page {page} of {total_pages}" if show_controls else ""
    prev_disabled = page <= 1
    next_disabled = page >= total_pages

    return page, indicator, prev_disabled, next_disabled, container_style, html.Span(pagination_info, style=info_style)


# Search haplotypes
@app.callback(
    Output('haplotype-search-results', 'children'),
    Input('haplotype-sequence-search', 'value'),
    Input('selected-species-store', 'data'),
    Input('haplotype-marker-filter', 'value'),
    Input('haplotype-chromosome-filter', 'value'),
    Input('haplotype-sample-filter', 'value'),
    Input('haplotype-frequency-range', 'value'),
    Input('haplotype-results-page', 'data'),
    prevent_initial_call=True
)
def search_haplotypes(seq_search, species_id, marker_filter, chromosome_id, sample_filter, freq_range, current_page):
    """Search and display haplotypes with pagination"""
    try:
        db = DatabaseManager()
        with db.shared_connection():
            min_freq, max_freq = _resolve_frequency_bounds(freq_range)

            result = get_microhaplotypes_paginated(
                db,
                species_id=species_id,
                chromosome_id=chromosome_id,
                search_name=None,
                search_sequence=seq_search,
                marker_id=marker_filter,
                sample_filter=sample_filter,
                min_frequency=min_freq,
                max_frequency=max_freq,
                page=current_page or 1,
                per_page=7
            )

            if not result['microhaplotypes']:
                return html.Div("No haplotypes found", className="text-muted small")

            # Create clickable list
            haplotype_items = []
            for h in result['microhaplotypes']:
                presence_stats = get_presence_statistics(db, h['haplotype_name'], h.get('species_id'))
                species_sample_count = h.get('species_sample_count', 0)
                sample_count = presence_stats.get('present_samples', 0)
                if _is_missing_sample_context(species_sample_count) or _is_missing_sample_value(sample_count):
                    sample_label = "Missing samples"
                else:
                    sample_label = f"{sample_count} samples"
                freq_val = presence_stats.get('presence_frequency')

                item = dbc.ListGroupItem([
                    html.Div([
                        html.Strong(
                            h['haplotype_name'],
                            style={'display': 'block', 'lineHeight': '1.1', 'marginBottom': '0.15rem'}
                        ),
                        html.Small([
                            html.I(className="fas fa-leaf me-1"),
                            sample_label,
                            " | " if freq_val is not None else "",
                            f"Freq: {float(freq_val):.3f}" if freq_val is not None else ""
                        ], className="text-muted", style={'display': 'block', 'lineHeight': '1.1'})
                    ])
                ], action=True, id={'type': 'haplotype-list-item', 'index': h['haplotype_name']})
                haplotype_items.append(item)

        return html.Div([dbc.ListGroup(haplotype_items)])

    except Exception as e:
        return html.Div(f"Error: {str(e)}", className="text-danger small")


@app.callback(
    [Output('haplotype-detail-content', 'children'),
     Output('navigate-to-haplotype-store', 'data', allow_duplicate=True),
     Output('samples-data-store', 'data'),
     Output('toggle-samples', 'children'),
     Output('samples-section-wrapper', 'style')],
    Input({'type': 'haplotype-list-item', 'index': dash.ALL}, 'n_clicks'),
    Input('navigate-to-haplotype-store', 'data'),
    State('haplotype-detail-content', 'children'),
    prevent_initial_call=True
)
def show_haplotype_details(n_clicks, navigate_data, current_details):
    """Display selected haplotype details"""
    haplotype_name = None

    # Check what triggered the callback
    triggered = ctx.triggered_id if ctx.triggered else None

    # Priority 1: Check navigation store first (for cross-tab navigation)
    if triggered == 'navigate-to-haplotype-store':
        if navigate_data and isinstance(navigate_data, dict) and navigate_data.get('haplotype_name'):
            haplotype_name = navigate_data['haplotype_name']
    # Priority 2: Direct list item click
    elif triggered and isinstance(triggered, dict) and triggered.get('type') == 'haplotype-list-item':
        # Only update if there was an actual click (n_clicks changed)
        if n_clicks and any(clicks and clicks > 0 for clicks in n_clicks if clicks is not None):
            haplotype_name = triggered['index']

    # If no haplotype selected from this trigger, preserve current selection
    if not haplotype_name:
        # Check if we have existing details to preserve (not the placeholder)
        if current_details:
            if isinstance(current_details, str):
                if "Select a haplotype" not in current_details:
                    return no_update, no_update, no_update, no_update, no_update
            else:
                # It's a Div component, preserve it
                return no_update, no_update, no_update, no_update, no_update
        return (
            html.Div("Select a microhaplotype result to view details", className="text-muted"),
            no_update,
            None,
            [
                html.I(className="fas fa-leaf me-2"),
                "Samples (0)",
                html.I(className="fas fa-chevron-down ms-2", id='samples-chevron')
            ],
            {'display': 'none'},
        )

    try:
        db = DatabaseManager()
        with db.shared_connection():
            # Get haplotype details
            haplotype = get_microhaplotype_details(db, haplotype_name)
            if not haplotype:
                return (
                    html.Div("Haplotype not found", className="text-danger"),
                    no_update,
                    None,
                    [
                        html.I(className="fas fa-leaf me-2"),
                        "Samples (0)",
                        html.I(className="fas fa-chevron-down ms-2", id='samples-chevron')
                    ],
                    {'display': 'none'},
                )

            # Get samples and projects
            samples_micro = get_samples_for_microhaplotype(db, haplotype_name)

            # Projects can come from project artifacts and sample artifacts.
            projects_from_samples = get_projects_for_microhaplotype(db, haplotype_name)
            projects_from_presence = get_projects_for_allele_presence(db, haplotype_name)
            projects_from_sample_presence = get_projects_for_sample_presence(db, haplotype_name)

            # Deduplicate across all sources. sample_presence is last so its
            # richer fields overwrite earlier entries from allele_presence.
            combined = projects_from_presence + projects_from_samples + projects_from_sample_presence
            projects = _deduplicate_projects(combined)

            # Collect ALL DB ids (including duplicates) for contact lookups
            _all_project_ids = set()
            for p in combined:
                pid = p.get('id')
                if pid is not None:
                    _all_project_ids.add(pid)


            # Fetch rich contact data from the contacts table (institution + location)
            # Use _all_project_ids (all DB ids incl. duplicates) so contacts
            # are found regardless of which project variant they were linked to.
            contacts_data = get_contacts_for_projects(db, list(_all_project_ids)) if _all_project_ids else []

            # Get presence/absence data
            presence_samples = get_samples_for_allele(db, haplotype_name)
            species_sample_count = get_species_sample_count(db, haplotype.get('species_id'))
            missing_sample_context = _is_missing_sample_context(species_sample_count)
            presence_stats = get_presence_statistics(db, haplotype_name, haplotype.get('species_id'))

            # Calculate frequency from live presence stats so interrupted imports
            # don't leave the detail panel showing stale stored values.
            frequency = presence_stats.get('presence_frequency')

            # Use presence_samples as primary source (only samples with presence=1 for this haplotype)
            if presence_samples:
                samples = presence_samples
            else:
                samples = samples_micro

            # Create samples table data
            samples_table_data = create_samples_table(samples, presence_samples, presence_stats, haplotype_name)
            collaborators_table_data = build_collaborator_rows(projects, contacts_data)
            collaborators_count = len(collaborators_table_data)
            samples_count = len(samples_table_data)
            missing_samples_label = missing_sample_context or _is_missing_sample_value(
                presence_stats.get('present_samples', 0)
            )
            if missing_samples_label:
                samples_button_label = "Samples (Missing samples)"
            else:
                samples_button_label = f"Samples ({samples_count})"

        # Store samples data in a separate callback output
        return html.Div([
            # Header
            html.H5(haplotype['haplotype_name'], className="mb-1"),
            html.Div([
                html.P([
                    html.I(className="fas fa-search me-2"),
                    html.Strong("Marker: "),
                    haplotype['marker_id']
                ], className="text-muted small mb-0"),
                dbc.Button([
                    html.I(className="fas fa-info-circle me-2"),
                    f"Locus Details: {haplotype['marker_id']}"
                ], id={'type': 'view-marker-btn', 'index': haplotype['marker_id']}, color="info", size="sm", outline=True, className="mt-2 mb-3")
            ]),

            # Stats cards
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6(
                                f"{frequency:.3f}" if frequency is not None else "N/A",
                                className="mb-0"
                            ),
                            html.Small([
                                "Frequency",
                                html.I(
                                    className="fas fa-info-circle ms-1",
                                    id="frequency-tooltip-target",
                                    style={'cursor': 'help'}
                                )
                            ], className="text-muted"),
                            dbc.Tooltip(
                                "The proportion of samples containing this haplotype relative to the total number of samples for this species. Note: This represents sample frequency, not allelic frequency.",
                                target="frequency-tooltip-target",
                                placement="top"
                            )
                        ], className="text-center")
                    ])
                ], width=4),
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6(
                                "Missing samples"
                                if missing_samples_label
                                else f"{presence_stats.get('present_samples', 0)}",
                                className="mb-0"
                            ),
                            html.Small([
                                "Samples",
                                html.I(
                                    className="fas fa-info-circle ms-1",
                                    id="samples-tooltip-target",
                                    style={'cursor': 'help'}
                                )
                            ], className="text-muted"),
                            dbc.Tooltip(
                                "The number of samples that contain this haplotype.",
                                target="samples-tooltip-target",
                                placement="top"
                            )
                        ], className="text-center")
                    ])
                ], width=4),
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6(len(projects), className="mb-0"),
                            html.Small([
                                "Projects",
                                html.I(
                                    className="fas fa-info-circle ms-1",
                                    id="projects-tooltip-target",
                                    style={'cursor': 'help'}
                                )
                            ], className="text-muted"),
                            dbc.Tooltip(
                                "The number of projects that contain samples with this haplotype.",
                                target="projects-tooltip-target",
                                placement="top"
                            )
                        ], className="text-center")
                    ])
                ], width=4)
            ], className="mb-3"),

            # Sequence
            html.Hr(),
            html.H6("Sequence", className="mb-2"),
            html.Pre([
                html.Code(haplotype['haplotype_sequence'])
            ], className="p-2 bg-light border rounded"),

            # Collaborators section
            html.Hr(),
            html.Div([
                dbc.Button([
                    html.I(className="fas fa-address-book me-2"),
                    f"Collaborators ({collaborators_count})",
                    html.I(className="fas fa-chevron-down ms-2", id='collaborators-chevron')
                ], id='toggle-collaborators', color="secondary", outline=True, size="sm", className="mb-2 haplo-action-btn")
            ]),
            dbc.Collapse(
                create_contact_section(projects, contacts_data, collaborators_table_data),
                id='collaborators-collapse',
                is_open=False
            ),

            # Projects section
            html.Hr(),
            html.Div([
                dbc.Button([
                    html.I(className="fas fa-folder-open me-2"),
                    f"Projects ({len(projects)})",
                    html.I(className="fas fa-chevron-down ms-2", id='projects-chevron')
                ], id='toggle-projects', color="secondary", outline=True, size="sm", className="mb-2 haplo-action-btn")
            ]),
            dbc.Collapse(
                create_projects_cards(projects, contacts_data),
                id='projects-collapse',
                is_open=False
            )
        ]), no_update, samples_table_data, [
            html.I(className="fas fa-leaf me-2"),
            samples_button_label,
            html.I(className="fas fa-chevron-down ms-2", id='samples-chevron')
        ], {'display': 'block'}

    except Exception as e:
        return (
            html.Div(f"Error: {str(e)}", className="text-danger"),
            no_update,
            None,
            [
                html.I(className="fas fa-leaf me-2"),
                "Samples (0)",
                html.I(className="fas fa-chevron-down ms-2", id='samples-chevron')
            ],
            {'display': 'none'},
        )


# Toggle samples section
@app.callback(
    [Output('samples-collapse', 'style'),
     Output('samples-chevron', 'className'),
     Output('toggle-samples', 'className')],
    Input('toggle-samples', 'n_clicks'),
    State('samples-collapse', 'style'),
    prevent_initial_call=True
)
def toggle_samples(n_clicks, current_style):
    """Toggle samples section"""
    is_open = bool(current_style) and current_style.get('display') != 'none'
    new_open = not is_open
    new_style = {'display': 'block'} if new_open else {'display': 'none'}
    chevron_class = "fas fa-chevron-up ms-2" if new_open else "fas fa-chevron-down ms-2"
    button_class = "mb-2 haplo-action-btn haplo-action-btn-open" if new_open else "mb-2 haplo-action-btn"
    # #region agent log
    try:
        import json, time, os; _lp = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.cursor', 'debug-4b22b4.log'); os.makedirs(os.path.dirname(_lp), exist_ok=True); open(_lp, 'a').write(json.dumps({"sessionId":"4b22b4","location":"haplotype_explorer.py:toggle_samples","message":"toggle_samples fired","data":{"n_clicks":n_clicks,"current_style":str(current_style),"new_open":new_open,"button_class":button_class},"timestamp":int(time.time()*1000),"hypothesisId":"H1"}) + '\n')
    except Exception:
        pass
    # #endregion
    return new_style, chevron_class, button_class


# Toggle projects section
@app.callback(
    Output('projects-collapse', 'is_open'),
    Output('projects-chevron', 'className'),
    Output('toggle-projects', 'className'),
    Input('toggle-projects', 'n_clicks'),
    State('projects-collapse', 'is_open'),
    prevent_initial_call=True
)
def toggle_projects(n_clicks, is_open):
    """Toggle projects section"""
    new_state = not is_open
    chevron_class = "fas fa-chevron-up ms-2" if new_state else "fas fa-chevron-down ms-2"
    button_class = "mb-2 haplo-action-btn haplo-action-btn-open" if new_state else "mb-2 haplo-action-btn"
    # #region agent log
    try:
        import json, time, os; _lp = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.cursor', 'debug-4b22b4.log'); os.makedirs(os.path.dirname(_lp), exist_ok=True); open(_lp, 'a').write(json.dumps({"sessionId":"4b22b4","location":"haplotype_explorer.py:toggle_projects","message":"toggle_projects fired","data":{"n_clicks":n_clicks,"is_open":is_open,"new_state":new_state,"button_class":button_class},"timestamp":int(time.time()*1000),"hypothesisId":"H1"}) + '\n')
    except Exception:
        pass
    # #endregion
    return new_state, chevron_class, button_class


# Toggle collaborators section
@app.callback(
    [Output('collaborators-collapse', 'is_open'),
     Output('collaborators-chevron', 'className'),
     Output('toggle-collaborators', 'className')],
    Input('toggle-collaborators', 'n_clicks'),
    State('collaborators-collapse', 'is_open'),
    prevent_initial_call=True
)
def toggle_collaborators(n_clicks, is_open):
    """Toggle collaborators section"""
    new_state = not is_open
    chevron_class = "fas fa-chevron-up ms-2" if new_state else "fas fa-chevron-down ms-2"
    button_class = "mb-2 haplo-action-btn haplo-action-btn-open" if new_state else "mb-2 haplo-action-btn"
    # #region agent log
    try:
        import json, time, os; _lp = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.cursor', 'debug-4b22b4.log'); os.makedirs(os.path.dirname(_lp), exist_ok=True); open(_lp, 'a').write(json.dumps({"sessionId":"4b22b4","location":"haplotype_explorer.py:toggle_collaborators","message":"toggle_collaborators fired","data":{"n_clicks":n_clicks,"is_open":is_open,"new_state":new_state,"button_class":button_class},"timestamp":int(time.time()*1000),"hypothesisId":"H1"}) + '\n')
    except Exception:
        pass
    # #endregion
    return new_state, chevron_class, button_class


# Update samples table page and pagination
@app.callback(
    [Output('samples-table-page', 'data'),
     Output('samples-pagination', 'max_value'),
     Output('samples-pagination', 'active_page'),
     Output('samples-pagination', 'style')],
    Input('samples-search-input', 'value'),
    Input('samples-pagination', 'active_page'),
    State('samples-data-store', 'data'),
    State('samples-table-page', 'data'),
    prevent_initial_call=True
)
def update_samples_pagination(search_filter, pagination_page, samples_data, current_page):
    """Update samples table pagination based on search filter or pagination component"""
    # We use AG Grid's built-in pagination now, so keep Dash pagination hidden.
    return 1, 1, 1, {'display': 'none'}


# Update samples table (with separate search input and pagination)
@app.callback(
    [Output('samples-table-body', 'children'),
     Output('samples-pagination-info', 'children'),
     Output('samples-pagination', 'max_value', allow_duplicate=True),
     Output('samples-pagination', 'active_page', allow_duplicate=True),
     Output('samples-pagination', 'style', allow_duplicate=True),
     Output('samples-table-page', 'data', allow_duplicate=True)],
    Input('samples-data-store', 'data'),
    Input('samples-search-input', 'value'),
    Input('samples-table-page', 'data'),
    prevent_initial_call=True
)
def update_samples_table(samples_data, search_filter, current_page):
    """Render samples table with separate search input and pagination matching results section style."""
    triggered = ctx.triggered_id if ctx.triggered else None
    
    # Ensure samples_data is a list
    if not isinstance(samples_data, list):
        samples_data = []

    if not samples_data:
        return (
            html.Small("No samples found", className="text-muted"),
            "",
            1, 1, {'display': 'none'},
            1
        )

    # Filter samples based on search input
    filtered_data = samples_data
    if search_filter:
        search_lower = search_filter.lower()
        filtered_data = [
            row for row in samples_data
            if search_lower in str(row.get('Sample Name', '')).lower()
        ]
    
    if not filtered_data:
        return (
            html.Small("No samples match your search", className="text-muted"),
            "",
            1, 1, {'display': 'none'},
            1
        )

    # Create table (AG Grid with built-in pagination)
    ok_ag, ag_fallback = _require_ag_grid()
    table = ag_fallback if not ok_ag else dag.AgGrid(
        rowData=filtered_data,
        columnDefs=[
            {'headerName': '#', 'field': '#', 'width': 80, 'cellStyle': {'textAlign': 'center', 'color': '#000000', 'fontWeight': '500'}},
            {'headerName': 'Sample Name', 'field': 'Sample Name', 'flex': 1},
            {'headerName': 'Owners', 'field': 'Owners', 'flex': 1},
        ],
        defaultColDef={
            'sortable': True,
            'resizable': True,
            'filter': False,
            'wrapText': True,
            'autoHeight': True,
        },
        dashGridOptions={
            'headerHeight': 36,
            'rowHeight': 38,
            'domLayout': 'autoHeight',
            'suppressCellFocus': True,
            'pagination': True,
            'paginationPageSize': 10,
            # Disable user ability to change page size
            'paginationPageSizeSelector': False,
        },
        className='ag-theme-alpine',
        style={'borderRadius': '8px', 'border': '1px solid #e9ecef', 'overflow': 'hidden'}
    )

    # Calculate pagination info
    total_count = len(filtered_data)
    
    # Create pagination info text matching results section style
    if total_count > 0:
        pagination_info = html.Span(f"Total: {total_count:,} samples", className="text-muted small")
    else:
        pagination_info = ""
    
    return (
        table,
        pagination_info,
        1,
        1,
        {'display': 'none'},
        1
    )


def create_samples_table(samples, presence_samples=None, presence_stats=None, haplotype_name=None):
    """Create a paginated table of samples for better readability"""
    if not samples:
        return []  # Return empty list instead of HTML component

    def _owner_from_project_code(project_code: str) -> str:
        """Best-effort owner extraction for headers like P01_Debby_Zhanyou_..."""
        if not project_code:
            return ''
        toks = [t for t in str(project_code).split('_') if t]
        if len(toks) >= 2 and toks[0].upper().startswith('P') and toks[0][1:].isdigit():
            if toks[1].lower() == 'validation':
                return ''
            owners = [toks[1]]
            # Capture 2-owner pattern like P01_Debby_Zhanyou_digestibility...
            if len(toks) >= 4 and toks[2][:1].isupper() and toks[3][:1].islower():
                owners.append(toks[2])
            return ', '.join(owners)
        return ''

    def _format_owners(raw_owner: str, project_code: str = None) -> str:
        raw = (raw_owner or '').strip()
        if not raw:
            raw = _owner_from_project_code(project_code)
        if not raw:
            return 'Unknown'
        # Normalize common separators: "A & B" -> "A, B"
        normalized = str(raw).replace('&', ',')
        parts = [p.strip() for p in normalized.split(',') if p.strip()]
        return ', '.join(parts) if parts else 'Unknown'

    # Aggregate owners per sample_code (in case input ever contains duplicates)
    owners_by_sample = {}
    for s in samples:
        code = str(s.get('sample_code') or '').strip()
        if not code:
            continue
        owner = _format_owners(s.get('pi_name'), s.get('project_code'))
        owners_by_sample.setdefault(code, set()).add(owner)

    # Stable, sorted output
    sample_codes = sorted(owners_by_sample.keys())

    table_data = []
    for i, sample_code in enumerate(sample_codes):
        owners = sorted([o for o in owners_by_sample.get(sample_code, set()) if o and o.lower() != 'unknown'])
        owners_str = ', '.join(owners) if owners else 'Unknown'
        table_data.append({
            '#': i + 1,
            'Sample Name': sample_code,
            'Owners': owners_str
        })
    
    return table_data


def create_projects_cards(projects, contacts_data=None):
    """Create a compact project list (one line per project).

    Shows only:
      - Contact
      - Informal name
      - Genotyping project

    This is intentionally minimal to keep the UI tight.
    """
    if not projects:
        return html.Small("No projects found", className="text-muted")

    dal_pattern = re.compile(r"DA[lI](\d{2})-(\d+)", re.IGNORECASE)

    def _extract_genotyping_source(proj):
        # Prefer a parsed value if it was recorded in projects.description by the importer
        desc = (proj.get('description') or '')
        for part in [p.strip() for p in desc.split(';') if p.strip()]:
            if part.lower().startswith('genotyping_source='):
                return part.split('=', 1)[1].strip() or None

        # Fallback: parse from project_code tokens
        code = str(proj.get('project_code') or '')
        toks = [t for t in code.split('_') if t]
        dal = [t for t in toks if t.lower().startswith('dal')]
        return '_'.join(dal) if dal else None

    def _genotyping_sort_key(proj):
        """Sort by parsed genotyping project number, then project code."""
        source = _extract_genotyping_source(proj) or ''
        match = dal_pattern.search(source)
        if match:
            return (0, int(match.group(1)), int(match.group(2)), str(proj.get('project_code') or ''))
        return (1, str(source).lower(), str(proj.get('project_code') or ''))

    contacts_by_project_id = {}
    for c in (contacts_data or []):
        project_id = c.get('project_id')
        if project_id is None:
            continue
        name = (c.get('full_name') or '').strip()
        if not name:
            continue
        contacts_by_project_id.setdefault(project_id, set()).add(name)

    rows = []
    for proj in sorted(projects, key=_genotyping_sort_key):
        project_id = proj.get('id')
        contact_names = sorted(contacts_by_project_id.get(project_id, set()))
        if contact_names:
            contact = ", ".join(contact_names)
        else:
            contact = (proj.get('pi_name') or '').strip() or '—'
        informal = (proj.get('project_name') or '').strip() or '—'
        geno = _extract_genotyping_source(proj) or '—'

        rows.append({
            'Contact': contact,
            'Informal name': informal,
            'Genotyping project': geno
        })

    ok_ag, ag_fallback = _require_ag_grid()
    return ag_fallback if not ok_ag else dag.AgGrid(
        rowData=rows,
        columnDefs=[
            {'headerName': 'Contact', 'field': 'Contact', 'flex': 1},
            {'headerName': 'Informal name', 'field': 'Informal name', 'flex': 1},
            {'headerName': 'Genotyping project', 'field': 'Genotyping project', 'flex': 1},
        ],
        defaultColDef={
            'sortable': True,
            'resizable': True,
            'filter': False,
            'wrapText': True,
            'autoHeight': True,
        },
        dashGridOptions={
            'headerHeight': 34,
            'rowHeight': 36,
            'domLayout': 'autoHeight',
            'suppressCellFocus': True,
            'pagination': True,
            'paginationPageSize': 5,
            # Disable user ability to change page size
            'paginationPageSizeSelector': False,
        },
        className='ag-theme-alpine',
        style={'border': '1px solid #e9ecef', 'borderRadius': '8px', 'overflow': 'hidden'}
    )



def build_collaborator_rows(projects, contacts_data=None):
    """Build de-duplicated collaborator rows from linked contacts only."""
    return build_collaborator_rows_from_contacts(contacts_data)


def create_contact_section(projects, contacts_data=None, rows=None):
    """Render collaborators as a compact table (name / institution / location / email).

    When *contacts_data* (from the ``contacts`` table) is available, institution
    and location come from there (mapped from HapSearch_owner_contacts.csv's
    "Employer" and "Primary Location").  Otherwise falls back to the project-level
    ``pi_institution`` field.
    """
    rows = rows if rows is not None else build_collaborator_rows(projects, contacts_data)
    if not rows:
        return html.Div("No collaborators available", className="text-muted small")

    ok_ag, ag_fallback = _require_ag_grid()
    return ag_fallback if not ok_ag else dag.AgGrid(
        rowData=rows,
        columnDefs=[
            {'headerName': 'Name', 'field': 'Name', 'flex': 1},
            {'headerName': 'Institution', 'field': 'Institution', 'flex': 1},
            {'headerName': 'Location', 'field': 'Location', 'flex': 1},
            {'headerName': 'Email', 'field': 'Email', 'flex': 1},
        ],
        defaultColDef={
            'sortable': True,
            'resizable': True,
            'filter': False,
            'wrapText': True,
            'autoHeight': True,
        },
        dashGridOptions={
            'headerHeight': 34,
            'rowHeight': 36,
            'domLayout': 'autoHeight',
            'suppressCellFocus': True,
            'pagination': True,
            'paginationPageSize': 10,
            'paginationPageSizeSelector': False,
        },
        className='ag-theme-alpine',
        style={'border': '1px solid #e9ecef', 'borderRadius': '8px', 'overflow': 'hidden'}
    )



# Callback to navigate to Marker Explorer
@app.callback(
    Output('navigate-to-marker-store', 'data'),
    Input({'type': 'view-marker-btn', 'index': dash.ALL}, 'n_clicks'),
    prevent_initial_call=True
)
def navigate_to_marker_explorer(n_clicks):
    """Store marker ID and trigger navigation to Marker Explorer tab"""
    triggered = ctx.triggered_id

    # For pattern-matching callbacks, triggered_id is a dict with type and index
    if not triggered or not isinstance(triggered, dict):
        return no_update

    if triggered.get('type') != 'view-marker-btn':
        return no_update

    # Check if button was actually clicked (not just created)
    # When buttons are first created, ALL n_clicks values are 0 or None
    # When a button is actually clicked, at least one n_clicks value will be > 0
    if n_clicks:
        # Check if ANY button has been clicked (n_clicks > 0)
        has_real_click = any(clicks and clicks > 0 for clicks in n_clicks)
        if not has_real_click:
            # All buttons have n_clicks of 0 or None - they were just created, not clicked
            return no_update

    # Extract marker ID from the triggered button's ID
    marker_id = triggered.get('index')
    if not marker_id:
        return no_update

    # Return data dict - Dash will detect changes even for same value
    return {'marker_id': marker_id}


# Toggle left panel minimize/expand
@app.callback(
    [Output('haplotype-left-panel-minimized', 'data'),
     Output('haplotype-left-col', 'width'),
     Output('haplotype-right-col', 'width'),
     Output('haplotype-filters-body', 'style'),
     Output('haplotype-results-card', 'style'),
     Output('haplotype-minimize-icon', 'className'),
     Output('haplotype-search-title', 'style'),
     Output('haplotype-search-icon', 'style')],
    Input('haplotype-minimize-btn', 'n_clicks'),
    State('haplotype-left-panel-minimized', 'data'),
    prevent_initial_call=True
)
def toggle_haplotype_left_panel(n_clicks, is_minimized):
    """Toggle left panel between minimized and expanded states"""
    new_state = not is_minimized
    
    if new_state:  # Minimizing
        return (
            True,  # Store state
            1,     # Left column width (minimized)
            11,    # Right column width (expanded)
            {'display': 'none'},  # Hide filters
            {'display': 'none'},  # Hide results
            "fas fa-chevron-right",  # Change icon to right chevron
            {'display': 'none'},  # Hide title text
            {'display': 'none'}  # Hide search icon
        )
    else:  # Expanding
        return (
            False,  # Store state
            3,      # Left column width (normal)
            9,      # Right column width (normal)
            {},     # Show filters
            {},  # Show results (no internal scrolling)
            "fas fa-chevron-left",  # Change icon to left chevron
            {},     # Show title text
            {'marginRight': '0.5rem'}  # Show search icon with margin
        )
