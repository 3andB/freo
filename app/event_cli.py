"""Recovery and inspection CLI for timed events."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import click
from flask import Blueprint

from app.models import TimedEvent
from app.services.stations import get_station
from app.services.timed_events import conflict_warnings, event_for, generate_occurrences, save_event, set_enabled, upcoming, validate_content

event_cli = Blueprint('event_cli', __name__)


@event_cli.cli.group('event')
def event_group():
    """Manage exact-time events."""


@event_group.command('list')
@click.option('--station', required=True)
def list_events(station):
    row = get_station(station)
    if not row: raise click.ClickException('Station not found')
    for event in TimedEvent.query.filter_by(station_id=row.id).order_by(TimedEvent.name):
        click.echo(f'{event.uuid} {event.timing_mode} {event.recurrence_type} {event.name} enabled={event.enabled}')


@event_group.command('occurrences')
@click.option('--station', required=True)
def occurrences(station):
    row = get_station(station)
    if not row: raise click.ClickException('Station not found')
    generate_occurrences(row)
    for item in upcoming(row): click.echo(f'{item.id} {item.scheduled_for_utc.replace(tzinfo=item.scheduled_for_utc.tzinfo or timezone.utc).astimezone(ZoneInfo(row.timezone)).isoformat()} {item.state} {item.event.name}')


@event_group.command('preview')
@click.option('--station', required=True)
@click.option('--hours', default=24, type=click.IntRange(1,192))
def preview_events(station, hours):
    row = get_station(station)
    if not row: raise click.ClickException('Station not found')
    from app.services.timed_events import projected_occurrences
    now=datetime.now(timezone.utc)
    for item in projected_occurrences(row,now,now+timedelta(hours=hours)):
        click.echo(f'{item.scheduled_for_utc.astimezone(ZoneInfo(row.timezone)).isoformat()} {item.event.timing_mode} {item.event.name}')


@event_group.command('create')
@click.option('--station', required=True)
@click.option('--name', required=True)
@click.option('--mode', type=click.Choice(['soft','hard','non_interrupting']), default='soft')
@click.option('--at', 'at_value', help='Station-local YYYY-MM-DDTHH:MM:SS')
@click.option('--weekly', type=click.IntRange(0,6))
@click.option('--time', 'time_value')
@click.option('--track')
@click.option('--playlist')
@click.option('--recurrence',type=click.Choice(['quarter_hour','hourly','daily','weekly','monthly']))
@click.option('--days',multiple=True,type=click.IntRange(0,6))
@click.option('--hours',multiple=True,type=click.IntRange(0,23))
@click.option('--starts-on')
@click.option('--ends-on')
@click.option('--month-day',default=1,type=click.IntRange(1,31))
@click.option('--month-nth',default=0,type=click.IntRange(-2,5))
@click.option('--month-weekday',default=0,type=click.IntRange(0,6))
@click.option('--interrupt-dj',is_flag=True,default=False)
@click.option('--playlist-playback',type=click.Choice(['one','all']))
@click.option('--block')
@click.option('--late', default=300, type=click.IntRange(1,86400))
@click.option('--missed', type=click.Choice(['skip','play_late']), default='skip')
@click.option('--interrupt', type=click.Choice(['never','music_only']), default='never')
@click.option('--priority', default=100, type=click.IntRange(0,1000))
def create_event(station, name, mode, at_value, weekly, time_value, track, playlist, block, late, missed, interrupt, priority, recurrence,days,hours,starts_on,ends_on,month_day,month_nth,month_weekday,interrupt_dj,playlist_playback):
    if bool(at_value) == bool(recurrence or weekly is not None): raise click.ClickException('Choose --at or a repeating rule')
    if sum(bool(value) for value in (track,playlist,block)) != 1: raise click.ClickException('Choose one of --track, --playlist, or --block')
    day, at = (at_value.split('T',1) if at_value and 'T' in at_value else (None,time_value))
    try:
        row=save_event(station,name=name,timing_mode=mode.upper(),recurrence_type='ONE_TIME' if at_value else (recurrence or 'weekly').upper(),
            content_type='TRACK' if track else 'PLAYLIST' if playlist else 'EVENT_BLOCK',content_identifier=track or playlist or block,
            local_date=day,local_time=at,weekday=weekly,weekdays=list(days) or None,repeat_hours=list(hours) or None,starts_on=starts_on,ends_on=ends_on,
            month_day=month_day,month_nth=month_nth,month_weekday=month_weekday,interrupt_dj=interrupt_dj,playlist_playback=playlist_playback.upper() if playlist_playback else None,
            late_tolerance_seconds=late,missed_policy=missed.upper(),interrupt_policy=interrupt.upper(),priority=priority)
    except ValueError as error:raise click.ClickException(str(error)) from error
    click.echo(f'Created event {row.uuid}')


@event_group.command('show')
@click.option('--station', required=True)
@click.argument('identifier')
def show_event(station, identifier):
    try: event = event_for(station, identifier)
    except ValueError as error: raise click.ClickException(str(error)) from error
    click.echo(json.dumps({'uuid':event.uuid,'name':event.name,'mode':event.timing_mode,'recurrence':event.recurrence_type,'enabled':event.enabled}))


@event_group.command('validate')
@click.option('--station', required=True)
@click.argument('identifier')
def validate_event(station, identifier):
    try:
        event = event_for(station, identifier); validate_content(event)
    except (OSError, ValueError) as error: raise click.ClickException(str(error)) from error
    warnings = conflict_warnings(event)
    click.echo('Valid' if not warnings else 'Valid with warnings: ' + ' '.join(warnings))


@event_group.command('enable')
@click.option('--station', required=True)
@click.argument('identifier')
def enable_event(station, identifier): set_enabled(event_for(station, identifier), True)


@event_group.command('disable')
@click.option('--station', required=True)
@click.argument('identifier')
def disable_event(station, identifier): set_enabled(event_for(station, identifier), False)
