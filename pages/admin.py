"""Admin Page - User management for administrators

Provides a table of whitelisted users and forms to add, edit, and remove users.
This tab is only rendered when the logged-in user has role='admin'.
"""

import dash
from dash import dcc, html, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dash_app import app
from database.db_manager import DatabaseManager
from auth.session import is_admin


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = dbc.Container([
    # Status alert (hidden by default)
    html.Div(id='admin-status-alert'),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-users-cog me-2"),
                    "User Management"
                ]),
                dbc.CardBody([
                    # Add User Form
                    dbc.Row([
                        dbc.Col([
                            html.H6("Add New User", className="mb-3"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("ORCID iD", html_for="admin-add-orcid"),
                                    dbc.Input(
                                        id="admin-add-orcid",
                                        type="text",
                                        placeholder="0000-0001-2345-6789",
                                    ),
                                ], md=4),
                                dbc.Col([
                                    dbc.Label("Display Name", html_for="admin-add-name"),
                                    dbc.Input(
                                        id="admin-add-name",
                                        type="text",
                                        placeholder="Jane Doe",
                                    ),
                                ], md=3),
                                dbc.Col([
                                    dbc.Label("Email (optional)", html_for="admin-add-email"),
                                    dbc.Input(
                                        id="admin-add-email",
                                        type="email",
                                        placeholder="user@example.com",
                                    ),
                                ], md=3),
                                dbc.Col([
                                    dbc.Label("Role", html_for="admin-add-role"),
                                    dcc.Dropdown(
                                        id="admin-add-role",
                                        options=[
                                            {"label": "User", "value": "user"},
                                            {"label": "Admin", "value": "admin"},
                                        ],
                                        value="user",
                                        clearable=False,
                                    ),
                                ], md=2),
                            ], className="mb-3"),
                            dbc.Button(
                                [html.I(className="fas fa-plus me-2"), "Add User"],
                                id="admin-add-btn",
                                color="primary",
                                className="mb-4",
                            ),
                        ], width=12),
                    ]),

                    html.Hr(),

                    # Users Table
                    html.H6("Registered Users", className="mb-3"),
                    dcc.Loading(
                        html.Div(id="admin-users-table"),
                        type="default",
                    ),
                ])
            ], className="mb-4")
        ], width=12)
    ]),

    # Hidden store to trigger table refresh
    dcc.Store(id="admin-refresh-trigger", data=0),

    # Confirmation modal for deletion
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Confirm Removal")),
        dbc.ModalBody("Are you sure you want to remove this user?"),
        dbc.ModalFooter([
            dbc.Button("Cancel", id="admin-delete-cancel", className="me-2",
                        color="secondary"),
            dbc.Button("Remove", id="admin-delete-confirm", color="danger"),
        ]),
    ], id="admin-delete-modal", is_open=False),
    dcc.Store(id="admin-delete-target-orcid", data=None),

], fluid=True, className="py-3")


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _get_all_users():
    """Fetch all users from the database."""
    try:
        db = DatabaseManager()
        return db.execute_query(
            "SELECT orcid_id, display_name, email, role, is_active, "
            "created_at, last_login FROM users ORDER BY created_at DESC"
        )
    except Exception:
        return []


