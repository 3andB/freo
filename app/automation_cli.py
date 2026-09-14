"""Root-run administration for categories, rotations, and automation."""
import click
from flask import Blueprint

from app.extensions import db
from app.models import MediaCategory, Rotation, RotationSlot, SelectionDecision
from app.services.automation import (activate, add_slot, assign_track, category_create,
    category_for, preview, require_station, rotation_create, rotation_for, set_automation)
from app.services.station_runtime import require_root
from app.services.media_storage import LocalMediaStorage

automation_cli = Blueprint('automation_cli', __name__)


def admin():
    require_root()


@automation_cli.cli.group('category')
def category_group():
    """Manage station-scoped media categories."""


@category_group.command('list')
@click.option('--station', required=True)
def category_list(station):
    item = require_station(station)
    for category in MediaCategory.query.filter_by(station_id=item.id).order_by(MediaCategory.name):
        click.echo(f'{category.slug}\t{category.name}\t{"enabled" if category.enabled else "disabled"}\t{len(category.tracks)} tracks')


@category_group.command('show')
@click.option('--station', required=True)
@click.argument('slug')
def category_show(station, slug):
    category = category_for(station, slug)
    click.echo(f'{category.slug}\t{category.name}\t{"enabled" if category.enabled else "disabled"}')
    for track in category.tracks:
        click.echo(f'{track.uuid}\t{track.title}\t{track.artist}')


@category_group.command('create')
@click.option('--station', required=True)
@click.option('--name', required=True)
@click.option('--slug', required=True)
def category_create_command(station, name, slug):
    admin()
    category = category_create(station, name, slug)
    click.echo(f'Created category {category.slug}')


@category_group.command('assign')
@click.option('--station', required=True)
@click.option('--track', required=True)
@click.option('--category', required=True)
def category_assign(station, track, category):
    admin()
    assign_track(station, track, category)
    click.echo('Track assigned')


@category_group.command('unassign')
@click.option('--station', required=True)
@click.option('--track', required=True)
@click.option('--category', required=True)
def category_unassign(station, track, category):
    admin()
    assign_track(station, track, category, False)
    click.echo('Track unassigned')


@category_group.command('disable')
@click.option('--station', required=True)
@click.argument('slug')
def category_disable(station, slug):
    admin()
    category = category_for(station, slug)
    category.enabled = False
    db.session.commit()
    click.echo('Category disabled')


@category_group.command('enable')
@click.option('--station', required=True)
@click.argument('slug')
def category_enable(station, slug):
    admin()
    category = category_for(station, slug)
    category.enabled = True
    db.session.commit()
    click.echo('Category enabled')


@automation_cli.cli.group('rotation')
def rotation_group():
    """Manage explicit category sequences."""


@rotation_group.command('list')
@click.option('--station', required=True)
def rotation_list(station):
    item = require_station(station)
    for rotation in Rotation.query.filter_by(station_id=item.id).order_by(Rotation.name):
        click.echo(f'{rotation.slug}\t{rotation.name}\t{len(rotation.slots)} slots')


@rotation_group.command('create')
@click.option('--station', required=True)
@click.option('--name', required=True)
@click.option('--slug', required=True)
def rotation_create_command(station, name, slug):
    admin()
    rotation = rotation_create(station, name, slug)
    click.echo(f'Created rotation {rotation.slug}')


@rotation_group.command('add-slot')
@click.option('--station', required=True)
@click.option('--rotation', required=True)
@click.option('--category', required=True)
def rotation_add_slot(station, rotation, category):
    admin()
    slot = add_slot(station, rotation, category)
    click.echo(f'Added slot {slot.position}')


@rotation_group.command('disable-slot')
@click.option('--station', required=True)
@click.option('--rotation', required=True)
@click.option('--position', required=True, type=click.IntRange(1, 1000))
def rotation_disable_slot(station, rotation, position):
    admin()
    item = rotation_for(station, rotation)
    slot = RotationSlot.query.filter_by(rotation_id=item.id, position=position).first()
    if slot is None:
        raise click.ClickException('Slot not found')
    slot.enabled = False
    db.session.commit()
    click.echo(f'Disabled slot {position}')


@rotation_group.command('enable-slot')
@click.option('--station', required=True)
@click.option('--rotation', required=True)
@click.option('--position', required=True, type=click.IntRange(1, 1000))
def rotation_enable_slot(station, rotation, position):
    admin()
    item = rotation_for(station, rotation)
    slot = RotationSlot.query.filter_by(rotation_id=item.id, position=position).first()
    if slot is None or not slot.category.enabled:
        raise click.ClickException('Slot or category is unavailable')
    slot.enabled = True
    db.session.commit()
    click.echo(f'Enabled slot {position}')


