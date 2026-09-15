"""Recovery and inspection CLI for timed events."""
import json
from datetime import datetime, timedelta, timezone

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
    for item in upcoming(row): click.echo(f'{item.id} {item.scheduled_for_utc.isoformat()} {item.state} {item.event.name}')


@event_group.command('preview')
@click.option('--station', required=True)
@click.option('--hours', default=24, type=click.IntRange(1,192))
def preview_events(station, hours):
    row = get_station(station)
    if not row: raise click.ClickException('Station not found')
    generate_occurrences(row, horizon_hours=hours)
    end = datetime.now(timezone.utc) + timedelta(hours=hours)
    for item in upcoming(row, limit=200):
        when = item.scheduled_for_utc.replace(tzinfo=item.scheduled_for_utc.tzinfo or timezone.utc)
        if when <= end: click.echo(f'{when.isoformat()} {item.event.timing_mode} {item.event.name}')


@event_group.command('create')
@click.option('--station', required=True)
@click.option('--name', required=True)
@click.option('--mode', type=click.Choice(['soft','hard','non_interrupting']), required=True)
@click.option('--at', 'at_value', help='Station-local YYYY-MM-DDTHH:MM:SS')
@click.option('--weekly', type=click.IntRange(0,6))
@click.option('--time', 'time_value')
@click.option('--track')
@click.option('--imaging')
@click.option('--block')
@click.option('--late', default=10, type=click.IntRange(1,86400))
@click.option('--missed', type=click.Choice(['skip','play_late']), default='skip')
@click.option('--interrupt', type=click.Choice(['never','music_only']), default='never')
@click.option('--priority', default=100, type=click.IntRange(0,1000))
def create_event(station, name, mode, at_value, weekly, time_value, track, imaging, block, late, missed, interrupt, priority):
    if bool(at_value) == (weekly is not None): raise click.ClickException('Choose exactly one of --at or --weekly')
    if sum(bool(value) for value in (track,imaging,block)) != 1: raise click.ClickException('Choose exactly one of --track, --imaging, or --block')
    date, at = (at_value.split('T',1) if at_value and 'T' in at_value else (None, time_value))
    try:
        row = save_event(station, name=name, timing_mode=mode.upper(), recurrence_type='ONE_TIME' if at_value else 'WEEKLY',
            content_type='TRACK' if track else 'IMAGING_ASSET' if imaging else 'EVENT_BLOCK', content_identifier=track or imaging or block,
            local_date=date, local_time=at, weekday=weekly, late_tolerance_seconds=late,
            missed_policy=missed.upper(), interrupt_policy=interrupt.upper(), priority=priority)
    except ValueError as error: raise click.ClickException(str(error)) from error
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
