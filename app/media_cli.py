"""Administrative media commands; no web upload path."""
import click
from flask import Blueprint
from app.models import Track
from app.services.media import ingest, require_admin, refresh_playlist, set_enabled, verify
from app.services.station_runtime import service_action
from app.services.stations import get_station

media_cli = Blueprint('media_cli', __name__)


@media_cli.cli.group('media')
def media_group():
    """Manage station-scoped approved audio from the server CLI."""


def track_by_uuid(value):
    track = Track.query.filter_by(uuid=value).first()
    if track is None:
        raise click.ClickException('Track not found')
    return track


@media_group.command('list')
@click.option('--station', required=True)
def list_command(station):
    item = get_station(station)
    if item is None:
        raise click.ClickException('Station not found')
    for track in Track.query.filter_by(station_id=item.id).order_by(Track.id):
        click.echo(f'{track.uuid}\t{track.title}\t{track.artist}\t{track.ingest_status}\t{"enabled" if track.enabled else "disabled"}')


@media_group.command('ingest')
@click.option('--station', required=True)
@click.option('--file', 'source', required=True, type=click.Path(exists=True))
@click.option('--title')
@click.option('--artist')
@click.option('--album')
def ingest_command(station, source, title, artist, album):
    require_admin()
    try:
        track, duplicate = ingest(station, source, title, artist, album)
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(f'{"Existing" if duplicate else "Ingested"} track {track.uuid} for {station}')


@media_group.command('show')
@click.argument('track_uuid')
def show_command(track_uuid):
    track = track_by_uuid(track_uuid)
    click.echo(f'{track.uuid}\t{track.station.slug}\t{track.title}\t{track.artist}\t{track.album}\t{track.duration_ms} ms\t{track.ingest_status}')


@media_group.command('verify')
@click.argument('track_uuid')
def verify_command(track_uuid):
    try:
        verify(track_by_uuid(track_uuid))
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo('Track file, checksum, and probe verified')


@media_group.command('disable')
@click.argument('track_uuid')
def disable_command(track_uuid):
    require_admin()
    try:
        track = track_by_uuid(track_uuid)
        set_enabled(track, False)
        if track.station.desired_state == 'running':
            service_action(track.station.slug, 'restart')
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo('Track disabled and playlist refreshed')


@media_group.command('enable')
@click.argument('track_uuid')
def enable_command(track_uuid):
    require_admin()
    try:
        track = track_by_uuid(track_uuid)
        verify(track)
        set_enabled(track, True)
        if track.station.desired_state == 'running':
            service_action(track.station.slug, 'restart')
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo('Track enabled and playlist refreshed')


@media_group.command('audit')
@click.option('--station', required=True)
def audit_command(station):
    require_admin()
    item = get_station(station)
    if item is None:
        raise click.ClickException('Station not found')
    problems = 0
    for track in Track.query.filter_by(station_id=item.id):
        try:
            verify(track)
        except Exception:
            problems += 1
            click.echo(f'Problem with track {track.uuid}')
    click.echo(f'Audited station {station}: {problems} problem(s)')
