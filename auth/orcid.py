"""ORCID OAuth2 Flask routes for authentication"""

import secrets
import requests as http_requests
from flask import Blueprint, redirect, request, session, url_for, render_template
import config
from auth.session import lookup_user, update_last_login, start_local_dev_session

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login')
def login():
    """Redirect user to ORCID authorization page."""
    if config.BYPASS_ORCID_AUTH:
        start_local_dev_session()
        return redirect('/app/')

    # Generate a random state parameter to prevent CSRF
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state

    # Build the callback URL dynamically
    redirect_uri = request.url_root.rstrip('/') + url_for('auth.callback')

    params = {
        'client_id': config.ORCID_CLIENT_ID,
        'response_type': 'code',
        'scope': '/authenticate',
        'redirect_uri': redirect_uri,
        'state': state,
    }
    authorize_url = config.ORCID_AUTHORIZE_URL + '?' + '&'.join(
        f'{k}={v}' for k, v in params.items()
    )
    return redirect(authorize_url)


@auth_bp.route('/callback')
def callback():
    """Handle the ORCID OAuth2 callback."""
    # Verify state parameter
    state = request.args.get('state')
    if state != session.pop('oauth_state', None):
        return render_template('auth_error.html',
                               error='Invalid state parameter. Please try again.'), 400

    code = request.args.get('code')
    if not code:
        error = request.args.get('error_description', 'Authorization was denied.')
        return render_template('auth_error.html', error=error), 400

    # Exchange authorization code for access token
    redirect_uri = request.url_root.rstrip('/') + url_for('auth.callback')
    token_data = {
        'client_id': config.ORCID_CLIENT_ID,
        'client_secret': config.ORCID_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
    }

    try:
        resp = http_requests.post(
            config.ORCID_TOKEN_URL,
            data=token_data,
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        resp.raise_for_status()
        token_json = resp.json()
    except Exception as e:
        return render_template('auth_error.html',
                               error=f'Failed to exchange token with ORCID: {e}'), 500

    # Extract ORCID iD and name from the token response
    orcid_id = token_json.get('orcid')
    display_name = token_json.get('name', '')

    if not orcid_id:
        return render_template('auth_error.html',
                               error='Could not retrieve ORCID iD.'), 500

    # Dev bypass: allow configured ORCID through as admin without DB whitelist
    _norm = lambda x: (x or '').replace('-', '')
    if config.BYPASS_AUTH_WHITELIST and _norm(orcid_id) == _norm(config.BYPASS_DEV_ORCID):
        session['orcid_id'] = orcid_id
        session['user_name'] = config.BYPASS_DEV_NAME
        session['user_role'] = config.BYPASS_DEV_ROLE
        return redirect('/app/')

    # Check whitelist
    user = lookup_user(orcid_id)
    if not user:
        return render_template('auth_error.html',
                               error='Your ORCID iD is not authorized to access this application. '
                                     'Please contact an administrator.'), 403

    # Set session
    session['orcid_id'] = orcid_id
    session['user_name'] = user.get('display_name') or display_name
    session['user_role'] = user.get('role', 'user')

    # Update last login timestamp
    update_last_login(orcid_id)

    return redirect('/app/')


@auth_bp.route('/logout')
def logout():
    """Clear the session and redirect to the landing page."""
    session.clear()
    return redirect('/')
