# src/app/config.py
import os
from dotenv import load_dotenv
from app.utility.secrets_helper import get_secret

load_dotenv()

class Config:
    """
    The single, authoritative configuration class for the Flask application.
    
    It reads all configuration from environment variables and will raise an
    error on startup if required variables are missing, ensuring the
    application is always configured correctly.
    """
    # --- Secrets ---
    SECRET_KEY = get_secret('storage_secret_key', 'SECRET_KEY')
    ISI_SYNC_API_KEY = get_secret('isi_sync_api_key', 'ISI_SYNC_API_KEY')
    
    # --- Database URL Construction ---
    db_user = os.getenv('POSTGRES_USER')
    db_name = os.getenv('POSTGRES_DB')
    db_password = get_secret('postgres_password', 'POSTGRES_PASSWORD')
    db_host = os.getenv('POSTGRES_HOST', 'postgres_db')

    # If a full DATABASE_URL exists (e.g., local non-docker dev), use it.
    # Otherwise, construct it safely using the secret.
    env_db_url = os.getenv('DATABASE_URL')
    if env_db_url:
        SQLALCHEMY_DATABASE_URI = env_db_url
    elif db_user and db_password and db_name:
        SQLALCHEMY_DATABASE_URI = f"postgresql://{db_user}:{db_password}@{db_host}:5432/{db_name}"
    else:
        SQLALCHEMY_DATABASE_URI = None

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # --- Startup Validation ---
    # This block makes the application fail fast if not configured properly.
    if not SECRET_KEY:
        raise ValueError("FATAL ERROR: No SECRET_KEY set for Flask application.")
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("FATAL ERROR: No DATABASE_URL set for Flask application.")


class TestingConfig(Config):
    """
    Configuration for running automated tests.
    Uses an in-memory SQLite database for speed and isolation.
    """
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:' # Tests should not touch the real DB
    WTF_CSRF_ENABLED = False # Disable CSRF tokens in tests for simplicity
    # Set a dummy secret key for testing
    SECRET_KEY = 'testing-secret-key'