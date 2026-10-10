"""Authenticated visual scheduling; all audio commands remain worker-owned."""
import copy
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, jsonify, render_template, request, redirect, url_for, send_file
from app.extensions import db
from app.models import (ScheduleComposition, ScheduleCompositionRevision, ScheduleTransition,
                        ScheduleProgram, ScheduleAssignment, Clock, ChannelSchedule, Playlist, TimedEvent, Station, LiveQueueSnapshot, SelectionDecision, ImagingAsset)
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, require_csrf, current_admin, can_manage_programming, can_control_playout
from app.services.admin_media import audit
from app.services import visual_schedule as vs
from app.services.schedule_documents import ScheduleConflict, merge_items, merge_value

schedule_studio=Blueprint('schedule_studio',__name__)


def station_for(slug):
    station=station_or_404(slug,require_enabled=False)
    if not can_manage_programming(current_admin(),station):abort(403)
    return station


def legacy_calendar(station):
    result=[]
    programs=ScheduleProgram.query.filter_by(station_id=station.id,enabled=True).all()
    for row in programs:
        if row.baseline_assignment_id:continue
        result.append(dict(id=f'legacy-{row.id}',start=row.start_minute*60,end=row.end_minute*60,
            source=dict(kind='legacy',id=row.clock_id,name=row.name,duration=(row.end_minute-row.start_minute)*60),
            rule=dict(frequency='once' if row.on_date else 'weekly',anchor=row.on_date.isoformat() if row.on_date else '2020-01-01',
                      weekdays=[row.weekday],interval=1,exceptions=[])))
    # Expand the weekly baseline, then subtract bounded recurring programs,
    # including the previous day's overnight tail. Dated overrides stay separate.
    assignments=ScheduleAssignment.query.filter_by(station_id=station.id,enabled=True).order_by(ScheduleAssignment.weekday,ScheduleAssignment.start_time).all()
    bounded=list(result)
    for index,row in enumerate(assignments):
        start=row.weekday*86400+row.start_time.hour*3600+row.start_time.minute*60
        following=assignments[(index+1)%len(assignments)]
        end=following.weekday*86400+following.start_time.hour*3600+following.start_time.minute*60
        if end<=start:end+=7*86400
        point=start
        while point<end:
            stop=min(end,(point//86400+1)*86400)
            weekday=(point//86400)%7
            pieces=[(point%86400,(stop-1)%86400+1)]
            for program in bounded:
                if program['rule']['frequency']!='weekly':continue
                for offset in (0,-86400):
                    origin=(weekday+(offset//86400))%7
                    if origin not in program['rule']['weekdays']:continue
                    c,d=program['start']+offset,program['end']+offset
                    revised=[]
                    for a,b in pieces:
                        if d<=a or c>=b:revised.append((a,b));continue
                        if a<c:revised.append((a,c))
                        if b>d:revised.append((d,b))
                    pieces=revised
            for j,(a,b) in enumerate(pieces):
                result.append(dict(id=f'baseline-{row.id}-{point//86400}-{j}',start=a,end=b,
                    source=dict(kind='legacy',id=row.clock_id,name=row.clock.name,duration=b-a),
                    rule=dict(frequency='weekly',anchor='2020-01-01',weekdays=[weekday],interval=1,exceptions=[])))
            point=stop
    return result


def calendar_items(station, row):
    return row.calendar if row and row.calendar_saved else legacy_calendar(station) if not row or not row.activated else []


def state_json(station):
    from app.services.broadcast_status import cached_status
    row=vs.policy(station)
    command=ScheduleTransition.query.filter_by(station_id=station.id).order_by(ScheduleTransition.created_at.desc()).first()
    snapshot=LiveQueueSnapshot.query.filter_by(station_id=station.id).first()
    current=SelectionDecision.query.filter_by(id=snapshot.current_decision_id,station_id=station.id).first() if snapshot and snapshot.current_decision_id else None
    playing_fallback=bool(current and current.reason=='default_playlist')
    return dict(broadcast=cached_status([station])[station.slug],playing_fallback=playing_fallback,held=bool(station.automation and station.automation.hold),mode=row.mode if row else 'CALENDAR',activated=bool(row and row.activated),revision=row.revision if row else 1,
        calendar=calendar_items(station, row),
        assignments=row.assignments if row else [],simple=row.simple if row else None,
        fallback=vs.fallback(station),transition=dict(id=command.id,state=command.state,mode=command.mode,error=command.error) if command else None,
        timezone=station.timezone)


def render_workspace(slug,view='calendar'):
    station=station_for(slug)
    if view=='control':
        return render_template('admin/station_control.html',selected=station,stations=admin_stations(),
            page='station-control',initial=state_json(station),can_switch=can_control_playout(current_admin(),station))
    if view not in ('calendar','shows','blocks','simple'):abort(404)
    return render_template('admin/schedule_studio.html',selected=station,stations=admin_stations(),page='studio-'+view,
        workspace=view,initial=state_json(station))


@schedule_studio.get('/admin/stations/<slug>/schedule-studio/<view>')
@admin_required
def page(slug,view):
    requested=request.args.get('station',slug)
    if requested!=slug:
        station_for(requested)
        return redirect(url_for('.page',slug=requested,view=view,date=request.args.get('date')))
    if view=='active':
        row=vs.policy(station_for(slug));view=row.mode.lower() if row else 'calendar'
    return render_workspace(slug,view)


@schedule_studio.get('/admin/stations/<slug>/schedule-studio/api/<action>')
@admin_required
def read(slug,action):
    station=station_for(slug)
    try:
        if action=='state':return jsonify(state_json(station))
        if action=='sources':return jsonify(vs.search_sources(station,request.args.get('kind','song'),request.args.get('q',''),request.args.get('page','1')))
        if action=='compositions':
            page=vs.integer(request.args.get('page','1'),1,100000,'Page')
            query=vs.text(request.args.get('q',''),150)
            rows=ScheduleComposition.query.filter_by(station_id=station.id,archived=False,kind=request.args.get('kind','SHOW')).filter(ScheduleComposition.name.ilike('%'+query+'%')).order_by(ScheduleComposition.name,ScheduleComposition.id).offset((page-1)*40).limit(41).all()
            return jsonify(items=[vs.composition_json(r) for r in rows[:40]],more=len(rows)>40)
        if action=='composition':
            row=ScheduleComposition.query.filter_by(station_id=station.id,id=request.args.get('id')).first()
            if not row:abort(404)
            return jsonify(vs.composition_json(row))
        if action=='events':
            from app.services.timed_events import _instants
            start=date.fromisoformat(request.args['date']);days=vs.integer(request.args.get('days','7'),1,42,'Days')
            zone=ZoneInfo(station.timezone)
            begin=vs._wall_to_utc(datetime.combine(start,datetime.min.time()),zone)
            end=vs._wall_to_utc(datetime.combine(start+timedelta(days=days),datetime.min.time()),zone)
            result=[]
            for event in TimedEvent.query.filter_by(station_id=station.id,enabled=True):
                for at in _instants(event,begin,end):
                    local=at.astimezone(zone)
                    if start<=local.date()<start+timedelta(days=days):
                        result.append(dict(id=event.uuid,name=event.name,date=local.date().isoformat(),second=local.hour*3600+local.minute*60,timing=event.timing_mode,recurring=event.recurrence_type != 'ONE_TIME'))
            return jsonify(items=result)
        abort(404)
    except (ValueError,TypeError,KeyError) as error:return jsonify(error=str(error) or 'Invalid request'),400


@schedule_studio.post('/admin/stations/<slug>/schedule-studio/api/<action>')
@admin_required
def write(slug,action):
    station=station_for(slug);require_csrf()
    try:
        data=json.loads(request.form.get('payload','{}'))
        if not isinstance(data,dict):raise ValueError('Invalid request')
        if action == 'calendar-preview':
            return jsonify(items=vs.clean_document(station, data.get('items', [])))
        db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
        if action=='broadcast':
            if not can_control_playout(current_admin(),station):abort(403)
            from app.services.master_broadcast import request_broadcast
            request_broadcast(station,data.get('enabled'),data.get('revision'),current_admin())
            db.session.commit()
            return jsonify(state_json(station))
        elif action=='block-workspace':
            schedule=ChannelSchedule.query.filter_by(station_id=station.id).with_for_update().first() or vs.policy(station,True)
            if schedule.revision!=data.get('revision') and 'base' not in data:
                raise ValueError('Another editor changed this schedule. Reload before saving.')
            if ScheduleTransition.query.filter_by(station_id=station.id).filter(ScheduleTransition.state.in_(('PENDING','PREPARING','FADING'))).first():
                return jsonify(error='Finishing the mode change. Your edits will save shortly.',retryable=True),409
            composition=data.get('composition')
            if not isinstance(composition,dict) or composition.get('kind')!='BLOCK':
                raise ValueError('Choose a Block')
            # Assigning a saved Block must not create a new content revision.
            row=ScheduleComposition.query.filter_by(id=composition.get('id'),station_id=station.id,kind='BLOCK',archived=False).first() if composition.get('id') else None
            saved=vs.composition_json(row) if row else None
            unchanged=bool(saved and all(composition.get(key)==saved.get(key) for key in ('revision','name','description','sections')))
            if not unchanged:
                row=vs.save_composition(station,composition)
            db.session.flush()
            items=merge_items(data['base'],data.get('items',[]),schedule.assignments) if 'base' in data else data.get('items',[])
            schedule.assignments=vs.clean_document(station,items,assignments=True)
            schedule.revision+=1
            output=dict(composition=vs.composition_json(row),revision=schedule.revision,items=schedule.assignments)
        elif action=='composition':
            row=vs.save_composition(station,data);db.session.flush();output=vs.composition_json(row)
        elif action in ('apply-revision','apply-revision-preview'):
            composition=ScheduleComposition.query.filter_by(id=data.get('id'),station_id=station.id).first()
            if not composition or composition.revision!=data.get('version'):
                raise ValueError('This composition changed. Reload before applying it.')
            row=vs.policy(station,True)
            tomorrow=datetime.now(ZoneInfo(station.timezone)).date()+timedelta(days=1)
            effective=date.fromisoformat(data.get('effective_on') or tomorrow.isoformat())
            if effective<tomorrow:raise ValueError('Apply from tomorrow or later to preserve current playback.')
            if action=='apply-revision-preview':
                return jsonify(message=f'Use revision {composition.revision} of {composition.name} in Calendar and Blocks from {effective}. Current playback and Simple stay unchanged.',effective_on=effective.isoformat())
            if row.revision!=data.get('revision'):raise ValueError('Schedule changed. Review this update again.')
            if ScheduleTransition.query.filter_by(station_id=station.id).filter(ScheduleTransition.state.in_(('PENDING','PREPARING','FADING'))).first():raise ValueError('Wait for the mode change to finish.')
            updates=[u for u in row.revision_updates if not (u['id']==composition.id and u['effective_on']==effective.isoformat())]
            updates.append(dict(id=composition.id,version=composition.revision,effective_on=effective.isoformat()))
            row.revision_updates=updates;row.revision+=1;output=dict(revision=row.revision)
        elif action=='recurrence':
            return jsonify(dates=vs.rule_dates(vs.clean_rule(data),date.fromisoformat(data['anchor'])))
        elif action=='transition-preview':
            if data.get('mode') not in vs.MODES:raise ValueError('Choose Calendar, Blocks, or Simple')
            row=vs.policy(station,True)
            calendar=legacy_calendar(station) if not row.calendar_saved and not row.activated else None
            return jsonify(vs.transition_preview(station,data.get('mode'),simple=data.get('simple'),calendar=calendar))
        elif action=='transition':
            if not can_control_playout(current_admin(),station):abort(403)
            row=vs.policy(station,True)
            if data.get('mode')=='CALENDAR' and not row.calendar_saved and not row.activated:
                row.calendar=vs.clean_document(station,legacy_calendar(station));row.calendar_saved=True
            command=vs.transition_request(station,data);output=dict(id=command.id,state=command.state)
        elif action in ('calendar','assignments','simple','default'):
            row=ChannelSchedule.query.filter_by(station_id=station.id).with_for_update().first() or vs.policy(station,True)
            if row.revision!=data.get('revision') and 'base' not in data:raise ValueError('Another editor changed this schedule. Reload before saving.')
            if ScheduleTransition.query.filter_by(station_id=station.id).filter(ScheduleTransition.state.in_(('PENDING','PREPARING','FADING'))).first():
                return jsonify(error='Finishing the mode change. Your edits will save shortly.',retryable=True),409
            if action in ('calendar','assignments'):
                current=calendar_items(station,row) if action=='calendar' else row.assignments
                items=merge_items(data['base'],data.get('items',[]),current) if 'base' in data else data.get('items',[])
                setattr(row,action,vs.clean_document(station,items,assignments=action=='assignments'))
                if action=='calendar':row.calendar_saved=True
            elif action=='simple':
                proposed=vs.source(station,data['source'],allow_block=True) if data.get('source') else None
                row.simple=merge_value(data['base'],proposed,row.simple) if 'base' in data else proposed
            else:
                ref=vs.source(station,dict(kind='playlist',id=data.get('playlist')))
                if not vs.source_tracks(station,ref):raise ValueError('Choose a playlist with playable songs')
                row.default_playlist_id=merge_value(data['base'],ref['id'],row.default_playlist_id) if 'base' in data else ref['id']
            row.revision+=1;output=dict(revision=row.revision)
            if action in ('calendar','assignments'): output['items'] = getattr(row,action)
            if action == 'simple': output['source'] = row.simple
            if action == 'default':
                output['playlist'] = row.default_playlist_id
                playlist = db.session.get(Playlist, row.default_playlist_id) if row.default_playlist_id else None
                output['name'] = playlist.name if playlist else 'No default playlist'
        else:abort(404)
        audit('visual_schedule_'+action,user_id=current_admin().id,station_id=station.id,target_type='station',target_id=station.slug,summary='Updated '+action+' in scheduling workspace')
        db.session.commit();return jsonify(output)
    except ScheduleConflict as error:
        db.session.rollback();return jsonify(error=str(error),conflict=True,state=state_json(station)),409
    except (ValueError,TypeError,KeyError) as error:
        db.session.rollback();return jsonify(error=str(error) or 'Invalid schedule'),400


@schedule_studio.get('/admin/stations/<slug>/schedule-studio/audio/<int:identifier>')
@admin_required
def audition(slug,identifier):
    station=station_for(slug)
    asset=ImagingAsset.query.filter_by(id=identifier,station_id=station.id,enabled=True,ingest_status='accepted',decommissioned_at=None).first_or_404()
    from app.services.media_storage import LocalMediaStorage
    try:path=LocalMediaStorage().imaging_file(station.slug,asset.storage_key)
    except (OSError,ValueError):abort(404)
    response=send_file(path,mimetype='audio/mpeg',conditional=True,max_age=0)
    response.headers['Cache-Control']='private, no-store'
    return response
