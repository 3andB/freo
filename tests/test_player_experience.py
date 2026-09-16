"""Public player boundaries, schedule snapshots, and listener feedback."""
from datetime import datetime, timedelta, timezone, date
from io import BytesIO
import pytest
from werkzeug.datastructures import MultiDict
from app.extensions import db
from app.models import (Station, StationPlayerSettings, StationPlayerAsset, PublicScheduleRevision,
                        ListenerVote, ListenerFeedbackEvent, SelectionDecision, LiveQueueSnapshot, Track)
from app.services import player as service
from tests.test_web import app, admin_client
from tests.test_station_settings_flags import png

ADMIN='/admin/stations/test-station/player-settings'
PUBLIC='/api/stations/test-station'
CSRF='test-admin-csrf-token'


def config_form(revision=0, **values):
    data=MultiDict(dict(csrf=CSRF,revision=str(revision),action='save',palette='aurora',cover_position='center',
        schedule_mode='automatic',schedule_default='week',motion='yes'))
    data.setlist('schedule_views',['day','week','month'])
    for key,value in values.items():data[key]=value
    return data


def enable(app, **config):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        row=StationPlayerSettings.query.filter_by(station_id=station.id).first()
        if not row:row=StationPlayerSettings(station_id=station.id,revision=1);db.session.add(row)
        row.config=dict(service.DEFAULTS,voting_enabled=True,comments_enabled=True,**config)
        db.session.commit()
        return SelectionDecision.query.filter_by(station_id=station.id,status='started').one().id


def vote(client,identifier,value=1,comment=None,revision=None):
    path=f'{PUBLIC}/feedback/{identifier}'
    state=client.get(path).json
    data=dict(value=value,revision=state['vote']['revision'] if revision is None else revision)
    if comment is not None:data['comment']=comment
    return client.post(path,json=data,headers={'X-Listener-CSRF':state['csrf']})


def test_settings_validation_assets_aliases_and_atomic_conflicts(app):
    admin=admin_client(app)
    assert app.test_client().get(ADMIN).status_code==302
    assert admin.post(ADMIN,data={}).status_code==400
    data=config_form(message='Welcome <script>bad()</script>',message_enabled='yes',social_enabled='yes',
        social_Instagram='https://instagram.com/station',visible_Instagram='yes',
        ad_top_enabled='yes',ad_top_alt='Sponsor',ad_top_url='https://example.test',
        cover=(BytesIO(png()),'cover.png'),ad_top=(BytesIO(png()),'ad.png'))
    result=admin.post(ADMIN,data=data)
    assert result.status_code==302
    page=app.test_client().get('/player/test-station').text
    assert 'Welcome &lt;script&gt;' in page and 'https://instagram.com/station' in page
    with app.app_context():
        assert service.public_context(Station.query.filter_by(slug='test-station').one())['player_config']['ad_top_visible'], str(StationPlayerSettings.query.one().config)
    assert 'Advertisement' in page and 'Sponsor' in page
    image=app.test_client().get('/station-assets/test-station/player/cover.png')
    assert image.status_code==200 and image.mimetype=='image/png'
    assert app.test_client().get('/station-assets/test-station/player/cover.png',headers={'If-None-Match':image.headers['ETag']}).status_code==304
    assert admin.post(ADMIN,data=config_form(message='lost update')).status_code==400
    assert admin.post(ADMIN,data=config_form(1,social_X='javascript:alert(1)')).status_code==400
    assert admin.post(ADMIN,data=config_form(1,cover=(BytesIO(b'<svg/>'),'fake.png'))).status_code==400
    assert admin.get(ADMIN).status_code==200
    assert admin.post(ADMIN,data=config_form(1,message='New message')).status_code==302
    with app.app_context():
        assert StationPlayerSettings.query.count()==1
        assert StationPlayerSettings.query.one().config['message']=='New message'
        assert StationPlayerAsset.query.count()==2
        station=Station.query.filter_by(slug='test-station').one();station.public_slug='new-name';db.session.commit()
    assert app.test_client().get('/player/new-name').status_code==200
    assert app.test_client().get('/api/stations/new-name/player').status_code==200
    assert app.test_client().get('/station-assets/new-name/player/cover.png').status_code==200


