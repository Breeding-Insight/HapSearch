"""Session helpers for authentication and authorization"""

from functools import wraps
from flask import session, redirect, request
from database.db_manager import DatabaseManager
import config


def start_local_dev_session():
    """Create a local development session when ORCID auth is bypassed."""
    session['orcid_id'] = config.BYPASS_DEV_ORCID
    session['user_name'] = config.BYPASS_DEV_NAME
    session['user_role'] = config.BYPASS_DEV_ROLE


def get_current_user():
    """Get the current authenticated user from the Flask session.
    
    Returns:
        dict with orcid_id, user_name, user_role or None if not authenticated.
    """
    orcid_id = session.get('orcid_id')
    if not orcid_id:
        return None
    return {
        'orcid_id': orcid_id,
        'user_name': session.get('user_name', ''),
        'user_role': session.get('user_role', 'user'),
    }


def is_authenticated():
    """Check if the current request has a valid session."""
    return session.get('orcid_id') is not None


def is_admin():
    """Check if the current user is an admin."""
    return is_authenticated() and session.get('user_role') == 'admin'


def require_login(f):
    """Flask route decorator that redirects to landing page if not logged in."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            return redirect('/')
        return f(*args, **kwargs)
    return decorated_function


def lookup_user(orcid_id):
    """Look up a user in the whitelist by ORCID iD.
    
    Returns:
        dict with user record or None if not found / inactive.
    """
    try:
        db = DatabaseManager()
        results = db.execute_query(
            "SELECT * FROM users WHERE orcid_id = ? AND is_active = 1",
            (orcid_id,)
        )
        return results[0] if results else None
    except Exception:
        return None


def update_last_login(orcid_id):
    """Update last_login timestamp for a user."""
    try:
        db = DatabaseManager()
        db.execute_update(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE orcid_id = ?",
            (orcid_id,)
        )
    except Exception:
        pass