def _build_users_table(users):
    """Build a Bootstrap-styled table from user records."""
    if not users:
        return html.P("No users found. Add a user above to get started.",
                       className="text-muted")

    header = html.Thead(html.Tr([
        html.Th("ORCID iD"),
        html.Th("Name"),
        html.Th("Email"),
        html.Th("Role"),
        html.Th("Active"),
        html.Th("Last Login"),
        html.Th("Actions"),
    ]))

    rows = []
    for u in users:
        orcid_id = u['orcid_id']
        is_active = u.get('is_active', 1)

        toggle_btn = dbc.Button(
            html.I(className="fas fa-toggle-on" if is_active else "fas fa-toggle-off"),
            id={"type": "admin-toggle-active", "index": orcid_id},
            color="success" if is_active else "secondary",
            size="sm",
            className="me-1",
            title="Toggle active status",
        )

        role_btn = dbc.Button(
            html.I(className="fas fa-user-shield" if u['role'] == 'admin' else "fas fa-user"),
            id={"type": "admin-toggle-role", "index": orcid_id},
            color="warning" if u['role'] == 'admin' else "info",
            size="sm",
            className="me-1",
            title="Toggle role (admin/user)",
            outline=True,
        )

        delete_btn = dbc.Button(
            html.I(className="fas fa-trash-alt"),
            id={"type": "admin-delete-user", "index": orcid_id},
            color="danger",
            size="sm",
            outline=True,
            title="Remove user",
        )

        rows.append(html.Tr([
            html.Td(html.A(orcid_id,
                           href=f"https://orcid.org/{orcid_id}",
                           target="_blank",
                           className="text-decoration-none")),
            html.Td(u.get('display_name') or ''),
            html.Td(u.get('email') or ''),
            html.Td(dbc.Badge(u['role'], color="danger" if u['role'] == 'admin' else "primary")),
            html.Td(dbc.Badge("Active" if is_active else "Inactive",
                              color="success" if is_active else "secondary")),
            html.Td(u.get('last_login') or 'Never'),
            html.Td([toggle_btn, role_btn, delete_btn]),
        ]))

    return dbc.Table(
        [header, html.Tbody(rows)],
        bordered=True,
        hover=True,
        responsive=True,
        size="sm",
    )


# --- Render table ---
@callback(
    Output('admin-users-table', 'children'),
    Input('admin-refresh-trigger', 'data'),
    prevent_initial_call=False,
)
def render_users_table(_trigger):
    if not is_admin():
        return dbc.Alert(
            "Unauthorized: admin access required.",
            color="danger",
            dismissable=True,
        )
    users = _get_all_users()
    return _build_users_table(users)


# --- Add user ---
@callback(
    Output('admin-status-alert', 'children', allow_duplicate=True),
    Output('admin-refresh-trigger', 'data', allow_duplicate=True),
    Output('admin-add-orcid', 'value'),
    Output('admin-add-name', 'value'),
    Output('admin-add-email', 'value'),
    Input('admin-add-btn', 'n_clicks'),
    State('admin-add-orcid', 'value'),
    State('admin-add-name', 'value'),
    State('admin-add-email', 'value'),
    State('admin-add-role', 'value'),
    State('admin-refresh-trigger', 'data'),
    prevent_initial_call=True,
)
def add_user(n_clicks, orcid_id, name, email, role, refresh):
    if not is_admin():
        alert = dbc.Alert(
            "Unauthorized: admin access required.",
            color="danger",
            dismissable=True,
            duration=5000,
        )
        return alert, no_update, no_update, no_update, no_update

    if not n_clicks or not orcid_id:
        return no_update, no_update, no_update, no_update, no_update

    orcid_id = orcid_id.strip()

    try:
        db = DatabaseManager()
        # Check if user already exists
        existing = db.execute_query(
            "SELECT orcid_id FROM users WHERE orcid_id = ?", (orcid_id,)
        )
        if existing:
            alert = dbc.Alert(
                f"User with ORCID {orcid_id} already exists.",
                color="warning", dismissable=True, duration=5000,
            )
            return alert, no_update, no_update, no_update, no_update

        db.execute_update(
            "INSERT INTO users (orcid_id, display_name, email, role) VALUES (?, ?, ?, ?)",
            (orcid_id, name or None, email or None, role),
        )
        alert = dbc.Alert(
            f"User {orcid_id} added successfully.",
            color="success", dismissable=True, duration=5000,
        )
        return alert, (refresh or 0) + 1, '', '', ''
    except Exception as e:
        alert = dbc.Alert(
            f"Error adding user: {e}",
            color="danger", dismissable=True, duration=5000,
        )
        return alert, no_update, no_update, no_update, no_update


