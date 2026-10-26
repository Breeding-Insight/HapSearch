#!/usr/bin/env python3
"""HapSearch - Microhaplotype Analysis Platform

Tab-based interface variant of the microhaplotype analysis platform
"""

from dash import dcc, html, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc
from flask import redirect, session, send_from_directory

import config
import logging
import sys
import os

# stderr is collected by Cloud Logging on Cloud Run. Only auth events (such as
# sign-ins) are logged at INFO; everything else stays at WARNING.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger('auth').setLevel(logging.INFO)

# Add current directory to path for database/design imports
sys.path.insert(0, os.path.dirname(__file__))

from dash_app import app, server

# Register auth blueprint
from auth.orcid import auth_bp
server.register_blueprint(auth_bp)

# Import session helpers
from auth.session import is_authenticated, get_current_user, start_local_dev_session
from database import allele_filter
from auth.user_store import get_user_store

if config.USER_STORE_PREFLIGHT:
    try:
        get_user_store().assert_ready()
    except Exception as exc:
        raise RuntimeError(
            f"The {config.USER_STORE} user store is not reachable. On Cloud Run, check "
            "FIRESTORE_DATABASE, GOOGLE_CLOUD_PROJECT and that the service account has "
            f"roles/datastore.viewer. ({exc})"
        ) from exc


# ---------------------------------------------------------------------------
# Flask routes (landing page, auth guard)
# ---------------------------------------------------------------------------

@server.route('/')
def landing_page():
    """Send visitors to the app, the public landing page, or sign-in.

    The public landing page lives on GitHub Pages (landing/), so the service
    serves none of its own: signed-out visitors go to HAPSEARCH_LANDING_URL,
    or straight to sign-in when it is not set (e.g. local development).
    """
    if is_authenticated():
        return redirect('/app/')
    return redirect(config.LANDING_URL or '/auth/login')


@server.route('/health')
def health():
    """Unauthenticated wake-up/health check that never touches the database."""
    return 'ok', 200, {'Content-Type': 'text/plain', 'Cache-Control': 'no-store'}


