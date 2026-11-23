# src/app/__init__py

import os
from flask import Flask
from app.extensions import db, migrate, login_manager, csrf
from flask_cors import CORS


def create_app(config_class_string='config.Config'):
    """
    The application factory.
    """
    app = Flask(__name__)

    # 1. Configure the App
    app.config.from_object(config_class_string)

    # 2. Initialize Extensions with the App
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    
    # Initialize LoginManager and set the login view
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # Initialize CORS
    cors_origins_str = os.getenv('CORS_ORIGINS')
    allowed_origins = [origin.strip() for origin in cors_origins_str.split(',')] if cors_origins_str else []
    CORS(app, resources={r"/*": {"origins": allowed_origins}}, supports_credentials=True)

    # 3. Register Blueprints, Commands, and Models within the App Context
    with app.app_context():
        # Import models here to prevent circular dependencies.
        # This also ensures they are registered with SQLAlchemy.
        from . import auth, products, sales, inventory, associations

        # Import and register blueprints
        from app.products.routes import main,  api_bp
        app.register_blueprint(main)
        app.register_blueprint(api_bp)

        from app.definitions.routes import def_bp
        app.register_blueprint(def_bp)

        from app.sales.routes import sales_bp
        app.register_blueprint(sales_bp)

        from app.inventory.routes import inventory_bp
        app.register_blueprint(inventory_bp)

        from app.auth.routes import auth_bp
        app.register_blueprint(auth_bp)

        # Import and register custom CLI commands
        from . import commands
        commands.register_commands(app)
        

    # 4. Jinja Extensions (can be done outside the context)
    app.jinja_env.add_extension('jinja2.ext.do')
    app.jinja_env.add_extension('jinja2.ext.loopcontrols')

    return app
