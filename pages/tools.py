"""Tools - Batch export and data utilities

Additional features not in original: Batch operations, data comparison,
and statistics calculator
"""

from dash import dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import pandas as pd
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
    dbc.Tabs([
        # Tab 1: Batch Export
        dbc.Tab([
            html.Div([
                html.H5("Batch Data Export", className="mt-3 mb-3"),
                html.P("Export data in bulk for downstream analysis", className="text-muted"),

                # Export options
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Select Data to Export:", className="mb-3"),

                        # Species filter
                        dbc.Row([
                            dbc.Col([
                                html.Label("Filter by Species:", className="fw-bold small"),
                                dcc.Dropdown(
                                    id='export-species-filter',
                                    placeholder="All species",
                                    className="mb-3"
                                )
                            ], width=6)
                        ]),

                        # Export type selection
                        dbc.RadioItems(
                            id='export-type-radio',
                            options=[
                                {'label': 'All Markers', 'value': 'markers'},
                                {'label': 'All Haplotypes', 'value': 'haplotypes'},
                                {'label': 'All Genotypes', 'value': 'samples'},
                                {'label': 'All Projects', 'value': 'projects'},
                                {'label': 'All Variants', 'value': 'variants'},
                                {'label': 'Complete Dataset (All tables)', 'value': 'all'}
                            ],
                            value='markers',
                            className="mb-3"
                        ),

                        # Export format
                        html.Label("Export Format:", className="fw-bold small"),
                        dbc.RadioItems(
                            id='export-format-radio',
                            options=[
                                {'label': 'CSV', 'value': 'csv'},
                                {'label': 'TSV', 'value': 'tsv'},
                                {'label': 'JSON', 'value': 'json'}
                            ],
                            value='csv',
                            inline=True,
                            className="mb-3"
                        ),

                        html.Hr(),

                        # Export button
                        dbc.Button([
                            html.I(className="fas fa-download me-2"),
                            "Export Data"
                        ], id='export-data-btn', color="primary", size="lg", className="w-100")
                    ])
                ]),

                # Download component
                dcc.Download(id='download-export-data'),

                # Status message
                html.Div(id='export-status', className="mt-3")
            ])
        ], label="Batch Export", tab_id="export-tab"),

        # Tab 2: Database Statistics
        dbc.Tab([
            html.Div([
                html.H5("Database Statistics", className="mt-3 mb-3"),
                html.P("Comprehensive overview of database contents", className="text-muted"),

                dbc.Button([
                    html.I(className="fas fa-sync me-2"),
                    "Refresh Statistics"
                ], id='refresh-stats-btn', color="primary", size="sm", className="mb-3"),

                dcc.Loading(
                    html.Div(id='database-stats-display'),
                    type="default"
                )
            ])
        ], label="Database Stats", tab_id="stats-tab"),

        # Tab 3: Data Summary
        dbc.Tab([
            html.Div([
                html.H5("Data Summary Report", className="mt-3 mb-3"),
                html.P("Generate summary reports for your data", className="text-muted"),

                dbc.Card([
                    dbc.CardBody([
                        html.Label("Select Species:", className="fw-bold small"),
                        dcc.Dropdown(
                            id='summary-species-dropdown',
                            placeholder="Select species...",
                            className="mb-3"
                        ),

                        dbc.Button([
                            html.I(className="fas fa-chart-bar me-2"),
                            "Generate Summary"
                        ], id='generate-summary-btn', color="success", className="w-100")
                    ])
                ]),

                html.Div(id='summary-report-display', className="mt-3")
            ])
        ], label="Data Summary", tab_id="summary-tab")
    ], id="tools-tabs", active_tab="export-tab")

], fluid=True)


# Load species for dropdowns
@app.callback(
    Output('export-species-filter', 'options'),
    Output('summary-species-dropdown', 'options'),
    Input('export-species-filter', 'id')
)
def load_species(_):
    """Load species for all dropdowns"""
    try:
        db = DatabaseManager()
        species = get_all_species(db)
        options = [{'label': f"{s['common_name']} ({s['name']})", 'value': s['id']}
                   for s in species]
        return options, options
    except Exception:
        return [], []


