"""Explicit adoption and audited installation settings management."""
import json
import click
from flask import Blueprint

settings_cli = Blueprint('installation_settings_cli', __name__)


@settings_cli.cli.group('settings')
def settings():
    """Persist operator settings without changing bootstrap secrets."""


@settings.command('import-environment')
def import_environment():
    from app.services.installation_settings import import_environment as adopt
    try:
        changed = adopt()
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    click.echo('Installation settings imported.' if changed else 'Saved settings retained; no changes.')


@settings.command('show')
def show():
    from app.services.installation_settings import snapshot
    values, revision = snapshot()
    click.echo(json.dumps(dict(revision=revision, settings=values), indent=2))


@settings.command('set')
@click.argument('key')
@click.argument('value')
@click.option('--revision', type=int, required=True)
def set_value(key, value, revision):
    """Set KEY to a JSON VALUE using the revision from settings show."""
    from app.services.installation_settings import set_setting
    try:
        result = set_setting(key, json.loads(value), revision)
    except (ValueError, RuntimeError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(f'Settings revision {result}. Domain changes need proxy review; live-mic changes need station rendering/restart.')
