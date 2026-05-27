#!/usr/bin/env python3
"""HapSearch - Microhaplotype Analysis Platform

Tab-based interface variant of the microhaplotype analysis platform
"""

from dash import dcc, html, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc
from flask import redirect, session, render_template, send_from_directory

import config
import sys
import os

# Add current directory to path for database/design imports
sys.path.insert(0, os.path.dirname(__file__))

from dash_app import app, server

# Register auth blueprint
from auth.orcid import auth_bp
server.register_blueprint(auth_bp)

# Import session helpers
from auth.session import is_authenticated, is_admin, get_current_user, start_local_dev_session


# ---------------------------------------------------------------------------
# Flask routes (landing page, auth guard)
# ---------------------------------------------------------------------------

@server.route('/')
def landing_page():
    """Serve the public landing page."""
    user = get_current_user() if is_authenticated() else None
    return render_template('landing.html',
                           app_env=config.APP_ENV,
                           user=user)


@server.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files for the landing page."""
    import logging
    base_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(base_dir, 'static')
    file_path = os.path.join(static_dir, filename)
    
    # Security: prevent directory traversal
    if not os.path.abspath(file_path).startswith(os.path.abspath(static_dir)):
        from flask import abort
        abort(403)
    
    try:
        if not os.path.exists(file_path):
            from flask import abort
            abort(404)
        return send_from_directory(static_dir, filename)
    except Exception as e:
        import logging
        logging.error(f"Error serving static file {filename}: {e}")
        from flask import abort
        abort(500)


@server.route('/favicon.ico')
def favicon():
    """Serve favicon with cache-busting-friendly source."""
    return send_from_directory(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'),
        'HaploSearch_favicon_2.png',
        mimetype='image/png',
        max_age=0,
    )


@server.before_request
def require_auth_for_app():
    """Redirect unauthenticated users away from the Dash app."""
    from flask import request
    # Skip static files and auth routes
    if request.path.startswith('/static/') or request.path.startswith('/auth/'):
        return
    # Always allow Dash internals to load (js/css bundles, assets, layout/deps endpoints)
    # otherwise the browser receives redirects/html instead of scripts and the app crashes.
    if (
        request.path.startswith('/app/_dash-')
        or request.path.startswith('/app/_favicon')
        or request.path.startswith('/app/assets/')
        or request.path.startswith('/app/_dash-component-suites/')
    ):
        return
    # Only guard Dash routes under /app/
    if request.path.startswith('/app'):
        if config.BYPASS_ORCID_AUTH:
            start_local_dev_session()
            return
        if not is_authenticated():
            return redirect('/')


# ---------------------------------------------------------------------------
# Dash layout & callbacks
# ---------------------------------------------------------------------------

from pages import overview, marker_explorer, haplotype_explorer


def serve_layout():
    """Dynamically build the layout so admin tab is conditionally included."""
    user = get_current_user()
    user_display = user['user_name'] if user else ''
    user_role = user['user_role'] if user else 'user'

    tabs = [
        dbc.Tab(
            overview.layout,
            label="Overview",
            tab_id="overview-tab",
            label_style={"color": "#000000"},
            active_label_style={"color": "#245842", "fontWeight": "700"},
            tab_style={"marginRight": "5px"}
        ),
        dbc.Tab(
            haplotype_explorer.layout,
            label="Microhaplotypes",
            tab_id="haplotype-tab",
            tab_class_name="microhaplotypes-tab",
            label_style={"color": "#000000"},
            active_label_style={"color": "#245842", "fontWeight": "700"}
        ),
        dbc.Tab(
            marker_explorer.layout,
            label="Multiple Sequence Alignment",
            tab_id="marker-tab",
            label_style={"color": "#000000"},
            active_label_style={"color": "#245842", "fontWeight": "700"},
            tab_style={"marginRight": "5px"}
        ),
    ]

    # Header right: user, admin settings icon (visible only for admins), logout
    from pages import admin
    header_right_elts = [
        html.I(className="fas fa-user me-1"),
        user_display,
        " | ",
        dbc.Button(
            html.I(className="fas fa-cog"),
            id="admin-open-btn",
            color="link",
            size="sm",
            className="p-0 me-1",
            title="User management",
            style={"display": "inline-block" if user_role == 'admin' else "none", "color": "#000000"},
        ),
        " ",
        html.A("Logout", href="/auth/logout", className="text-muted")
    ]

    layout_children = [
        dcc.Store(id='selected-species-store', data=None),
        dcc.Store(id='navigate-to-haplotype-store', data=None),
        dcc.Store(id='navigate-to-marker-store', data=None),
        dcc.Store(id='app-initialized-store', data=False),
        html.Div([
            html.Div([
                html.Div([
                    html.Div([
                        html.Img(
                            src="/static/Haplosearch%20logo_favicon.png",
                            alt="HapSearch",
                        )
                    ], className="app-hero-icon"),
                    html.H1([
                        html.Span("Hap", className="hero-bold"),
                        "Search"
                    ], className="app-hero-title mb-0")
                ], className="app-hero-left"),
                html.Div([
                    html.Div(id='db-status-header', className="text-end"),
                    html.Div(header_right_elts, className="app-hero-user-line")
                ], className="app-hero-right")
            ], className="app-hero-top-row"),
            html.P(
                "Browse, search, and analyze microhaplotype data across species and projects.",
                className="app-hero-subtitle"
            )
        ], className="app-hero-section"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.Label("Select Species:", className="fw-bold me-3 mb-0"),
                            dcc.Dropdown(
                                id='global-species-dropdown',
                                placeholder="Select a species...",
                                style={'minWidth': '300px'}
                            )
                        ], style={'display': 'flex', 'alignItems': 'center'})
                    ])
                ], className="mb-3")
            ], width=12)
        ]),

        dbc.Tabs(tabs, id="main-tabs", active_tab="overview-tab", className="mb-4"),

        html.Footer([
            html.Div([
                html.Div([
                    html.Img(
                        src="/static/USDAARSIdentityColor_clearBKG.png",
                        alt="USDA ARS Logo",
                        style={"height": "50px", "width": "auto", "maxWidth": "150px"}
                    ),
                    html.Img(
                        src="/static/IFAS-RGB.png",
                        alt="UF/IFAS Logo",
                        style={"height": "50px", "width": "auto", "maxWidth": "200px"}
                    ),
                    html.Img(
                        src="/static/BreedingInsightLogo-RGB-1600px.png",
                        alt="Breeding Insight Logo",
                        style={"height": "50px", "width": "auto", "maxWidth": "200px"}
                    ),
                ], className="app-footer-logos"),
                html.Div([
                    html.Small("Funded by USDA-ARS and housed at University of Florida (UF/IFAS)."),
                    html.Br(),
                    html.Small("© 2026 Breeding Insight", style={"marginTop": "0.5rem", "display": "block"}),
                ], className="app-footer-text"),
            ], className="container")
        ], className="app-footer"),
        # Admin modal (always in DOM so callback works; only openable by admins via settings icon)
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("User Management"), close_button=True),
            dbc.ModalBody(admin.layout),
            dbc.ModalFooter(dbc.Button("Close", id="admin-modal-close", color="secondary")),
        ], id="admin-modal", is_open=False, size="xl", scrollable=True),
    ]

    return dbc.Container(layout_children, fluid=True, className="p-4")


app.layout = serve_layout


@callback(
    Output('global-species-dropdown', 'options'),
    Output('global-species-dropdown', 'value'),
    Output('selected-species-store', 'data'),
    Input('global-species-dropdown', 'id'),
    prevent_initial_call=False
)
def load_global_species(_):
    """Load available species and set default"""
    try:
        from database.db_manager import DatabaseManager
        from database.queries import get_all_species

        db = DatabaseManager()
        species = get_all_species(db)
        options = [{'label': f"{s['common_name']} ({s['name']})", 'value': s['id']}
                   for s in species]

        default_value = species[0]['id'] if species else None

        return options, default_value, default_value
    except Exception as e:
        return [], None, None


@callback(
    Output('selected-species-store', 'data', allow_duplicate=True),
    Input('global-species-dropdown', 'value'),
    prevent_initial_call=True
)
def update_global_species_store(species_id):
    """Update global species store when dropdown selection changes"""
    return species_id


# Callback to update database status header
@callback(
    Output('db-status-header', 'children'),
    Input('main-tabs', 'active_tab'),
    Input('app-initialized-store', 'data'),
    prevent_initial_call=False
)
def update_db_status(active_tab, app_initialized):
    """Display database statistics in header"""
    try:
        from database.db_manager import DatabaseManager
        from database.queries import get_database_statistics

        db = DatabaseManager()
        stats = get_database_statistics(db)

        return html.Div([
            html.Small([
                html.I(className="fas fa-database me-2"),
                f"{stats['species_count']} Species | ",
                f"{stats['marker_count']:,} Loci | ",
                f"{stats['microhaplotype_count']:,} Microhaplotypes | ",
                f"{stats['sample_count']:,} Genotypes"
            ], className="text-muted")
        ])
    except Exception as e:
        import traceback
        print(f"Error in update_db_status: {e}")
        print(traceback.format_exc())
        return html.Small([
            html.I(className="fas fa-exclamation-triangle me-2 text-danger"),
            f"Database error: {str(e)}"
        ])


@callback(
    Output('app-initialized-store', 'data'),
    Input('main-tabs', 'active_tab'),
    State('app-initialized-store', 'data'),
    prevent_initial_call=False
)
def mark_app_initialized_on_tab_change(active_tab, current_initialized):
    """Mark app as initialized when user manually changes tabs"""
    if current_initialized:
        return no_update
    if active_tab == "overview-tab":
        return False
    return True


@callback(
    Output('admin-modal', 'is_open'),
    Input('admin-open-btn', 'n_clicks'),
    Input('admin-modal-close', 'n_clicks'),
    State('admin-modal', 'is_open'),
    prevent_initial_call=True,
)
def toggle_admin_modal(open_clicks, close_clicks, is_open):
    """Open admin modal from settings icon, close from Close button."""
    if ctx.triggered_id == 'admin-open-btn':
        return True
    return False


@callback(
    Output('main-tabs', 'active_tab'),
    Input('navigate-to-haplotype-store', 'data'),
    Input('navigate-to-marker-store', 'data'),
    State('main-tabs', 'active_tab'),
    State('app-initialized-store', 'data'),
    prevent_initial_call=True
)
def navigate_between_tabs(haplotype_data, marker_data, current_tab, app_initialized):
    """Switch tabs based on cross-tab navigation"""
    triggered_id = ctx.triggered_id
    
    if not app_initialized:
        return no_update
    
    if triggered_id == 'navigate-to-haplotype-store':
        if (haplotype_data is not None and 
            isinstance(haplotype_data, dict) and 
            haplotype_data.get('haplotype_name')):
            return 'haplotype-tab'
    
    elif triggered_id == 'navigate-to-marker-store':
        if (marker_data is not None and 
            isinstance(marker_data, dict) and 
            marker_data.get('marker_id')):
            return 'marker-tab'
    
    return no_update


if __name__ == '__main__':
    app.run(
        debug=config.DEBUG_MODE,
        host=config.APP_HOST,
        port=config.APP_PORT,
        ssl_context=config.SSL_CONTEXT
    )
