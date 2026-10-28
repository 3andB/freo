"""Station-authorized report presentation and streaming CSV exports."""
import csv
import io
from itertools import islice
from flask import Blueprint, abort, request, render_template, Response, stream_with_context
from app.routes.statistics import context
from app.routes.web import admin_stations
from app.services.admin_auth import admin_required
from app.services import broadcast_reports as reports

broadcast_reports = Blueprint('broadcast_reports', __name__)


@broadcast_reports.get('/admin/stations/<slug>/broadcast-reports')
@admin_required
def page(slug):
    station = context(slug)
    try:
        result = reports.summary(station, request.args)
        page_number = max(1, int(request.args.get('page', 1)))
    except ValueError:
        abort(400, 'Choose a valid date range and page.')
    response = Response(render_template('admin/broadcast_reports.html', selected=station,
        stations=admin_stations(), page='broadcast-reports', report=result,
        performances=list(reports.performances(station, result['period'], 100, (page_number-1)*100)),
        tracks=list(islice(reports.tracks(station, result['period']),100)), page_number=page_number,
        filters={key:request.args[key] for key in ('range','start','end') if key in request.args}))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@broadcast_reports.get('/admin/stations/<slug>/broadcast-reports/<kind>.csv')
@admin_required
def export(slug, kind):
    station = context(slug)
    if kind not in ('performances', 'tracks', 'summary'):
        abort(404)
    try:
        result = reports.summary(station, request.args)
    except ValueError as error:
        abort(400, str(error))
    columns = (['decision_id','track_uuid','artist','title','album','isrc','kind','played_at','local_time',
                'source_duration_seconds','listeners','audience_at','metadata_source'] if kind == 'performances' else
               ['track_uuid','artist','title','album','isrc','plays'] if kind == 'tracks' else ['metric','value'])
    def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        def write(values):
            output.seek(0); output.truncate(0)
            writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in values])
            return output.getvalue()
        yield write(['Station', station.name, 'Timezone', station.timezone])
        yield write(['Start UTC epoch', result['period']['start'], 'End exclusive UTC epoch', result['period']['end']])
        yield write(['Audience coverage %',result['audience']['total']['coverage'],'Audience resolution seconds',result['audience']['resolution_seconds']])
        yield write(['Session start UTC epoch',result['sessions']['start'],'Session end UTC epoch',result['sessions']['end'],'Session resolution seconds',3600])
        yield write(['Source duration is not verified airtime. Connections are not unique people. No licensing compliance certification.'])
        yield write(columns)
        if kind == 'performances': rows = reports.performances(station, result['period'])
        elif kind == 'tracks': rows = reports.tracks(station, result['period'])
        else:
            metrics = dict(total_performances=result['total_performances'], unique_listeners=None,
                **{k:result['audience']['total'][k] for k in ('average','peak','listener_hours','coverage')},
                **{'session_'+k:result['sessions'][k] for k in ('starts','completed','average_seconds','coverage')})
            rows = (dict(metric=k,value=v) for k,v in metrics.items())
        for row in rows: yield write([row.get(key) for key in columns])
    return Response(stream_with_context(generate()), mimetype='text/csv', headers={
        'Content-Disposition':f'attachment; filename="broadcast-{kind}.csv"', 'Cache-Control':'private, no-store'})
