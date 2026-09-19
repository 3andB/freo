"""Offline migration for the retired Imaging feature."""
import json
import click
from flask import Blueprint
from app.services.stations import get_station
from app.services.imaging_migration import inventory, convert

audio_migration_cli=Blueprint('audio_migration_cli',__name__)


@audio_migration_cli.cli.command('migrate-station-audio')
@click.option('--station',required=True)
@click.option('--apply',is_flag=True,help='Convert after stopping station and backing up database/media. Default: inventory only.')
@click.option('--mapping',type=click.File('r'),help='Reviewed JSON object mapping legacy asset IDs to duplicate track UUIDs.')
def migrate(station,apply,mapping):
    row=get_station(station)
    if not row:raise click.ClickException('Station not found')
    try:
        result=convert(row,mapping=json.load(mapping) if mapping else None) if apply else inventory(row)
        click.echo(json.dumps(result,indent=2))
    except (ValueError,OSError) as error:raise click.ClickException(str(error)) from error
