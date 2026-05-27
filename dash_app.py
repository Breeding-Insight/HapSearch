"""Dash app instance - imported by both main app and page modules"""

import dash
import dash_bootstrap_components as dbc
import config
import os
from werkzeug.middleware.proxy_fix import ProxyFix

# Initialize Dash app with Bootstrap theme, mounted at /app/
_ASSETS_FOLDER = os.path.join(os.path.dirname(__file__), "assets")
_TEMPLATES_FOLDER = os.path.join(os.path.dirname(__file__), "templates")

app = dash.Dash(
    __name__,
    url_base_pathname='/app/',
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
    assets_folder=_ASSETS_FOLDER,
    suppress_callback_exceptions=True,
    title=config.APP_TITLE
)

# Ensure Dash /app uses the same favicon as the landing page.
# Keep a single favicon source to avoid browser precedence/caching conflicts.
app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        <link rel="icon" type="image/png" href="/static/HaploSearch_favicon_2.png">
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""

server = app.server  # For deployment

# Configure Flask server
server.secret_key = config.SECRET_KEY
server.template_folder = _TEMPLATES_FOLDER
# Configure static folder for serving static files (e.g., images for landing page)
_STATIC_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
if os.path.exists(_STATIC_FOLDER):
    server.static_folder = _STATIC_FOLDER

# Trust X-Forwarded-Proto when behind a reverse proxy (e.g. ngrok) so redirect_uri uses https
server.wsgi_app = ProxyFix(server.wsgi_app, x_proto=1)