def test_station_message_and_ad_windows_visibility(app):
    now=datetime.now(timezone.utc)
    enable(app,message_enabled=True,message='Not yet',message_start=(now+timedelta(days=1)).isoformat())
    assert 'Not yet' not in app.test_client().get('/player/test-station').text
    admin=admin_client(app)
    assert admin.post(ADMIN,data=config_form(1,message_start='2026-09-01T09:00',message_end='2026-08-01T09:00Z')).status_code==400
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.enabled=False;db.session.commit()
    assert app.test_client().get(PUBLIC+'/player').status_code==404
    assert app.test_client().get(PUBLIC+'/public-schedule?start=2026-01-01').status_code==404


def test_current_song_requires_fresh_station_scoped_observation(app):
    public=app.test_client()
    assert public.get(PUBLIC+'/player').json['current']==[]
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        identifier=SelectionDecision.query.filter_by(status='started').one().id
        db.session.add(LiveQueueSnapshot(station_id=station.id,current_decision_id=identifier,observed_at=datetime.now(timezone.utc),broadcast_online=True,broadcast_observed_at=datetime.now(timezone.utc)))
        db.session.commit()
    data=public.get(PUBLIC+'/player').json
    assert data['current'][0]['decision_id']==identifier and data['stream_online'] is True
    assert 'storage_key' not in str(data) and 'internal.mp3' not in str(data)
    with app.app_context():
        LiveQueueSnapshot.query.one().observed_at=datetime.now(timezone.utc)-timedelta(seconds=30);db.session.commit()
    data=public.get(PUBLIC+'/player').json
    assert data['current']==[] and data['recent'][0]['title']=='Verified Test Track'


def test_votes_retry_change_clear_comments_and_station_scope(app):
    identifier=enable(app,public_totals=True)
    one,two=app.test_client(),app.test_client()
    assert vote(one,identifier,1,'Great chorus').status_code==200
    assert vote(one,identifier,1,'Great chorus',revision=0).status_code==200
    assert vote(two,identifier,-1).json['totals']['total']==2
    with app.app_context():
        assert ListenerVote.query.count()==2 and ListenerFeedbackEvent.query.filter_by(action='vote').count()==2
    assert vote(one,identifier,-1,revision=0).status_code==409
    result=vote(one,identifier,-1).json
    assert result['totals']['up']==0 and result['totals']['down']==2
    assert result['vote']['comment']=='Great chorus'
    assert vote(one,identifier,0).json['totals']['total']==1
    assert one.get(f'/api/stations/second-station/feedback/{identifier}').status_code==404
    assert 'Great chorus' not in str(two.get(f'{PUBLIC}/feedback/{identifier}').json)
    admin=admin_client(app)
    assert 'Great chorus' in admin.get('/admin/stations/test-station/listener-feedback').text
    song=admin.get('/admin/api/stations/test-station/music').json['songs'][0]
    assert song['votes']['down']==1 and song['votes']['comments']==1
    assert 'listener comments' in admin.get(song['detail']).text


def test_feedback_security_moderation_and_rate_limit(app):
    identifier=enable(app)
    public=app.test_client();path=f'{PUBLIC}/feedback/{identifier}'
    state=public.get(path).json
    assert public.post(path,json={'value':1,'revision':0}).status_code==400
    assert public.post(path,json={'value':1,'revision':0},headers={'X-Listener-CSRF':state['csrf'],'Origin':'https://elsewhere.test'}).status_code==403
    assert vote(public,identifier,True).status_code==400
    assert vote(public,identifier,1,'x'*501).status_code==400
    assert vote(public,identifier,1,{'unexpected':'object'}).status_code==400
    assert vote(public,identifier,1,'<script>alert(1)</script>').status_code==200
    admin=admin_client(app)
    page=admin.get('/admin/stations/test-station/listener-feedback').text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page
    with app.app_context():
        row=ListenerVote.query.one();row_id=row.id
    inbox='/admin/stations/test-station/listener-feedback'
    assert admin.post(inbox,data=dict(csrf=CSRF,id=row_id,revision=1,action='exclude',reason='Spam campaign')).status_code==302
    with app.app_context():assert service.vote_stats(Station.query.filter_by(slug='test-station').one().id)=={}
    assert admin.post('/admin/stations/second-station/listener-feedback',data=dict(csrf=CSRF,id=row_id,revision=2,action='restore')).status_code==404
    for n in range(19):assert vote(public,identifier,(-1 if n%2==0 else 1)).status_code==200
    assert vote(public,identifier,1).status_code==429


