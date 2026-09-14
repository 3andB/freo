"""Root-only programming changes and read-only schedule inspection."""
from datetime import datetime, timezone

import click
from flask import Blueprint

from app.extensions import db
from app.models import Clock, ScheduleAssignment, ClockState
from app.services.automation import require_station
from app.services.clocks import (add_clock_slot, assign, clock_for, create_clock,
                                 current, move_clock_slot, remove_assignment, set_default_clock,
                                 set_timezone, validate_clock, preview_clock)
from app.services.station_runtime import require_root

schedule_cli = Blueprint('schedule_cli', __name__)
DAY_NAMES = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


def day_number(value):
    try:
        return DAY_NAMES.index(value.casefold())
    except ValueError as error:
        raise click.BadParameter('Use a full weekday name') from error


def instant(value):
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise click.BadParameter('Timestamp must include a UTC offset')
    return parsed


@schedule_cli.cli.group('clock')
def clock_group():
    """Manage station clock sequences."""


@clock_group.command('list')
@click.option('--station', required=True)
def list_clocks(station):
    item = require_station(station)
    for clock in Clock.query.filter_by(station_id=item.id).order_by(Clock.name):
        click.echo(f'{clock.slug}\t{clock.name}\t{len(clock.slots)} slots\t{"enabled" if clock.enabled else "disabled"}')


@clock_group.command('create')
@click.option('--station', required=True)
@click.option('--name', required=True)
@click.option('--slug', required=True)
def create(station, name, slug):
    require_root()
    click.echo(f'Created {create_clock(station, name, slug).slug}')


@clock_group.command('add-slot')
@click.option('--station', required=True)
@click.option('--clock', required=True)
@click.option('--type', 'slot_type', type=click.Choice(['rotation', 'category', 'cart', 'imaging_group']), required=True)
@click.option('--target', required=True)
def add(station, clock, slot_type, target):
    require_root()
    slot = add_clock_slot(station, clock, slot_type, target)
    click.echo(f'Added slot {slot.position}')


@clock_group.command('show')
@click.option('--station', required=True)
@click.argument('slug')
def show(station, slug):
    clock = clock_for(station, slug)
    click.echo(f'{clock.slug}\t{clock.name}')
    for slot in clock.slots:
        target = slot.rotation.slug if slot.rotation else slot.category.slug if slot.category else slot.imaging_asset.cart_code or slot.imaging_asset.uuid if slot.imaging_asset else slot.imaging_group.slug if slot.imaging_group else 'missing'
        click.echo(f'{slot.position}\t{slot.slot_type}\t{target}\t{"enabled" if slot.enabled else "disabled"}')


@clock_group.command('validate')
@click.option('--station', required=True)
@click.argument('slug')
def validate(station, slug):
    clock = clock_for(station, slug)
    click.echo(f'Valid: {len(validate_clock(clock))} enabled slots')


@clock_group.command('preview')
@click.option('--station', required=True)
@click.option('--slots', type=click.IntRange(1, 100), default=10)
@click.argument('slug')
def clock_preview(station, slots, slug):
    for item in preview_clock(station, slug, slots):
        click.echo(f'{item["clock_slot"]}\t{item["type"]}\t{item["category"]}\t'
                   f'{item["track"] or "fallback"}\t{item["artist"] or "-"}\t{item["relaxation"]}')


@clock_group.command('default')
@click.option('--station', required=True)
@click.argument('slug', required=False)
def default(station, slug):
    require_root()
    set_default_clock(station, slug)
    click.echo(f'Default clock: {slug or "none"}')


@clock_group.command('move-slot')
@click.option('--station', required=True)
@click.option('--clock', required=True)
@click.option('--from-position', type=click.IntRange(1, 1000), required=True)
@click.option('--to-position', type=click.IntRange(1, 1000), required=True)
def move(station, clock, from_position, to_position):
    require_root()
    move_clock_slot(station, clock, from_position, to_position)
    click.echo('Clock slots reordered')


@schedule_cli.cli.group('schedule')
def schedule_group():
    """Manage recurring local-wall-time assignments."""


@schedule_group.command('timezone')
@click.option('--station', required=True)
@click.argument('name')
def timezone_command(station, name):
    require_root()
    click.echo(f'Timezone: {set_timezone(station, name).timezone}')


@schedule_group.command('assign')
@click.option('--station', required=True)
@click.option('--day', required=True)
@click.option('--time', 'start_time', required=True)
@click.option('--clock', required=True)
def assign_command(station, day, start_time, clock):
    require_root()
    row = assign(station, day_number(day), start_time, clock)
    click.echo(f'Assignment {row.id}: {DAY_NAMES[row.weekday]} {row.start_time.strftime("%H:%M")} -> {row.clock.slug}')


@schedule_group.command('remove')
@click.option('--station', required=True)
@click.argument('assignment_id', type=int)
def remove(station, assignment_id):
    require_root()
    remove_assignment(station, assignment_id)
    click.echo('Assignment removed')


@schedule_group.command('list')
@click.option('--station', required=True)
def list_schedule(station):
    item = require_station(station)
    rows = ScheduleAssignment.query.filter_by(station_id=item.id).order_by(ScheduleAssignment.weekday, ScheduleAssignment.start_time).all()
    for row in rows:
        click.echo(f'{row.id}\t{DAY_NAMES[row.weekday].upper()} {row.start_time.strftime("%H:%M")}\t{row.clock.slug}\t{"enabled" if row.enabled else "disabled"}')


@schedule_group.command('resolve')
@click.option('--station', required=True)
@click.option('--at')
def resolve_command(station, at):
    for key, value in current(station, instant(at)).items():
        click.echo(f'{key}: {value}')


@schedule_group.command('status')
@click.option('--station', required=True)
def status(station):
    item = require_station(station)
    for key, value in current(station).items():
        click.echo(f'{key}: {value}')
    cursor = db.session.get(ClockState, item.id)
    click.echo(f'next_clock_slot_index: {cursor.next_slot_index if cursor else None}')


@schedule_group.command('preview')
@click.option('--station', required=True)
@click.option('--from', 'from_at', required=True)
@click.option('--hours', type=click.IntRange(1, 168), default=24)
def preview(station, from_at, hours):
    from datetime import timedelta
    start = instant(from_at)
    end = start + timedelta(hours=hours)
    point = start
    seen = set()
    while point <= end:
        resolved = current(station, point)
        marker = (resolved['clock'], resolved['source'], resolved['occurrence'])
        if marker not in seen:
            click.echo(f'{resolved["local_time"]}\t{resolved["clock"] or "rotation/fallback"}\t{resolved["source"]}')
            seen.add(marker)
        next_at = resolved['next_transition']
        if not next_at:
            break
        following = datetime.fromisoformat(next_at)
        if following <= point:
            break
        point = following
