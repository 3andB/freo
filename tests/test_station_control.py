"""Station Control uses saved scheduling modes and station-scoped access."""
import pytest
from app.extensions import db
from app.models import Station
from app.services import visual_schedule as vs
from tests.test_web import app, admin_client


@pytest.mark.parametrize('mode', ['CALENDAR', 'BLOCKS', 'SIMPLE'])
def test_control_displays_current_mode_and_workspace_links(app, mode):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        vs.policy(station, True).mode = mode
        db.session.commit()
    client = admin_client(app)
    response = client.get('/admin/stations/test-station/schedule-studio/control')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'System currently running in {mode.title()} mode.' in html
    for workspace in ['calendar', 'blocks', 'simple']:
        assert f'/schedule-studio/{workspace}' in html
    response = client.get('/admin/stations/test-station/schedule-studio/control?station=second-station')
    assert response.status_code == 302
    assert '/second-station/schedule-studio/control' in response.location
    assert client.get('/admin/stations/missing/schedule-studio/control').status_code == 404


def test_control_requires_authentication(app):
    assert app.test_client().get('/admin/stations/test-station/schedule-studio/control').status_code == 302
