from app.extensions import db
from app.models import AdminUser, AuditEvent
from app.services.license_agreement import AGREEMENT_VERSION
from tests.test_web import app, admin_client


def test_first_use_acceptance_is_durable_and_per_account(app):
    client = admin_client(app)
    html = client.get('/admin').text
    assert 'data-required="true" open' in html
    assert '<strong>You may not broadcast copyrighted material without permission. Doing so is a direct violation of this license.</strong>' in html
    assert 'https://freo.live/licensing' in html
    with client.session_transaction() as state:
        csrf = state['admin_csrf']
    data = dict(csrf=csrf, agree='yes', version=AGREEMENT_VERSION)
    for _ in range(2):
        response = client.post('/admin/license-agreement/accept', data=data, headers={'Accept': 'application/json'})
        assert response.json['accepted'] is True
    with app.app_context():
        record = AuditEvent.query.filter_by(action='license.accept').one()
        assert record.target_id == AGREEMENT_VERSION
        assert record.created_at
        second = AdminUser(email='second@example.test', password_hash='unused')
        db.session.add(second)
        db.session.commit()
        second_id = second.id
    fresh = admin_client(app)
    assert 'data-required="false"' in fresh.get('/admin').text
    assert 'data-license-open' in fresh.get('/admin/stations/test-station/schedule-studio/control').text
    with fresh.session_transaction() as state:
        state['admin_user_id'] = second_id
    assert 'data-required="true" open' in fresh.get('/admin').text
    assert 'id="license-agreement"' not in client.get('/').text


def test_acceptance_requires_login_csrf_and_explicit_current_agreement(app):
    url = '/admin/license-agreement/accept'
    assert app.test_client().post(url).status_code == 302
    client = admin_client(app)
    client.get('/admin')
    with client.session_transaction() as state:
        csrf = state['admin_csrf']
    for data in [dict(agree='yes', version=AGREEMENT_VERSION),
                 dict(csrf=csrf, version=AGREEMENT_VERSION),
                 dict(csrf=csrf, agree='yes', version='old')]:
        assert client.post(url, data=data).status_code == 400
    with app.app_context():
        assert AuditEvent.query.filter_by(action='license.accept').count() == 0
    response = client.post(url, data=dict(csrf=csrf, agree='yes', version=AGREEMENT_VERSION))
    assert response.status_code == 302
    assert response.location.endswith('/admin')


def test_old_acceptance_does_not_hide_new_agreement(app):
    with app.app_context():
        db.session.add(AuditEvent(admin_user_id=AdminUser.query.first().id, action='license.accept',
                                 target_type='license_agreement', target_id='old'))
        db.session.commit()
    assert 'data-required="true" open' in admin_client(app).get('/admin').text
