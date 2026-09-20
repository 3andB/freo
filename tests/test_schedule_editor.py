"""Pure browser editing operations, including deterministic randomized intervals."""
import shutil
import subprocess
from pathlib import Path
import pytest


def test_schedule_editor_operations():
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the pure editor regression suite')
    result=subprocess.run(['node','--test',str(Path(__file__).with_name('schedule_editor.test.cjs'))],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_calendar_preview_validates_hidden_series_without_publishing(app_fixture):
    import json
    from tests.test_web import admin_client
    from app.extensions import db
    from app.models import Station, Track, ChannelSchedule
    from app.services import visual_schedule as vs
    app=app_fixture;client=admin_client(app)
    with app.app_context():
        station=Station.query.first();policy=vs.policy(station,True)
        ref=vs.source(station,dict(kind='song',id=Track.query.first().id))
        rows=[dict(id='repeat',start=32400,end=36000,source=ref,rule=dict(frequency='weekly',anchor='2026-09-21',weekdays=[0]))]
        policy.calendar=vs.clean_document(station,rows);policy.calendar_saved=True;db.session.commit();revision=policy.revision
    def preview(items):
        return client.post('/admin/stations/test-station/schedule-studio/api/calendar-preview',data={'csrf':'test-admin-csrf-token','payload':json.dumps({'items':items})})
    conflict={**rows[0],'id':'other','start':34200,'end':37800}
    response=preview(rows+[conflict]);assert response.status_code==400 and 'overlap' in response.json['error']
    override={**conflict,'rule':dict(frequency='once',anchor='2026-09-21')}
    response=preview(rows+[override]);assert response.status_code==200 and len(response.json['items'])==2
    with app.app_context():
        saved=ChannelSchedule.query.first();assert saved.revision==revision and len(saved.calendar)==1


from tests.test_web import app as app_fixture


def test_browser_recurrence_matches_playback_rules_across_leap_year():
    import json
    from datetime import date, timedelta
    from app.services import visual_schedule as vs
    if not shutil.which('node'):pytest.skip('Node.js is required')
    start=date(2027,12,1)
    days=[(start+timedelta(days=i)).isoformat() for i in range(430)]
    rules=[]
    for frequency in ['once','dates','daily','weekly','monthly']:
        for interval in [1,2,3]:
            for nth in ([0,-1,5] if frequency=='monthly' else [0]):
                rules.append(vs.clean_rule(dict(frequency=frequency,anchor='2027-12-05',starts_on='2027-12-20',until='2029-01-02',interval=interval,
                    weekdays=[0,3,6],month_day=31,nth=nth,weekday=4,dates=['2027-12-31','2028-02-29'],exceptions=['2028-01-31','2028-02-29'])))
    expected=[[bool(vs.matches(rule,date.fromisoformat(day))) for day in days] for rule in rules]
    module=str(Path(__file__).resolve().parents[1]/'app/static/schedule_editor.js')
    script="const e=require(process.argv[1]);let raw='';process.stdin.on('data',d=>raw+=d);process.stdin.on('end',()=>{const {rules,days}=JSON.parse(raw);process.stdout.write(JSON.stringify(rules.map(r=>days.map(d=>!!e.matches(r,d)))));});"
    result=subprocess.run(['node','-e',script,module],input=json.dumps(dict(rules=rules,days=days)),capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==expected
