"""Keep live status and station identity readable across viewport sizes."""
from app.extensions import db
from app.models import Station
from tests.test_live_browser import app_fixture, booth
from tests.test_player_experience_browser import seed


def test_player_header_status_does_not_overlap_identity(booth):
    app, driver, base, _ = booth
    seed(app)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        station.name = 'Demo Channel 1'
        station.description = ('The original community channel. A little company, '
                               'a fresh discovery, and a place to settle into the music.')
        station.publish_contact = True
        station.contact_email = 'radio@example.test'
        db.session.commit()
    driver.get(base + '/player/test-station')
    for long_identity in (False, True):
        if long_identity:
            driver.execute_script("""
                document.querySelector('.radio-station-line h1').textContent =
                  'Community Radio for Independent Music and Local Voices';
                document.querySelector('.radio-description').textContent =
                  'Local voices, independent music, community news and more. '.repeat(5);
            """)
        for width in (320, 390, 650, 1200):
            driver.set_window_size(width, 900)
            geometry = driver.execute_script("""
                const rect = selector => {
                  const r = document.querySelector(selector).getBoundingClientRect();
                  return {top:r.top, bottom:r.bottom, left:r.left, right:r.right};
                };
                return {cover:rect('.radio-cover'), status:rect('.radio-live-label'),
                  identity:rect('.radio-cover-copy'), viewport:innerWidth,
                  documentWidth:document.documentElement.scrollWidth};
            """)
            status, identity, cover = (geometry[key] for key in ('status', 'identity', 'cover'))
            assert (status['bottom'] <= identity['top'] + .5 or
                    identity['bottom'] <= status['top'] + .5 or
                    status['right'] <= identity['left'] + .5 or
                    identity['right'] <= status['left'] + .5), geometry
            assert identity['top'] >= cover['top'] - .5, geometry
            assert identity['bottom'] <= cover['bottom'] + .5, geometry
            assert geometry['documentWidth'] <= geometry['viewport'] + 1, geometry