@rotation_group.command('show')
@click.option('--station', required=True)
@click.argument('slug')
def rotation_show(station, slug):
    rotation = rotation_for(station, slug)
    click.echo(f'{rotation.slug}: {rotation.name}')
    for slot in rotation.slots:
        click.echo(f'{slot.position}\t{slot.category.slug}\t{"enabled" if slot.enabled else "disabled"}')


@rotation_group.command('validate')
@click.option('--station', required=True)
@click.argument('slug')
def rotation_validate(station, slug):
    item = rotation_for(station, slug)
    if not item.enabled or not item.slots:
        raise click.ClickException('Rotation is disabled or has no slots')
    storage = LocalMediaStorage()
    for slot in item.slots:
        if not slot.enabled:
            click.echo(f'Slot {slot.position}: disabled; skipped')
            continue
        if slot.category.station_id != item.station_id:
            raise click.ClickException(f'Slot {slot.position} crosses station boundary')
        if not slot.category.enabled:
            click.echo(f'Warning: slot {slot.position} category is disabled')
        count = 0
        for track in slot.category.tracks:
            if track.station_id == item.station_id and track.enabled and track.ingest_status == 'accepted':
                try:
                    storage.regular_file(station, track.storage_key)
                    count += 1
                except (OSError, ValueError):
                    pass
        click.echo(f'Slot {slot.position}: {slot.category.slug}, {count} playable tracks')
    click.echo('Rotation structure valid')


@rotation_group.command('disable')
@click.option('--station', required=True)
@click.argument('slug')
def rotation_disable(station, slug):
    admin()
    item = rotation_for(station, slug)
    item.enabled = False
    db.session.commit()
    click.echo('Rotation disabled; active worker will stop refilling it')


@rotation_group.command('enable')
@click.option('--station', required=True)
@click.argument('slug')
def rotation_enable(station, slug):
    admin()
    item = rotation_for(station, slug)
    item.enabled = True
    db.session.commit()
    click.echo('Rotation enabled')


@rotation_group.command('activate')
@click.option('--station', required=True)
@click.argument('slug')
def rotation_activate(station, slug):
    admin()
    activate(station, slug)
    click.echo(f'Activated rotation {slug}; automation remains disabled until enabled explicitly')


@rotation_group.command('preview')
@click.option('--station', required=True)
@click.option('--count', type=click.IntRange(1, 100), default=10)
def rotation_preview(station, count):
    for choice in preview(station, count):
        click.echo(f'{choice["slot"]}\t{choice["category"]}\t{choice["track"] or "fallback"}\t{choice["relaxation"]}\t{choice["candidate_count"]} candidates')


@automation_cli.cli.group('automation')
def automation_group():
    """Inspect and control station automation from the server CLI."""


@automation_group.command('enable')
@click.option('--station', required=True)
@click.option('--track-separation', type=int)
@click.option('--artist-separation', type=int)
def automation_enable(station, track_separation, artist_separation):
    admin()
    set_automation(station, True, track_separation, artist_separation)
    click.echo('Automation enabled')


@automation_group.command('disable')
@click.option('--station', required=True)
def automation_disable(station):
    admin()
    set_automation(station, False)
    click.echo('Automation disabled; already queued audio may finish')


@automation_group.command('status')
@click.option('--station', required=True)
def automation_status(station):
    item = require_station(station)
    state = item.automation
    click.echo(f'{station}: enabled={bool(state and state.enabled)} rotation={state.active_rotation.slug if state and state.active_rotation else "none"} cursor={state.next_slot_index if state else 0}')


@automation_group.command('queue')
@click.option('--station', required=True)
def automation_queue(station):
    item = require_station(station)
    state = item.automation
    click.echo(f'{station}: observed_queue_depth={state.observed_queue_depth if state else "unknown"}')


@automation_group.command('explain')
@click.option('--station', required=True)
@click.option('--last', type=click.IntRange(1, 100), default=10)
def automation_explain(station, last):
    item = require_station(station)
    for decision in SelectionDecision.query.filter_by(station_id=item.id).order_by(SelectionDecision.id.desc()).limit(last):
        click.echo(f'{decision.id}\t{decision.status}\t{decision.category.slug if decision.category else "-"}\t{decision.track.uuid if decision.track else "-"}\t{decision.relaxation}\t{decision.reason}')


@automation_cli.cli.group('history')
def history_group():
    """Read actual playback-start history."""


@history_group.command('list')
@click.option('--station', required=True)
@click.option('--limit', type=click.IntRange(1, 100), default=50)
def history_list(station, limit):
    item = require_station(station)
    for decision in SelectionDecision.query.filter_by(station_id=item.id, status='started').order_by(SelectionDecision.started_at.desc()).limit(limit):
        click.echo(f'{decision.started_at.isoformat()}\t{decision.track.uuid if decision.track else "-"}\t{decision.category.slug if decision.category else "-"}')
