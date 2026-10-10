"""Root-run recovery commands for station imaging, without playout restarts."""
import click
from flask import Blueprint

from app.models import ImagingAsset, ImagingGroup
from app.services.media import require_admin
from app.services.imaging import (asset_for, create_group, ingest_imaging,
    set_asset_enabled, set_group_membership, verify_imaging)
from app.services.automation import require_station

imaging_cli = Blueprint('imaging_cli', __name__)


@imaging_cli.cli.group('imaging')
def imaging_group():
    """Manage first-class non-music audio."""


@imaging_group.command('list')
@click.option('--station', required=True)
def list_assets(station):
    item = require_station(station)
    for asset in ImagingAsset.query.filter_by(station_id=item.id).order_by(ImagingAsset.id):
        click.echo(f'{asset.uuid}\t{asset.cart_code or "—"}\t{asset.asset_type}\t{asset.name}\t{"enabled" if asset.enabled else "disabled"}')


@imaging_group.command('show')
@click.option('--station', required=True)
@click.argument('identifier')
def show_asset(station, identifier):
    asset = asset_for(station, identifier)
    click.echo(f'{asset.uuid}\t{asset.name}\t{asset.asset_type}\t{asset.duration_ms} ms\t{asset.ingest_status}')


@imaging_group.command('ingest')
@click.option('--station', required=True)
@click.option('--file', 'source', required=True, type=click.Path(exists=True))
@click.option('--type', 'asset_type', required=True)
@click.option('--name')
@click.option('--cart-code')
def ingest_asset(station, source, asset_type, name, cart_code):
    require_admin()
    try:
        asset, duplicate = ingest_imaging(station, source, asset_type, name, cart_code)
    except Exception as error:
        raise click.ClickException(str(error)) from error
    click.echo(f'{"Existing" if duplicate else "Ingested"} imaging {asset.uuid}; disabled pending review')


@imaging_group.command('verify')
@click.option('--station', required=True)
@click.argument('identifier')
def verify_asset(station, identifier):
    verify_imaging(asset_for(station, identifier))
    click.echo('Checksum and audio probe verified')


@imaging_group.command('enable')
@click.option('--station', required=True)
@click.argument('identifier')
def enable_asset(station, identifier):
    require_admin()
    asset = asset_for(station, identifier)
    verify_imaging(asset)
    set_asset_enabled(asset, True)
    click.echo('Imaging enabled without playout restart')


@imaging_group.command('disable')
@click.option('--station', required=True)
@click.argument('identifier')
def disable_asset(station, identifier):
    require_admin()
    set_asset_enabled(asset_for(station, identifier), False)
    click.echo('Imaging disabled for future selection')


@imaging_cli.cli.group('imaging-group')
def groups():
    """Manage station-scoped imaging pools."""


@groups.command('list')
@click.option('--station', required=True)
def list_groups(station):
    item = require_station(station)
    for group in ImagingGroup.query.filter_by(station_id=item.id).order_by(ImagingGroup.name):
        click.echo(f'{group.slug}\t{group.name}\t{len(group.assets)} assets\t{"enabled" if group.enabled else "disabled"}')


@groups.command('create')
@click.option('--station', required=True)
@click.option('--name', required=True)
@click.option('--slug', required=True)
def create_group_command(station, name, slug):
    require_admin()
    click.echo(create_group(station, name, slug).slug)


@groups.command('assign')
@click.option('--station', required=True)
@click.option('--asset', required=True)
@click.option('--group', 'group_slug', required=True)
def assign_asset(station, asset, group_slug):
    require_admin()
    set_group_membership(station, group_slug, asset_for(station, asset).uuid, True)
    click.echo('Imaging asset assigned')


@groups.command('remove')
@click.option('--station', required=True)
@click.option('--asset', required=True)
@click.option('--group', 'group_slug', required=True)
def remove_asset(station, asset, group_slug):
    require_admin()
    set_group_membership(station, group_slug, asset_for(station, asset).uuid, False)
    click.echo('Imaging asset removed')
