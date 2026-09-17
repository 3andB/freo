"""Root-run station administration. No mutation endpoint is exposed by Flask."""
import time
import json
import click
from flask import Blueprint

from app.extensions import db
from app.models import Station
from app.routes.stations import observed_status
from app.services.station_runtime import render, require_root, service_action
from app.services.stations import create_station, get_station, public_station, set_enabled

station_cli = Blueprint('station_cli', __name__)


@station_cli.cli.group('station')
def station_group():
    """Manage database-backed stations from the server CLI."""


def known(slug):
    try:
        station = get_station(slug)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    if station is None:
        raise click.ClickException('Station not found')
    return station


def admin():
    try:
        require_root()
    except PermissionError as error:
        raise click.ClickException(str(error)) from error


@station_group.command('list')
def list_command():
    for item in Station.query.filter_by(deleted_at=None).order_by(Station.slug):
        click.echo(f'{item.slug}\t{item.name}\t{item.desired_state}')


@station_group.command('create')
@click.argument('slug')
@click.option('--name', required=True)
@click.option('--description', default='')
@click.option('--timezone', 'timezone_name', default='UTC')
@click.option('--if-not-exists', is_flag=True, help='Resume an identical setup request safely.')
@click.option('--json', 'as_json', is_flag=True)
@click.option('--start', 'start_after', is_flag=True)
def create_command(slug, name, description, timezone_name, if_not_exists, as_json, start_after):
    admin()
    try:
        from app.services.station_lifecycle import process_station
        from app.services.schedule import validate_timezone
        timezone_name = validate_timezone(timezone_name)
        station = get_station(slug) if if_not_exists else None
        if station:
            if (station.name, station.description, station.timezone) != (name.strip(), description, timezone_name):
                raise ValueError('Existing station differs from the requested setup')
            if station.lifecycle_state not in ('ready', 'pending_create', 'create_failed'):
                raise ValueError('Station is being deleted')
        else:
            station = create_station(name, slug, description, pending=True, timezone_name=timezone_name)
        process_station(station)
        if start_after and not station.enabled:
            raise ValueError('Station is disabled; enable it before starting')
        if start_after and station.desired_state != 'running':
            service_action(slug, 'start')
            if not wait_online(station):
                service_action(slug, 'stop')
                raise ValueError('Station did not begin streaming')
            station.desired_state = 'running'
            db.session.commit()
        click.echo(json.dumps(public_station(station)) if as_json else f'Created and rendered {station.slug}; desired state {station.desired_state}')
    except Exception as error:
        db.session.rollback()
        raise click.ClickException(str(error) if isinstance(error, ValueError) else 'Station setup failed; check provisioning status and retry') from error


@station_group.command('delete')
@click.argument('slug')
@click.option('--yes', is_flag=True, help='Confirm removal of this station runtime; retain media and history.')
@click.option('--json', 'as_json', is_flag=True)
def delete_command(slug, yes, as_json):
    admin()
    from app.services.stations import validate_slug, request_delete
    from app.services.station_lifecycle import process_station
    try:
        validate_slug(slug)
        station = Station.query.filter_by(slug=slug).first()
        if station is None:
            raise ValueError('Station not found')
        if not yes:
            raise ValueError('Pass --yes to remove this station runtime. Media and history are retained.')
        if not station.deleted_at:
            request_delete(station)
            process_station(station)
        click.echo(json.dumps(dict(slug=slug, status='deleted', media='retained')) if as_json else f'Deleted {slug}; media and history retained')
    except Exception as error:
        db.session.rollback()
        raise click.ClickException(str(error) if isinstance(error, ValueError) else 'Station deletion failed; check provisioning status and retry') from error


@station_group.command('process-pending')
def process_pending_command():
    admin()
    from app.services.station_lifecycle import process_pending
    try:
        process_pending()
    except Exception as error:
        raise click.ClickException('Station provisioning failed; retry from Stations after checking runtime services') from error


@station_group.command('retry')
@click.argument('slug')
def retry_command(slug):
    admin()
    from app.services.station_lifecycle import retry, process_station
    station = known(slug)
    try:
        retry(station)
        process_station(station)
    except Exception as error:
        raise click.ClickException('Station retry failed; check runtime services') from error
    click.echo(station.lifecycle_state)


@station_group.command('show')
@click.argument('slug')
def show_command(slug):
    click.echo(public_station(known(slug)))


@station_group.command('render')
@click.argument('slug')
def render_command(slug):
    admin()
    try:
        station = known(slug)
        from app.services.media import _prepare_dirs
        from app.services.media_storage import LocalMediaStorage
        _prepare_dirs(LocalMediaStorage(), station.slug)
        render(station)
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo('Station config validated and installed')


@station_group.command('validate')
@click.argument('slug')
def validate_command(slug):
    station = known(slug)
    if not station.stream or station.stream.format != 'mp3' or station.stream.bitrate not in (64, 96, 128):
        raise click.ClickException('Unsupported station stream')
    click.echo('Station model valid; use render to validate runtime config')


@station_group.command('status')
@click.argument('slug')
def status_command(slug):
    click.echo(observed_status(known(slug)))


@station_group.command('disable')
@click.argument('slug')
def disable_command(slug):
    admin()
    station = known(slug)
    try:
        service_action(slug, 'stop')
        set_enabled(station, False)
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(f'Disabled {slug}')


@station_group.command('enable')
@click.argument('slug')
def enable_command(slug):
    admin()
    station = known(slug)
    if station.lifecycle_state != 'ready':
        raise click.ClickException('Station provisioning is not ready')
    set_enabled(station, True)
    click.echo(f'Enabled {slug}; desired state stopped')


def wait_online(station):
    for _ in range(30):
        status = observed_status(station)
        if status['playout'] == 'running' and status['stream'] == 'online':
            return True
        time.sleep(2)
    return False


@station_group.command('start')
@click.argument('slug')
def start_command(slug):
    admin()
    station = known(slug)
    if station.lifecycle_state != 'ready' or not station.enabled or not station.stream.enabled:
        raise click.ClickException('Station is disabled')
    try:
        render(station)
        service_action(slug, 'start')
        if not wait_online(station):
            service_action(slug, 'stop')
            raise click.ClickException('Station did not begin streaming')
        station.desired_state = 'running'
        db.session.commit()
    except click.ClickException:
        raise
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(f'Started {slug}')


@station_group.command('stop')
@click.argument('slug')
def stop_command(slug):
    admin()
    station = known(slug)
    try:
        service_action(slug, 'stop')
        station.desired_state = 'stopped'
        db.session.commit()
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(f'Stopped {slug}')


@station_group.command('restart')
@click.argument('slug')
def restart_command(slug):
    admin()
    station = known(slug)
    if station.desired_state != 'running':
        raise click.ClickException('Station is not desired running; use start')
    try:
        service_action(slug, 'restart')
        if not wait_online(station):
            raise click.ClickException('Station did not recover')
    except click.ClickException:
        raise
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(f'Restarted {slug}')