# --- Toggle active status ---
@callback(
    Output('admin-status-alert', 'children', allow_duplicate=True),
    Output('admin-refresh-trigger', 'data', allow_duplicate=True),
    Input({"type": "admin-toggle-active", "index": dash.ALL}, 'n_clicks'),
    State('admin-refresh-trigger', 'data'),
    prevent_initial_call=True,
)
def toggle_active(all_clicks, refresh):
    if not is_admin():
        alert = dbc.Alert(
            "Unauthorized: admin access required.",
            color="danger",
            dismissable=True,
            duration=5000,
        )
        return alert, no_update

    if not ctx.triggered_id or not any(all_clicks):
        return no_update, no_update
    orcid_id = ctx.triggered_id['index']
    try:
        db = DatabaseManager()
        db.execute_update(
            "UPDATE users SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END "
            "WHERE orcid_id = ?",
            (orcid_id,),
        )
        alert = dbc.Alert(
            f"Toggled active status for {orcid_id}.",
            color="info", dismissable=True, duration=3000,
        )
        return alert, (refresh or 0) + 1
    except Exception as e:
        return dbc.Alert(f"Error: {e}", color="danger", dismissable=True, duration=5000), no_update


# --- Toggle role ---
@callback(
    Output('admin-status-alert', 'children', allow_duplicate=True),
    Output('admin-refresh-trigger', 'data', allow_duplicate=True),
    Input({"type": "admin-toggle-role", "index": dash.ALL}, 'n_clicks'),
    State('admin-refresh-trigger', 'data'),
    prevent_initial_call=True,
)
def toggle_role(all_clicks, refresh):
    if not is_admin():
        alert = dbc.Alert(
            "Unauthorized: admin access required.",
            color="danger",
            dismissable=True,
            duration=5000,
        )
        return alert, no_update

    if not ctx.triggered_id or not any(all_clicks):
        return no_update, no_update
    orcid_id = ctx.triggered_id['index']
    try:
        db = DatabaseManager()
        db.execute_update(
            "UPDATE users SET role = CASE WHEN role = 'admin' THEN 'user' ELSE 'admin' END "
            "WHERE orcid_id = ?",
            (orcid_id,),
        )
        alert = dbc.Alert(
            f"Toggled role for {orcid_id}.",
            color="info", dismissable=True, duration=3000,
        )
        return alert, (refresh or 0) + 1
    except Exception as e:
        return dbc.Alert(f"Error: {e}", color="danger", dismissable=True, duration=5000), no_update


# --- Delete user (open modal) ---
@callback(
    Output('admin-delete-modal', 'is_open', allow_duplicate=True),
    Output('admin-delete-target-orcid', 'data', allow_duplicate=True),
    Input({"type": "admin-delete-user", "index": dash.ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def open_delete_modal(all_clicks):
    if not is_admin():
        return no_update, no_update

    if not ctx.triggered_id or not any(all_clicks):
        return no_update, no_update
    return True, ctx.triggered_id['index']


# --- Delete user (cancel) ---
@callback(
    Output('admin-delete-modal', 'is_open', allow_duplicate=True),
    Input('admin-delete-cancel', 'n_clicks'),
    prevent_initial_call=True,
)
def cancel_delete(_):
    if not is_admin():
        return no_update
    return False


# --- Delete user (confirm) ---
@callback(
    Output('admin-delete-modal', 'is_open'),
    Output('admin-status-alert', 'children'),
    Output('admin-refresh-trigger', 'data'),
    Input('admin-delete-confirm', 'n_clicks'),
    State('admin-delete-target-orcid', 'data'),
    State('admin-refresh-trigger', 'data'),
    prevent_initial_call=True,
)
def confirm_delete(n_clicks, orcid_id, refresh):
    if not is_admin():
        alert = dbc.Alert(
            "Unauthorized: admin access required.",
            color="danger",
            dismissable=True,
            duration=5000,
        )
        return False, alert, no_update

    if not n_clicks or not orcid_id:
        return no_update, no_update, no_update
    try:
        db = DatabaseManager()
        db.execute_update("DELETE FROM users WHERE orcid_id = ?", (orcid_id,))
        alert = dbc.Alert(
            f"User {orcid_id} removed.",
            color="warning", dismissable=True, duration=5000,
        )
        return False, alert, (refresh or 0) + 1
    except Exception as e:
        alert = dbc.Alert(
            f"Error removing user: {e}",
            color="danger", dismissable=True, duration=5000,
        )
        return False, alert, no_update
