"""Admin configuration queues work; it never contacts the central API."""
import re
import click
import time
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from app.extensions import db
from app.version import VERSION
from app.routes.web import admin_stations
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.services.admin_media import audit
from app.services.central_api import Reporter, installation
from app.services.central_api.client import APIError, uuid_string, timestamp
from app.services.central_api.identity import IdentityStore
from app.services.central_api.licensing import effective_time
from app.services.central_api.releases import check_version

central_api = Blueprint('central_api', __name__)


def queue_activation(code):
    code = code.strip().upper()
    if not re.fullmatch(r'FREO-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}', code):
        raise ValueError('Enter the activation code from your Freo Live station profile')
    row = installation()
    # Only a short-lived activation code crosses the private database queue.
    # Installation bearer credentials remain in the reporter's private file.
    row.state = {k: v for k, v in row.state.items() if k != 'claim'}
    row.state = dict(row.state, activation={'code': code, 'expires': time.time() + 1800})
    if not row.installation_id:
        if row.registration_state == 'registration_uncertain':
            raise ValueError('Recover the existing installation credential before connecting its owner profile')
        if row.registration_state != 'enrolling':
            row.registration_state = 'activation_queued'
    row.last_error = ''
    db.session.commit()


def configure(email, retry=False):
    email = email.strip()
    if len(email) > 254 or not re.fullmatch(r'[^\s@\x00-\x1f]+@[^\s@\x00-\x1f]+\.[^\s@\x00-\x1f]+', email):
        raise ValueError('Enter a valid station manager email')
    row = installation()
    if row.installation_id:
        raise ValueError('This installation already has an identity; contact Freo for account or credential changes')
    if row.registration_state != 'unconfigured' and not (retry and row.registration_state == 'registration_uncertain'):
        raise ValueError('Registration is already queued or requires an explicit retry acknowledgement')
    row.manager_email = email
    row.registration_state = 'retry_registration' if retry else 'pending'
    row.last_error = ''
    db.session.commit()


@central_api.route('/admin/installation', methods=['GET', 'POST'])
@admin_required
def settings():
    row = installation()
    error = None
    if request.method == 'POST':
        require_csrf()
        try:
            if request.form.get('action') == 'activate':
                queue_activation(request.form.get('activation_code', ''))
            elif request.form.get('action') == 'retry_connection':
                if row.registration_state == 'registration_uncertain':
                    raise ValueError('Recover the existing credential before retrying')
                if row.installation_id:
                    row.registration_state = 'enrolled'
                # Explicit operator retry; keep entitlement and identity intact.
                row.state = {key: value for key, value in row.state.items() if key not in ('license', 'report', 'enrollment', 'claim', 'retry_after')}
                db.session.commit()
            else:
                configure(request.form.get('manager_email', ''), retry=request.form.get('acknowledge_retry') == 'yes')
            audit('central_api_configured', user_id=current_admin().id, target_type='installation', target_id='1',
                  summary='Central API setup or connection retry requested')
            db.session.commit()
            flash('Configuration saved. The background reporter will process it.', 'success')
            return redirect(url_for('.settings'))
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
    cache = row.license_cache
    server_now = effective_time(cache) if cache else None
    grace_elapsed = bool(cache and server_now is not None and server_now > timestamp(cache['entitlement']['grace_until']))
    expiry = cache['entitlement']['expires_at'] if cache else None
    using_grace = bool(expiry and server_now is not None and server_now > timestamp(expiry))
    receipt = row.state.get('last_heartbeat', {})
    update_available = receipt.get('update_available')
    if receipt.get('freo_version') != VERSION or row.state.get('report', {}).get('failures'):
        update_available = None
    response = current_app.make_response((render_template('admin/installation.html', installation=row,
        installed_version=VERSION, update_available=update_available,
        cache=cache, server_now=server_now, grace_elapsed=grace_elapsed, using_grace=using_grace, error=error, stations=admin_stations(), selected=None, page='installation'), 400 if error else 200))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@central_api.cli.group('central-api')
def cli():
    """Configure and run the independent central API reporter."""


@cli.command('check-version')
def check_version_command():
    """Check the public release without enrollment or installation credentials."""
    click.echo('Installed version: ' + VERSION)
    try:
        result = check_version(current_app.config['FREO_API_URL'])
    except APIError as error:
        raise click.ClickException('Version check unavailable; update status unknown (' + error.code + ').') from None
    click.echo('Latest version: ' + result['latest_version'])
    click.echo('Update available.' if result['update_available'] else 'No newer version available.')


@cli.command('configure')
@click.option('--email', prompt='Station manager email')
def configure_command(email):
    try:
        configure(email)
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    click.echo('Registration queued. Start freo-central-api.service to process it.')


@cli.command('recover-credential')
@click.option('--installation-id', prompt=True)
def recover_credential(installation_id):
    """Import an operator-recovered credential, without creating an identity."""
    token = click.prompt('Credential', hide_input=True)
    row = installation()
    try:
        uuid_string(installation_id)
        if row.installation_id and row.installation_id != installation_id:
            raise ValueError('Installation ID does not match the existing installation')
        if not re.fullmatch(r'freo_[A-Za-z0-9_-]{43}', token):
            raise ValueError('Invalid credential format')
        store = IdentityStore(current_app.config['FREO_API_STATE_DIR'])
        with store.lock():
            saved = store.read()
            if saved and saved.get('installation_id', installation_id) != installation_id:
                raise ValueError('Installation ID does not match the saved identity')
            store.write({'installation_id': installation_id, 'access_token': token})
        row.installation_id = installation_id
        row.registration_state = 'enrolled'
        row.state = {key: value for key, value in row.state.items() if key not in ('license', 'report', 'enrollment', 'claim', 'retry_after')}
        db.session.commit()
    except (ValueError, APIError) as error:
        raise click.ClickException(str(error)) from None
    click.echo('Credential saved. Start the reporter to verify it.')


@cli.command('activate')
def activate_command():
    """Queue an owner activation without displaying its code or credential."""
    code = click.prompt('Activation code', hide_input=True)
    try:
        queue_activation(code)
    except ValueError as error:
        db.session.rollback()
        raise click.ClickException(str(error)) from None
    click.echo('Activation queued. The background reporter will connect your station profile.')


@cli.command('run')
@click.option('--once', is_flag=True, help='One sampling/reporting tick for diagnostics.')
def run(once):
    reporter = Reporter()
    try:
        with reporter.store.lock():
            while True:
                started = time.monotonic()
                try:
                    reporter.tick()
                except Exception as error:
                    db.session.rollback()
                    # Even DB/OS failures never propagate into broadcast workers.
                    current_app.logger.error('Central API reporter tick failed (%s)', type(error).__name__)
                finally:
                    db.session.remove()
                if once:
                    break
                time.sleep(max(1, 60 - (time.monotonic() - started)))
    except APIError as error:
        raise click.ClickException(error.code) from None