# Export data
@app.callback(
    Output('download-export-data', 'data'),
    Output('export-status', 'children'),
    Input('export-data-btn', 'n_clicks'),
    State('export-type-radio', 'value'),
    State('export-format-radio', 'value'),
    State('export-species-filter', 'value'),
    prevent_initial_call=True
)
def export_data(n_clicks, export_type, export_format, species_id):
    """Export selected data"""
    if not n_clicks:
        return None, None

    try:
        db = DatabaseManager()

        # Build query based on export type
        if export_type == 'markers':
            query = """
            SELECT m.marker_id, c.chromosome_name, m.position_start, m.position_end,
                   m.marker_type, m.description, s.name as species
            FROM markers m
            JOIN chromosomes c ON m.chromosome_id = c.id
            JOIN species s ON c.species_id = s.id
            """
            if species_id:
                query += " WHERE s.id = ?"
                data = db.execute_query(query, (species_id,))
            else:
                data = db.execute_query(query)
            filename = f"markers_export.{export_format}"

        elif export_type == 'haplotypes':
            query = """
            SELECT h.haplotype_name, h.haplotype_sequence, m.marker_id,
                   h.frequency, h.sample_count
            FROM microhaplotypes h
            JOIN markers m ON h.marker_id = m.id
            JOIN chromosomes c ON m.chromosome_id = c.id
            """
            if species_id:
                query += " WHERE c.species_id = ?"
                data = db.execute_query(query, (species_id,))
            else:
                data = db.execute_query(query)
            filename = f"haplotypes_export.{export_format}"

        elif export_type == 'samples':
            query = """
            SELECT s.sample_code, p.project_code, sp.name as species,
                   s.sample_type, s.collection_date, s.collection_location
            FROM samples s
            JOIN projects p ON s.project_id = p.id
            JOIN species sp ON s.species_id = sp.id
            """
            if species_id:
                query += " WHERE s.species_id = ?"
                data = db.execute_query(query, (species_id,))
            else:
                data = db.execute_query(query)
            filename = f"samples_export.{export_format}"

        elif export_type == 'projects':
            query = """
            SELECT project_code, project_name, pi_name, pi_email,
                   pi_institution, pi_department, description, start_date
            FROM projects
            """
            data = db.execute_query(query)
            filename = f"projects_export.{export_format}"

        elif export_type == 'variants':
            query = """
            SELECT m.marker_id, v.position, v.variant_type,
                   v.reference_allele, v.alternate_allele, v.frequency
            FROM variants v
            JOIN markers m ON v.marker_id = m.id
            JOIN chromosomes c ON m.chromosome_id = c.id
            """
            if species_id:
                query += " WHERE c.species_id = ?"
                data = db.execute_query(query, (species_id,))
            else:
                data = db.execute_query(query)
            filename = f"variants_export.{export_format}"

        else:  # 'all'
            return None, dbc.Alert("Complete dataset export coming soon!", color="info")

        if not data:
            return None, dbc.Alert("No data found to export", color="warning")

        # Convert to DataFrame
        df = pd.DataFrame(data)

        # Export based on format
        if export_format == 'csv':
            content = df.to_csv(index=False)
        elif export_format == 'tsv':
            content = df.to_csv(index=False, sep='\t')
        else:  # json
            content = df.to_json(orient='records', indent=2)

        return (
            dict(content=content, filename=filename),
            dbc.Alert(f"Exported {len(data)} records successfully!", color="success")
        )

    except Exception as e:
        return None, dbc.Alert(f"Error: {str(e)}", color="danger")


