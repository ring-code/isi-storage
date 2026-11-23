import os

def get_secret(secret_name, env_fallback=None):
    """
    Reads a secret from Docker Secrets (/run/secrets/).
    Falls back to environment variables for local non-docker development.
    """
    secret_path = f'/run/secrets/{secret_name}'
    
    # 1. Try to read from Docker Secret
    if os.path.exists(secret_path):
        with open(secret_path, 'r') as f:
            return f.read().strip()
            
    # 2. Fall back to standard environment variable (from .env or OS)
    if env_fallback:
        return os.getenv(env_fallback)
        
    return None