def test_unconfirmed_expired_and_changed_song_feedback(app):
    identifier=enable(app)
    public=app.test_client();state=public.get(f'{PUBLIC}/feedback/{identifier}').json
    with app.app_context():
        decision=db.session.get(SelectionDecision,identifier)
        second=SelectionDecision(station_id=decision.station_id,track_id=decision.track_id,status='queued')
        db.session.add(second);db.session.commit();second_id=second.id
    assert public.get(f'{PUBLIC}/feedback/{second_id}').status_code==404
    # Captured decision is still valid when another selection enters the queue.
    assert public.post(f'{PUBLIC}/feedback/{identifier}',json=dict(value=1,revision=0),headers={'X-Listener-CSRF':state['csrf']}).status_code==200
    with app.app_context():
        db.session.get(SelectionDecision,identifier).started_at=datetime.now(timezone.utc)-timedelta(hours=25);db.session.commit()
    assert public.get(f'{PUBLIC}/feedback/{identifier}').status_code==404


def test_schedule_publication_snapshot_override_and_preview(app):
    admin=admin_client(app)
    assert admin.post(ADMIN,data=config_form(schedule_enabled='yes',action='publish')).status_code==302
    today=datetime.now(timezone.utc).date().isoformat()
    public=app.test_client()
    data=public.get(PUBLIC+f'/public-schedule?start={today}&days=31').json
    assert data['entries'][0]['title']=='Power'
    with app.app_context():
        from app.models import MediaCategory
        MediaCategory.query.one().name='Changed category';db.session.commit()
    assert public.get(PUBLIC+f'/public-schedule?start={today}').json['entries'][0]['title']=='Power'
    assert admin.post(ADMIN,data=config_form(1,action='preview',schedule_enabled='yes')).status_code==200
    with app.app_context():assert PublicScheduleRevision.query.count()==1
    form=dict(csrf=CSRF,revision=1,action='add-entry',title='Morning show',description='A personal selection',on_date=today,start='09:00',end='11:00')
    assert admin.post(ADMIN,data=form).status_code==302
    assert admin.post(ADMIN,data=config_form(2,schedule_mode='combined',schedule_enabled='yes',action='publish')).status_code==302
    entries=public.get(PUBLIC+f'/public-schedule?start={today}&days=1').json['entries']
    assert [row['title'] for row in entries]==['Changed category','Morning show','Changed category']
    assert entries[0]['end']==entries[1]['start'] and entries[1]['end']==entries[2]['start']
    assert public.get(PUBLIC+f'/public-schedule?start={today}&days=999').status_code==400


