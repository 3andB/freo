"""Root-run account bootstrap. Password is read without command-line arguments."""
import click
from flask import Blueprint
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import AdminUser

admin_cli = Blueprint('admin_cli', __name__)


@admin_cli.cli.group('admin')
def admin():
    """Manage login-only dashboard accounts."""


@admin.command('set-password')
@click.option('--email', required=True)
def set_password(email):
    normalized = email.strip().lower()
    if not normalized or len(normalized) > 254 or '@' not in normalized:
        raise click.ClickException('Invalid email address')
    password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
    if len(password) < 16:
        raise click.ClickException('Password must contain at least 16 characters')
    user = AdminUser.query.filter_by(email=normalized).first()
    if user is None:
        user = AdminUser(email=normalized)
        db.session.add(user)
    user.password_hash = generate_password_hash(password, method='scrypt')
    user.active = True
    db.session.commit()
    click.echo(f'Admin login ready for {normalized}')
