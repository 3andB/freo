"""Recovery CLI for ordered block definitions and previews."""
import click
from flask import Blueprint
from app.models import EventBlock, EventBlockExecution
from app.services.event_blocks import add_item, block_for, create_execution, save_block, set_enabled, validate_block
from app.services.stations import get_station

block_cli=Blueprint('block_cli',__name__)

@block_cli.cli.group('block')
def group(): """Manage ordered event blocks."""

@group.command('list')
@click.option('--station',required=True)
def list_blocks(station):
    row=get_station(station)
    if not row: raise click.ClickException('Station not found')
    for block in EventBlock.query.filter_by(station_id=row.id).order_by(EventBlock.name):
        click.echo(f'{block.slug}\t{block.block_type}\t{len(block.items)} items\t{block.duration_ms} ms\t{"enabled" if block.enabled else "disabled"}')

@group.command('create')
@click.option('--station',required=True)
@click.option('--name',required=True)
@click.option('--type','block_type',default='GENERIC')
@click.option('--failure-policy',default='ABORT_BLOCK')
def create(station,name,block_type,failure_policy):
    try: row=save_block(station,name=name,block_type=block_type.upper(),failure_policy=failure_policy.upper());click.echo(row.slug)
    except ValueError as error: raise click.ClickException(str(error))

@group.command('add')
@click.option('--station',required=True)
@click.option('--block',required=True)
@click.option('--kind',required=True,type=click.Choice(['track','imaging']))
@click.option('--content',required=True)
def add(station,block,kind,content):
    try: row=add_item(block_for(station,block),'TRACK' if kind=='track' else 'IMAGING_ASSET',content);click.echo(row.position)
    except ValueError as error: raise click.ClickException(str(error))

@group.command('validate')
@click.option('--station',required=True)
@click.argument('block')
def validate(station,block):
    try: errors=validate_block(block_for(station,block))
    except ValueError as error: raise click.ClickException(str(error))
    if errors: raise click.ClickException('; '.join(errors))
    click.echo('valid')

@group.command('enable')
@click.option('--station',required=True)
@click.argument('block')
def enable(station,block):
    try: set_enabled(block_for(station,block),True);click.echo('enabled')
    except ValueError as error: raise click.ClickException(str(error))

@group.command('disable')
@click.option('--station',required=True)
@click.argument('block')
def disable(station,block): set_enabled(block_for(station,block),False);click.echo('disabled')

@group.command('queue')
@click.option('--station',required=True)
@click.argument('block')
def queue(station,block):
    """Create a durable manual execution; the worker performs playout."""
    try: execution=create_execution(block_for(station,block),'MANUAL');click.echo(execution.id)
    except ValueError as error: raise click.ClickException(str(error))

@group.command('executions')
@click.option('--station',required=True)
def executions(station):
    row=get_station(station)
    if not row: raise click.ClickException('Station not found')
    for run in EventBlockExecution.query.filter_by(station_id=row.id).order_by(EventBlockExecution.id.desc()).limit(20):
        items=','.join(f'{item.position}:{item.state}:{item.selection_decision_id or "-"}' for item in run.items)
        click.echo(f'{run.id}\t{run.block.slug}\t{run.source}\t{run.state}\t{items}')
