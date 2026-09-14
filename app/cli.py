"""Root-run station administration. No mutation endpoint is exposed by Flask."""
import time
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
    for item in Station.query.order_by(Station.slug):
        click.echo(f'{item.slug}\t{item.name}\t{item.desired_state}')


@station_group.command('create')
@click.argument('slug')
@click.option('--name', required=True)
@click.option('--description', default='')
def create_command(slug, name, description):
    admin()
    try:
        station = create_station(name, slug, description)
        from app.services.media import _prepare_dirs
        from app.services.media_storage import LocalMediaStorage
        _prepare_dirs(LocalMediaStorage(), station.slug)
        render(station)
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(f'Created and rendered {station.slug}; desired state stopped')


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
    if not station.stream or station.stream.format != 'mp3' or station.stream.bitrate != 64:
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
    if not station.enabled or not station.stream.enabled:
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