# Display database statistics
@app.callback(
    Output('database-stats-display', 'children'),
    Input('refresh-stats-btn', 'n_clicks'),
    Input('tools-tabs', 'active_tab')
)
def display_database_stats(n_clicks, active_tab):
    """Display comprehensive database statistics"""
    if active_tab != 'stats-tab':
        return None

    try:
        db = DatabaseManager()

        # Get counts for each table
        stats = {}

        # Species
        species_data = db.execute_query("SELECT id, name, common_name FROM species")
        stats['species'] = len(species_data)

        # Chromosomes
        chr_count = db.execute_query("SELECT COUNT(*) as count FROM chromosomes")[0]['count']
        stats['chromosomes'] = chr_count

        # Markers
        marker_count = db.execute_query("SELECT COUNT(*) as count FROM markers")[0]['count']
        stats['markers'] = marker_count

        # Microhaplotypes
        hap_count = db.execute_query("SELECT COUNT(*) as count FROM microhaplotypes")[0]['count']
        stats['microhaplotypes'] = hap_count

        # Variants
        var_count = db.execute_query("SELECT COUNT(*) as count FROM variants")[0]['count']
        stats['variants'] = var_count

        # Projects
        proj_count = db.execute_query("SELECT COUNT(*) as count FROM projects")[0]['count']
        stats['projects'] = proj_count

        # Samples
        sample_count = db.execute_query("SELECT COUNT(*) as count FROM samples")[0]['count']
        stats['samples'] = sample_count

        # Create display
        return html.Div([
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.I(className="fas fa-globe fa-2x mb-2 text-primary"),
                            html.H3(stats['species'], className="mb-0"),
                            html.Small("Species", className="text-muted")
                        ], className="text-center")
                    ])
                ], width=12, md=6, lg=3, className="mb-3"),

                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.I(className="fas fa-search fa-2x mb-2 text-success"),
                            html.H3(f"{stats['markers']:,}", className="mb-0"),
                            html.Small("Markers", className="text-muted")
                        ], className="text-center")
                    ])
                ], width=12, md=6, lg=3, className="mb-3"),

                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.I(className="fas fa-dna fa-2x mb-2 text-info"),
                            html.H3(f"{stats['microhaplotypes']:,}", className="mb-0"),
                            html.Small("Haplotypes", className="text-muted")
                        ], className="text-center")
                    ])
                ], width=12, md=6, lg=3, className="mb-3"),

                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.I(className="fas fa-vial fa-2x mb-2 text-warning"),
                            html.H3(f"{stats['samples']:,}", className="mb-0"),
                            html.Small("Genotypes", className="text-muted")
                        ], className="text-center")
                    ])
                ], width=12, md=6, lg=3, className="mb-3"),
            ]),

            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.I(className="fas fa-exchange-alt fa-2x mb-2 text-danger"),
                            html.H3(f"{stats['variants']:,}", className="mb-0"),
                            html.Small("Variants", className="text-muted")
                        ], className="text-center")
                    ])
                ], width=12, md=6, lg=4, className="mb-3"),

                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.I(className="fas fa-folder fa-2x mb-2 text-secondary"),
                            html.H3(stats['projects'], className="mb-0"),
                            html.Small("Projects", className="text-muted")
                        ], className="text-center")
                    ])
                ], width=12, md=6, lg=4, className="mb-3"),

                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.I(className="fas fa-th fa-2x mb-2 text-dark"),
                            html.H3(stats['chromosomes'], className="mb-0"),
                            html.Small("Chromosomes", className="text-muted")
                        ], className="text-center")
                    ])
                ], width=12, md=6, lg=4, className="mb-3"),
            ]),

            # Species breakdown
            html.Hr(className="my-4"),
            html.H5("Species Breakdown", className="mb-3"),
            dbc.Table([
                html.Thead(html.Tr([
                    html.Th("Species"),
                    html.Th("Common Name")
                ])),
                html.Tbody([
                    html.Tr([
                        html.Td(sp['name']),
                        html.Td(sp['common_name'])
                    ]) for sp in species_data
                ])
            ], striped=True, hover=True)
        ])

    except Exception as e:
        return dbc.Alert(f"Error loading statistics: {str(e)}", color="danger")


# Generate data summary
@app.callback(
    Output('summary-report-display', 'children'),
    Input('generate-summary-btn', 'n_clicks'),
    State('summary-species-dropdown', 'value'),
    prevent_initial_call=True
)
def generate_summary_report(n_clicks, species_id):
    """Generate a comprehensive summary report for selected species"""
    if not species_id:
        return dbc.Alert("Please select a species", color="warning")

    try:
        db = DatabaseManager()

        # Get species info
        species = db.execute_query(
            "SELECT name, common_name FROM species WHERE id = ?",
            (species_id,)
        )[0]

        # Get counts
        chr_query = "SELECT COUNT(*) as count FROM chromosomes WHERE species_id = ?"
        chr_count = db.execute_query(chr_query, (species_id,))[0]['count']

        marker_query = """
        SELECT COUNT(*) as count FROM markers m
        JOIN chromosomes c ON m.chromosome_id = c.id
        WHERE c.species_id = ?
        """
        marker_count = db.execute_query(marker_query, (species_id,))[0]['count']

        hap_query = """
        SELECT COUNT(*) as count FROM microhaplotypes h
        JOIN markers m ON h.marker_id = m.id
        JOIN chromosomes c ON m.chromosome_id = c.id
        WHERE c.species_id = ?
        """
        hap_count = db.execute_query(hap_query, (species_id,))[0]['count']

        sample_query = "SELECT COUNT(*) as count FROM samples WHERE species_id = ?"
        sample_count = db.execute_query(sample_query, (species_id,))[0]['count']

        return dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-file-alt me-2"),
                    f"Summary Report: {species['common_name']}"
                ], className="mb-0")
            ]),
            dbc.CardBody([
                html.H6(f"Scientific Name: {species['name']}", className="text-muted mb-3"),

                dbc.ListGroup([
                    dbc.ListGroupItem([
                        html.Strong("Chromosomes: "),
                        f"{chr_count}"
                    ]),
                    dbc.ListGroupItem([
                        html.Strong("Markers: "),
                        f"{marker_count:,}"
                    ]),
                    dbc.ListGroupItem([
                        html.Strong("Unique Haplotypes: "),
                        f"{hap_count:,}"
                    ]),
                    dbc.ListGroupItem([
                        html.Strong("Genotypes: "),
                        f"{sample_count:,}"
                    ]),
                    dbc.ListGroupItem([
                        html.Strong("Avg Haplotypes per Marker: "),
                        f"{hap_count/marker_count:.2f}" if marker_count > 0 else "N/A"
                    ])
                ])
            ])
        ])

    except Exception as e:
        return dbc.Alert(f"Error generating summary: {str(e)}", color="danger")
