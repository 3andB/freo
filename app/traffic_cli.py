"""Traffic log recovery and batch CLI."""
from datetime import date
import click
from flask import Blueprint
from app.models import TrafficLog
from app.services.stations import get_station
from app.services.traffic import finalize_log,generate_log,reconcile_log
traffic_cli=Blueprint('traffic_cli',__name__)
@traffic_cli.cli.group('traffic')
def group():"""Generate and reconcile traffic logs."""
@group.command('generate')
@click.option('--station',required=True)
@click.option('--date','log_date',required=True,type=click.DateTime(formats=['%Y-%m-%d']))
def generate(station,log_date):
    try:
        log,report=generate_log(station,log_date.date())
        for row in report:click.echo(f"{row['campaign']}: requested={row['requested']} scheduled={row['scheduled']} unscheduled={row['unscheduled']}")
        click.echo(f'log={log.id} status={log.status}')
    except ValueError as error:raise click.ClickException(str(error))
def _log(station,log_date):
    s=get_station(station);row=TrafficLog.query.filter_by(station_id=s.id if s else None,log_date=date.fromisoformat(log_date)).first()
    if not row:raise click.ClickException('Traffic log not found')
    return row
@group.command('finalize')
@click.option('--station',required=True)
@click.option('--date','log_date',required=True)
def finalize(station,log_date):
    try:row=finalize_log(_log(station,log_date));click.echo(row.status)
    except ValueError as error:raise click.ClickException(str(error))
@group.command('reconcile')
@click.option('--station',required=True)
@click.option('--date','log_date',required=True)
def reconcile(station,log_date):
    row=reconcile_log(_log(station,log_date));click.echo(row.status)
@group.command('show')
@click.option('--station',required=True)
@click.option('--date','log_date',required=True)
def show(station,log_date):
    row=_log(station,log_date)
    for p in sorted(row.placements,key=lambda x:(x.scheduled_for_utc,x.position)):click.echo(f'{p.scheduled_for_utc.isoformat()}\t{p.stopset.slug}\t{p.advertiser_name}\t{p.campaign_name}\t{p.creative_code}\t{p.status}')
