"""Authenticate route fixtures through the application's real login issuance."""
from flask import session
from app.extensions import db
from app.models import AdminUser
from app.services.admin_setup import sign_in


def authenticate(client, user_id, csrf='test-admin-csrf-token'):
    with client.application.test_request_context():
        sign_in(db.session.get(AdminUser, user_id))
        values = dict(session)
        values['admin_csrf'] = csrf
    with client.session_transaction() as state:
        state.clear()
        state.update(values)