@server.route('/robots.txt')
def robots_txt():
    """Keep crawlers from waking the scale-to-zero service."""
    return 'User-agent: *\nDisallow: /\n', 200, {'Content-Type': 'text/plain'}


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
        'brand/hapsearch-icon.png',
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
    """Dynamically build the layout so the header shows the signed-in user."""
    user = get_current_user()
    user_display = user['user_name'] if user else ''

    tabs = [
        dbc.Tab(
            overview.layout,
            label="Filter by Programs",
            tab_id="programs-tab",
            tab_style={"marginRight": "5px"}
        ),
        dbc.Tab(
            haplotype_explorer.layout,
            label="Microhaplotypes",
            tab_id="haplotype-tab",
            tab_class_name="microhaplotypes-tab",
        ),
        dbc.Tab(
            marker_explorer.layout,
            label="Multiple Sequence Alignment",
            tab_id="marker-tab",
            tab_style={"marginRight": "5px"}
        ),
        dbc.Tab(
            overview.database_layout,
            label="Database Overview",
            tab_id="database-tab",
        ),
    ]

    # Header right: user, logout
    header_right_elts = [
        html.I(className="fas fa-user me-1"),
        user_display,
        html.Span("|", className="app-header-sep", **{"aria-hidden": "true"}),
        html.A("Log out", href="/auth/logout")
    ]

    layout_children = [
        dcc.Store(id='selected-species-store', data=None),
        dcc.Store(id='navigate-to-haplotype-store', data=None),
        dcc.Store(id='navigate-to-marker-store', data=None),
        dcc.Store(id='app-initialized-store', data=False),
        # Header and footer follow the landing page (landing/index.html).
        html.Header([
            html.Div([
                html.A(
                    html.Img(src="/static/brand/breeding-insight-logo.png", alt="Breeding Insight",
                             className="app-bi-logo"),
                    href="https://breedinginsight.org/",
                ),
                html.Span(className="app-brand-divider", **{"aria-hidden": "true"}),
                html.A([
                    html.Img(src="/static/brand/hapsearch-logo.png", alt=""),
                    html.Span([
                        html.Span("Hap", className="wm-hap"),
                        html.Span("Search", className="wm-search"),
                    ], className="app-name"),
                ], href="/app/", className="app-brand"),
            ], className="app-header-left"),
            html.Div([
                html.Div(id='db-status-header', className="app-header-stats"),
                html.Div(header_right_elts, className="app-header-user"),
            ], className="app-header-right"),
        ], className="app-header"),

        # Global filters: every tab follows the species, programs and alleles
        # chosen here (see database/allele_filter.py).
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Species", htmlFor='global-species-dropdown',
                                   className="fw-bold small mb-1"),
                        dcc.Dropdown(id='global-species-dropdown', placeholder="Select a species...",
                                     clearable=False),
                    ], lg=3, md=12, className="mb-2 mb-lg-0"),
                    dbc.Col([
                        html.Label("Programs", htmlFor='global-programs-dropdown',
                                   className="fw-bold small mb-1"),
                        dcc.Dropdown(id='global-programs-dropdown', multi=True,
                                     placeholder="All programs"),
                    ], lg=5, md=12, className="mb-2 mb-lg-0"),
                    dbc.Col([
                        html.Label("Alleles", htmlFor='global-allele-filter',
                                   className="fw-bold small mb-1"),
                        dcc.Dropdown(id='global-allele-filter', value='any', clearable=False,
                                     searchable=True),
                    ], lg=4, md=12),
                ], className="g-3"),
            ])
        ], className="mb-3 app-filter-bar"),

        dbc.Tabs(tabs, id="main-tabs", active_tab="programs-tab", className="mb-4"),

        html.Footer([
            html.Ul([
                html.Li(html.Img(src="/static/brand/breeding-insight-logo-white.png",
                                 alt="Breeding Insight"), className="logo-bi"),
                html.Li(html.Img(src="/static/brand/usda-ars-logo-white.png",
                                 alt="USDA Agricultural Research Service")),
                html.Li(html.A(html.Img(src="/static/brand/uf-ifas-logo.svg",
                                        alt="University of Florida Institute of Food and Agricultural Sciences (UF/IFAS)"),
                               href="https://ifas.ufl.edu/"), className="logo-ifas"),
                html.Li(html.Img(src="/static/brand/cornell-logo-white.png", alt="Cornell University")),
            ], className="app-partner-logos", **{"aria-label": "Partner organizations"}),
            html.P(
                "Breeding Insight is funded by the U.S. Department of Agriculture (USDA) Agricultural "
                "Research Service (ARS) through University of Florida/IFAS. Formerly at Cornell University.",
                className="app-funding",
            ),
            html.Div([
                html.P("© 2026 Breeding Insight"),
                html.Ul([
                    html.Li(html.A("About Breeding Insight", href="https://breedinginsight.org/about-bi/")),
                    html.Li(html.A("Contact us", href="https://breedinginsight.org/contact-us/")),
                    html.Li(html.A("Source code", href="https://github.com/Breeding-Insight/HapSearch")),
                ]),
            ], className="app-footer-bottom"),
        ], className="app-footer"),
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


@callback(
    Output('global-programs-dropdown', 'options'),
    Output('global-programs-dropdown', 'value'),
    Input('selected-species-store', 'data'),
)
def load_global_programs(species_id):
    """List the species' programs; none selected means all programs."""
    if not species_id:
        return [], []
    try:
        catalog = allele_filter.program_catalog(int(species_id))
        options = [{'label': group['label'], 'value': group['group_id']} for group in catalog]
        # Empty shows the "All programs" placeholder; every view treats an
        # empty selection as all programs (allele_filter.default_program_ids).
        return options, []
    except Exception:
        return [], []


@callback(
    Output('global-allele-filter', 'options'),
    Output('global-allele-filter', 'value'),
    Input('global-programs-dropdown', 'value'),
    State('selected-species-store', 'data'),
)
def load_allele_filter_options(program_ids, species_id):
    """Offer allele filters for the selected programs; reset to all alleles."""
    try:
        return allele_filter.allele_filter_options(species_id, program_ids), allele_filter.ANY
    except Exception:
        return [], allele_filter.ANY


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
                f"{stats['sample_count']:,} Samples"
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
    if active_tab == "programs-tab":
        return False
    return True


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
