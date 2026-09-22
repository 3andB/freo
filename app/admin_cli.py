"""Root-run account bootstrap. Password is read without command-line arguments."""
import click
import os
from flask import Blueprint
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import AdminUser

admin_cli = Blueprint('admin_cli', __name__)


@admin_cli.cli.group('admin')
def admin():
    """Manage global admin accounts from the trusted server CLI."""


def root_only():
    if os.geteuid() != 0:
        raise click.ClickException('Admin accounts require the root-run CLI')


@admin.command('set-password')
@click.option('--email', required=True)
def set_password(email):
    root_only()
    normalized = email.strip().lower()
    if not normalized or len(normalized) > 254 or '@' not in normalized:
        raise click.ClickException('Invalid email address')
    password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
    if len(password) < 16:
        raise click.ClickException('Password must contain at least 16 characters')
    user = AdminUser.query.filter_by(email=normalized).first()
    if user is None:
        user = AdminUser(email=normalized, installation_admin=AdminUser.query.count() == 0)
        db.session.add(user)
    user.password_hash = generate_password_hash(password, method='scrypt')
    user.active = True
    db.session.commit()
    click.echo(f'Admin login ready for {normalized}')


@admin.command('list')
def list_admins():
    root_only()
    for user in AdminUser.query.order_by(AdminUser.email):
        click.echo(f'{user.email}\t{"active" if user.active else "disabled"}')


@admin.command('installation-role')
@click.argument('email')
@click.option('--grant/--revoke', required=True)
def installation_role(email, grant):
    """Explicitly grant/revoke installation-wide license and upgrade management."""
    root_only()
    user = AdminUser.query.filter_by(email=email.strip().lower()).first()
    if user is None:
        raise click.ClickException('Admin not found')
    user.installation_admin = grant
    db.session.commit()
    click.echo('Installation role updated.')


@admin.command('disable')
@click.argument('email')
def disable_admin(email):
    root_only()
    user = AdminUser.query.filter_by(email=email.strip().lower()).first()
    if user is None:
        raise click.ClickException('Admin not found')
    user.active = False
    db.session.commit()
    click.echo('Admin disabled')


@admin.command('enable')
@click.argument('email')
def enable_admin(email):
    root_only()
    user = AdminUser.query.filter_by(email=email.strip().lower()).first()
    if user is None:
        raise click.ClickException('Admin not found')
    user.active = True
    db.session.commit()
    click.echo('Admin enabled')