def test_schedule_overnight_dst_overlap_and_retention(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.timezone='America/New_York'
        custom=dict(title='Night shift',description='',start_minute=1380,end_minute=1560,on_date='2026-10-31',weekday=None,hidden=False)
        config=dict(service.DEFAULTS,schedule_mode='custom',custom_entries=[custom])
        entries=service.build_schedule(station,config,date(2026,10,31),2)
        assert service.timestamp(entries[0]['end'])-service.timestamp(entries[0]['start'])==timedelta(hours=4)
        config['custom_entries']=[custom,dict(custom,title='Collision')]
        with pytest.raises(ValueError,match='overlap'):service.build_schedule(station,config,date(2026,10,31),2)
    identifier=enable(app,auto_publish=True,schedule_enabled=True)
    assert vote(app.test_client(),identifier,1,'Old comment').status_code==200
    with app.app_context():
        ListenerVote.query.one().updated_at=datetime.now(timezone.utc)-timedelta(days=91);db.session.commit()
        service.refresh_public_schedules();service.refresh_public_schedules()
        assert PublicScheduleRevision.query.count()==1
        assert ListenerVote.query.one().comment=='' and ListenerVote.query.one().value==1


def test_dj_mix_ignores_muted_decks_and_takeover_reports_cart(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.automation.operator_mode='DJ_BOOTH'
        first=SelectionDecision.query.filter_by(status='started').one()
        cart=SelectionDecision(station_id=station.id,track_id=first.track_id,status='started',started_at=datetime.now(timezone.utc),cart_mode='TAKEOVER',playback_bus='CART')
        db.session.add(cart);db.session.flush();cart_id=cart.id
        db.session.add(LiveQueueSnapshot(station_id=station.id,current_decision_id=first.id,observed_at=datetime.now(timezone.utc),mixer=dict(mode='DJ_BOOTH',a_id=first.id,a_playing=True,transition={'a_gain':0})))
        db.session.commit()
    public=app.test_client()
    assert public.get(PUBLIC+'/player').json['current']==[]
    with app.app_context():
        row=LiveQueueSnapshot.query.one();row.mixer=dict(row.mixer,cart_id=cart_id);db.session.commit()
    assert [row['decision_id'] for row in public.get(PUBLIC+'/player').json['current']]==[cart_id]


def test_preview_does_not_publish_and_unpublish_keeps_broadcast(app):
    admin=admin_client(app)
    result=admin.post(ADMIN,data=config_form(action='preview-player',message_enabled='yes',message='Preview only'))
    assert result.status_code==200 and 'Preview only' in result.text and 'Unpublished preview' in result.text
    assert 'Preview only' not in app.test_client().get('/player/test-station').text
    with app.app_context():assert StationPlayerSettings.query.count()==0
    admin.post(ADMIN,data=config_form(action='publish',schedule_enabled='yes'))
    assert admin.post(ADMIN,data=dict(csrf=CSRF,revision=1,action='unpublish')).status_code==302
    today=datetime.now(timezone.utc).date().isoformat()
    assert app.test_client().get(PUBLIC+f'/public-schedule?start={today}').json['entries']==[]
    with app.app_context():
        from app.models import ScheduleAssignment
        assert ScheduleAssignment.query.count()==1 and PublicScheduleRevision.query.count()==1


def test_song_art_is_limited_to_station_confirmed_plays(app):
    from app.models import MusicArtwork
    identifier=enable(app)
    with app.app_context():
        song=Track.query.first();art=MusicArtwork(id='test-art',station_id=song.station_id,image=png())
        db.session.add(art);song.cover_id=art.id;db.session.commit()
    public=app.test_client()
    data=public.get(PUBLIC+'/player').json
    url=data['recent'][0]['artwork']
    assert public.get(url).mimetype=='image/png'
    assert public.get(url.replace('test-station','second-station')).status_code==404
    with app.app_context():
        Track.query.first().deleted_at=datetime.now(timezone.utc);db.session.commit()
    assert public.get(url).status_code==404


def test_multiline_message_and_comments_preserve_line_breaks(app):
    admin=admin_client(app)
    assert admin.post(ADMIN,data=config_form(message_enabled='yes',message='First line\nSecond line',voting_enabled='yes',comments_enabled='yes')).status_code==302
    assert 'First line\nSecond line' in app.test_client().get('/player/test-station').text
    with app.app_context():identifier=SelectionDecision.query.filter_by(status='started').one().id
    assert vote(app.test_client(),identifier,1,'First thought\nAnother thought').json['vote']['comment']=='First thought\nAnother thought'


def test_invalid_player_settings_retains_draft_without_saving(app):
    admin=admin_client(app)
    response=admin.post(ADMIN,data=config_form(message='Keep this draft',message_enabled='yes',social_X='javascript:bad()'))
    assert response.status_code==400 and 'Keep this draft' in response.text
    with app.app_context():assert StationPlayerSettings.query.count()==0
    assert 'Keep this draft' not in app.test_client().get('/player/test-station').text
