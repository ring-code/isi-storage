# src/app/commands.py

import click
from flask.cli import with_appcontext
from .auth.models import User, UserRights
from .inventory.models import DamageTemplate
from .extensions import db
from dotenv import load_dotenv
from flask_migrate import upgrade

# Load environment variables 
load_dotenv()


# Define a new command group called 'seed'
@click.group()
def seed():
    """Commands for seeding the database."""
    pass


@seed.command("init")
@with_appcontext
def init_db():
    """Runs database migrations and seeds the initial data."""
    print("--- [1/4] Running database migrations ---")
    upgrade()
    print("--- Migrations complete. ---")
    db.session.commit()
    
    print("--- [2/4] Seeding default user roles ---")
    UserRights.insert_default_roles()
    
    print("--- [3/4] Seeding default admin user ---")
    User.insert_default_admin()

    print("--- [4/4] Seeding default damage templates ---")
    DamageTemplate.insert_default_templates()
    
    db.session.commit()
    print("--- Seeding complete. ---")


@click.command('reset-admin-pw')
@click.argument('email')
@click.password_option()  
@with_appcontext
def reset_admin_pw(email, password):
    """Resets a user password securely."""
    user = User.query.filter_by(email=email).first()
    if not user:
        click.echo(f"Error: User {email} not found.")
        return

    user.set_password(password)
    db.session.commit()
    click.echo(f"Success: Password for {user.user_name} updated.")


def register_commands(app):
    """Registers the custom command groups with the Flask app."""
    app.cli.add_command(seed)
    app.cli.add_command(reset_admin_pw)