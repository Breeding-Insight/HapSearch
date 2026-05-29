"""Project Browser - Dedicated view for exploring projects and PI information

Different from original: Projects are primary focus with expandable details,
filtering by PI, institution, and species
"""

import dash
from dash import dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import app for callback registration
from dash_app import app

from database.db_manager import DatabaseManager
from database.queries import get_all_species

# Layout
layout = dbc.Container([
    # Filters
    dbc.Row([
        dbc.Col([
            html.Label("Search Projects:", className="fw-bold small"),
            dbc.Input(
                id='project-search-input',
                type='text',
                placeholder='Search by project name or code...',
                debounce=True,
                className="mb-3"
            )
        ], width=4),
        dbc.Col([
            html.Label("Filter by PI:", className="fw-bold small"),
            dbc.Input(
                id='project-pi-filter',
                type='text',
                placeholder='PI name...',
                debounce=True,
                className="mb-3"
            )
        ], width=4),
        dbc.Col([
            html.Label("Filter by Species:", className="fw-bold small"),
            dcc.Dropdown(
                id='project-species-filter',
                placeholder="All species",
                className="mb-3"
            )
        ], width=4)
    ]),

    html.Hr(),

    # Results
    dcc.Loading(
        html.Div(id='project-browser-results'),
        type="default"
    )

], fluid=True)


# Load species for filter
@app.callback(
    Output('project-species-filter', 'options'),
    Input('project-species-filter', 'id')
)
def load_species(_):
    """Load species for dropdown"""
    try:
        db = DatabaseManager()
        species = get_all_species(db)
        return [{'label': f"{s['common_name']} ({s['name']})", 'value': s['id']}
                for s in species]
    except Exception:
        return []


# Load and display projects
@app.callback(
    Output('project-browser-results', 'children'),
    Input('project-search-input', 'value'),
    Input('project-pi-filter', 'value'),
    Input('project-species-filter', 'value')
)
def load_projects(search_term, pi_filter, species_id):
    """Load and display projects based on filters"""
    try:
        db = DatabaseManager()

        # Build query
        species_list_expr = "STRING_AGG(sp.common_name, ', ')"
        query = f"""
        SELECT
            p.id,
            p.project_code,
            p.project_name,
            p.pi_name,
            p.pi_email,
            p.pi_institution,
            p.pi_department,
            p.description,
            p.start_date,
            COUNT(DISTINCT s.id) as sample_count,
            COUNT(DISTINCT ms.microhaplotype_id) as unique_haplotypes,
            {species_list_expr} as species_list
        FROM projects p
        LEFT JOIN samples s ON p.id = s.project_id
        LEFT JOIN microhaplotype_samples ms ON s.id = ms.sample_id
        LEFT JOIN species sp ON s.species_id = sp.id
        WHERE 1=1
        """
        params = []

        if search_term:
            query += " AND (p.project_code LIKE ? OR p.project_name LIKE ?)"
            search_pattern = f"%{search_term}%"
            params.extend([search_pattern, search_pattern])

        if pi_filter:
            query += " AND p.pi_name LIKE ?"
            params.append(f"%{pi_filter}%")

        if species_id:
            query += " AND s.species_id = ?"
            params.append(species_id)

        query += (
            " GROUP BY p.id, p.project_code, p.project_name, p.pi_name, p.pi_email, "
            "p.pi_institution, p.pi_department, p.description, p.start_date "
            "ORDER BY p.project_name"
        )

        projects = db.execute_query(query, tuple(params))

        if not projects:
            return dbc.Alert("No projects found matching the criteria", color="info")

        # Create project cards
        project_cards = []
        for proj in projects:
            card = create_project_card(proj)
            project_cards.append(
                dbc.Col(card, width=12, md=6, lg=4, className="mb-3")
            )

        return dbc.Row(project_cards)

    except Exception as e:
        return dbc.Alert(f"Error loading projects: {str(e)}", color="danger")


def create_project_card(project):
    """Create a detailed project card"""
    return dbc.Card([
        dbc.CardHeader([
            html.H6([
                html.I(className="fas fa-folder-open me-2"),
                project['project_name']
            ], className="mb-0")
        ]),
        dbc.CardBody([
            # Project Code
            html.Div([
                html.Strong("Code: "),
                html.Code(project['project_code'], className="small")
            ], className="mb-2"),

            html.Hr(className="my-2"),

            # PI Information Section
            html.Div([
                html.Strong([
                    html.I(className="fas fa-user-circle me-2"),
                    "Principal Investigator"
                ], className="d-block mb-2"),

                html.Div([
                    html.I(className="fas fa-user me-2", style={'width': '20px'}),
                    html.A(
                        project['pi_name'],
                        href=f"mailto:{project['pi_email']}",
                        className="text-decoration-none"
                    )
                ], className="small mb-1"),

                html.Div([
                    html.I(className="fas fa-envelope me-2", style={'width': '20px'}),
                    html.Small(project['pi_email'], className="text-muted")
                ], className="small mb-1"),

                html.Div([
                    html.I(className="fas fa-building me-2", style={'width': '20px'}),
                    project['pi_institution']
                ], className="small mb-1"),

                html.Div([
                    html.I(className="fas fa-flask me-2", style={'width': '20px'}),
                    project.get('pi_department', 'N/A')
                ], className="small")
            ], className="mb-2"),

            html.Hr(className="my-2"),

            # Project Statistics
            html.Div([
                html.Strong([
                    html.I(className="fas fa-chart-bar me-2"),
                    "Statistics"
                ], className="d-block mb-2"),

                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.H5(project['sample_count'] or 0, className="mb-0 text-primary"),
                            html.Small("Samples", className="text-muted")
                        ], className="text-center")
                    ], width=6),
                    dbc.Col([
                        html.Div([
                            html.H5(project['unique_haplotypes'] or 0, className="mb-0 text-success"),
                            html.Small("Haplotypes", className="text-muted")
                        ], className="text-center")
                    ], width=6)
                ])
            ], className="mb-2"),

            # Species
            html.Div([
                html.I(className="fas fa-dna me-2"),
                html.Small(project.get('species_list', 'N/A'), className="text-muted")
            ], className="small mb-2") if project.get('species_list') else None,

            # Description (collapsible)
            html.Div([
                dbc.Button(
                    [html.I(className="fas fa-info-circle me-2"), "Details"],
                    id={'type': 'project-details-btn', 'index': project['id']},
                    color="link",
                    size="sm",
                    className="p-0"
                ),
                dbc.Collapse(
                    html.Div([
                        html.Hr(className="my-2"),
                        html.Small([
                            html.Strong("Description:"),
                            html.Br(),
                            project.get('description', 'No description available')
                        ], className="text-muted"),
                        html.Small([
                            html.Br(),
                            html.Strong("Start Date: "),
                            project.get('start_date', 'N/A')
                        ], className="text-muted d-block mt-2")
                    ]),
                    id={'type': 'project-details-collapse', 'index': project['id']},
                    is_open=False
                )
            ])
        ])
    ], className="h-100 shadow-sm")


# Toggle project details
@app.callback(
    Output({'type': 'project-details-collapse', 'index': dash.MATCH}, 'is_open'),
    Input({'type': 'project-details-btn', 'index': dash.MATCH}, 'n_clicks'),
    State({'type': 'project-details-collapse', 'index': dash.MATCH}, 'is_open'),
    prevent_initial_call=True
)
def toggle_project_details(n_clicks, is_open):
    """Toggle project details section"""
    if n_clicks:
        return not is_open
    return is_open
